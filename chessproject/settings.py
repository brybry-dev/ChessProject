"""
Préférences de l'interface (J5)
-------------------------------
Apparence (thème, plateau, aides visuelles) et derniers réglages de l'écran
« Nouvelle partie », conservés d'une session à l'autre dans ``settings.json``.

Le fichier est une simple commodité : absent, illisible ou partiellement invalide,
il est ignoré champ par champ (valeur par défaut) sans jamais empêcher le jeu de
démarrer. L'écriture est atomique, comme la sauvegarde de partie.
"""

import contextlib
import json
import logging
import os
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any

from chessproject import i18n, paths
from chessproject.ai import levels
from chessproject.core import clock

logger = logging.getLogger(__name__)

SETTINGS_VERSION = 1

THEMES = ("sombre", "clair")
BOARDS = ("Ardoise", "Noyer", "Forêt", "Marine")
MODES = ("PvC", "PvP", "CvC")
COLORS = ("w", "r", "b")  # blancs, au hasard, noirs


@dataclass(frozen=True)
class Settings:
    theme: str = "sombre"
    board: str = "Ardoise"
    show_eval: bool = True
    show_analysis: bool = False  # variante principale de la position affichée (J9.1)
    hints_vs_ai: bool = True  # bouton « Indice » disponible contre l'IA (J9.2)
    show_coordinates: bool = True
    show_legal_moves: bool = True
    sound: bool = True
    language: str = "fr"  # langue de l'interface (J11.3), cf. i18n.LANGUAGES
    # Derniers choix de l'écran « Nouvelle partie ».
    mode: str = "PvC"
    color: str = "w"
    level: str = levels.DEFAULT_LEVEL.name
    time_control: str = clock.BLITZ_5_0.pgn_tag
    # Dernier dossier d'export ou d'import PGN (J11.1) ; vide : dossier des données.
    pgn_dir: str = ""

    @property
    def control(self) -> clock.TimeControl:
        """Cadence choisie : le préréglage correspondant (pour son nom), sinon la cadence
        lue telle quelle, sinon la cadence par défaut."""
        try:
            control = clock.TimeControl.from_pgn(self.time_control)
        except ValueError:
            return clock.BLITZ_5_0
        return next((preset for preset in clock.PRESETS if preset == control), control)


_CHOICES: dict[str, tuple[str, ...]] = {
    "theme": THEMES,
    "language": i18n.LANGUAGES,
    "board": BOARDS,
    "mode": MODES,
    "color": COLORS,
    "level": tuple(level.name for level in levels.LEVELS),
}


def _valid(name: str, value: Any, default: Any) -> bool:
    if isinstance(default, bool):
        return isinstance(value, bool)
    if not isinstance(value, str):
        return False
    if name in _CHOICES:
        return value in _CHOICES[name]
    if name == "time_control":
        try:
            clock.TimeControl.from_pgn(value)
        except ValueError:
            return False
    return True


def from_dict(data: Any) -> Settings:
    """Préférences lues d'un objet JSON : chaque champ invalide garde sa valeur par défaut."""
    defaults = Settings()
    if not isinstance(data, dict):
        return defaults
    values: dict[str, Any] = {}
    for f in fields(Settings):
        if f.name in data:
            value = data[f.name]
            if _valid(f.name, value, getattr(defaults, f.name)):
                values[f.name] = value
            else:
                logger.warning("Préférence %s ignorée : %r", f.name, value)
    return replace(defaults, **values)


def to_dict(settings: Settings) -> dict[str, Any]:
    return {"version": SETTINGS_VERSION, **asdict(settings)}


def load(path: Path | None = None) -> Settings:
    path = path or paths.settings_file()
    try:
        with open(path, encoding="utf-8") as f:
            return from_dict(json.load(f))
    except FileNotFoundError:
        return Settings()
    except (OSError, ValueError) as ex:
        logger.warning("Préférences illisibles (%s) : valeurs par défaut", ex)
        return Settings()


def save(settings: Settings, path: Path | None = None) -> bool:
    """Écrit les préférences (atomique) ; renvoie False en cas d'échec, sans lever."""
    path = path or paths.settings_file()
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(to_dict(settings), f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError as ex:
        logger.error("Écriture des préférences impossible : %s", ex)
        with contextlib.suppress(OSError):
            tmp.unlink()
        return False
