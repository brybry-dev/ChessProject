"""
Thème visuel (J5.2)
-------------------
Couleurs de l'interface (thèmes sombre et clair), palettes d'échiquier, couleurs
des surlignages et polices. Toutes les valeurs de couleur de l'interface viennent
d'ici : aucun module de dessin ne code de couleur en dur.

Polices : IBM Plex Sans / Mono livrées avec le jeu (SIL OFL 1.1), pour un rendu
identique sur tous les systèmes ; à défaut, une police système équivalente.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache

import pygame as p

from chessproject import paths

logger = logging.getLogger(__name__)

RGB = tuple[int, int, int]
RGBA = tuple[int, int, int, int]


@dataclass(frozen=True)
class Theme:
    name: str
    bg: RGB
    surface: RGB
    surface2: RGB
    border: RGB
    text: RGB
    muted: RGB
    accent: RGB
    on_accent: RGB
    current: RGBA  # coup courant dans l'historique
    hover: RGBA  # survol d'un bouton discret
    scrim: RGBA  # voile derrière une fenêtre modale
    danger_bg: RGB  # pendule sous 20 s
    danger_text: RGB


ACCENT: RGB = (227, 169, 83)

THEMES: dict[str, Theme] = {
    "sombre": Theme(
        name="sombre",
        bg=(20, 22, 26),
        surface=(28, 31, 37),
        surface2=(39, 43, 51),
        border=(47, 52, 61),
        text=(236, 234, 229),
        muted=(164, 170, 179),
        accent=ACCENT,
        on_accent=(22, 24, 29),
        current=(227, 169, 83, 56),
        hover=(255, 255, 255, 18),
        scrim=(10, 11, 14, 165),
        danger_bg=(242, 211, 204),
        danger_text=(122, 31, 18),
    ),
    "clair": Theme(
        name="clair",
        bg=(243, 241, 236),
        surface=(255, 255, 255),
        surface2=(239, 236, 229),
        border=(223, 218, 208),
        text=(27, 29, 33),
        muted=(90, 96, 105),
        accent=ACCENT,
        on_accent=(22, 24, 29),
        current=(227, 169, 83, 82),
        hover=(0, 0, 0, 14),
        scrim=(20, 22, 26, 120),
        danger_bg=(242, 211, 204),
        danger_text=(122, 31, 18),
    ),
}


@dataclass(frozen=True)
class BoardPalette:
    name: str
    light: RGB
    dark: RGB


PALETTES: dict[str, BoardPalette] = {
    palette.name: palette
    for palette in (
        BoardPalette("Ardoise", (228, 220, 203), (126, 138, 154)),
        BoardPalette("Noyer", (237, 214, 176), (184, 135, 98)),
        BoardPalette("Forêt", (233, 237, 214), (120, 150, 104)),
        BoardPalette("Marine", (222, 227, 230), (140, 162, 173)),
    )
}

# Surlignages de l'échiquier (couleur, opacité 0-255).
LAST_MOVE: RGBA = (227, 169, 83, 105)
SELECTED: RGBA = (227, 169, 83, 135)
HINT: RGBA = (20, 22, 26, 70)  # points des coups possibles
CHECK: RGBA = (214, 69, 65, 170)
ARROW: RGBA = (76, 139, 214, 200)
MARK: RGBA = (76, 139, 214, 210)
EVAL_WHITE: RGB = (236, 234, 229)
EVAL_BLACK: RGB = (42, 45, 51)
# Bilan de partie (J9.3) : imprécision, erreur, gaffe (palette Okabe-Ito, lisible par
# les daltoniens).
JUDGEMENT_COLORS: dict[str, RGB] = {
    "inaccuracy": (86, 180, 233),
    "mistake": (230, 159, 0),
    "blunder": (223, 83, 83),
}
WHITE_PIECE_TILE: RGB = (236, 234, 229)
BLACK_PIECE_TILE: RGB = (42, 45, 51)
DROP_TARGET: RGB = (255, 255, 255)  # case survolée pendant un glisser-déposer
WARNING_DOT: RGB = (214, 69, 65)  # pastille de la ligne d'état (échec, erreur)
SHADOW: RGB = (0, 0, 0)
# Choix de promotion : toujours clair, pour que les pièces des deux camps se lisent.
PROMOTION_BG: RGB = (244, 241, 234)
PROMOTION_HOVER: RGB = (235, 203, 143)
PROMOTION_CANCEL: RGB = (220, 214, 202)
PROMOTION_CANCEL_HOVER: RGB = (205, 198, 186)
PROMOTION_CANCEL_TEXT: RGB = (58, 63, 73)


def theme(name: str) -> Theme:
    return THEMES.get(name, THEMES["sombre"])


def palette(name: str) -> BoardPalette:
    return PALETTES.get(name, PALETTES["Ardoise"])


# --------------------------------------------------------------------------
# Polices
# --------------------------------------------------------------------------
_FONT_FILES = {
    ("sans", "regular"): "IBMPlexSans-Regular.ttf",
    ("sans", "medium"): "IBMPlexSans-Medium.ttf",
    ("sans", "semibold"): "IBMPlexSans-SemiBold.ttf",
    ("mono", "regular"): "IBMPlexMono-Medium.ttf",
    ("mono", "medium"): "IBMPlexMono-Medium.ttf",
    ("mono", "semibold"): "IBMPlexMono-SemiBold.ttf",
}
_SYSTEM_FALLBACK = {
    "sans": "Inter,Segoe UI,Helvetica Neue,Helvetica,Arial,DejaVu Sans",
    "mono": "JetBrains Mono,Cascadia Mono,Consolas,Menlo,DejaVu Sans Mono",
}


@lru_cache(maxsize=64)
def font(size: int, weight: str = "regular", mono: bool = False) -> p.font.Font:
    """Police d'interface (mise en cache) : ``weight`` parmi regular, medium, semibold."""
    family = "mono" if mono else "sans"
    path = paths.FONTS_DIR / _FONT_FILES[(family, weight)]
    try:
        return p.font.Font(str(path), size)
    except (OSError, FileNotFoundError) as ex:
        logger.warning("Police %s indisponible (%s) : police système", path.name, ex)
        return p.font.SysFont(_SYSTEM_FALLBACK[family], size, bold=weight != "regular")
