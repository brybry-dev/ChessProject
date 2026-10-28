"""
Module chessproject.ai.review
-----------------------------
Bilan de partie (J9.3) : évaluation de chaque position de la partie, courbe
d'évaluation et classement des coups en imprécisions, erreurs et gaffes.

Mesure. Dans chaque position, le moteur cherche le meilleur coup (profondeur
``REVIEW_DEPTH``, plafond de ``REVIEW_NODES`` nœuds), puis, si le coup joué est
différent, l'évalue au même horizon (une profondeur de moins, depuis la position
suivante, même table de transposition). Comparer deux scores de même horizon évite le
bruit de parité d'une évaluation position par position : le meilleur coup perd
exactement 0. Profondeur et nœuds étant fixés, le bilan est le même sur toutes les
machines.

Seuils. Un coup se juge à la chute du **score attendu** du camp qui le joue, entre le
meilleur coup et le coup joué : ``expected_score(cp) = 1 / (1 + 10 ** (-cp / 400))``
(la formule Elo, 400 cp ≈ 91 %), un mat comptant pour 0 ou 1. Une chute d'au moins
20 points est une imprécision (?!), 30 points une erreur (?), 40 points une gaffe (??).
Depuis l'égalité, cela fait environ 150 cp, 240 cp et 380 cp ; depuis +9, perdre 3 pions
ne compte pas. Ces seuils sont plus larges que ceux des sites d'échecs (10 / 20 / 30),
calibrés pour des moteurs bien plus profonds : sur cinq parties de théorie de
référence, ce moteur à profondeur 3 voit des chutes allant jusqu'à 18 points sur des
coups pourtant corrects (lignes tactiques mal vues à cet horizon), alors qu'une pièce
laissée en prise en coûte plus de 50 et un mat concédé 100 (``tests/test_review.py``).
La perte moyenne par coup (en centipions, scores bornés à ±1000) complète le bilan.

Meilleur coup (J13.1). La variante principale de chaque recherche est gardée, en SAN :
pour une faute, c'est la suite que le moteur proposait à la place du coup joué. Chaque
coup de la variante est rejoué et vérifié ; elle s'arrête au premier coup qui ne serait
pas légal (une table de transposition peut prolonger une variante par un coup d'une
autre position).

Export (J13.2). :func:`pgn_annotations` traduit le bilan en annotations PGN : symbole de
la faute en NAG (``$6`` ?!, ``$2`` ?, ``$4`` ??) et évaluation de la position atteinte
en commentaire ``[%eval 0.42]`` (pions, du point de vue des Blancs) ou ``[%eval #-3]``
(mat en 3 pour les Noirs), la convention que lisent python-chess et les sites d'échecs.
"""

import contextlib
import copy
import queue
from dataclasses import dataclass, field
from multiprocessing import Process, Queue
from typing import Any

from chessproject.ai import search
from chessproject.core import engine, notation, pgn

REVIEW_DEPTH = 3
REVIEW_NODES = 20_000  # plafond par recherche ; environ 0,25 s par position en moyenne
EVAL_CAP_CP = 1_000  # borne des scores pour la perte moyenne (un mat compte 1000)

INACCURACY = "inaccuracy"
MISTAKE = "mistake"
BLUNDER = "blunder"
# (seuil de chute du score attendu, catégorie), du plus grave au plus léger
THRESHOLDS: tuple[tuple[float, str], ...] = ((0.40, BLUNDER), (0.30, MISTAKE), (0.20, INACCURACY))
SYMBOLS: dict[str, str] = {INACCURACY: "?!", MISTAKE: "?", BLUNDER: "??"}
LABELS: dict[str, str] = {INACCURACY: "Imprécisions", MISTAKE: "Erreurs", BLUNDER: "Gaffes"}
# NAG du standard PGN (§10) : $2 coup faible, $4 très faible, $6 douteux.
NAGS: dict[str, int] = {INACCURACY: 6, MISTAKE: 2, BLUNDER: 4}


def expected_score(cp: int) -> float:
    """Score attendu des Blancs pour une évaluation ``cp`` (point de vue des Blancs)."""
    if cp >= search.MATE_THRESHOLD:
        return 1.0
    if cp <= -search.MATE_THRESHOLD:
        return 0.0
    return 1 / (1 + 10 ** (-cp / 400))


def classify(drop: float) -> str | None:
    """Catégorie d'un coup selon la chute de score attendu de son camp (0 à 1)."""
    # Arrondi : 0,40 calculé en flottants ne doit pas tomber juste sous le seuil.
    drop = round(drop, 9)
    return next((kind for threshold, kind in THRESHOLDS if drop >= threshold), None)


def _cap(cp: int) -> int:
    return max(-EVAL_CAP_CP, min(EVAL_CAP_CP, cp))


