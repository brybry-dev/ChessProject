"""
Module chessproject.ai.search
-----------------------------
Recherche NegaMax avec élagage alpha-bêta, approfondissement itératif et une table de
transposition simple.

Conventions de score :
  - ``negamax`` renvoie un score du point de vue du camp **au trait** (positif = bon pour
    lui) ;
  - ``score_board`` renvoie un score du point de vue des **Blancs** (positif = avantage
    blanc), en centipions entiers ;
  - un mat se note ``MATE - ply`` (``ply`` = distance à la racine, en demi-coups) : plus le
    mat est proche, plus le score est grand, ce qui fait préférer le mat le plus court ;
  - les bornes de recherche ``±INF`` sont strictement au-delà de tout score de mat.
"""

import random
import time
from dataclasses import dataclass
from typing import Any

from chessproject.core import engine

INF: int = 10**6  # Borne de la fenêtre alpha-bêta, strictement supérieure à MATE
MATE: int = 100_000  # Score d'un mat à la racine ; un mat à `ply` demi-coups vaut MATE - ply
MAX_PLY: int = 128  # Profondeur maximale envisageable : sert de seuil pour reconnaître un mat
MATE_THRESHOLD: int = MATE - MAX_PLY  # |score| >= MATE_THRESHOLD <=> score de mat
DEPTH: int = 3  # Profondeur maximale

# Valeurs des pièces en centipions
PIECE_VALUES: dict[str, int] = {"K": 0, "Q": 900, "R": 500, "B": 330, "N": 320, "p": 100}
# Valeur de l'attaquant pour MVV-LVA : le roi est l'attaquant le moins souhaitable
_ATTACKER_VALUES: dict[str, int] = {**PIECE_VALUES, "K": 1000}

CENTER_BONUS: int = 50  # Bonus pour une pièce sur une case centrale (les deux camps)
CENTER_SQUARES: frozenset[tuple[int, int]] = frozenset({(3, 3), (3, 4), (4, 3), (4, 4)})
KING_SAFETY_PENALTY: int = 50  # Par pièce ennemie adjacente au roi (les deux camps)
_KING_OFFSETS: tuple[tuple[int, int], ...] = (
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, -1),
    (0, 1),
    (1, -1),
    (1, 0),
    (1, 1),
)

# Tables positionnelles en centipions, du point de vue des Blancs (rangée 0 = 8e rangée).
# Les tables noires sont les mêmes, rangées inversées : l'évaluation est donc exactement
# antisymétrique par miroir des couleurs.
_WHITE_POSITION_SCORES: dict[str, tuple[tuple[int, ...], ...]] = {
    "N": (
        (0, 10, 20, 20, 20, 20, 10, 0),
        (10, 30, 50, 50, 50, 50, 30, 10),
        (20, 50, 60, 65, 65, 60, 50, 20),
        (20, 55, 65, 70, 70, 65, 55, 20),
        (20, 50, 65, 70, 70, 65, 50, 20),
        (20, 55, 60, 65, 65, 60, 55, 20),
        (10, 30, 50, 55, 55, 50, 30, 10),
        (0, 10, 20, 20, 20, 20, 10, 0),
    ),
    "B": (
        (0, 20, 20, 20, 20, 20, 20, 0),
        (20, 40, 40, 40, 40, 40, 40, 20),
        (20, 40, 50, 60, 60, 50, 40, 20),
        (20, 50, 50, 60, 60, 50, 50, 20),
        (20, 40, 60, 60, 60, 60, 40, 20),
        (20, 60, 60, 60, 60, 60, 60, 20),
        (20, 50, 40, 40, 40, 40, 50, 20),
        (0, 20, 20, 20, 20, 20, 20, 0),
    ),
    "R": (
        (25, 25, 25, 25, 25, 25, 25, 25),
        (50, 75, 75, 75, 75, 75, 75, 50),
        (0, 25, 25, 25, 25, 25, 25, 0),
        (0, 25, 25, 25, 25, 25, 25, 0),
        (0, 25, 25, 25, 25, 25, 25, 0),
        (0, 25, 25, 25, 25, 25, 25, 0),
        (0, 25, 25, 25, 25, 25, 25, 0),
        (25, 25, 25, 50, 50, 25, 25, 25),
    ),
    "Q": (
        (0, 20, 20, 30, 30, 20, 20, 0),
        (20, 40, 40, 40, 40, 40, 40, 20),
        (20, 40, 50, 50, 50, 50, 40, 20),
        (30, 40, 50, 50, 50, 50, 40, 30),
        (40, 40, 50, 50, 50, 50, 40, 30),
        (20, 50, 50, 50, 50, 50, 40, 20),
        (20, 40, 50, 40, 40, 40, 40, 20),
        (0, 20, 20, 30, 30, 20, 20, 0),
    ),
    "p": (
        (80, 80, 80, 80, 80, 80, 80, 80),
        (70, 70, 70, 70, 70, 70, 70, 70),
        (30, 30, 40, 50, 50, 40, 30, 30),
        (25, 25, 30, 45, 45, 30, 25, 25),
        (20, 20, 20, 20, 20, 20, 20, 20),
        (25, 15, 10, 20, 20, 10, 15, 25),
        (25, 30, 30, 0, 0, 30, 30, 25),
        (20, 20, 20, 20, 20, 20, 20, 20),
    ),
}
PIECE_POSITION_SCORES: dict[str, tuple[tuple[int, ...], ...]] = {
    **{"w" + kind: table for kind, table in _WHITE_POSITION_SCORES.items()},
    **{"b" + kind: table[::-1] for kind, table in _WHITE_POSITION_SCORES.items()},
}

