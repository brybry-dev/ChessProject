"""
Mise en page adaptative (J5.3)
------------------------------
Positions de l'en-tête, de l'échiquier, de la barre d'évaluation et du panneau
latéral, calculées à partir de la taille de la fenêtre (fonction pure, testée sans
affichage). L'échiquier occupe toute la hauteur disponible ; sa taille est un
multiple de 8 pour que toutes les cases aient la même taille entière.
"""

from dataclasses import dataclass

import pygame as p

HEADER_HEIGHT = 56
DEFAULT_SIZE = (1280, 800)
MIN_SIZE = (960, 640)
PANEL_MIN_WIDTH = 300
PANEL_MAX_WIDTH = 440
EVAL_WIDTH = 12
EVAL_GAP = 12
MIN_SQUARE = 40


@dataclass(frozen=True)
class Layout:
    width: int
    height: int
    header: p.Rect
    board: p.Rect
    eval_bar: p.Rect | None
    panel: p.Rect

    @property
    def sq_size(self) -> int:
        return int(self.board.width) // 8


def clamp_window_size(width: int, height: int) -> tuple[int, int]:
    """Taille de fenêtre ramenée au minimum utilisable."""
    return max(width, MIN_SIZE[0]), max(height, MIN_SIZE[1])


def initial_window_size(screen_width: int, screen_height: int) -> tuple[int, int]:
    """Taille de départ : la taille par défaut, réduite pour tenir dans l'écran (barre
    des tâches et décorations comprises) ; un écran inconnu (0) ne réduit rien."""
    width, height = DEFAULT_SIZE
    if screen_width > 0:
        width = min(width, int(screen_width * 0.92))
    if screen_height > 0:
        height = min(height, int(screen_height * 0.88))
    return clamp_window_size(width, height)


def compute(width: int, height: int, show_eval: bool = True) -> Layout:
    """Mise en page pour une fenêtre ``width`` × ``height`` (au moins MIN_SIZE)."""
    width, height = clamp_window_size(width, height)
    roomy = width >= 1200 and height >= 760
    margin = 32 if roomy else 20
    gap = 32 if roomy else 20
    eval_space = EVAL_WIDTH + EVAL_GAP if show_eval else 0

    avail_h = height - HEADER_HEIGHT - 2 * margin
    avail_w = width - 2 * margin - eval_space - gap - PANEL_MIN_WIDTH
    board_size = max(8 * MIN_SQUARE, min(avail_h, avail_w)) // 8 * 8
    panel_w = width - 2 * margin - eval_space - gap - board_size
    panel_w = min(PANEL_MAX_WIDTH, max(PANEL_MIN_WIDTH, panel_w))

    total = eval_space + board_size + gap + panel_w
    left = (width - total) // 2
    top = HEADER_HEIGHT + margin + max(0, (avail_h - board_size) // 2)

    eval_bar = p.Rect(left, top, EVAL_WIDTH, board_size) if show_eval else None
    board = p.Rect(left + eval_space, top, board_size, board_size)
    panel = p.Rect(board.right + gap, top, panel_w, board_size)
    header = p.Rect(0, 0, width, HEADER_HEIGHT)
    return Layout(width, height, header, board, eval_bar, panel)
