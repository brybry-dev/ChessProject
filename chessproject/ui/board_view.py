"""
Rendu de l'échiquier (J5.2 / J5.4)
---------------------------------
Cases, coordonnées, pièces vectorielles, surlignages (dernier coup, sélection,
échec), coups possibles, flèches et marques de l'utilisateur, pièce tenue pendant
un glisser-déposer et animation des coups (non bloquante : elle est calculée à
chaque image à partir de l'heure courante).

L'orientation est une rotation de 180° de l'affichage ; la position du moteur ne
change jamais (cf. rapport d'analyse B26).
"""

import io
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

import pygame as p
import pygame.gfxdraw

from chessproject import paths
from chessproject.core import engine
from chessproject.ui import theme as th
from chessproject.ui import widgets as w

logger = logging.getLogger(__name__)

DIMENSION = engine.DIMENSION
Square = tuple[int, int]


# --------------------------------------------------------------------------
# Pièces
# --------------------------------------------------------------------------
class PieceSet:
    """Images des pièces à la taille demandée : SVG rastérisé à la taille exacte (net
    à toutes les tailles), ou à défaut l'ancienne image PNG redimensionnée."""

    def __init__(self, pieces_dir=paths.PIECES_DIR, images_dir=paths.IMAGES_DIR):
        self.pieces_dir = pieces_dir
        self.images_dir = images_dir
        self.cache: dict[tuple[str, int], p.Surface] = {}
        # Un SVG inutilisable l'est pour toutes les pièces : on passe alors au PNG.
        self.svg_failed = False

    def get_image(self, piece: str, size: int = 64) -> p.Surface:
        """Image de ``piece`` (code moteur : ``"wK"``, ``"bp"``…) de ``size`` pixels."""
        key = (piece, size)
        if key not in self.cache:
            self.cache[key] = self._load(piece, size)
        return self.cache[key]

    def _load(self, piece: str, size: int) -> p.Surface:
        svg = self.pieces_dir / f"{piece[0]}{piece[1].upper()}.svg"
        try:
            if self.svg_failed:
                raise ValueError("SVG déjà en échec")
            data = svg.read_text(encoding="utf-8")
            # nanosvg (SDL_image) rastérise à la taille déclarée par width / height.
            data = re.sub(r"<svg\b", f'<svg width="{size}" height="{size}"', data, count=1)
            image = p.image.load(io.BytesIO(data.encode("utf-8")), "piece.svg")
            if image.get_bounding_rect().width == 0:
                # Vu sur la CI Windows (pygame 2.6, SDL_image) : image à la bonne taille
                # mais entièrement transparente. Mieux vaut la pièce PNG que rien.
                raise ValueError(
                    f"image transparente ({image.get_size()}, {image.get_bitsize()} bits, "
                    f"masques {image.get_masks()})"
                )
            if image.get_size() != (size, size):
                image = w.smoothscale(image, (size, size))
        except (OSError, p.error, ValueError) as ex:
            if not self.svg_failed:
                logger.warning("Pièce %s : SVG indisponible (%s), images PNG utilisées", piece, ex)
            self.svg_failed = True
            png = self.images_dir / f"{piece}.png"
            if not png.exists():
                raise FileNotFoundError(f"Image not found: {png}") from ex
            image = w.smoothscale(p.image.load(str(png)), (size, size))
        if p.display.get_surface() is not None:
            image = image.convert_alpha()
        return image


# Ancien nom, conservé pour les appelants existants.
ResourceManager = PieceSet


# --------------------------------------------------------------------------
# Animation
# --------------------------------------------------------------------------
@dataclass
class Animation:
    """Glissement des pièces d'un coup : (pièce, départ, arrivée) pour chaque pièce
    qui bouge (deux pour un roque), et la pièce prise, qui s'efface."""

    slides: list[tuple[str, Square, Square]]
    captured: tuple[str, Square] | None
    start_ms: int
    duration_ms: int

    def progress(self, now_ms: int) -> float:
        if self.duration_ms <= 0:
            return 1.0
        return max(0.0, min(1.0, (now_ms - self.start_ms) / self.duration_ms))

    @property
    def hidden(self) -> set[Square]:
        """Cases d'arrivée : la pièce y est déjà dans la position, on la masque."""
        return {end for _, _, end in self.slides}