# --------------------------------------------------------------------------
# Recherche (J3.2 – J3.5)
# --------------------------------------------------------------------------
# Table de transposition à bornes (J3.3) : un score peut être exact, ou une borne
# inférieure (coupure bêta) / supérieure (aucun coup n'a dépassé alpha).
EXACT: int = 0
LOWER: int = 1
UPPER: int = 2
TT_MAX_ENTRIES: int = 1 << 20  # au-delà, la table est vidée (remplacement simple)
TIME_CHECK_INTERVAL: int = 1024  # nœuds entre deux lectures de l'horloge
QUIESCENCE_MAX_PLY: int = 16  # garde-fou : la quiescence s'arrête au-delà


@dataclass(slots=True)
class TTEntry:
    depth: int
    score: int
    flag: int
    best_move: engine.Move | None


TranspositionTable = dict[int, TTEntry]


@dataclass(frozen=True, slots=True)
class SearchLimits:
    """Limites d'une recherche ; au moins une doit être donnée (sinon profondeur DEPTH)."""

    depth: int | None = None
    movetime_ms: int | None = None
    nodes: int | None = None


@dataclass(slots=True)
class SearchResult:
    move: engine.Move | None
    score: int  # du point de vue du camp au trait, en centipions (ou score de mat)
    depth: int  # dernière profondeur entièrement explorée
    nodes: int
    elapsed_ms: int
    pv: list[engine.Move]


class SearchLimitError(Exception):
    """Levée au milieu de l'arbre quand une limite de temps ou de nœuds est atteinte."""


def _to_tt_score(score: int, ply: int) -> int:
    # Un score de mat est stocké relativement au nœud, pas à la racine : il reste juste
    # quand la même position est retrouvée à une autre distance de la racine.
    if score >= MATE_THRESHOLD:
        return score + ply
    if score <= -MATE_THRESHOLD:
        return score - ply
    return score


def _from_tt_score(score: int, ply: int) -> int:
    if score >= MATE_THRESHOLD:
        return score - ply
    if score <= -MATE_THRESHOLD:
        return score + ply
    return score


