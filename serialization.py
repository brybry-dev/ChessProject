"""
Sérialisation des parties
-------------------------
Sauvegarde / chargement d'une partie au format JSON : position de départ
(standard ou avec roi/dame permutés) + liste des coups joués.

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

import ChessEngine
from fen_utils import load_fen

SAVE_VERSION = 1
DEFAULT_SAVE_FILE = "saved_game.json"


def _piece_to_fen_char(piece: str) -> str:
    letter = "P" if piece[1] == "p" else piece[1]
    return letter.upper() if piece[0] == "w" else letter.lower()


def to_fen(game_state: ChessEngine.GameState) -> str:
    """Retourne la FEN complète (6 champs) de la position courante.

    Le champ de roque suppose les cases standard roi/tour ; il n'est donné
    qu'à titre indicatif et n'est pas utilisé pour recharger la partie.
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
        enpassant = chr(ord("a") + ep[1]) + str(ChessEngine.DIMENSION - ep[0])
    else:
        enpassant = "-"

    halfmove = game_state.fifty_move_counter
    fullmove = len(game_state.move_log) // 2 + 1
    return f"{board_part} {turn} {castling} {enpassant} {halfmove} {fullmove}"


def game_to_dict(
    game_state: ChessEngine.GameState, flip_board: bool = False, start_fen: str | None = None
) -> dict[str, Any]:
    """Sérialise la partie : position de départ + liste des coups.

    ``start_fen`` par défaut = position initiale standard (roi/dame permutés si
    ``flip_board``). Le donner explicitement permet de sauvegarder une partie
    commencée depuis une position arbitraire (chargée par FEN).
    """
    if start_fen is None:
        start_fen = to_fen(ChessEngine.GameState(flip_board=flip_board))
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
    game_state: ChessEngine.GameState,
    flip_board: bool = False,
    filename: str = DEFAULT_SAVE_FILE,
    start_fen: str | None = None,
) -> None:
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(game_to_dict(game_state, flip_board, start_fen), f, indent=2)
        logging.info("Partie sauvegardée dans %s", filename)
    except Exception as e:  # noqa: BLE001 - on journalise et on continue
        logging.error("Erreur lors de la sauvegarde : %s", e)


def _find_move(
    game_state: ChessEngine.GameState,
    start_row: int,
    start_col: int,
    end_row: int,
    end_col: int,
    promotion: str | None,
) -> ChessEngine.Move:
    for move in game_state.getValidMoves():
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


def load_game(filename: str = DEFAULT_SAVE_FILE) -> tuple[ChessEngine.GameState, bool]:
    """Recharge une partie et renvoie ``(game_state, flip_board)``.

    Rejoue les coups depuis la position de départ : l'état obtenu est donc
    toujours conforme aux règles courantes du moteur.
    """
    with open(filename, encoding="utf-8") as f:
        data = json.load(f)

    version = data.get("version")
    if version != SAVE_VERSION:
        raise ValueError(f"Version de sauvegarde non supportée : {version!r}")

    flip_board = bool(data.get("flip_board", False))
    start_fen = data.get("start_fen")
    if start_fen:
        game_state = load_fen(start_fen)
    else:
        game_state = ChessEngine.GameState(flip_board=flip_board)
    for entry in data.get("moves", []):
        start_row, start_col, end_row, end_col, promotion = entry
        move = _find_move(game_state, start_row, start_col, end_row, end_col, promotion)
        game_state.makeMove(move, validate=False)
    game_state.getValidMoves()  # recalcule checkmate / stalemate
    logging.info("Partie chargée depuis %s (%d coups)", filename, len(game_state.move_log))
    return game_state, flip_board