ANIMATION_BASE_MS = 120
ANIMATION_PER_SQUARE_MS = 22
ANIMATION_MAX_MS = 260


def animation_for(move: engine.Move, now_ms: int) -> Animation:
    start, end = (move.start_row, move.start_col), (move.end_row, move.end_col)
    slides = [(move.piece_moved, start, end)]
    if move.is_castle_move:
        row = move.end_row
        if move.end_col == 6:  # petit roque : tour h -> f
            slides.append((move.piece_moved[0] + "R", (row, 7), (row, 5)))
        else:  # grand roque : tour a -> d
            slides.append((move.piece_moved[0] + "R", (row, 0), (row, 3)))
    captured = None
    if move.piece_captured != "--":
        square = (move.start_row, move.end_col) if move.is_enpassant_move else end
        captured = (move.piece_captured, square)
    distance = max(abs(move.end_row - move.start_row), abs(move.end_col - move.start_col))
    duration = min(ANIMATION_MAX_MS, ANIMATION_BASE_MS + ANIMATION_PER_SQUARE_MS * distance)
    return Animation(slides, captured, now_ms, duration)


def ease_out_cubic(t: float) -> float:
    return 1 - pow(1 - t, 3)


# --------------------------------------------------------------------------
# Rendu
# --------------------------------------------------------------------------
@dataclass
class Drag:
    """Pièce tenue à la souris : sa case d'origine et la position du pointeur."""

    origin: Square
    piece: str
    pos: tuple[int, int]
    active: bool = False  # vrai dès que le pointeur a quitté le seuil de déplacement


@dataclass
class BoardScene:
    """Tout ce qu'il faut pour dessiner une image de l'échiquier."""

    board: list[list[str]]
    last_move: tuple[Square, Square] | None = None
    selected: Square | None = None
    targets: list[tuple[Square, bool]] = field(default_factory=list)  # (case, prise ?)
    check: Square | None = None
    drag: Drag | None = None
    arrows: Iterable[tuple[Square, Square]] = ()
    marks: Iterable[Square] = ()
    pending_arrow: tuple[Square, Square] | None = None


