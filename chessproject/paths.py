"""
Chemins du jeu
--------------
Ressources livrées avec le code (pièces, polices, sons) et données de l'utilisateur
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
PIECES_DIR = ASSETS_DIR / "pieces"  # jeu vectoriel « Chessnut » (Apache 2.0)
FONTS_DIR = ASSETS_DIR / "fonts"  # IBM Plex Sans / Mono (SIL OFL 1.1)

SAVE_FILE_NAME = "saved_game.json"
SAVES_DIR_NAME = "saves"
SAVE_EXTENSION = ".json"
PGN_EXTENSION = ".pgn"
LOG_FILE_NAME = "chess.log"
PGN_FILE_NAME = "partie.pgn"
SETTINGS_FILE_NAME = "settings.json"


def user_data_dir() -> Path:
    """Dossier des données utilisateur, créé au besoin."""
    override = os.environ.get("CHESSPROJECT_DATA_DIR")
    path = Path(override) if override else user_data_path(APP_NAME, appauthor=False)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_file() -> Path:
    """Emplacement de la sauvegarde (écriture)."""
    return user_data_dir() / SAVE_FILE_NAME


def saves_dir() -> Path:
    """Dossier des sauvegardes (J11.1), créé au besoin."""
    path = user_data_dir() / SAVES_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def adopt_legacy_save() -> Path | None:
    """Copie l'ancienne sauvegarde unique (``saved_game.json``, versions 1.3 et
    antérieures) dans le dossier des sauvegardes, si elle n'y est pas déjà. L'original
    est laissé en place. Renvoie la copie, ou None."""
    legacy = existing_save_file()
    target = saves_dir() / SAVE_FILE_NAME
    if not legacy.exists() or target.exists():
        return None
    try:
        target.write_bytes(legacy.read_bytes())
    except OSError:
        return None
    return target


def places() -> list[tuple[str, Path]]:
    """Dossiers proposés par le choix de fichier : données du jeu, dossier personnel,
    Documents et Téléchargements s'ils existent (noms français, traduits à l'affichage)."""
    home = Path.home()
    found = [("Données du jeu", user_data_dir()), ("Dossier personnel", home)]
    for label, names in (
        ("Documents", ("Documents",)),
        ("Téléchargements", ("Downloads", "Téléchargements")),
    ):
        folder = next((home / n for n in names if (home / n).is_dir()), None)
        if folder is not None:
            found.append((label, folder))
    return found


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
    """Fichier PGN proposé par défaut à l'export (touche E)."""
    return user_data_dir() / PGN_FILE_NAME


def settings_file() -> Path:
    """Préférences de l'interface (thème, plateau, dernière partie configurée)."""
    return user_data_dir() / SETTINGS_FILE_NAME
