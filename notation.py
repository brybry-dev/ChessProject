"""
Notation SAN et UCI
-------------------
Conversion entre les ``ChessEngine.Move`` et les deux notations usuelles :

- **UCI** (« notation coordonnée longue ») : ``e2e4``, ``e7e8n``, roque noté par le
  déplacement du roi (``e1g1``) ;
- **SAN** (notation algébrique standard, PGN) : ``Nbd2``, ``exd5``, ``exd8=N``,
  ``O-O-O``, ``Qxf7#``…

Corrige B19 et B35 (``Move.getChessNotation`` / ``Move.__str__`` ne sont pas de la
SAN) sans toucher au moteur : ce module ne s'appuie que sur l'API publique du
``GameState`` (``getValidMoves``, ``makeMove``, ``undoMove``, ``inCheck``).

Correspondance des cases : ``row 0`` = rangée 8, ``col 0`` = colonne a
(cf. ``Move.ranks_to_rows`` / ``Move.files_to_cols``).
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable

from ChessEngine import GameState, Move, Termination


class NotationError(ValueError):
    """Texte de coup illisible, ou coup illégal / ambigu dans la position donnée."""


# --------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------
def square_name(row: int, col: int) -> str:
    """Nom algébrique d'une case du moteur : ``(7, 4)`` → ``"e1"``."""
    return Move.cols_to_files[col] + Move.rows_to_ranks[row]


def parse_square(text: str) -> tuple[int, int]:
    """Case algébrique → ``(row, col)`` du moteur : ``"e1"`` → ``(7, 4)``."""
    if len(text) != 2 or text[0] not in Move.files_to_cols or text[1] not in Move.ranks_to_rows:
        raise NotationError(f"Case invalide : {text!r}")
    return Move.ranks_to_rows[text[1]], Move.files_to_cols[text[0]]


# --------------------------------------------------------------------------
# Accès à la position sans la modifier durablement
# --------------------------------------------------------------------------
def _legal_moves(game_state: GameState) -> list[Move]:
    """Copie de la liste des coups légaux (le moteur la met en cache)."""
    return list(game_state.getValidMoves())


def _find_legal(game_state: GameState, move: Move) -> Move:
    for legal in _legal_moves(game_state):
        if legal == move:
            return legal
    raise NotationError(f"Coup illégal dans la position : {to_uci(move)}")


def _check_suffix(game_state: GameState, move: Move) -> str:
    """``"+"``, ``"#"`` ou ``""`` : joue le coup, observe, puis l'annule.

    Le mat prime sur les nulles automatiques dans le moteur (FIDE 9.3) : un mat donné
    au 100ᵉ demi-coup est donc bien noté « # ».

    ``undoMove`` remet à zéro le statut de fin et vide le cache des coups : ces
    attributs, ainsi que ``in_check`` / ``pins`` / ``checks``, sont restaurés à
    l'identique pour que l'appelant retrouve exactement sa position.
    """
    saved = (
        game_state._valid_moves,
        game_state.checkmate,
        game_state.stalemate,
        game_state.termination,
        game_state.in_check,
        game_state.pins,
        game_state.checks,
    )
    game_state.makeMove(move, validate=False)
    try:
        if not game_state.inCheck():
            return ""
        game_state.getValidMoves()
        return "#" if game_state.termination is Termination.CHECKMATE else "+"
    finally:
        game_state.undoMove()
        (
            game_state._valid_moves,
            game_state.checkmate,
            game_state.stalemate,
            game_state.termination,
            game_state.in_check,
            game_state.pins,
            game_state.checks,
        ) = saved


# --------------------------------------------------------------------------
# UCI
# --------------------------------------------------------------------------
_UCI_RE = re.compile(r"^([a-h][1-8])([a-h][1-8])([qrbn])?$")


def to_uci(move: Move) -> str:
    """Notation UCI : ``"e2e4"``, ``"e7e8n"`` ; roque = déplacement du roi (``"e1g1"``)."""
    text = square_name(move.start_row, move.start_col) + square_name(move.end_row, move.end_col)
    if move.is_pawn_promotion:
        text += (move.promotion_piece or "Q").lower()
    return text