class Renderer:
    """Dessin de l'échiquier dans ``board_rect`` et conversions écran <-> cases."""

    def __init__(self, screen, resources, board_rect, flip_board=False):
        self.screen = screen
        self.resources = resources
        self.board_rect = p.Rect(board_rect)
        self.flip_board = flip_board
        self.palette = th.palette("Ardoise")
        self.show_coordinates = True
        self.show_legal_moves = True
        self.animation: Animation | None = None

    @property
    def sq_size(self) -> int:
        return self.board_rect.width // DIMENSION

    # -- conversion logique <-> affichage --------------------------------
    # Plateau retourné = rotation de 180° : rangées ET colonnes sont inversées.
    def display_row(self, row):
        return row if not self.flip_board else DIMENSION - 1 - row

    def display_col(self, col):
        return col if not self.flip_board else DIMENSION - 1 - col

    def square_from_pixel(self, pos) -> Square | None:
        """(x, y) écran -> (row, col) logique, ou None si hors plateau."""
        x, y = pos[0] - self.board_rect.x, pos[1] - self.board_rect.y
        if x < 0 or y < 0:
            return None
        disp_col, disp_row = x // self.sq_size, y // self.sq_size
        if disp_col < DIMENSION and disp_row < DIMENSION:
            # La rotation est son propre inverse.
            return self.display_row(disp_row), self.display_col(disp_col)
        return None

    def square_rect(self, row, col) -> p.Rect:
        """Rectangle écran de la case logique (row, col)."""
        return self._rect(self.display_row(row), self.display_col(col))

    def square_center(self, square: Square) -> tuple[float, float]:
        rect = self.square_rect(*square)
        return rect.x + rect.width / 2, rect.y + rect.height / 2

    def file_label(self, disp_col):
        """Lettre de colonne affichée sous la colonne d'affichage ``disp_col``."""
        return "abcdefgh"[self.display_col(disp_col)]

    def rank_label(self, disp_row):
        """Numéro de rangée affiché à gauche de la rangée d'affichage ``disp_row``."""
        return str(DIMENSION - self.display_row(disp_row))

    def _rect(self, disp_row, disp_col) -> p.Rect:
        size = self.sq_size
        return p.Rect(
            self.board_rect.x + disp_col * size, self.board_rect.y + disp_row * size, size, size
        )

    # -- animation -------------------------------------------------------
    def start_animation(self, move: engine.Move, now_ms: int) -> None:
        self.animation = animation_for(move, now_ms)

    def animating(self, now_ms: int) -> bool:
        if self.animation is not None and self.animation.progress(now_ms) >= 1.0:
            self.animation = None
        return self.animation is not None

    # -- dessin ---------------------------------------------------------
    def draw(self, scene: BoardScene, now_ms: int) -> None:
        size = self.sq_size
        animation = self.animation if self.animating(now_ms) else None
        w.shadow(self.screen, self.board_rect, radius=6, depth=22)
        self._draw_squares()
        if scene.last_move:
            for square in scene.last_move:
                w.translucent(self.screen, th.LAST_MOVE, self.square_rect(*square))
        if scene.selected:
            w.translucent(self.screen, th.SELECTED, self.square_rect(*scene.selected))
        if scene.check:
            center = self.square_rect(*scene.check).center
            w.circle(self.screen, th.CHECK, center, int(size * 0.48))
            w.ring(self.screen, (*th.CHECK_RING, 255), center, int(size * 0.48), max(2, size // 32))
        if self.show_coordinates:
            self._draw_coordinates()

        hidden: set[Square] = set(animation.hidden) if animation else set()
        if scene.drag and scene.drag.active:
            hidden.add(scene.drag.origin)
        for row in range(DIMENSION):
            for col in range(DIMENSION):
                piece = scene.board[row][col]
                if piece == "--":
                    continue
                rect = self.square_rect(row, col)
                if (row, col) in hidden:
                    if scene.drag and scene.drag.active and (row, col) == scene.drag.origin:
                        ghost = self.resources.get_image(piece, size).copy()
                        ghost.set_alpha(70)
                        self.screen.blit(ghost, rect)
                    continue
                self.screen.blit(self.resources.get_image(piece, size), rect)

        if self.show_legal_moves:
            for square, capture in scene.targets:
                center = self.square_rect(*square).center
                if capture:
                    w.ring(self.screen, th.HINT, center, int(size * 0.46), max(3, size // 14))
                else:
                    w.circle(self.screen, th.HINT, center, max(5, int(size * 0.15)))

        if animation:
            self._draw_animation(animation, now_ms)
        self._draw_annotations(scene)
        if scene.drag and scene.drag.active:
            hover = self.square_from_pixel(scene.drag.pos)
            if hover is not None:
                p.draw.rect(self.screen, th.DROP_TARGET, self.square_rect(*hover), 3)
            image = self.resources.get_image(scene.drag.piece, int(size * 1.08))
            self.screen.blit(image, image.get_rect(center=scene.drag.pos))

    def _draw_squares(self) -> None:
        for disp_row in range(DIMENSION):
            for disp_col in range(DIMENSION):
                light = (disp_row + disp_col) % 2 == 0  # la rotation conserve la parité
                color = self.palette.light if light else self.palette.dark
                p.draw.rect(self.screen, color, self._rect(disp_row, disp_col))

    def _draw_coordinates(self) -> None:
        size = self.sq_size
        font = th.font(max(10, size // 6), "semibold")
        pad = max(3, size // 16)
        for i in range(DIMENSION):
            # Rangées sur la première colonne affichée, colonnes sur la dernière rangée.
            rect = self._rect(i, 0)
            # Case (i, 0) claire si i est pair : encre foncée lisible sur chaque case.
            on_light = i % 2 == 0
            color = self.palette.coord_on_light if on_light else self.palette.coord_on_dark
            w.text(self.screen, self.rank_label(i), font, color, (rect.x + pad, rect.y + pad // 2))
            rect = self._rect(DIMENSION - 1, i)
            on_light = (DIMENSION - 1 + i) % 2 == 0
            color = self.palette.coord_on_light if on_light else self.palette.coord_on_dark
            w.text(
                self.screen,
                self.file_label(i),
                font,
                color,
                (rect.right - pad, rect.bottom - pad // 2),
                "bottomright",
            )

    def _draw_animation(self, animation: Animation, now_ms: int) -> None:
        size = self.sq_size
        t = ease_out_cubic(animation.progress(now_ms))
        if animation.captured:
            piece, square = animation.captured
            image = self.resources.get_image(piece, size).copy()
            image.set_alpha(int(255 * (1 - t)))
            self.screen.blit(image, self.square_rect(*square))
        for piece, start, end in animation.slides:
            # Coordonnées logiques fractionnaires, puis passage en affichage.
            row = start[0] + (end[0] - start[0]) * t
            col = start[1] + (end[1] - start[1]) * t
            x = self.board_rect.x + self.display_col(col) * size
            y = self.board_rect.y + self.display_row(row) * size
            self.screen.blit(self.resources.get_image(piece, size), (round(x), round(y)))

    def _draw_annotations(self, scene: BoardScene) -> None:
        size = self.sq_size
        for square in scene.marks:
            center = self.square_rect(*square).center
            w.ring(self.screen, th.MARK, center, int(size * 0.46), max(3, size // 12))
        arrows = list(scene.arrows)
        if scene.pending_arrow:
            arrows.append(scene.pending_arrow)
        if not arrows:
            return
        layer = p.Surface(self.board_rect.size, p.SRCALPHA)
        for start, end in arrows:
            _arrow(layer, self._local(start), self._local(end), size, th.ARROW)
        self.screen.blit(layer, self.board_rect.topleft)

    def _local(self, square: Square) -> tuple[float, float]:
        x, y = self.square_center(square)
        return x - self.board_rect.x, y - self.board_rect.y


def _arrow(surface, start, end, sq_size, color) -> None:
    """Flèche pleine de ``start`` vers ``end`` (centres de cases), bords lissés."""
    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy
    length = (dx * dx + dy * dy) ** 0.5
    if length == 0:
        return
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    shaft = sq_size * 0.09
    head_len = sq_size * 0.42
    head_w = sq_size * 0.26
    # Départ légèrement décalé du centre, pointe un peu avant le centre d'arrivée.
    sx, sy = sx + ux * sq_size * 0.22, sy + uy * sq_size * 0.22
    tip = (ex - ux * sq_size * 0.12, ey - uy * sq_size * 0.12)
    base = (tip[0] - ux * head_len, tip[1] - uy * head_len)
    points = [
        (sx + nx * shaft, sy + ny * shaft),
        (base[0] + nx * shaft, base[1] + ny * shaft),
        (base[0] + nx * head_w, base[1] + ny * head_w),
        tip,
        (base[0] - nx * head_w, base[1] - ny * head_w),
        (base[0] - nx * shaft, base[1] - ny * shaft),
        (sx - nx * shaft, sy - ny * shaft),
    ]
    points_i = [(round(x), round(y)) for x, y in points]
    pygame.gfxdraw.filled_polygon(surface, points_i, color)
    pygame.gfxdraw.aapolygon(surface, points_i, color)