class Searcher:
    """NegaMax alpha-bêta, approfondissement itératif, table de transposition à bornes,
    ordonnancement (coup de la table, MVV-LVA, coups tueurs, historique) et quiescence.

    La position passée à ``think`` est rendue intacte, y compris quand la recherche est
    interrompue par une limite (les coups joués sont annulés en remontant).
    """

    def __init__(self, clock: Any = time.monotonic) -> None:
        self.tt: TranspositionTable = {}
        self.clock = clock
        self.nodes = 0
        self._deadline: float | None = None
        self._max_nodes: int | None = None
        self._killers: list[list[engine.Move | None]] = []
        self._history: dict[tuple[str, int, int], int] = {}

    # -- interface ------------------------------------------------------
    def think(self, game_state: engine.GameState, limits: SearchLimits) -> SearchResult:
        start = self.clock()
        self.nodes = 0
        self._deadline = (
            start + limits.movetime_ms / 1000 if limits.movetime_ms is not None else None
        )
        self._max_nodes = limits.nodes
        self._killers = [[None, None] for _ in range(MAX_PLY)]
        self._history = {}
        if len(self.tt) > TT_MAX_ENTRIES:
            self.tt.clear()
        max_depth = limits.depth
        if max_depth is None:
            max_depth = MAX_PLY if (limits.movetime_ms or limits.nodes) else DEPTH

        root_moves = game_state.get_valid_moves()
        result = SearchResult(None, 0, 0, 0, 0, [])
        if not root_moves:
            result.score = -MATE if game_state.checkmate else 0
            return result
        result.move = self._ordered(game_state, root_moves, None, 0)[0]
        for depth in range(1, max_depth + 1):
            try:
                score, move = self.negamax(game_state, root_moves, depth, -INF, INF, 0)
            except SearchLimitError:
                break  # profondeur inachevée : on garde le résultat de la précédente
            if move is not None:
                result.move, result.score, result.depth = move, score, depth
            if abs(score) >= MATE_THRESHOLD:
                break  # mat trouvé (pour l'un ou l'autre camp) : chercher plus loin est inutile
        result.nodes = self.nodes
        result.elapsed_ms = int((self.clock() - start) * 1000)
        # Les limites ne valent que pour cet appel : un negamax lancé ensuite sur le même
        # Searcher (ex. réévaluation des coups par les niveaux) ne doit pas être interrompu.
        self._deadline = None
        self._max_nodes = None
        result.pv = self._principal_variation(game_state, result.depth)
        return result

    # -- arbre ----------------------------------------------------------
    def _tick(self) -> None:
        self.nodes += 1
        if self._max_nodes is not None and self.nodes >= self._max_nodes:
            raise SearchLimitError
        if (
            self._deadline is not None
            and self.nodes % TIME_CHECK_INTERVAL == 0
            and self.clock() >= self._deadline
        ):
            raise SearchLimitError

    def negamax(
        self,
        game_state: engine.GameState,
        valid_moves: list[engine.Move],
        depth: int,
        alpha: int,
        beta: int,
        ply: int,
    ) -> tuple[int, engine.Move | None]:
        """Score du point de vue du camp au trait. ``valid_moves`` = ``get_valid_moves()``
        de la position courante (qui positionne ``checkmate`` / nulles, lus si vide)."""
        self._tick()
        if not valid_moves:
            return (-MATE + ply if game_state.checkmate else 0), None
        if depth <= 0:
            return self.quiescence(game_state, valid_moves, alpha, beta, ply), None

        key = game_state.zobrist_key
        entry = self.tt.get(key)
        tt_move: engine.Move | None = None
        if entry is not None:
            tt_move = entry.best_move
            # Jamais de court-circuit à la racine : il faut un coup, pas seulement un score.
            if ply > 0 and entry.depth >= depth:
                tt_score = _from_tt_score(entry.score, ply)
                if entry.flag == EXACT:
                    return tt_score, tt_move
                if entry.flag == LOWER and tt_score >= beta:
                    return tt_score, tt_move
                if entry.flag == UPPER and tt_score <= alpha:
                    return tt_score, tt_move

        alpha_orig = alpha
        ordered = self._ordered(game_state, valid_moves, tt_move, ply)
        best_score = -INF
        best_move: engine.Move = ordered[0]
        for move in ordered:
            game_state.make_move(move, validate=False)
            try:
                score, _ = self.negamax(
                    game_state, game_state.get_valid_moves(), depth - 1, -beta, -alpha, ply + 1
                )
            finally:
                game_state.undo_move()
            score = -score
            if score > best_score:
                best_score, best_move = score, move
            if score > alpha:
                alpha = score
            if alpha >= beta:
                if not move.is_capture and not move.is_pawn_promotion:
                    self._record_quiet_cutoff(move, depth, ply)
                break

        if best_score <= alpha_orig:
            flag = UPPER
        elif best_score >= beta:
            flag = LOWER
        else:
            flag = EXACT
        self.tt[key] = TTEntry(depth, _to_tt_score(best_score, ply), flag, best_move)
        return best_score, best_move

    def quiescence(
        self,
        game_state: engine.GameState,
        valid_moves: list[engine.Move],
        alpha: int,
        beta: int,
        ply: int,
    ) -> int:
        """Prolonge la recherche sur les captures et promotions pour n'évaluer que des
        positions calmes (effet d'horizon, J3.5). En échec, tous les coups sont examinés."""
        if not valid_moves:
            return -MATE + ply if game_state.checkmate else 0
        in_check = game_state.in_check
        if not in_check:
            color = 1 if game_state.white_to_move else -1
            stand_pat = color * score_board(game_state)
            if stand_pat >= beta or ply >= QUIESCENCE_MAX_PLY:
                return stand_pat
            alpha = max(alpha, stand_pat)
            candidates = [m for m in valid_moves if m.is_capture or m.is_pawn_promotion]
        else:
            candidates = valid_moves
        best = alpha if not in_check else -INF
        for move in sorted(candidates, key=self._capture_order, reverse=True):
            self._tick()
            game_state.make_move(move, validate=False)
            try:
                score = -self.quiescence(
                    game_state, game_state.get_valid_moves(), -beta, -alpha, ply + 1
                )
            finally:
                game_state.undo_move()
            if score > best:
                best = score
            if score > alpha:
                alpha = score
            if alpha >= beta:
                break
        return best

    # -- ordonnancement (J3.4) --------------------------------------------
    @staticmethod
    def _capture_order(move: engine.Move) -> int:
        return move_ordering_heuristic(move)

    def _ordered(
        self,
        game_state: engine.GameState,
        moves: list[engine.Move],
        tt_move: engine.Move | None,
        ply: int,
    ) -> list[engine.Move]:
        killers = self._killers[ply] if ply < len(self._killers) else [None, None]

        def key(move: engine.Move) -> int:
            if move == tt_move:
                return 10_000_000
            tactical = move_ordering_heuristic(move)
            if tactical:
                return 1_000_000 + tactical
            if move == killers[0]:
                return 900_000
            if move == killers[1]:
                return 800_000
            return self._history.get(_history_key(move), 0)

        # sorted() et non list.sort() : la liste reçue est le cache du moteur (B39).
        return sorted(moves, key=key, reverse=True)

    def _record_quiet_cutoff(self, move: engine.Move, depth: int, ply: int) -> None:
        if ply < len(self._killers):
            killers = self._killers[ply]
            if killers[0] != move:
                killers[1], killers[0] = killers[0], move
        hkey = _history_key(move)
        self._history[hkey] = min(self._history.get(hkey, 0) + depth * depth, 700_000)

    def _principal_variation(self, game_state: engine.GameState, depth: int) -> list[engine.Move]:
        """Ligne principale lue dans la table de transposition (rendue intacte)."""
        pv: list[engine.Move] = []
        seen: set[int] = set()
        try:
            while len(pv) < max(depth, 1) and game_state.zobrist_key not in seen:
                seen.add(game_state.zobrist_key)
                entry = self.tt.get(game_state.zobrist_key)
                if entry is None or entry.best_move not in game_state.get_valid_moves():
                    break
                assert entry.best_move is not None
                pv.append(entry.best_move)
                game_state.make_move(entry.best_move, validate=False)
        finally:
            for _ in pv:
                game_state.undo_move()
        return pv