def parse_uci(game_state: GameState, text: str) -> Move:
    """Renvoie le coup légal de ``game_state`` noté ``text`` en UCI.

    Lève ``NotationError`` si le texte est mal formé ou si le coup n'est pas légal
    (y compris une promotion sans pièce, ou une pièce de promotion sur un coup normal).
    """
    match = _UCI_RE.match(text.strip().lower())
    if match is None:
        raise NotationError(f"Coup UCI mal formé : {text!r}")
    start = parse_square(match.group(1))
    end = parse_square(match.group(2))
    promo = match.group(3).upper() if match.group(3) else None
    for move in _legal_moves(game_state):
        if (move.start_row, move.start_col) != start or (move.end_row, move.end_col) != end:
            continue
        if move.promotion_piece == promo:
            return move
    raise NotationError(f"Coup UCI illégal dans la position : {text!r}")


# --------------------------------------------------------------------------
# SAN
# --------------------------------------------------------------------------
def _piece_letter(move: Move) -> str:
    """Lettre SAN de la pièce jouée, ``""`` pour un pion."""
    kind = move.piece_moved[1]
    return "" if kind == "p" else kind


def _disambiguation(move: Move, legal: Iterable[Move]) -> str:
    """Désambiguïsation minimale : colonne, sinon rangée, sinon les deux."""
    rivals = [
        other
        for other in legal
        if other.piece_moved == move.piece_moved
        and (other.end_row, other.end_col) == (move.end_row, move.end_col)
        and (other.start_row, other.start_col) != (move.start_row, move.start_col)
    ]
    if not rivals:
        return ""
    from_square = square_name(move.start_row, move.start_col)
    if all(other.start_col != move.start_col for other in rivals):
        return from_square[0]
    if all(other.start_row != move.start_row for other in rivals):
        return from_square[1]
    return from_square


def _san_without_suffix(move: Move, legal: list[Move]) -> str:
    if move.is_castle_move:
        return "O-O" if move.end_col > move.start_col else "O-O-O"
    target = square_name(move.end_row, move.end_col)
    letter = _piece_letter(move)
    if not letter:
        # Pion : la colonne de départ précède toute prise (en passant compris).
        text = (Move.cols_to_files[move.start_col] + "x" + target) if move.is_capture else target
        if move.is_pawn_promotion:
            text += "=" + (move.promotion_piece or "Q")
        return text
    disamb = "" if letter == "K" else _disambiguation(move, legal)
    return letter + disamb + ("x" if move.is_capture else "") + target


def to_san(game_state: GameState, move: Move) -> str:
    """SAN du coup ``move`` joué dans ``game_state`` (position AVANT le coup).

    La position est rendue intacte (le coup est joué puis annulé pour détecter
    ``+`` / ``#``). Lève ``NotationError`` si le coup n'est pas légal.
    """
    legal = _legal_moves(game_state)
    actual = next((m for m in legal if m == move), None)
    if actual is None:
        raise NotationError(f"Coup illégal dans la position : {to_uci(move)}")
    return _san_without_suffix(actual, legal) + _check_suffix(game_state, actual)


_SAN_RE = re.compile(
    r"^(?P<piece>[KQRBN])?"
    r"(?P<from_file>[a-h])?(?P<from_rank>[1-8])?"
    r"(?P<capture>[x:])?"
    r"(?P<to>[a-h][1-8])"
    r"(?:=?(?P<promo>[QRBNqrbn]))?$"
)
_ANNOTATIONS_RE = re.compile(r"[+#!?]+$")
_EN_PASSANT_RE = re.compile(r"\s*e\.?p\.?$")


def _normalize_san(text: str) -> str:
    san = text.strip()
    san = _ANNOTATIONS_RE.sub("", san)
    san = _EN_PASSANT_RE.sub("", san)
    san = _ANNOTATIONS_RE.sub("", san)  # « exd6 e.p.+ » comme « exd6+ e.p. »
    return san.strip()


