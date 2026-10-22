"""Génère l'icône de l'application (``chessproject/assets/icon.png``, 512 px) : le
cavalier du jeu de pièces sur une tuile aux couleurs du thème. À relancer seulement
si le jeu de pièces ou la couleur d'accent changent.

    python tools/make_icon.py
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as p

from chessproject import paths
from chessproject.ui import theme as th
from chessproject.ui.board_view import PieceSet

SIZE = 512


def main() -> None:
    p.init()
    p.display.set_mode((1, 1))
    icon = p.Surface((SIZE, SIZE), p.SRCALPHA)
    p.draw.rect(icon, th.THEMES["sombre"].surface2, icon.get_rect(), border_radius=SIZE // 5)
    inner = p.Rect(0, 0, SIZE - 40, SIZE - 40)
    inner.center = icon.get_rect().center
    p.draw.rect(icon, th.ACCENT, inner, border_radius=SIZE // 6)
    knight = PieceSet().get_image("wN", int(SIZE * 0.72))
    icon.blit(knight, knight.get_rect(center=(SIZE // 2, SIZE // 2 + SIZE // 40)))
    target = paths.ASSETS_DIR / "icon.png"
    p.image.save(icon, str(target))
    print(f"Icône écrite : {target}")


if __name__ == "__main__":
    main()
