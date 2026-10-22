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

import copy
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from chessproject.core import engine
from chessproject.core.fen import fullmove_number as fullmove_number  # réexport
from chessproject.core.fen import load_fen
from chessproject.core.fen import to_fen as to_fen  # réexport (historique : défini ici)
from chessproject.core.notation import NotationError, parse_uci, to_uci

logger = logging.getLogger(__name__)

# v2 : ``flip_board`` n'est plus qu'une préférence d'affichage, la position est
# toujours standard. v1 : en mode retourné, la position était le miroir
# (colonnes inversées, roi et dame permutés) de la vraie partie (cf. B26).
# v3 (J4.5) : coups en UCI, mode de jeu, couleur de l'humain, niveau de l'IA, pendules et
# fin de partie hors position (abandon, temps, accord).
SAVE_VERSION = 3
SUPPORTED_VERSIONS = (1, 2, 3)
DEFAULT_SAVE_FILE = "saved_game.json"


class SaveFormatError(ValueError):
    """Fichier de sauvegarde illisible, mal formé ou contenant un coup illégal."""


# Fins de partie décidées hors de la position : seules à être enregistrées (une fin par
# mat, pat ou nulle se recalcule en rejouant les coups).
_EXTERNAL_TERMINATIONS = (
    engine.Termination.TIME_FORFEIT,
    engine.Termination.TIMEOUT_VS_INSUFFICIENT_MATERIAL,
    engine.Termination.RESIGNATION,
    engine.Termination.DRAW_AGREEMENT,
)


@dataclass
class SavedGame:
    """Contenu d'une sauvegarde : la partie rejouée et le contexte de jeu."""

    game_state: engine.GameState
    flip_board: bool = False
    mode: str | None = None  # "PvP", "PvC", "CvC" ; None pour les sauvegardes v1/v2
    human_white: bool | None = None
    human_black: bool | None = None
    level: str | None = None
    clock: dict[str, Any] | None = None  # état sérialisé de la pendule
    result: engine.GameResult | None = None  # fin hors position (abandon, temps, accord)


def start_position(game_state: engine.GameState) -> engine.GameState:
    """Position de départ de la partie (copie rembobinée ; ``game_state`` intact)."""
    start = copy.deepcopy(game_state)
    for _ in range(len(start.move_log)):
        start.undo_move()
    return start


def game_to_dict(
    game_state: engine.GameState,
    flip_board: bool = False,
    start_fen: str | None = None,
    *,
    mode: str | None = None,
    human_white: bool | None = None,
    human_black: bool | None = None,
    level: str | None = None,
    clock: dict[str, Any] | None = None,
    result: engine.GameResult | None = None,
) -> dict[str, Any]:
    """Sérialise la partie (format v3) : position de départ, coups UCI, contexte de jeu.

    ``start_fen`` par défaut = la position de départ réelle de la partie, y compris pour
    une partie chargée depuis une FEN. ``flip_board`` n'est qu'une préférence d'affichage.
    """
    if start_fen is None:
        start_fen = to_fen(start_position(game_state))
    data: dict[str, Any] = {
        "version": SAVE_VERSION,
        "flip_board": bool(flip_board),
        "start_fen": start_fen,
        "moves": [to_uci(m) for m in game_state.move_log],
        "fen": to_fen(game_state),
        "mode": mode,
        "human_white": human_white,
        "human_black": human_black,
        "level": level,
        "clock": clock,
        "result": None,
    }
    if result is not None and result.termination in _EXTERNAL_TERMINATIONS:
        assert result.termination is not None
        data["result"] = {
            "termination": result.termination.value,
            "winner": result.winner.value if result.winner else None,
        }
    return data


