"""
Utilitaires FEN
---------------
Chargement d'une position au format FEN vers un ``ChessEngine.GameState``.
Utilisé par la suite de tests (perft, non-régression). Ne gère que ce qui est
nécessaire au moteur : plateau, trait, droits de roque, case d'en passant.
"""

import ChessEngine


def load_fen(fen: str) -> ChessEngine.GameState:
    """Construit un GameState à partir d'une chaîne FEN."""
    board_part, turn, castling, enpassant = fen.split()[:4]

    board = []
    for fen_row in board_part.split("/"):
        row = []
        for ch in fen_row:
            if ch.isdigit():
                row.extend(["--"] * int(ch))
            else:
                color = "w" if ch.isupper() else "b"
                kind = "p" if ch.upper() == "P" else ch.upper()
                row.append(color + kind)
        if len(row) != ChessEngine.DIMENSION:
            raise ValueError(f"Rangée FEN invalide : {fen_row!r}")
        board.append(row)
    if len(board) != ChessEngine.DIMENSION:
        raise ValueError("La FEN doit décrire 8 rangées")

    gs = ChessEngine.GameState()
    gs.board = board
    gs.white_to_move = turn == "w"
    gs.current_castling_rights = ChessEngine.CastleRights(
        "K" in castling, "k" in castling, "Q" in castling, "q" in castling
    )
    gs.castle_rights_log = [
        ChessEngine.CastleRights(
            gs.current_castling_rights.wks,
            gs.current_castling_rights.bks,
            gs.current_castling_rights.wqs,
            gs.current_castling_rights.bqs,
        )
    ]

    if enpassant != "-":
        col = ord(enpassant[0]) - ord("a")
        row = ChessEngine.DIMENSION - int(enpassant[1])
        gs.enpassant_possible = (row, col)  # type: ignore[assignment]
    else:
        gs.enpassant_possible = ()  # type: ignore[assignment]
    gs.enpassant_possible_log = [gs.enpassant_possible]

    for r in range(ChessEngine.DIMENSION):
        for c in range(ChessEngine.DIMENSION):
            if gs.board[r][c] == "wK":
                gs.white_king_location = (r, c)
            elif gs.board[r][c] == "bK":
                gs.black_king_location = (r, c)

    gs.move_log = []
    gs.fifty_move_counter = 0
    gs.fifty_move_counter_log = [0]
    gs.position_history = {}
    gs.position_history_log = [{}]
    gs._valid_moves = None
    gs._update_position_history()
    return gs


def perft(game_state: ChessEngine.GameState, depth: int) -> int:
    """Compte les nœuds feuilles de l'arbre des coups légaux jusqu'à ``depth``."""
    if depth == 0:
        return 1
    total = 0
    for move in list(game_state.getValidMoves()):
        game_state.makeMove(move, validate=False)
        total += perft(game_state, depth - 1)
        game_state.undoMove()
    return total


def perft_divide(game_state: ChessEngine.GameState, depth: int) -> "dict[str, int]":
    """perft détaillé par coup racine (utile au diagnostic)."""
    result: dict[str, int] = {}
    for move in list(game_state.getValidMoves()):
        game_state.makeMove(move, validate=False)
        result[move.getChessNotation()] = perft(game_state, depth - 1)
        game_state.undoMove()
    return result
