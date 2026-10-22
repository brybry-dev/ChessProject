"""
Utilitaires FEN
---------------
Chargement **validé** d'une position au format FEN vers un ``ChessEngine.GameState``
(cf. rapport d'analyse B36, B41). Toute FEN mal formée ou décrivant une position
illégale lève une :class:`FenError` au message explicite : la FEN d'une sauvegarde
JSON (``start_fen``), modifiable à la main, ne peut donc plus introduire un état
incohérent dans le moteur.

Les compteurs sont pris en compte : le champ demi-coups initialise
``fifty_move_counter`` ; le numéro de coup initialise ``GameState.start_fullmove``.

``perft`` / ``perft_divide`` restent ici provisoirement (importés par les tests).
"""

import ChessEngine

DIMENSION = ChessEngine.DIMENSION
FILES = "abcdefgh"
PIECE_CHARS = "PNBRQKpnbrqk"


class FenError(ValueError):
    """FEN mal formée ou décrivant une position illégale."""


def start_fullmove(game_state: ChessEngine.GameState) -> int:
    """Numéro de coup de la position de départ du ``game_state``."""
    return game_state.start_fullmove


def _square_name(row: int, col: int) -> str:
    return f"{FILES[col]}{DIMENSION - row}"


def _parse_board(board_part: str) -> list[list[str]]:
    fen_rows = board_part.split("/")
    if len(fen_rows) != DIMENSION:
        raise FenError(f"Le plateau doit décrire 8 rangées, {len(fen_rows)} trouvée(s)")
    board: list[list[str]] = []
    for index, fen_row in enumerate(fen_rows):
        rank = DIMENSION - index
        row: list[str] = []
        for ch in fen_row:
            if ch in "12345678":
                row.extend(["--"] * int(ch))
            elif ch in PIECE_CHARS:
                color = "w" if ch.isupper() else "b"
                kind = "p" if ch.upper() == "P" else ch.upper()
                row.append(color + kind)
            else:
                raise FenError(f"Caractère invalide {ch!r} dans la rangée {rank} : {fen_row!r}")
        if len(row) != DIMENSION:
            raise FenError(f"La rangée {rank} ({fen_row!r}) compte {len(row)} case(s) au lieu de 8")
        board.append(row)
    return board


def _find_king(board: list[list[str]], piece: str, side: str) -> tuple[int, int]:
    squares = [(r, c) for r in range(DIMENSION) for c in range(DIMENSION) if board[r][c] == piece]
    if len(squares) != 1:
        raise FenError(f"Il faut exactement un roi {side}, {len(squares)} trouvé(s)")
    return squares[0]


# Droit de roque -> (case du roi, case de la tour, roi attendu, tour attendue)
_CASTLING_REQUIREMENTS = {
    "K": ((7, 4), (7, 7), "wK", "wR"),
    "Q": ((7, 4), (7, 0), "wK", "wR"),
    "k": ((0, 4), (0, 7), "bK", "bR"),
    "q": ((0, 4), (0, 0), "bK", "bR"),
}


def _parse_castling(castling: str, board: list[list[str]]) -> ChessEngine.CastleRights:
    if castling == "-":
        return ChessEngine.CastleRights(False, False, False, False)
    if any(ch not in "KQkq" for ch in castling):
        raise FenError(f"Champ de roque invalide : {castling!r} (attendu ⊂ 'KQkq' ou '-')")
    if len(set(castling)) != len(castling):
        raise FenError(f"Champ de roque invalide : {castling!r} (droit en double)")
    for right in castling:
        (kr, kc), (rr, rc), king, rook = _CASTLING_REQUIREMENTS[right]
        if board[kr][kc] != king or board[rr][rc] != rook:
            raise FenError(
                f"Droit de roque {right!r} incohérent : roi attendu en {_square_name(kr, kc)} "
                f"et tour en {_square_name(rr, rc)}"
            )
    return ChessEngine.CastleRights(
        "K" in castling, "k" in castling, "Q" in castling, "q" in castling
    )


