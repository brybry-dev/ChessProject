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
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from chessproject.ai import evaluate
from chessproject.core import engine

INF: int = 10**6  # Borne de la fenêtre alpha-bêta, strictement supérieure à MATE
MATE: int = 100_000  # Score d'un mat à la racine ; un mat à `ply` demi-coups vaut MATE - ply
MAX_PLY: int = 128  # Profondeur maximale envisageable : sert de seuil pour reconnaître un mat
MATE_THRESHOLD: int = MATE - MAX_PLY  # |score| >= MATE_THRESHOLD <=> score de mat
DEPTH: int = 3  # Profondeur maximale

# Valeurs des pièces en centipions
PIECE_VALUES: dict[str, int] = evaluate.PIECE_VALUES
# Valeur de l'attaquant pour MVV-LVA : le roi est l'attaquant le moins souhaitable
_ATTACKER_VALUES: dict[str, int] = {**PIECE_VALUES, "K": 1000}


# --------------------------------------------------------------------------
# Recherche (J3.2 – J3.5)
# --------------------------------------------------------------------------
# Table de transposition à bornes (J3.3) : un score peut être exact, ou une borne
# inférieure (coupure bêta) / supérieure (aucun coup n'a dépassé alpha).
EXACT: int = 0
LOWER: int = 1
UPPER: int = 2
TT_MAX_ENTRIES: int = 1 << 20  # au-delà, la table est vidée (remplacement simple)
# Nœuds entre deux lectures de l'horloge : ~13 ms à ~19 k nœuds/s, assez fin pour le bullet.
TIME_CHECK_INTERVAL: int = 256
QUIESCENCE_MAX_PLY: int = 16  # garde-fou : la quiescence s'arrête au-delà

# Techniques d'élagage (J10.2), chacune mesurée en mini-ligue à temps égal.
NULL_MOVE_REDUCTION: int = 2  # R du coup nul : recherche à depth - 1 - R
NULL_MOVE_MIN_DEPTH: int = 3
LMR_MIN_DEPTH: int = 3
LMR_MIN_MOVE_INDEX: int = 3  # les coups calmes à partir du 4e sont réduits d'un demi-coup
ASPIRATION_WINDOW: int = 50  # demi-largeur de la fenêtre autour du score précédent (cp)
ASPIRATION_MIN_DEPTH: int = 4


@dataclass(frozen=True, slots=True)
class SearchFeatures:
    """Techniques activées. ``pvs`` : fenêtre nulle après le premier coup ;
    ``aspiration`` : fenêtre étroite autour du score de l'itération précédente ;
    ``null_move`` : coup nul (passer son tour) pour couper tôt les positions trop
    bonnes ; ``lmr`` : réduction de profondeur des coups calmes tardifs."""

    pvs: bool = False
    aspiration: bool = False
    null_move: bool = False
    lmr: bool = False

    @classmethod
    def parse(cls, text: str) -> "SearchFeatures":
        """« pvs,lmr » ; « none » : aucune technique ; « all » : toutes."""
        names = {name.strip() for name in text.split(",") if name.strip()}
        if names == {"none"}:
            return cls()
        if names == {"all"}:
            return cls(True, True, True, True)
        unknown = names - set(cls.__slots__)
        if unknown:
            raise ValueError(f"technique inconnue : {', '.join(sorted(unknown))}")
        return cls(**{name: True for name in names})

    def __str__(self) -> str:
        return ",".join(name for name in self.__slots__ if getattr(self, name)) or "none"


