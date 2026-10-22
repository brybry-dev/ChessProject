"""
Sérialisation des parties
-------------------------
Sauvegarde / chargement d'une partie au format JSON : position de départ
+ liste des coups joués + orientation d'affichage.

Remplace l'ancienne sauvegarde ``pickle`` (cf. rapport d'analyse B17) :
``pickle`` recharge un objet arbitraire sans contrôle de schéma et constitue
un risque de sécurité si le fichier provient d'ailleurs. Le format JSON ici
est lisible, versionné et rejoue les coups par le moteur, donc toujours
cohérent avec les règles courantes.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from chessproject.core import engine
from chessproject.core.fen import load_fen, start_fullmove

logger = logging.getLogger(__name__)

# v2 : ``flip_board`` n'est plus qu'une préférence d'affichage, la position est
# toujours standard. v1 : en mode retourné, la position était le miroir
# (colonnes inversées, roi et dame permutés) de la vraie partie (cf. B26).
SAVE_VERSION = 2
SUPPORTED_VERSIONS = (1, 2)
DEFAULT_SAVE_FILE = "saved_game.json"


def _piece_to_fen_char(piece: str) -> str:
    letter = "P" if piece[1] == "p" else piece[1]
    return letter.upper() if piece[0] == "w" else letter.lower()


def fullmove_number(game_state: engine.GameState) -> int:
    """Numéro de coup FEN de la position courante (cf. B36).

    ``start_fullmove + (demi-coups joués + (1 si la position de départ avait les
    Noirs au trait)) // 2``. Le numéro de départ vient de la FEN chargée
    (:func:`chessproject.core.fen.start_fullmove`, 1 par défaut). Le camp au trait au départ
    se déduit du trait courant et de la parité du nombre de demi-coups joués.
    """
    plies = len(game_state.move_log)
    start_black = (not game_state.white_to_move) == (plies % 2 == 0)
    return start_fullmove(game_state) + (plies + int(start_black)) // 2


def to_fen(game_state: engine.GameState) -> str:
    """Retourne la FEN complète (6 champs) de la position courante.

    - Roque : droits tels que stockés par le moteur (cases standard roi/tour).
    - En passant : la case est écrite **telle que stockée** par le moteur, qui la
      pose après toute avance de deux cases d'un pion, qu'une prise en passant soit
      possible ou non (convention FEN d'origine, et non celle « seulement si la prise
      est légale » de certains moteurs). ``load_fen`` relit cette case à l'identique.
    - Demi-coups : ``fifty_move_counter`` ; numéro de coup : :func:`fullmove_number`.
    """
    rows: list[str] = []
    for board_row in game_state.board:
        fen_row = ""
        empties = 0
        for piece in board_row:
            if piece == "--":
                empties += 1
                continue
            if empties:
                fen_row += str(empties)
                empties = 0
            fen_row += _piece_to_fen_char(piece)
        if empties:
            fen_row += str(empties)
        rows.append(fen_row)
    board_part = "/".join(rows)

    turn = "w" if game_state.white_to_move else "b"

    cr = game_state.current_castling_rights
    castling = (
        ("K" if cr.wks else "")
        + ("Q" if cr.wqs else "")
        + ("k" if cr.bks else "")
        + ("q" if cr.bqs else "")
    )
    castling = castling or "-"

    ep = game_state.enpassant_possible
    if ep:
        enpassant = chr(ord("a") + ep[1]) + str(engine.DIMENSION - ep[0])
    else:
        enpassant = "-"

    halfmove = game_state.fifty_move_counter
    fullmove = fullmove_number(game_state)
    return f"{board_part} {turn} {castling} {enpassant} {halfmove} {fullmove}"


def game_to_dict(
    game_state: engine.GameState, flip_board: bool = False, start_fen: str | None = None
) -> dict[str, Any]:
    """Sérialise la partie : position de départ + liste des coups.

    ``start_fen`` par défaut = position initiale standard. Le donner explicitement
    permet de sauvegarder une partie commencée depuis une position arbitraire
    (chargée par FEN). ``flip_board`` n'est qu'une préférence d'affichage.
    """
    if start_fen is None:
        start_fen = to_fen(engine.GameState())
    moves: list[list[Any | None]] = [
        [m.start_row, m.start_col, m.end_row, m.end_col, m.promotion_piece]
        for m in game_state.move_log
    ]
    return {
        "version": SAVE_VERSION,
        "flip_board": bool(flip_board),
        "start_fen": start_fen,
        "moves": moves,
        "fen": to_fen(game_state),
    }


def save_game(
    game_state: engine.GameState,
    flip_board: bool = False,
    filename: str = DEFAULT_SAVE_FILE,
    start_fen: str | None = None,
) -> None:
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(game_to_dict(game_state, flip_board, start_fen), f, indent=2)
        logger.info("Partie sauvegardée dans %s", filename)
    except Exception as e:  # noqa: BLE001 - on journalise et on continue
        logger.error("Erreur lors de la sauvegarde : %s", e)


def _find_move(
    game_state: engine.GameState,
    start_row: int,
    start_col: int,
    end_row: int,
    end_col: int,
    promotion: str | None,
) -> engine.Move:
    for move in game_state.get_valid_moves():
        if (move.start_row, move.start_col, move.end_row, move.end_col) != (
            start_row,
            start_col,
            end_row,
            end_col,
        ):
            continue
        if move.is_pawn_promotion and promotion is not None and move.promotion_piece != promotion:
            continue
        return move
    raise ValueError(
        f"Coup enregistré illégal dans la position : "
        f"({start_row},{start_col})->({end_row},{end_col}) promo={promotion}"
    )


def _mirror_fen_files(fen: str) -> str:
    """Reflète une FEN selon l'axe vertical (colonne a <-> h).

    Sert à migrer les sauvegardes v1 en mode retourné, dont la position était
    le miroir de la vraie partie. Les droits de roque côté roi et côté dame
    s'échangent, la case en passant est reflétée ; les compteurs sont conservés.
    """
    fields = fen.split()
    # Une rangée FEN se reflète en inversant ses caractères (les chiffres sont
    # des longueurs de cases vides, toujours sur un seul caractère).
    fields[0] = "/".join(rank[::-1] for rank in fields[0].split("/"))
    if len(fields) > 2 and fields[2] != "-":
        swap = {"K": "Q", "Q": "K", "k": "q", "q": "k"}
        mirrored = "".join(swap[c] for c in fields[2])
        fields[2] = "".join(c for c in "KQkq" if c in mirrored)
    if len(fields) > 3 and fields[3] != "-":
        fields[3] = chr(ord("a") + ord("h") - ord(fields[3][0])) + fields[3][1:]
    return " ".join(fields)


def load_game(filename: str = DEFAULT_SAVE_FILE) -> tuple[engine.GameState, bool]:
    """Recharge une partie et renvoie ``(game_state, flip_board)``.

    Rejoue les coups depuis la position de départ : l'état obtenu est donc
    toujours conforme aux règles courantes du moteur. Une ``start_fen`` mal
    formée ou illégale lève :class:`chessproject.core.fen.FenError` (cf. B41).
    """
    with open(filename, encoding="utf-8") as f:
        data = json.load(f)

    version = data.get("version")
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f"Version de sauvegarde non supportée : {version!r}")

    flip_board = bool(data.get("flip_board", False))
    # Migration v1 en mode retourné : la partie est reflétée vers la vraie position.
    # Les coups sont revalidés par le moteur ; un coup devenu illégal (ex. roque
    # joué par la dame à cause de B26) fait échouer le chargement explicitement.
    mirror = version == 1 and flip_board
    start_fen = data.get("start_fen")
    if start_fen:
        game_state = load_fen(_mirror_fen_files(start_fen) if mirror else start_fen)
    else:
        game_state = engine.GameState()
    for entry in data.get("moves", []):
        start_row, start_col, end_row, end_col, promotion = entry
        if mirror:
            last = engine.DIMENSION - 1
            start_col, end_col = last - start_col, last - end_col
        move = _find_move(game_state, start_row, start_col, end_row, end_col, promotion)
        game_state.make_move(move, validate=False)
    game_state.get_valid_moves()  # recalcule checkmate / stalemate
    logger.info("Partie chargée depuis %s (%d coups)", filename, len(game_state.move_log))
    return game_state, flip_board