def save_game(
    game_state: engine.GameState,
    flip_board: bool = False,
    filename: str = DEFAULT_SAVE_FILE,
    start_fen: str | None = None,
    **context: Any,
) -> bool:
    """Écrit la sauvegarde de façon atomique (fichier temporaire puis remplacement) : un
    arrêt pendant l'écriture laisse l'ancienne sauvegarde intacte. Renvoie True si la
    sauvegarde a réussi ; l'erreur est journalisée sinon. ``context`` : voir game_to_dict."""
    tmp = filename + ".tmp"
    try:
        data = game_to_dict(game_state, flip_board, start_fen, **context)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, filename)
        logger.info("Partie sauvegardée dans %s", filename)
        return True
    except Exception as e:  # noqa: BLE001 - on journalise et on le signale à l'appelant
        logger.error("Erreur lors de la sauvegarde : %s", e)
        if os.path.exists(tmp):
            os.remove(tmp)
        return False


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


def _optional(data: dict[str, Any], key: str, kind: type | tuple[type, ...]) -> Any:
    value = data.get(key)
    if value is not None and not isinstance(value, kind):
        raise SaveFormatError(f"Champ {key!r} invalide : {value!r}")
    return value


def _parse_result(raw: Any) -> engine.GameResult | None:
    if raw is None:
        return None
    try:
        termination = engine.Termination(raw["termination"])
        winner = engine.Color(raw["winner"]) if raw.get("winner") else None
    except (TypeError, KeyError, ValueError) as exc:
        raise SaveFormatError(f"Résultat de partie invalide : {raw!r}") from exc
    if termination not in _EXTERNAL_TERMINATIONS:
        raise SaveFormatError(f"Fin de partie non enregistrable : {termination.value}")
    return engine.GameResult(termination, winner)


def load_save(filename: str = DEFAULT_SAVE_FILE) -> SavedGame:
    """Recharge une sauvegarde (v1, v2 ou v3) en rejouant ses coups par le moteur.

    Lève :class:`SaveFormatError` pour un fichier mal formé ou un coup illégal, et
    :class:`chessproject.core.fen.FenError` pour une position de départ invalide (B41).
    """
    try:
        with open(filename, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise SaveFormatError(f"Sauvegarde illisible (JSON invalide) : {exc}") from exc
    if not isinstance(data, dict):
        raise SaveFormatError("La sauvegarde doit être un objet JSON")

    version = data.get("version")
    if version not in SUPPORTED_VERSIONS:
        raise SaveFormatError(f"Version de sauvegarde non supportée : {version!r}")
    moves = data.get("moves", [])
    if not isinstance(moves, list):
        raise SaveFormatError("Le champ 'moves' doit être une liste")

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
    for index, entry in enumerate(moves, start=1):
        try:
            if version >= 3:
                if not isinstance(entry, str):
                    raise SaveFormatError(f"coup {index} : chaîne UCI attendue, {entry!r}")
                move = parse_uci(game_state, entry)
            else:
                start_row, start_col, end_row, end_col, promotion = entry
                if mirror:
                    last = engine.DIMENSION - 1
                    start_col, end_col = last - start_col, last - end_col
                move = _find_move(game_state, start_row, start_col, end_row, end_col, promotion)
        except (NotationError, ValueError, TypeError) as exc:
            if isinstance(exc, SaveFormatError):
                raise
            raise SaveFormatError(f"Coup {index} invalide ({entry!r}) : {exc}") from exc
        game_state.make_move(move, validate=False)
    game_state.get_valid_moves()  # recalcule checkmate / stalemate
    logger.info("Partie chargée depuis %s (%d coups)", filename, len(game_state.move_log))
    return SavedGame(
        game_state=game_state,
        flip_board=flip_board,
        mode=_optional(data, "mode", str),
        human_white=_optional(data, "human_white", bool),
        human_black=_optional(data, "human_black", bool),
        level=_optional(data, "level", str),
        clock=_optional(data, "clock", dict),
        result=_parse_result(data.get("result")),
    )


def load_game(filename: str = DEFAULT_SAVE_FILE) -> tuple[engine.GameState, bool]:
    """Recharge une partie et renvoie ``(game_state, flip_board)`` (cf. :func:`load_save`)."""
    saved = load_save(filename)
    return saved.game_state, saved.flip_board