NO_FEATURES = SearchFeatures()
# Pleine force (UCI, analyse, indice) : PVS, coup nul et LMR, +24 Elo [−18, +65] à
# 400 ms par coup sur 192 parties (J10.2). Les fenêtres d'aspiration, sans gain mesurable
# en nœuds, restent coupées. Niveaux et bilan de partie : NO_FEATURES.
DEFAULT_FEATURES = SearchFeatures(pvs=True, null_move=True, lmr=True)


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

    def __init__(self, clock: Any = time.monotonic, features: SearchFeatures | None = None) -> None:
        self.tt: TranspositionTable = {}
        self.clock = clock
        # None : DEFAULT_FEATURES lu à chaque recherche (le moteur UCI peut le changer).
        self._features = features
        self.nodes = 0
        self._deadline: float | None = None
        self._max_nodes: int | None = None
        self._killers: list[list[engine.Move | None]] = []
        self._history: dict[tuple[str, int, int], int] = {}

    # -- interface ------------------------------------------------------
    def think(
        self,
        game_state: engine.GameState,
        limits: SearchLimits,
        on_iteration: Callable[[SearchResult], None] | None = None,
    ) -> SearchResult:
        """Approfondissement itératif jusqu'à ``limits``. ``on_iteration`` reçoit le
        résultat de chaque profondeur achevée, variante principale comprise (J9.1)."""
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
        aspiration = self.features.aspiration
        for depth in range(1, max_depth + 1):
            try:
                if aspiration and depth >= ASPIRATION_MIN_DEPTH and result.depth:
                    score, move = self._aspiration_search(
                        game_state, root_moves, depth, result.score
                    )
                else:
                    score, move = self.negamax(game_state, root_moves, depth, -INF, INF, 0)
            except SearchLimitError:
                break  # profondeur inachevée : on garde le résultat de la précédente
            if move is not None:
                result.move, result.score, result.depth = move, score, depth
                if on_iteration is not None:
                    on_iteration(
                        SearchResult(
                            move,
                            score,
                            depth,
                            self.nodes,
                            int((self.clock() - start) * 1000),
                            self._principal_variation(game_state, depth),
                        )
                    )
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

    @property
    def features(self) -> SearchFeatures:
        return DEFAULT_FEATURES if self._features is None else self._features

    def _aspiration_search(
        self,
        game_state: engine.GameState,
        root_moves: list[engine.Move],
        depth: int,
        previous: int,
    ) -> tuple[int, engine.Move | None]:
        """Fenêtre ±ASPIRATION_WINDOW autour du score précédent ; si le score en sort,
        nouvelle recherche en fenêtre complète."""
        if abs(previous) >= MATE_THRESHOLD:
            return self.negamax(game_state, root_moves, depth, -INF, INF, 0)
        alpha, beta = previous - ASPIRATION_WINDOW, previous + ASPIRATION_WINDOW
        score, move = self.negamax(game_state, root_moves, depth, alpha, beta, 0)
        if alpha < score < beta:
            return score, move
        return self.negamax(game_state, root_moves, depth, -INF, INF, 0)

    def set_limits(self, deadline: float | None, extra_nodes: int | None) -> None:
        """Limites des appels directs à ``negamax`` après ``think`` (réévaluation des
        niveaux) : échéance absolue (horloge du Searcher) et nœuds supplémentaires au-delà
        du compteur actuel. ``SearchLimitError`` est levée quand l'une est atteinte."""
        self._deadline = deadline
        self._max_nodes = None if extra_nodes is None else self.nodes + extra_nodes

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
        valid_moves: list[engine.Move] | None,
        depth: int,
        alpha: int,
        beta: int,
        ply: int,
    ) -> tuple[int, engine.Move | None]:
        """Score du point de vue du camp au trait. ``valid_moves`` = ``get_valid_moves()``
        de la position courante (qui positionne ``checkmate`` / nulles, lus si vide), ou
        ``None`` : ils sont alors générés seulement si besoin (J10.1)."""
        self._tick()
        if depth <= 0:
            return self.quiescence(game_state, valid_moves, alpha, beta, ply), None
        if valid_moves is None:
            valid_moves = game_state.get_valid_moves()
        if not valid_moves:
            return (-MATE + ply if game_state.checkmate else 0), None

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

        features = self.features
        in_check = game_state.in_check
        if (
            features.null_move
            and ply > 0
            and depth >= NULL_MOVE_MIN_DEPTH
            and not in_check
            and beta < MATE_THRESHOLD
            and _has_pieces(game_state)
        ):
            # Passer son tour et rester au-dessus de bêta : la position est trop bonne,
            # l'adversaire évitera d'y entrer. Exclu sans pièce (zugzwang en finale).
            old_enpassant = game_state.make_null_move()
            try:
                score, _ = self.negamax(
                    game_state, None, depth - 1 - NULL_MOVE_REDUCTION, -beta, -beta + 1, ply + 1
                )
            finally:
                game_state.undo_null_move(old_enpassant)
            if -score >= beta:
                return beta, None

        alpha_orig = alpha
        ordered = self._ordered(game_state, valid_moves, tt_move, ply)
        best_score = -INF
        best_move: engine.Move = ordered[0]
        for index, move in enumerate(ordered):
            game_state.make_move(move, validate=False)
            try:
                score = self._search_child(
                    game_state, move, index, depth, alpha, beta, ply, in_check, features
                )
            finally:
                game_state.undo_move()
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

    def _search_child(
        self,
        game_state: engine.GameState,
        move: engine.Move,
        index: int,
        depth: int,
        alpha: int,
        beta: int,
        ply: int,
        in_check: bool,
        features: SearchFeatures,
    ) -> int:
        """Score du coup ``move`` (déjà joué), du point de vue du camp qui l'a joué."""
        if index == 0 or not (features.pvs or features.lmr):
            return -self.negamax(game_state, None, depth - 1, -beta, -alpha, ply + 1)[0]
        new_depth = depth - 1
        if (
            features.lmr
            and ply > 0  # jamais à la racine : un sacrifice calme y serait vu trop tard
            and depth >= LMR_MIN_DEPTH
            and index >= LMR_MIN_MOVE_INDEX
            and not in_check
            and not move.is_capture
            and not move.is_pawn_promotion
            and not game_state.king_in_check()
        ):
            # Coup calme tardif : recherche réduite en fenêtre nulle ; s'il dépasse
            # alpha, il est revu à pleine profondeur.
            score = -self.negamax(game_state, None, new_depth - 1, -alpha - 1, -alpha, ply + 1)[0]
            if score <= alpha:
                return score
        if features.pvs:
            score = -self.negamax(game_state, None, new_depth, -alpha - 1, -alpha, ply + 1)[0]
            if not alpha < score < beta:
                return score
        return -self.negamax(game_state, None, new_depth, -beta, -alpha, ply + 1)[0]

    def quiescence(
        self,
        game_state: engine.GameState,
        valid_moves: list[engine.Move] | None,
        alpha: int,
        beta: int,
        ply: int,
    ) -> int:
        """Prolonge la recherche sur les captures et promotions pour n'évaluer que des
        positions calmes (effet d'horizon, J3.5). En échec, tous les coups sont examinés.

        ``valid_moves`` peut être ``None`` : hors échec, la plupart des positions
        s'arrêtent sur l'évaluation statique, et il suffit alors de savoir qu'un coup
        légal existe ; la liste n'est générée qu'ensuite (J10.1)."""
        if valid_moves is None and not game_state.has_legal_moves():
            # Sans coup légal hors échec : pat ou nulle ; en échec, has_legal_moves a
            # généré les coups et positionné ``checkmate``.
            return -MATE + ply if game_state.checkmate else 0
        if valid_moves is not None and not valid_moves:
            return -MATE + ply if game_state.checkmate else 0
        in_check = game_state.in_check
        if not in_check:
            color = 1 if game_state.white_to_move else -1
            stand_pat = color * score_board(game_state)
            if stand_pat >= beta or ply >= QUIESCENCE_MAX_PLY:
                return stand_pat
            alpha = max(alpha, stand_pat)
            if valid_moves is None:
                valid_moves = game_state.get_valid_moves()
            candidates = [m for m in valid_moves if m.is_capture or m.is_pawn_promotion]
        else:
            candidates = game_state.get_valid_moves() if valid_moves is None else valid_moves
        best = alpha if not in_check else -INF
        for move in sorted(candidates, key=self._capture_order, reverse=True):
            self._tick()
            game_state.make_move(move, validate=False)
            try:
                score = -self.quiescence(game_state, None, -beta, -alpha, ply + 1)
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