def _parse_enpassant(
    enpassant: str, board: list[list[str]], white_to_move: bool
) -> tuple[int, int] | None:
    """Case en passant : syntaxe, puis plausibilité (un pion adverse vient d'avancer de 2)."""
    if enpassant == "-":
        return None
    if len(enpassant) != 2 or enpassant[0] not in FILES or enpassant[1] not in "12345678":
        raise FenError(f"Case en passant invalide : {enpassant!r}")
    expected_rank = 6 if white_to_move else 3
    if int(enpassant[1]) != expected_rank:
        side = "Blancs" if white_to_move else "Noirs"
        raise FenError(
            f"Case en passant {enpassant!r} impossible : rangée {expected_rank} attendue "
            f"quand les {side} ont le trait"
        )
    col = FILES.index(enpassant[0])
    row = DIMENSION - expected_rank
    # Le pion adverse qui vient d'avancer de deux cases est juste « devant » la case
    # (vu du camp au trait) ; la case traversée et sa case de départ sont vides.
    pawn_row, origin_row = (row + 1, row - 1) if white_to_move else (row - 1, row + 1)
    enemy_pawn = "bp" if white_to_move else "wp"
    if board[row][col] != "--" or board[origin_row][col] != "--":
        raise FenError(
            f"Case en passant {enpassant!r} impossible : {enpassant} et "
            f"{_square_name(origin_row, col)} doivent être vides"
        )
    if board[pawn_row][col] != enemy_pawn:
        raise FenError(
            f"Case en passant {enpassant!r} impossible : pas de pion adverse en "
            f"{_square_name(pawn_row, col)}"
        )
    return (row, col)


def _parse_counter(value: str, name: str, minimum: int) -> int:
    # isdigit() + isascii() : refuse signe, espaces et chiffres non ASCII.
    if not (value.isascii() and value.isdigit()) or int(value) < minimum:
        raise FenError(f"Compteur {name} invalide : {value!r} (entier ≥ {minimum} attendu)")
    return int(value)


def load_fen(fen: str) -> ChessEngine.GameState:
    """Construit un GameState à partir d'une chaîne FEN, après validation.

    Accepte 6 champs, ou 4 (compteurs omis : demi-coups 0, coup 1). Lève
    :class:`FenError` si la FEN est mal formée ou si la position est illégale :
    plateau (8 rangées de 8 cases, caractères de pièce), un roi par camp, aucun
    pion sur les rangées 1 et 8, trait, droits de roque cohérents avec le roi et
    la tour en place, case en passant plausible, camp sans trait non en échec,
    compteurs entiers (demi-coups ≥ 0, coup ≥ 1).
    """
    fields = fen.split()
    if len(fields) == 4:
        fields += ["0", "1"]
    if len(fields) != 6:
        raise FenError(f"Une FEN compte 4 ou 6 champs, {len(fields)} trouvé(s) : {fen!r}")
    board_part, turn, castling, enpassant, halfmove_str, fullmove_str = fields

    board = _parse_board(board_part)
    white_king = _find_king(board, "wK", "blanc")
    black_king = _find_king(board, "bK", "noir")
    for row in (0, DIMENSION - 1):
        if any(piece[1] == "p" for piece in board[row]):
            raise FenError(f"Pion interdit sur la rangée {DIMENSION - row}")
    if turn not in ("w", "b"):
        raise FenError(f"Trait invalide : {turn!r} (attendu 'w' ou 'b')")
    white_to_move = turn == "w"
    rights = _parse_castling(castling, board)
    enpassant_square = _parse_enpassant(enpassant, board, white_to_move)
    halfmove = _parse_counter(halfmove_str, "de demi-coups", 0)
    fullmove = _parse_counter(fullmove_str, "de coups", 1)

    gs = ChessEngine.GameState()
    gs.board = board
    gs.white_king_location = white_king
    gs.black_king_location = black_king

    # Le camp qui n'a pas le trait ne peut pas être en échec (son roi serait pris) :
    # on inverse temporairement le trait pour réutiliser inCheck().
    gs.white_to_move = not white_to_move
    if gs.inCheck():
        side = "noir" if white_to_move else "blanc"
        raise FenError(f"Position illégale : le roi {side} est en échec sans avoir le trait")
    gs.white_to_move = white_to_move

    gs.current_castling_rights = rights
    gs.enpassant_possible = enpassant_square
    gs.fifty_move_counter = halfmove
    gs.start_fullmove = fullmove
    gs.reset_history()
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