@dataclass(frozen=True, slots=True)
class MoveReview:
    ply: int  # demi-coups joués après ce coup (1 pour le premier)
    white: bool
    label: str  # « 12... Nf6 »
    san: str
    loss_cp: int  # perte en centipions (scores bornés), 0 si le coup ne perd rien
    drop: float  # chute du score attendu du camp qui joue (0 à 1)
    judgement: str | None
    number: int = 1  # numéro du coup (12 pour « 12... Nf6 »)
    best: tuple[str, ...] = ()  # variante du moteur à la place de ce coup (SAN, J13.1)

    @property
    def symbol(self) -> str:
        return SYMBOLS.get(self.judgement or "", "")

    @property
    def best_line(self) -> str:
        """Variante numérotée du meilleur coup : ``"12... Nc6 13. d4"`` (vide sans variante)."""
        return " ".join(notation.format_move_lines(list(self.best), self.number, self.white))


@dataclass(slots=True)
class SideSummary:
    inaccuracies: int = 0
    mistakes: int = 0
    blunders: int = 0
    acpl: int = 0  # perte moyenne par coup, en centipions

    def count(self, judgement: str) -> int:
        return {INACCURACY: self.inaccuracies, MISTAKE: self.mistakes, BLUNDER: self.blunders}[
            judgement
        ]


@dataclass(slots=True)
class GameReview:
    evals: list[int]  # une évaluation par position (point de vue des Blancs), départ compris
    moves: list[MoveReview]
    white: SideSummary = field(default_factory=SideSummary)
    black: SideSummary = field(default_factory=SideSummary)


def build(
    evals: list[int],
    sans: list[str],
    white_starts: bool,
    start_fullmove: int,
    played: list[int] | None = None,
    lines: list[tuple[str, ...]] | None = None,
) -> GameReview:
    """Bilan à partir des évaluations des positions (``len(sans) + 1``, meilleur coup) et
    des scores des coups joués (``played``, même horizon ; par défaut, l'évaluation de
    la position suivante). Tous les scores sont du point de vue des Blancs. ``lines`` :
    variante du moteur dans chaque position (au moins une par coup joué)."""
    if len(evals) != len(sans) + 1:
        raise ValueError("une évaluation par position est attendue")
    if played is None:
        played = evals[1:]
    if len(played) != len(sans):
        raise ValueError("un score par coup joué est attendu")
    if lines is not None and len(lines) < len(sans):
        raise ValueError("une variante par coup joué est attendue")
    moves: list[MoveReview] = []
    losses: dict[bool, list[int]] = {True: [], False: []}
    sides = {True: SideSummary(), False: SideSummary()}
    white = white_starts
    number = start_fullmove
    for i, san in enumerate(sans):
        sign = 1 if white else -1
        before, after = evals[i], played[i]
        drop = sign * (expected_score(before) - expected_score(after))
        loss = max(0, sign * (_cap(before) - _cap(after)))
        judgement = classify(drop)
        label = f"{number}. {san}" if white else f"{number}... {san}"
        best = lines[i] if lines is not None else ()
        moves.append(
            MoveReview(i + 1, white, label, san, loss, max(0.0, drop), judgement, number, best)
        )
        losses[white].append(loss)
        side = sides[white]
        if judgement == INACCURACY:
            side.inaccuracies += 1
        elif judgement == MISTAKE:
            side.mistakes += 1
        elif judgement == BLUNDER:
            side.blunders += 1
        if not white:
            number += 1
        white = not white
    for color, values in losses.items():
        sides[color].acpl = round(sum(values) / len(values)) if values else 0
    return GameReview(list(evals), moves, sides[True], sides[False])


def pgn_eval(cp: int) -> str | None:
    """Évaluation au format ``[%eval]`` : ``"0.42"``, ``"-1.30"``, ``"#3"`` ou ``"#-2"``
    (mat en N coups, signe du camp qui mate) ; None pour une position déjà matée."""
    if abs(cp) >= search.MATE_THRESHOLD:
        plies = search.MATE - abs(cp)
        if plies == 0:
            return None
        moves = (plies + 1) // 2
        return f"#{moves}" if cp > 0 else f"#-{moves}"
    return f"{cp / 100:.2f}"


def pgn_annotations(result: GameReview) -> list[pgn.MoveAnnotation]:
    """Annotations PGN de chaque coup : NAG de la faute et évaluation de la position
    atteinte."""
    notes = []
    for move in result.moves:
        value = pgn_eval(result.evals[move.ply])
        notes.append(
            pgn.MoveAnnotation(
                nag=NAGS.get(move.judgement or ""),
                comment=None if value is None else f"[%eval {value}]",
            )
        )
    return notes


def _terminal_score(game_state: engine.GameState) -> int | None:
    """Score d'une partie finie (point de vue des Blancs), None si elle continue."""
    result = game_state.result()
    if not result.is_over:
        return None
    if result.winner is engine.Color.WHITE:
        return search.MATE
    if result.winner is engine.Color.BLACK:
        return -search.MATE
    return 0


def _search(
    searcher: search.Searcher, game_state: engine.GameState, depth: int, nodes: int
) -> search.SearchResult:
    return searcher.think(game_state, search.SearchLimits(depth=max(1, depth), nodes=nodes))


