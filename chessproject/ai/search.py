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

# Table de transposition : seuls les scores EXACTS (ni coupure bêta, ni échec bas) et hors
# mat y sont stockés, ce qui la rend sûre sans gérer les bornes (prévu en J3.3).
EXACT: int = 0


@dataclass(slots=True)
class TTEntry:
    depth: int
    score: int
    flag: int
    best_move: engine.Move | None


TranspositionTable = dict[str, TTEntry]


def find_best_move(
    game_state: engine.GameState, valid_moves: list[engine.Move], return_queue: Any
) -> None:
    """
    Cherche le meilleur coup en itérant en profondeur et le dépose dans ``return_queue``.
    Dépose toujours un coup légal s'il en existe un (``None`` sinon).
    """
    if not valid_moves:
        return_queue.put(None)
        return
    best_move: engine.Move = valid_moves[0]
    transposition_table: TranspositionTable = {}
    for current_depth in range(1, DEPTH + 1):
        score, move = negamax(
            game_state, valid_moves, current_depth, -INF, INF, 0, transposition_table
        )
        if move is not None:
            best_move = move
        # Un mat gagnant trouvé à cette profondeur est le plus court possible : inutile
        # d'aller plus loin.
        if score >= MATE_THRESHOLD:
            break
    return_queue.put(best_move)


def negamax(
    game_state: engine.GameState,
    valid_moves: list[engine.Move],
    depth: int,
    alpha: int,
    beta: int,
    ply: int,
    transposition_table: TranspositionTable,
) -> tuple[int, engine.Move | None]:
    """
    NegaMax avec élagage alpha-bêta.

    ``valid_moves`` doit être le résultat de ``game_state.get_valid_moves()`` pour la position
    courante : cet appel positionne ``checkmate`` / ``stalemate`` (nulles automatiques
    comprises), lus ici quand la liste est vide. Le score renvoyé est du point de vue du
    camp au trait. À la racine (``ply == 0``), le coup renvoyé n'est jamais ``None`` s'il
    existe un coup légal.
    """
    if not valid_moves:
        # Mat : le camp au trait a perdu, d'autant plus tard que ply est grand.
        # Sinon (pat, 50 coups, répétition, matériel insuffisant) : nulle.
        return (-MATE + ply if game_state.checkmate else 0), None
    if depth <= 0:
        color = 1 if game_state.white_to_move else -1
        return color * score_board(game_state), None

    board_hash = game_state.get_board_hash_str()
    entry = transposition_table.get(board_hash)
    tt_move: engine.Move | None = None
    if entry is not None:
        tt_move = entry.best_move
        # Jamais de court-circuit à la racine : il faut un coup, pas seulement un score.
        if ply > 0 and entry.flag == EXACT and entry.depth >= depth:
            return entry.score, entry.best_move

    alpha_orig = alpha
    ordered = sorted(
        valid_moves,
        key=lambda m: (m == tt_move, move_ordering_heuristic(game_state, m)),
        reverse=True,
    )
    max_score = -INF
    best_move: engine.Move = ordered[0]
    for move in ordered:
        game_state.make_move(move, validate=False)
        next_moves = game_state.get_valid_moves()
        score, _ = negamax(
            game_state, next_moves, depth - 1, -beta, -alpha, ply + 1, transposition_table
        )
        score = -score
        game_state.undo_move()
        if score > max_score:
            max_score = score
            best_move = move
        alpha = max(alpha, score)
        if alpha >= beta:
            break

    # Stockage : uniquement un score exact (strictement dans la fenêtre d'origine) et pas un
    # score de mat (il dépend du ply, il faudrait le ré-ajuster à la relecture).
    if alpha_orig < max_score < beta and abs(max_score) < MATE_THRESHOLD:
        transposition_table[board_hash] = TTEntry(depth, max_score, EXACT, best_move)
    elif entry is None:
        # Score non exact : on ne garde que le coup, pour l'ordonnancement.
        transposition_table[board_hash] = TTEntry(-1, 0, -1, best_move)
    return max_score, best_move


def move_ordering_heuristic(game_state: engine.GameState, move: engine.Move) -> int:
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
