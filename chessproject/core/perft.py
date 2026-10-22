"""
Perft
-----
Comptage des nœuds de l'arbre des coups légaux : validation de référence du
générateur de coups (cf. tests/test_perft.py).
"""

from chessproject.core import engine


def perft(game_state: engine.GameState, depth: int) -> int:
    """Compte les nœuds feuilles de l'arbre des coups légaux jusqu'à ``depth``."""
    if depth == 0:
        return 1
    total = 0
    for move in list(game_state.get_valid_moves()):
        game_state.make_move(move, validate=False)
        total += perft(game_state, depth - 1)
        game_state.undo_move()
    return total


def perft_divide(game_state: engine.GameState, depth: int) -> "dict[str, int]":
    """perft détaillé par coup racine (utile au diagnostic)."""
    result: dict[str, int] = {}
    for move in list(game_state.get_valid_moves()):
        game_state.make_move(move, validate=False)
        result[move.get_chess_notation()] = perft(game_state, depth - 1)
        game_state.undo_move()
    return result