def _has_pieces(game_state: engine.GameState) -> bool:
    """Le camp au trait a-t-il une pièce autre que roi et pions ?"""
    ally = "w" if game_state.white_to_move else "b"
    return any(
        piece[0] == ally and piece[1] not in "Kp" for row in game_state.board for piece in row
    )


def _history_key(move: engine.Move) -> tuple[str, int, int]:
    return (move.piece_moved, move.end_row, move.end_col)


def think(
    game_state: engine.GameState,
    limits: SearchLimits,
    searcher: Searcher | None = None,
    on_iteration: Callable[[SearchResult], None] | None = None,
) -> SearchResult:
    """Meilleur coup de la position selon ``limits`` (profondeur, temps, nœuds)."""
    return (searcher or Searcher()).think(game_state, limits, on_iteration)


def find_best_move(
    game_state: engine.GameState,
    valid_moves: list[engine.Move],
    return_queue: Any,
    level_name: str | None = None,
    movetime_ms: int | None = None,
) -> None:
    """Point d'entrée du processus de l'IA (UI, UCI) : dépose le coup choisi dans
    ``return_queue`` — toujours un coup légal s'il en existe un, ``None`` sinon.

    Sans ``level_name``, recherche à profondeur fixe ``DEPTH`` ; sinon, jeu au niveau de
    difficulté nommé (cf. ``chessproject.ai.levels``), avec un temps de réflexion plafonné
    à ``movetime_ms`` s'il est donné (cadence). ``valid_moves`` est conservé pour
    compatibilité : la recherche part de la position. Le livre d'ouvertures n'est pas
    consulté ici : l'interface le lit elle-même, sans lancer de processus (J8.3).
    """
    if not valid_moves:
        return_queue.put(None)
        return
    if level_name is None:
        return_queue.put(think(game_state, SearchLimits(depth=DEPTH)).move)
        return
    from chessproject.ai import levels  # import local : levels importe ce module

    level = levels.LEVELS_BY_NAME[level_name]
    return_queue.put(levels.choose_move(game_state, level, movetime_ms=movetime_ms, use_book=False))


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
    """Évaluation statique en centipions, du point de vue des Blancs (cf. ``evaluate``)."""
    return evaluate.evaluate(game_state)


def find_random_move(valid_moves: list[engine.Move]) -> engine.Move:
    """
    Retourne un coup aléatoire parmi ceux valides.
    """
    return random.choice(valid_moves)