def _history_key(move: engine.Move) -> tuple[str, int, int]:
    return (move.piece_moved, move.end_row, move.end_col)


def think(
    game_state: engine.GameState, limits: SearchLimits, searcher: Searcher | None = None
) -> SearchResult:
    """Meilleur coup de la position selon ``limits`` (profondeur, temps, nœuds)."""
    return (searcher or Searcher()).think(game_state, limits)


def find_best_move(
    game_state: engine.GameState,
    valid_moves: list[engine.Move],
    return_queue: Any,
    level_name: str | None = None,
) -> None:
    """Point d'entrée du processus de l'IA (UI, UCI) : dépose le coup choisi dans
    ``return_queue`` — toujours un coup légal s'il en existe un, ``None`` sinon.

    Sans ``level_name``, recherche à profondeur fixe ``DEPTH`` ; sinon, jeu au niveau de
    difficulté nommé (cf. ``chessproject.ai.levels``). ``valid_moves`` est conservé pour
    compatibilité : la recherche part de la position.
    """
    if not valid_moves:
        return_queue.put(None)
        return
    if level_name is None:
        return_queue.put(think(game_state, SearchLimits(depth=DEPTH)).move)
        return
    from chessproject.ai import levels  # import local : levels importe ce module

    return_queue.put(levels.choose_move(game_state, levels.LEVELS_BY_NAME[level_name]))