def legal_line(game_state: engine.GameState, moves: list[engine.Move]) -> tuple[str, ...]:
    """SAN de ``moves`` rejoués depuis ``game_state`` (rendu intact), jusqu'au premier
    coup illégal exclu."""
    sans: list[str] = []
    played = 0
    try:
        for move in moves:
            legal = next((m for m in game_state.get_valid_moves() if m == move), None)
            if legal is None:
                break
            sans.append(notation.to_san(game_state, legal))
            game_state.make_move(legal, validate=False)
            played += 1
    finally:
        for _ in range(played):
            game_state.undo_move()
    return tuple(sans)


def run(
    start_state: engine.GameState,
    moves: list[engine.Move],
    out_queue: Any,
    nodes: int = REVIEW_NODES,
    depth: int = REVIEW_DEPTH,
) -> None:
    """Point d'entrée du processus. Pour chaque position, de la position de départ à la
    position finale : ``(demi-coup, évaluation, score du coup joué, variante)`` (point
    de vue des Blancs ; ``None`` pour le coup de la position finale ; variante en SAN,
    vide si la partie est finie), puis ``None``."""
    game_state = copy.deepcopy(start_state)
    # Sans élagage : à horizon égal, le meilleur coup doit perdre exactement 0.
    searcher = search.Searcher(features=search.NO_FEATURES)
    try:
        for ply in range(len(moves) + 1):
            sign = 1 if game_state.white_to_move else -1
            terminal = _terminal_score(game_state)
            move = moves[ply] if ply < len(moves) else None
            if terminal is not None:
                out_queue.put((ply, terminal, None if move is None else terminal, ()))
                if move is None:
                    break
                game_state.make_move(move, validate=False)
                continue
            best = _search(searcher, game_state, depth, nodes)
            line = legal_line(game_state, best.pv or ([best.move] if best.move else []))
            played: int | None = None
            if move is not None:
                if move == best.move:
                    played = sign * best.score
                else:
                    game_state.make_move(move, validate=False)
                    played = _terminal_score(game_state)
                    if played is None:
                        reply = _search(searcher, game_state, best.depth - 1, nodes)
                        played = sign * -reply.score
                    game_state.undo_move()
                game_state.make_move(move, validate=False)
            out_queue.put((ply, sign * best.score, played, line))
    finally:
        out_queue.put(None)


class Reviewer:
    """Bilan calculé en arrière-plan, identifié par une clé (la partie et ses coups)."""

    def __init__(
        self, process: Any = Process, make_queue: Any = Queue, nodes: int = REVIEW_NODES
    ) -> None:
        self._process_factory = process
        self._make_queue = make_queue
        self.nodes = nodes
        self.key: object = None
        self.evals: list[int] = []
        self.played: list[int] = []
        self.lines: list[tuple[str, ...]] = []
        self.sans: list[str] = []
        self.white_starts = True
        self.start_fullmove = 1
        self.done = False
        self._process: Any = None
        self._queue: Any = None
        self._result: GameReview | None = None

    @property
    def total(self) -> int:
        """Nombre de positions à évaluer."""
        return len(self.sans) + 1

    def start(self, start_state: engine.GameState, moves: list[engine.Move], key: object) -> None:
        """Lance le bilan de la partie ; sans effet si cette clé est déjà traitée."""
        if key == self.key:
            return
        self.stop()
        self.key = key
        self.sans = notation.move_list_to_san(start_state, moves)
        self.white_starts = start_state.white_to_move
        self.start_fullmove = start_state.start_fullmove
        self._queue = self._make_queue()
        # daemon : le processus est tué avec l'application au lieu d'être attendu.
        self._process = self._process_factory(
            target=run, args=(start_state, list(moves), self._queue, self.nodes), daemon=True
        )
        self._process.start()

    def poll(self) -> int:
        """Relève les évaluations reçues ; renvoie le nombre de positions évaluées."""
        while self._queue is not None and not self.done:
            try:
                item = self._queue.get_nowait()
            except (queue.Empty, OSError, ValueError):
                if self._process is not None and not self._process.is_alive():
                    # Processus terminé : ce qui reste dans la file arrive tout de suite.
                    try:
                        item = self._queue.get(timeout=0.2)
                    except (queue.Empty, OSError, ValueError):
                        self.done = True
                        break
                else:
                    break
            if item is None:
                self.done = True
            else:
                self.evals.append(item[1])
                self.lines.append(item[3])
                if item[2] is not None:
                    self.played.append(item[2])
        return len(self.evals)

    def result(self) -> GameReview | None:
        """Bilan complet, ou None tant que toutes les positions ne sont pas évaluées."""
        if self._result is None and len(self.evals) == self.total:
            self._result = build(
                self.evals,
                self.sans,
                self.white_starts,
                self.start_fullmove,
                self.played,
                self.lines,
            )
        return self._result

    def stop(self) -> None:
        if self._process is not None and not self.done:
            with contextlib.suppress(Exception):
                self._process.terminate()
        self._process = self._queue = None
        self.key = None
        self.evals, self.played, self.lines, self.sans = [], [], [], []
        self.done = False
        self._result = None