def parse_san(game_state: GameState, text: str) -> Move:
    """Renvoie le coup légal de ``game_state`` noté ``text`` en SAN.

    Tolérant : suffixes ``+ # ! ?`` ignorés, ``0-0`` / ``0-0-0`` acceptés, ``e.p.``
    ignoré, promotion avec ou sans ``=``, sur-désambiguïsation (``Ngf3``) et prise sans
    ``x`` acceptées. Lève ``NotationError`` si le texte est illisible, si aucun coup
    légal ne correspond, si plusieurs correspondent (ambiguïté), ou si un ``x`` est
    écrit pour un coup qui ne prend rien.
    """
    san = _normalize_san(text)
    legal = _legal_moves(game_state)

    castle = san.upper().replace("0", "O")
    if castle in ("O-O", "O-O-O"):
        kingside = castle == "O-O"
        for move in legal:
            if move.is_castle_move and (move.end_col > move.start_col) == kingside:
                return move
        raise NotationError(f"Roque illégal dans la position : {text!r}")

    match = _SAN_RE.match(san)
    if match is None:
        raise NotationError(f"Coup SAN mal formé : {text!r}")
    kind = match.group("piece") or "p"
    to_row, to_col = parse_square(match.group("to"))
    from_file = match.group("from_file")
    from_rank = match.group("from_rank")
    promo = match.group("promo").upper() if match.group("promo") else None
    if promo is not None and kind != "p":
        raise NotationError(f"Seul un pion peut être promu : {text!r}")

    candidates = [
        move
        for move in legal
        if move.piece_moved[1] == kind
        and not move.is_castle_move
        and (move.end_row, move.end_col) == (to_row, to_col)
        and (from_file is None or Move.files_to_cols[from_file] == move.start_col)
        and (from_rank is None or Move.ranks_to_rows[from_rank] == move.start_row)
        and move.promotion_piece == promo
        # Pion sans colonne de départ : une poussée (une prise s'écrit « exd5 »).
        and (kind != "p" or from_file is not None or move.start_col == to_col)
    ]
    if not candidates:
        raise NotationError(f"Aucun coup légal ne correspond à {text!r}")
    if len(candidates) > 1:
        raise NotationError(f"Coup SAN ambigu : {text!r}")
    move = candidates[0]
    if match.group("capture") and not move.is_capture:
        raise NotationError(f"« x » pour un coup sans prise : {text!r}")
    return move


# --------------------------------------------------------------------------
# Historique
# --------------------------------------------------------------------------
def move_list_to_san(start_state: GameState, moves: Iterable[Move]) -> list[str]:
    """SAN de chaque coup de ``moves``, rejoués depuis ``start_state`` (laissé intact).

    Les coups sont rejoués sur une ``copy.deepcopy`` de la position et non sur un
    aller-retour FEN (``load_fen(to_fen(...))``) : la FEN perd l'historique des
    positions (triple répétition), le compteur des 50 coups (``load_fen`` le remet à
    zéro) et le journal des coups, or ces données font partie de la légalité dans ce
    moteur (nulles automatiques) et donc du « # » / « + » et des coups possibles.

    Lève ``NotationError`` dès qu'un coup est illégal à son tour.
    """
    game_state = copy.deepcopy(start_state)
    result: list[str] = []
    for move in moves:
        actual = _find_legal(game_state, move)
        result.append(to_san(game_state, actual))
        game_state.makeMove(actual, validate=False)
    return result


def san_history(game_state: GameState) -> list[str]:
    """SAN de tous les coups joués dans ``game_state`` (laissé intact).

    Une copie est ramenée à la position de départ par annulations successives,
    puis la partie y est rejouée : fonctionne aussi pour une partie chargée.
    """
    start = copy.deepcopy(game_state)
    for _ in range(len(start.move_log)):
        start.undoMove()
    return move_list_to_san(start, game_state.move_log)


def format_move_lines(sans: list[str], start_fullmove: int, white_starts: bool) -> list[str]:
    """Lignes numérotées de l'historique : ``"1. e4 e5"``, ``"12... Nf6"`` si les Noirs
    commencent."""
    lines: list[str] = []
    number = start_fullmove
    index = 0
    if not white_starts and sans:
        lines.append(f"{number}... {sans[0]}")
        number, index = number + 1, 1
    while index < len(sans):
        lines.append(" ".join([f"{number}.", *sans[index : index + 2]]))
        number, index = number + 1, index + 2
    return lines


__all__ = [
    "NotationError",
    "format_move_lines",
    "move_list_to_san",
    "san_history",
    "parse_san",
    "parse_square",
    "parse_uci",
    "square_name",
    "to_san",
    "to_uci",
]
