"""
Module ChessAI
----------------
"""

import random
from typing import Any

import ChessEngine

CHECKMATE: int = 1000
DEPTH: int = 3  # Profondeur maximale


def findBestMove(
    game_state: ChessEngine.GameState, valid_moves: list[ChessEngine.Move], return_queue: Any
) -> None:
    """
    Cherche le meilleur coup en itérant en profondeur.
    """
    best_move: ChessEngine.Move | None = None
    transposition_table: dict[str, dict[str, Any]] = {}
    for current_depth in range(1, DEPTH + 1):
        best_score, best_move = negamax(
            game_state,
            valid_moves,
            current_depth,
            -CHECKMATE,
            CHECKMATE,
            1 if game_state.white_to_move else -1,
            transposition_table,
        )
    return_queue.put(best_move)


def negamax(
    game_state: ChessEngine.GameState,
    valid_moves: list[ChessEngine.Move],
    depth: int,
    alpha: int,
    beta: int,
    turn_multiplier: int,
    transposition_table: dict[str, dict[str, Any]],
) -> tuple[int, ChessEngine.Move | None]:
    """
    Fonction récursive NegaMax avec élagage alpha‑beta.
    """
    board_hash = game_state.get_board_hash_str()
    if board_hash in transposition_table and transposition_table[board_hash]["depth"] >= depth:
        return transposition_table[board_hash]["score"], None
    if depth == 0:
        return turn_multiplier * scoreBoard(game_state), None

    valid_moves.sort(key=lambda move: moveOrderingHeuristic(game_state, move), reverse=True)
    max_score: int = -CHECKMATE
    best_move: ChessEngine.Move | None = None
    for move in valid_moves:
        game_state.makeMove(move, validate=False)
        next_moves = game_state.getValidMoves()
        score, _ = negamax(
            game_state, next_moves, depth - 1, -beta, -alpha, -turn_multiplier, transposition_table
        )
        score = -score
        game_state.undoMove()
        if score > max_score:
            max_score = score
            best_move = move
        alpha = max(alpha, score)
        if alpha >= beta:
            break
    transposition_table[board_hash] = {"score": max_score, "depth": depth}
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
      - Pénalité en cas de répétition de position
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

    # Pénalité pour répétition de position
    pos_hash = game_state.get_board_hash_str()
    repetition = game_state.position_history.get(pos_hash, 0)
    if repetition:
        total_score -= repetition * 10

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
