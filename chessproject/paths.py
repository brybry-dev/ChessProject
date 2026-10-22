"""
Chemins du jeu
--------------
Ressources livrées avec le code (images, sons) et données de l'utilisateur
(sauvegarde, journal). Rien ne dépend du dossier de lancement (cf. B42).

Le dossier de données est celui de la plateforme (``platformdirs``), ou
``$CHESSPROJECT_DATA_DIR`` s'il est défini (tests, installations portables).
"""

import os
from pathlib import Path

from platformdirs import user_data_path

APP_NAME = "ChessProject"

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
IMAGES_DIR = ASSETS_DIR / "images"
SOUNDS_DIR = ASSETS_DIR / "sounds"

SAVE_FILE_NAME = "saved_game.json"
LOG_FILE_NAME = "chess.log"
PGN_FILE_NAME = "partie.pgn"


def user_data_dir() -> Path:
    """Dossier des données utilisateur, créé au besoin."""
    override = os.environ.get("CHESSPROJECT_DATA_DIR")
    path = Path(override) if override else user_data_path(APP_NAME, appauthor=False)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_file() -> Path:
    """Emplacement de la sauvegarde (écriture)."""
    return user_data_dir() / SAVE_FILE_NAME


def existing_save_file() -> Path:
    """Sauvegarde à charger : celle du dossier utilisateur, sinon l'ancienne
    sauvegarde laissée dans le dossier courant par les versions précédentes."""
    current = save_file()
    legacy = Path.cwd() / SAVE_FILE_NAME
    if not current.exists() and legacy.exists():
        return legacy
    return current


def log_file() -> Path:
    return user_data_dir() / LOG_FILE_NAME


def pgn_file() -> Path:
    """Fichier PGN d'export / d'import de la partie (touches E et I)."""
    return user_data_dir() / PGN_FILE_NAME
