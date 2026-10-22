"""
Module ChessAI
----------------
Recherche NegaMax avec élagage alpha-bêta, approfondissement itératif et une table de
transposition simple.

Conventions de score :
  - ``negamax`` renvoie un score du point de vue du camp **au trait** (positif = bon pour
    lui) ;
  - ``scoreBoard`` renvoie un score du point de vue des **Blancs** (positif = avantage
    blanc) ;
  - un mat se note ``MATE - ply`` (``ply`` = distance à la racine, en demi-coups) : plus le
    mat est proche, plus le score est grand, ce qui fait préférer le mat le plus court ;
  - les bornes de recherche ``±INF`` sont strictement au-delà de tout score de mat.
"""

import random
from dataclasses import dataclass
from typing import Any

import ChessEngine

INF: int = 10**6  # Borne de la fenêtre alpha-bêta, strictement supérieure à MATE
MATE: int = 100_000  # Score d'un mat à la racine ; un mat à `ply` demi-coups vaut MATE - ply
MAX_PLY: int = 128  # Profondeur maximale envisageable : sert de seuil pour reconnaître un mat
MATE_THRESHOLD: int = MATE - MAX_PLY  # |score| >= MATE_THRESHOLD <=> score de mat
DEPTH: int = 3  # Profondeur maximale

CHECKMATE: int = 1000  # Échelle de l'évaluation actuelle (unités de pion)

# Table de transposition : seuls les scores EXACTS (ni coupure bêta, ni échec bas) et hors
# mat y sont stockés, ce qui la rend sûre sans gérer les bornes (prévu en J3.3).
EXACT: int = 0


@dataclass(slots=True)
class TTEntry:
    depth: int
    score: int
    flag: int
    best_move: ChessEngine.Move | None


TranspositionTable = dict[str, TTEntry]


def findBestMove(
    game_state: ChessEngine.GameState, valid_moves: list[ChessEngine.Move], return_queue: Any
) -> None:
    """
    Cherche le meilleur coup en itérant en profondeur et le dépose dans ``return_queue``.
    Dépose toujours un coup légal s'il en existe un (``None`` sinon).
    """
    if not valid_moves:
        return_queue.put(None)
        return
    best_move: ChessEngine.Move = valid_moves[0]
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
    game_state: ChessEngine.GameState,
    valid_moves: list[ChessEngine.Move],
    depth: int,
    alpha: int,
    beta: int,
    ply: int,
    transposition_table: TranspositionTable,
) -> tuple[int, ChessEngine.Move | None]:
    """
    NegaMax avec élagage alpha-bêta.

    ``valid_moves`` doit être le résultat de ``game_state.getValidMoves()`` pour la position
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
        return color * scoreBoard(game_state), None

    board_hash = game_state.get_board_hash_str()
    entry = transposition_table.get(board_hash)
    tt_move: ChessEngine.Move | None = None
    if entry is not None:
        tt_move = entry.best_move
        # Jamais de court-circuit à la racine : il faut un coup, pas seulement un score.
        if ply > 0 and entry.flag == EXACT and entry.depth >= depth:
            return entry.score, entry.best_move

    alpha_orig = alpha
    ordered = sorted(
        valid_moves,
        key=lambda m: (m == tt_move, moveOrderingHeuristic(game_state, m)),
        reverse=True,
    )
    max_score = -INF
    best_move: ChessEngine.Move = ordered[0]
    for move in ordered:
        game_state.makeMove(move, validate=False)
        next_moves = game_state.getValidMoves()
        score, _ = negamax(
            game_state, next_moves, depth - 1, -beta, -alpha, ply + 1, transposition_table
        )
        score = -score
        game_state.undoMove()
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


def moveOrderingHeuristic(game_state: ChessEngine.GameState, move: ChessEngine.Move) -> int:
    """
    Calcule un score pour ordonner les coups.
    Si le coup mène à une position déjà vue, on applique une pénalité.
    """
    score = 0
    if move.is_capture:
        score += 10 + ChessEngine.piece_score.get(move.piece_captured[1], 0)
    if move.is_pawn_promotion:
        score += 15
    # Simulation pour détecter la répétition
    game_state.makeMove(move, validate=False)
    pos_hash = game_state.get_board_hash_str()
    game_state.undoMove()
    if pos_hash in game_state.position_history:
        score -= 20  # Pénalité pour position répétée
    return score


def scoreBoard(game_state: ChessEngine.GameState) -> int:
    """
    Évalue le plateau en prenant en compte plusieurs critères :
      - Valeur matérielle et positionnelle
      - Contrôle du centre (bonus pour les pièces sur les cases centrales)
      - Sécurité du roi (pénalité si des pièces ennemies se trouvent autour du roi)
      - Mobilité (bonus pour un grand nombre de coups possibles)
    """
    if game_state.checkmate:
        return -CHECKMATE if game_state.white_to_move else CHECKMATE
    elif game_state.stalemate:
        return 0

    total_score: float = 0
    center_bonus: float = 0.5
    center_squares: list[tuple[int, int]] = [(3, 3), (3, 4), (4, 3), (4, 4)]

    # Valeur matériel et positionnelle
    for r in range(ChessEngine.DIMENSION):
        for c in range(ChessEngine.DIMENSION):
            piece = game_state.board[r][c]
            if piece != "--":
                piece_value = ChessEngine.piece_score.get(piece[1], 0)
                position_score: float = 0
                if piece[1] != "K":
                    position_score = ChessEngine.piece_position_scores.get(
                        piece, [[0] * ChessEngine.DIMENSION] * ChessEngine.DIMENSION
                    )[r][c]
                # Bonus pour le contrôle du centre
                if (r, c) in center_squares:
                    position_score += center_bonus
                if piece[0] == "w":
                    total_score += piece_value + position_score
                else:
                    total_score -= piece_value + position_score

    # Sécurité du roi : pénalité si des pièces ennemies sont adjacentes
    king_safety_penalty: float = 0
    adjacent_offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    if game_state.white_to_move:
        king_row, king_col = game_state.white_king_location
        enemy_color = "b"
    else:
        king_row, king_col = game_state.black_king_location
        enemy_color = "w"
    for dr, dc in adjacent_offsets:
        nr, nc = king_row + dr, king_col + dc
        if 0 <= nr < ChessEngine.DIMENSION and 0 <= nc < ChessEngine.DIMENSION:
            adj_piece = game_state.board[nr][nc]
            if adj_piece != "--" and adj_piece[0] == enemy_color:
                king_safety_penalty += 0.5
    if game_state.white_to_move:
        total_score -= king_safety_penalty
    else:
        total_score += king_safety_penalty

    # Mobilité : bonus proportionnel au nombre de coups disponibles
    mobility_bonus = 0.1 * len(game_state.getValidMoves())
    if game_state.white_to_move:
        total_score += mobility_bonus
    else:
        total_score -= mobility_bonus

    return int(total_score)


def get_board_hash(board: list[list[str]], white_to_move: bool) -> int:
    """
    Génère un hash pour l'état du plateau.
    """
    board_tuple = tuple(tuple(row) for row in board)
    return hash((board_tuple, white_to_move))


def findRandomMove(valid_moves: list[ChessEngine.Move]) -> ChessEngine.Move:
    """
    Retourne un coup aléatoire parmi ceux valides.
    """
    return random.choice(valid_moves)