def move_ordering_heuristic(move: engine.Move) -> int:
    """
    Score d'ordonnancement, sans jouer le coup : MVV-LVA pour les captures
    (``10 × victime - attaquant``) et bonus pour les promotions. Plus grand = essayé avant.
    """
    score = 0
    if move.is_capture:
        victim = PIECE_VALUES.get(move.piece_captured[1], 0)
        attacker = _ATTACKER_VALUES.get(move.piece_moved[1], 0)
        score += 10_000 + 10 * victim - attacker
    if move.is_pawn_promotion:
        score += 10 * PIECE_VALUES.get(move.promotion_piece or "Q", 0)
    return score


def score_board(game_state: engine.GameState) -> int:
    """
    Évaluation statique en centipions entiers, du point de vue des Blancs.

    Critères, tous calculés pour les deux camps (l'évaluation est antisymétrique par miroir
    des couleurs) :
      - valeur matérielle et tables positionnelles ;
      - contrôle du centre ;
      - sécurité du roi (pièces ennemies adjacentes).
    Les fins de partie (mat, nulles) sont traitées par la recherche, pas ici.
    """
    board = game_state.board
    total = 0
    for r in range(engine.DIMENSION):
        for c in range(engine.DIMENSION):
            piece = board[r][c]
            if piece == "--":
                continue
            value = PIECE_VALUES.get(piece[1], 0)
            table = PIECE_POSITION_SCORES.get(piece)
            if table is not None:
                value += table[r][c]
            if (r, c) in CENTER_SQUARES:
                value += CENTER_BONUS
            total += value if piece[0] == "w" else -value

    total -= _king_danger(board, game_state.white_king_location, "b")
    total += _king_danger(board, game_state.black_king_location, "w")
    return total


def _king_danger(board: list[list[str]], king: tuple[int, int], enemy_color: str) -> int:
    """Pénalité pour les pièces de ``enemy_color`` adjacentes au roi situé en ``king``."""
    king_row, king_col = king
    penalty = 0
    for dr, dc in _KING_OFFSETS:
        nr, nc = king_row + dr, king_col + dc
        if 0 <= nr < engine.DIMENSION and 0 <= nc < engine.DIMENSION:
            if board[nr][nc][0] == enemy_color:
                penalty += KING_SAFETY_PENALTY
    return penalty


def find_random_move(valid_moves: list[engine.Move]) -> engine.Move:
    """
    Retourne un coup aléatoire parmi ceux valides.
    """
    return random.choice(valid_moves)
