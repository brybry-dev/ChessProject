"""
Fichier Principal, gérant les entrées/sorties, la personnalisation et les sauvegardes.
"""

import logging
import logging.handlers
import os
import queue
import sys
import time
from contextlib import contextmanager
from multiprocessing import Process, Queue

import pygame as p

from chessproject import paths, serialization
from chessproject.ai import levels, search
from chessproject.core import clock as chess_clock_module
from chessproject.core import engine, notation, pgn

# --------------------------------------------------
# Constantes d'affichage
# --------------------------------------------------
DIMENSION = engine.DIMENSION
BOARD_WIDTH = BOARD_HEIGHT = 512
MOVE_LOG_PANEL_WIDTH = 250
LEFT_PANEL_WIDTH = 250
MOVE_LOG_PANEL_HEIGHT = BOARD_HEIGHT
MAX_FPS = 30
# Garde-fous du processus d'IA (B33) : au-delà, il est arrêté et un coup de
# repli est joué. La limite de réflexion pilotée par niveau viendra en J3.
AI_MAX_THINK_SECONDS = 30.0
AI_RESULT_TIMEOUT_SECONDS = 1.0
# Surcoût d'un coup de l'IA hors réflexion (lancement du processus, transmission du
# résultat, dépassement de l'échéance) : estimé au départ, puis mesuré en jeu.
AI_INITIAL_OVERHEAD_MS = 250.0
AI_OVERHEAD_SMOOTHING = 0.3
SQ_SIZE = BOARD_HEIGHT // DIMENSION


logger = logging.getLogger(__name__)

LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3


def _configure_logging() -> None:
    """Journal fichier tournant, niveau INFO, dans le dossier de données utilisateur.
    Appelé depuis main() pour éviter les effets de bord à l'import (tests)."""
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.handlers.RotatingFileHandler(
            paths.log_file(),
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
        )
        root.addHandler(handler)
        root.setLevel(logging.INFO)
    logger.info("Lancement du jeu d'échecs")


# --------------------------------------------------
# Gestion des ressources
# --------------------------------------------------
class ResourceManager:
    _instance = None
    # Attributs posés dynamiquement dans __new__ (singleton) : déclarés ici pour mypy.
    sq_size: int
    image_path: str
    cache: dict[str, p.Surface]

    def __new__(cls, sq_size, image_path=str(paths.IMAGES_DIR)):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.sq_size = sq_size
            cls._instance.image_path = image_path
            cls._instance.cache = {}
        return cls._instance

    def get_image(self, piece):
        if piece in self.cache:
            return self.cache[piece]
        path = os.path.join(self.image_path, piece + ".png")
        if not os.path.exists(path):
            logger.error("Image not found: %s", path)
            raise FileNotFoundError(f"Image not found: {path}")
        image = p.transform.scale(p.image.load(path), (self.sq_size, self.sq_size))
        self.cache[piece] = image
        return image


# --------------------------------------------------
# UI Manager
# --------------------------------------------------
class UIManager:
    def __init__(
        self, board_width, board_height, move_log_panel_width, move_log_panel_height, now=None
    ):
        # Source de temps en millisecondes, injectable pour les tests.
        self.now = now or p.time.get_ticks
        self.board_width = board_width
        self.board_height = board_height
        self.move_log_panel_width = move_log_panel_width
        self.move_log_panel_height = move_log_panel_height
        self.move_log_offset = 0
        self.max_scroll = 0
        self.SCROLL_SPEED = 20
        self._move_lines_key = None
        self._move_lines_cache = []
        # Couleurs par défaut du plateau
        self.board_color1 = p.Color("white")
        self.board_color2 = p.Color("gray")
        # Temps de jeu
        self.white_time: float = 0
        self.black_time: float = 0
        self.last_time = self.now()
        self.is_running = True
        # Pendule à cadence affichée à la place du chronomètre (fournie par le contrôleur).
        self.chess_clock: chess_clock_module.ChessClock | None = None

    def reset_timer(self):
        """Remet les pendules à zéro et resynchronise l'horloge de référence.
        À appeler quand la partie (re)commence, après les menus."""
        self.white_time = 0
        self.black_time = 0
        self.last_time = self.now()
        self.is_running = True

    @contextmanager
    def timer_paused(self):
        """Exclut du décompte le temps passé dans le bloc (menu, animation : B44)."""
        try:
            yield
        finally:
            self.last_time = self.now()

    def update_timer(self, white_to_move):
        current_time = self.now()
        elapsed = (current_time - self.last_time) / 1000  # Convertir en secondes
        self.last_time = current_time

        if self.is_running:
            if white_to_move:
                self.white_time += elapsed
            else:
                self.black_time += elapsed

    def draw_timer(self, screen, white_to_move):
        # Fond du chronomètre
        timer_rect = p.Rect(10, 10, LEFT_PANEL_WIDTH - 20, 100)
        p.draw.rect(screen, p.Color("black"), timer_rect)
        p.draw.rect(screen, p.Color("white"), timer_rect, 2)

        # Police pour le chronomètre
        font = p.font.SysFont("Arial", 24, bold=True)

        # Avec une cadence : temps restant de la pendule ; sans limite : temps écoulé.
        chess_clock = self.chess_clock
        if chess_clock is not None and not chess_clock.is_unlimited:
            for i, (label, color) in enumerate(
                (("Blancs", engine.Color.WHITE), ("Noirs", engine.Color.BLACK))
            ):
                remaining = chess_clock.remaining_ms(color)
                active = (color is engine.Color.WHITE) == white_to_move
                low = remaining is not None and remaining < 10_000
                tint = "orangered" if low and active else ("white" if active else "gray")
                text = font.render(
                    f"{label}: {chess_clock_module.format_ms(remaining)}", True, p.Color(tint)
                )
                screen.blit(text, (20, 20 + 40 * i))
            return

        # Formatage du temps
        def format_time(seconds):
            minutes = int(seconds // 60)
            seconds = int(seconds % 60)
            return f"{minutes:02d}:{seconds:02d}"

        # Affichage du temps des blancs
        white_text = font.render(
            f"Blancs: {format_time(self.white_time)}",
            True,
            p.Color("white") if white_to_move else p.Color("gray"),
        )
        screen.blit(white_text, (20, 20))

        # Affichage du temps des noirs
        black_text = font.render(
            f"Noirs: {format_time(self.black_time)}",
            True,
            p.Color("white") if not white_to_move else p.Color("gray"),
        )
        screen.blit(black_text, (20, 60))

    def draw_move_log(self, screen, game_state, font):
        # Panneau gauche
        left_panel_rect = p.Rect(0, 0, LEFT_PANEL_WIDTH, self.move_log_panel_height)
        p.draw.rect(screen, p.Color("black"), left_panel_rect)

        # Affichage du chronomètre
        self.draw_timer(screen, game_state.white_to_move)

        # Panneau droit (historique des coups)
        move_log_rect = p.Rect(
            self.board_width + LEFT_PANEL_WIDTH,
            0,
            self.move_log_panel_width,
            self.move_log_panel_height,
        )
        p.draw.rect(screen, p.Color("black"), move_log_rect)

        # Affichage des coups
        move_texts = self._move_lines(game_state)

        # Zone de défilement pour l'historique des coups
        line_height = font.get_height() + 2
        content_height = 5 + len(move_texts) * line_height
        self.max_scroll = max(0, content_height - self.move_log_panel_height)
        self.move_log_offset = min(self.move_log_offset, self.max_scroll)

        scroll_area = p.Surface((self.move_log_panel_width, self.move_log_panel_height))
        scroll_area.fill(p.Color("black"))
        y = 5 - self.move_log_offset
        for i, text in enumerate(move_texts):
            color = p.Color("yellow") if i == len(move_texts) - 1 else p.Color("white")
            text_surf = font.render(text, True, color)
            scroll_area.blit(text_surf, (5, y))
            y += font.get_height() + 2
        screen.blit(scroll_area, (self.board_width + LEFT_PANEL_WIDTH, 0))

    def _move_lines(self, game_state):
        """Historique en SAN, recalculé seulement quand la liste des coups change."""
        key = (id(game_state), tuple(m.move_id for m in game_state.move_log))
        if key != self._move_lines_key:
            sans = notation.san_history(game_state)
            white_starts = game_state.white_to_move == (len(sans) % 2 == 0)
            self._move_lines_cache = notation.format_move_lines(
                sans, game_state.start_fullmove, white_starts
            )
            self._move_lines_key = key
        return self._move_lines_cache

    def handle_scroll(self, event, mouse_pos):
        move_log_rect = p.Rect(
            self.board_width + LEFT_PANEL_WIDTH,
            0,
            self.move_log_panel_width,
            self.move_log_panel_height,
        )
        if move_log_rect.collidepoint(mouse_pos):
            new_offset = self.move_log_offset - event.y * self.SCROLL_SPEED
            self.move_log_offset = max(0, min(new_offset, self.max_scroll))

    def draw_loading_indicator(self, screen):
        font = p.font.SysFont("Arial", 24)
        dots = "." * ((p.time.get_ticks() // 500) % 4)
        text = font.render("IA réfléchit" + dots, True, p.Color("white"))
        screen.blit(text, (self.board_width + LEFT_PANEL_WIDTH + 10, self.board_height - 40))


# --------------------------------------------------
# Classes UI de base
# --------------------------------------------------
class Button:
    def __init__(self, text, pos, size, callback):
        self.text = text
        self.pos = pos
        self.size = size
        self.callback = callback
        self.rect = p.Rect(pos, size)
        self.hovered = False

    def draw(self, screen):
        color = p.Color("dodgerblue2") if self.hovered else p.Color("lightgray")
        p.draw.rect(screen, color, self.rect)
        font = p.font.SysFont("Arial", 24)
        text_surf = font.render(self.text, True, p.Color("black"))
        text_rect = text_surf.get_rect(center=self.rect.center)
        screen.blit(text_surf, text_rect)

    def check_hover(self, mouse_pos):
        self.hovered = self.rect.collidepoint(mouse_pos)


class PromotionPopup:
    """Choix de la pièce de promotion. Échap ou clic hors du popup : annulation."""

    def __init__(self, pos, size):
        self.rect = p.Rect(pos, size)
        self.pieces = ["Q", "R", "B", "N"]
        self.buttons = []
        btn_size = (60, 60)
        for i, piece in enumerate(self.pieces):
            x = self.rect.x + 10 + i * (btn_size[0] + 10)
            y = self.rect.centery - btn_size[1] // 2
            self.buttons.append(Button(piece, (x, y), btn_size, lambda: None))

    def draw(self, screen):
        p.draw.rect(screen, p.Color("white"), self.rect)
        p.draw.rect(screen, p.Color("black"), self.rect, 3)
        for btn in self.buttons:
            btn.check_hover(p.mouse.get_pos())
            btn.draw(screen)


# --------------------------------------------------
# Rendu du plateau
# --------------------------------------------------
class Renderer:
    """Encapsule tout le dessin du plateau et l'orientation.

    Remplace les fonctions de dessin au niveau module et la variable globale
    ``flip_board`` (cf. rapport d'analyse B22) : l'orientation est désormais un
    attribut d'objet, passé explicitement au lieu d'être mutée un peu partout.
    """

    def __init__(self, screen, sq_size, ui_manager, resource_manager, flip_board=False):
        self.screen = screen
        self.sq_size = sq_size
        self.ui = ui_manager
        self.resources = resource_manager
        self.flip_board = flip_board

    # -- conversion logique <-> affichage --------------------------------
    # Plateau retourné = rotation de 180° : rangées ET colonnes sont inversées.
    # La position du moteur, elle, ne change jamais (cf. rapport d'analyse B26).
    def display_row(self, row):
        return row if not self.flip_board else DIMENSION - 1 - row

    def display_col(self, col):
        return col if not self.flip_board else DIMENSION - 1 - col

    def square_from_pixel(self, pos):
        """(x, y) écran -> (row, col) logique, ou None si hors plateau."""
        disp_col = (pos[0] - LEFT_PANEL_WIDTH) // self.sq_size
        disp_row = pos[1] // self.sq_size
        if 0 <= disp_col < DIMENSION and 0 <= disp_row < DIMENSION:
            # La rotation est son propre inverse.
            return self.display_row(disp_row), self.display_col(disp_col)
        return None

    def square_rect(self, row, col):
        """Rectangle écran de la case logique (row, col)."""
        return self._rect(self.display_row(row), self.display_col(col))

    def file_label(self, disp_col):
        """Lettre de colonne affichée sous la colonne d'affichage ``disp_col``."""
        return "abcdefgh"[self.display_col(disp_col)]

    def rank_label(self, disp_row):
        """Numéro de rangée affiché à gauche de la rangée d'affichage ``disp_row``."""
        return str(DIMENSION - self.display_row(disp_row))

    def _rect(self, disp_row, disp_col):
        return p.Rect(
            disp_col * self.sq_size + LEFT_PANEL_WIDTH,
            disp_row * self.sq_size,
            self.sq_size,
            self.sq_size,
        )

    # -- dessin ---------------------------------------------------------
    @staticmethod
    def ease_out_cubic(t: float) -> float:
        return 1 - pow(1 - t, 3)

    def _square_color(self, disp_row, disp_col):
        # La rotation conserve la parité : a1 reste une case foncée.
        return self.ui.board_color1 if (disp_row + disp_col) % 2 == 0 else self.ui.board_color2

    def draw_board(self):
        font = p.font.SysFont("Arial", 16, bold=True)
        text_color = p.Color("black")
        for disp_row in range(DIMENSION):
            for disp_col in range(DIMENSION):
                rect = self._rect(disp_row, disp_col)
                p.draw.rect(self.screen, self._square_color(disp_row, disp_col), rect)
                if disp_col == 0:
                    rank_text = font.render(self.rank_label(disp_row), True, text_color)
                    self.screen.blit(rank_text, (rect.x + 2, rect.y + 2))
                if disp_row == DIMENSION - 1:
                    file_text = font.render(self.file_label(disp_col), True, text_color)
                    text_rect = file_text.get_rect(bottomright=(rect.right - 2, rect.bottom - 2))
                    self.screen.blit(file_text, text_rect)

    def draw_pieces(self, board):
        for row in range(DIMENSION):
            for col in range(DIMENSION):
                piece = board[row][col]
                if piece != "--":
                    self.screen.blit(self.resources.get_image(piece), self.square_rect(row, col))

    def highlight_squares(self, game_state, valid_moves, square_selected):
        if game_state.in_check:
            king_row, king_col = (
                game_state.white_king_location
                if game_state.white_to_move
                else game_state.black_king_location
            )
            s = p.Surface((self.sq_size, self.sq_size))
            s.set_alpha(150)
            s.fill(p.Color("red"))
            self.screen.blit(s, self.square_rect(king_row, king_col))
        if game_state.move_log:
            last_move = game_state.move_log[-1]
            s = p.Surface((self.sq_size, self.sq_size))
            s.set_alpha(100)
            s.fill(p.Color("green"))
            self.screen.blit(s, self.square_rect(last_move.end_row, last_move.end_col))
        if square_selected:
            row, col = square_selected
            s = p.Surface((self.sq_size, self.sq_size))
            s.set_alpha(100)
            s.fill(p.Color("blue"))
            self.screen.blit(s, self.square_rect(row, col))
            s.fill(p.Color("yellow"))
            for move in valid_moves:
                if move.start_row == row and move.start_col == col:
                    self.screen.blit(s, self.square_rect(move.end_row, move.end_col))

    def draw_end_game_text(self, text):
        # Taille réduite au besoin pour que le texte tienne dans le plateau (marge 16 px).
        size = 32
        font = p.font.SysFont("Helvetica", size, True, False)
        while font.size(text)[0] > BOARD_WIDTH - 32 and size > 12:
            size -= 2
            font = p.font.SysFont("Helvetica", size, True, False)
        text_object = font.render(text, True, p.Color("gray"))
        text_location = p.Rect(0, 0, BOARD_WIDTH, BOARD_HEIGHT).move(
            LEFT_PANEL_WIDTH + BOARD_WIDTH / 2 - text_object.get_width() / 2,
            BOARD_HEIGHT / 2 - text_object.get_height() / 2,
        )
        self.screen.blit(text_object, text_location)
        text_object = font.render(text, True, p.Color("black"))
        self.screen.blit(text_object, text_location.move(2, 2))

    def animate_move(self, move, board, clock):
        d_row = move.end_row - move.start_row
        d_col = move.end_col - move.start_col
        frames_per_square = 3
        frame_count = int((abs(d_row) + abs(d_col)) * frames_per_square)
        if frame_count == 0:
            return
        end_rect = self.square_rect(move.end_row, move.end_col)
        end_color = self._square_color(
            self.display_row(move.end_row), self.display_col(move.end_col)
        )
        for frame in range(frame_count + 1):
            t = frame / frame_count
            eased_t = self.ease_out_cubic(t)
            # Coordonnées logiques fractionnaires, puis passage en affichage.
            disp_row = self.display_row(move.start_row + d_row * eased_t)
            disp_col = self.display_col(move.start_col + d_col * eased_t)
            self.draw_board()
            self.draw_pieces(board)
            p.draw.rect(self.screen, end_color, end_rect)
            if move.piece_captured != "--":
                capture_rect = end_rect
                if move.is_enpassant_move:
                    capture_rect = self.square_rect(move.start_row, move.end_col)
                self.screen.blit(self.resources.get_image(move.piece_captured), capture_rect)
            self.screen.blit(
                self.resources.get_image(move.piece_moved),
                p.Rect(
                    disp_col * self.sq_size + LEFT_PANEL_WIDTH,
                    disp_row * self.sq_size,
                    self.sq_size,
                    self.sq_size,
                ),
            )
            p.display.flip()
            clock.tick(60)


# --------------------------------------------------
# Menus dynamiques de personnalisation
# --------------------------------------------------
def game_mode_menu(screen):
    buttons = []
    button_width = 200
    button_height = 50
    spacing = 20
    menu_surface = p.Surface(screen.get_size())
    menu_surface.fill(p.Color("white"))
    w, h = screen.get_size()
    total_height = 4 * button_height + 3 * spacing
    start_y = (h - total_height) // 2
    positions = [
        ((w - button_width) // 2, start_y),
        ((w - button_width) // 2, start_y + button_height + spacing),
        ((w - button_width) // 2, start_y + 2 * (button_height + spacing)),
        ((w - button_width) // 2, start_y + 3 * (button_height + spacing)),
    ]
    buttons.append(
        Button(
            "Joueur vs Joueur",
            positions[0],
            (button_width, button_height),
            lambda: ("PvP", True, True),
        )
    )
    buttons.append(
        Button(
            "Joueur vs IA",
            positions[1],
            (button_width, button_height),
            lambda: open_color_selection(screen, "PvC"),
        )
    )
    buttons.append(
        Button(
            "IA vs IA", positions[2], (button_width, button_height), lambda: ("CvC", False, False)
        )
    )
    buttons.append(
        Button("Quitter", positions[3], (button_width, button_height), lambda: sys.exit())
    )
    while True:
        menu_surface.fill(p.Color("white"))
        for btn in buttons:
            btn.check_hover(p.mouse.get_pos())
            btn.draw(menu_surface)
        for e in p.event.get():
            if e.type == p.QUIT:
                sys.exit()
            if e.type == p.MOUSEBUTTONDOWN:
                for btn in buttons:
                    if btn.rect.collidepoint(e.pos):
                        return btn.callback()
        screen.blit(menu_surface, (0, 0))
        p.display.flip()


def choice_menu(screen, title, options):
    """Menu générique : un titre et une colonne de boutons ; renvoie la valeur choisie.
    ``options`` : liste de couples (libellé, valeur)."""
    button_width, button_height, spacing = 240, 44, 14
    w, h = screen.get_size()
    total_height = len(options) * (button_height + spacing) - spacing
    start_y = max(70, (h - total_height) // 2)
    buttons = [
        Button(
            label,
            ((w - button_width) // 2, start_y + i * (button_height + spacing)),
            (button_width, button_height),
            lambda value=value: value,
        )
        for i, (label, value) in enumerate(options)
    ]
    title_font = p.font.SysFont("Arial", 30, bold=True)
    title_surface = title_font.render(title, True, p.Color("black"))
    menu_surface = p.Surface(screen.get_size())
    while True:
        menu_surface.fill(p.Color("white"))
        menu_surface.blit(title_surface, title_surface.get_rect(center=(w // 2, start_y - 40)))
        for btn in buttons:
            btn.check_hover(p.mouse.get_pos())
            btn.draw(menu_surface)
        for e in p.event.get():
            if e.type == p.QUIT:
                sys.exit()
            if e.type == p.MOUSEBUTTONDOWN:
                for btn in buttons:
                    if btn.rect.collidepoint(e.pos):
                        return btn.callback()
        screen.blit(menu_surface, (0, 0))
        p.display.flip()


def level_menu(screen):
    return choice_menu(
        screen, "Niveau de l'IA", [(level.name, level.name) for level in levels.LEVELS]
    )


def time_control_menu(screen):
    return choice_menu(
        screen, "Cadence", [(control.name, control) for control in chess_clock_module.PRESETS]
    )


def open_color_selection(screen, mode):
    buttons = []
    button_width = 200
    button_height = 50
    spacing = 20
    menu_surface = p.Surface(screen.get_size())
    menu_surface.fill(p.Color("white"))
    w, h = screen.get_size()
    total_height = 2 * button_height + spacing
    start_y = (h - total_height) // 2
    positions = [
        ((w - button_width) // 2, start_y),
        ((w - button_width) // 2, start_y + button_height + spacing),
    ]
    buttons.append(
        Button("Blanc", positions[0], (button_width, button_height), lambda: (mode, True, False))
    )
    buttons.append(
        Button("Noir", positions[1], (button_width, button_height), lambda: (mode, False, True))
    )
    while True:
        menu_surface.fill(p.Color("white"))
        for btn in buttons:
            btn.check_hover(p.mouse.get_pos())
            btn.draw(menu_surface)
        for e in p.event.get():
            if e.type == p.QUIT:
                sys.exit()
            if e.type == p.MOUSEBUTTONDOWN:
                for btn in buttons:
                    if btn.rect.collidepoint(e.pos):
                        return btn.callback()
        screen.blit(menu_surface, (0, 0))
        p.display.flip()


def customization_menu(screen, ui_manager):
    options = [
        (p.Color("white"), p.Color("gray")),
        (p.Color("beige"), p.Color("saddlebrown")),
        (p.Color("lightgreen"), p.Color("darkgreen")),
    ]
    buttons = []
    button_width = 250
    button_height = 50
    spacing = 20
    menu_surface = p.Surface(screen.get_size())
    menu_surface.fill(p.Color("white"))
    w, h = screen.get_size()
    total_height = len(options) * button_height + (len(options) - 1) * spacing
    start_y = (h - total_height) // 2
    for i, (col1, col2) in enumerate(options):
        pos = ((w - button_width) // 2, start_y + i * (button_height + spacing))

        def callback(c1=col1, c2=col2):
            ui_manager.board_color1 = c1
            ui_manager.board_color2 = c2

        buttons.append(Button(f"Couleurs {i + 1}", pos, (button_width, button_height), callback))
    while True:
        menu_surface.fill(p.Color("white"))
        for btn in buttons:
            btn.check_hover(p.mouse.get_pos())
            btn.draw(menu_surface)
        for e in p.event.get():
            if e.type == p.QUIT:
                sys.exit()
            if e.type == p.MOUSEBUTTONDOWN:
                for btn in buttons:
                    if btn.rect.collidepoint(e.pos):
                        btn.callback()
                        return
        screen.blit(menu_surface, (0, 0))
        p.display.flip()


def show_shortcuts_menu(screen):
    menu_surface = p.Surface(screen.get_size())
    menu_surface.fill(p.Color("white"))
    w, h = screen.get_size()

    # Création du bouton retour
    back_button = Button("Retour", (w // 2 - 100, h - 100), (200, 50), lambda: None)

    # Liste des raccourcis
    shortcuts = [
        ("Z", "Annuler le dernier coup"),
        ("R", "Réinitialiser la partie"),
        ("S", "Sauvegarder la partie"),
        ("L", "Charger la partie"),
        ("C", "Personnaliser les couleurs"),
        ("E", "Exporter la partie en PGN"),
        ("I", "Importer la partie PGN"),
        ("A", "Abandonner la partie"),
        ("N", "Proposer / accepter la nulle"),
        ("H", "Afficher/masquer les raccourcis"),
    ]

    # Affichage des raccourcis
    font = p.font.SysFont("Arial", 24)
    title_font = p.font.SysFont("Arial", 32, bold=True)

    # Titre
    title = title_font.render("Raccourcis Clavier", True, p.Color("black"))
    title_rect = title.get_rect(center=(w // 2, 50))
    menu_surface.blit(title, title_rect)

    # Raccourcis
    for i, (key, desc) in enumerate(shortcuts):
        key_text = font.render(f"{key}:", True, p.Color("blue"))
        desc_text = font.render(desc, True, p.Color("black"))
        y_pos = 150 + i * 40
        menu_surface.blit(key_text, (w // 2 - 150, y_pos))
        menu_surface.blit(desc_text, (w // 2 - 100, y_pos))

    while True:
        for e in p.event.get():
            if e.type == p.QUIT:
                sys.exit()
            if e.type == p.MOUSEBUTTONDOWN:
                if back_button.rect.collidepoint(e.pos):
                    return
            if e.type == p.KEYDOWN:
                if e.key == p.K_h:
                    return

        back_button.check_hover(p.mouse.get_pos())
        back_button.draw(menu_surface)
        screen.blit(menu_surface, (0, 0))
        p.display.flip()


# --------------------------------------------------
# Initialisation des sons
# --------------------------------------------------
move_sound = None
capture_sound = None
gameover_sound = None


def _load_sounds() -> None:
    """Initialise le mixer et charge les sons. Appelé depuis main() pour éviter
    d'ouvrir le périphérique audio à l'import (effet de bord pour les tests)."""
    global move_sound, capture_sound, gameover_sound
    try:
        p.mixer.init()
    except Exception as e:
        logger.warning("Impossible d'initialiser l'audio: %s", e)
        return
    for name, path in (
        ("move_sound", "move1.wav"),
        ("capture_sound", "capture1.wav"),
        ("gameover_sound", "gameover.wav"),
    ):
        try:
            globals()[name] = p.mixer.Sound(paths.SOUNDS_DIR / path)
        except Exception as e:
            logger.warning("Erreur chargement son %s: %s", path, e)


def _play_move_sound(move) -> None:
    sound = capture_sound if move.is_capture else move_sound
    if sound:
        sound.play()


# --------------------------------------------------
# Contrôleur de partie
# --------------------------------------------------
DRAW_ACCEPT_THRESHOLD_CP = 25  # l'IA accepte la nulle si elle ne s'estime pas mieux


def ai_accepts_draw(game_state, ai_is_white):
    """L'IA accepte une proposition de nulle si une courte recherche ne lui donne pas
    l'avantage (au plus DRAW_ACCEPT_THRESHOLD_CP centipions)."""
    result = search.think(game_state, search.SearchLimits(depth=2, movetime_ms=300))
    # Score du point de vue du camp au trait, ramené au point de vue de l'IA.
    ai_to_move = game_state.white_to_move == ai_is_white
    ai_score = result.score if ai_to_move else -result.score
    return ai_score <= DRAW_ACCEPT_THRESHOLD_CP


class GameController:
    """Boucle de jeu : événements, IA, rendu. Extrait de l'ancienne fonction
    ``main()`` monolithique (cf. rapport d'analyse : découpage de main())."""

    def __init__(
        self,
        screen,
        clock,
        ui_manager,
        resource_manager,
        mode,
        player_one,
        player_two,
        flip_board,
        *,
        time_control=None,
        clock_now=None,
    ):
        self.screen = screen
        self.clock = clock
        self.ui = ui_manager
        self.mode = mode
        self.player_one = player_one  # humain joue les blancs
        self.player_two = player_two  # humain joue les noirs
        self.renderer = Renderer(screen, SQ_SIZE, ui_manager, resource_manager, flip_board)
        self.move_log_font = p.font.SysFont("Arial", 14)

        self.game_state = engine.GameState()
        self.valid_moves = self.game_state.get_valid_moves()
        self.ui.reset_timer()

        # Pendule à cadence (J4.1) : un appui par coup joué, synchronisé dans update().
        self.time_control = time_control or chess_clock_module.DEFAULT
        self._clock_now = clock_now or time.monotonic
        self._start_clock()

        self.square_selected: tuple[int, int] | tuple[()] = ()
        self.player_clicks: list[tuple[int, int]] = []
        self.move_made = False
        self.animate = False

        self.ai_thinking = False
        self.ai_started_at = 0.0
        self.ai_overhead_ms = AI_INITIAL_OVERHEAD_MS
        self._ai_requested_ms = None
        # Niveau de l'IA (choix dans le menu prévu en J4.6).
        self.ai_level = levels.DEFAULT_LEVEL.name
        self.move_finder_process = None
        self.return_queue = None

        self.promotion_popup: PromotionPopup | None = None
        # Les 4 coups légaux de promotion (Q, R, B, N) de la case choisie.
        self.promotion_moves: list[engine.Move] = []

        # Fin de partie décidée hors de l'échiquier (abandon, accord, temps : J4).
        self.external_result: engine.GameResult | None = None
        # Proposition de nulle en attente (PvP) : (camp qui propose, nombre de demi-coups
        # joués au moment de la proposition). Un coup de l'adversaire la décline.
        self.draw_offer: tuple[engine.Color, int] | None = None

    # -- helpers -------------------------------------------------------
    @property
    def result(self):
        """Fin hors échiquier (abandon, accord…) si elle existe, sinon celle du moteur."""
        return self.external_result or self.game_state.result()

    @property
    def game_over(self):
        """Dérivé du résultat : aucun drapeau à resynchroniser."""
        return self.result.is_over

    @property
    def flip_board(self):
        return self.renderer.flip_board

    def human_turn(self):
        return (self.game_state.white_to_move and self.player_one) or (
            not self.game_state.white_to_move and self.player_two
        )

    def _reset_selection(self):
        self.square_selected = ()
        self.player_clicks = []

    def _stop_ai(self):
        if self.ai_thinking and self.move_finder_process:
            self.move_finder_process.terminate()
        self.ai_thinking = False

    def _start_clock(self, saved_clock=None):
        """Nouvelle pendule (ou pendule sauvegardée) pour la partie courante."""
        if saved_clock is not None:
            self.chess_clock = chess_clock_module.ChessClock.from_dict(saved_clock, self._clock_now)
            self.time_control = self.chess_clock.control
        else:
            self.chess_clock = chess_clock_module.ChessClock(self.time_control, self._clock_now)
            self.chess_clock.start(self.game_state.white_to_move)
        # Coups déjà joués avant cette pendule (partie chargée sans pendule).
        self._clock_base_plies = len(self.game_state.move_log) - self.chess_clock.press_count
        self.ui.chess_clock = self.chess_clock

    def _sync_clock(self):
        """Un appui par coup joué, un retour arrière par coup annulé."""
        target = len(self.game_state.move_log) - self._clock_base_plies
        while self.chess_clock.press_count < target:
            self.chess_clock.press()
        while self.chess_clock.press_count > max(target, 0):
            if not self.chess_clock.undo_press():
                break

    @contextmanager
    def _paused(self):
        """Ni le chronomètre ni la pendule ne tournent pendant un menu ou une animation."""
        with self.ui.timer_paused(), self.chess_clock.paused():
            yield

    def _new_game(self, game_state, saved_clock=None):
        self.game_state = game_state
        self.external_result = None
        self.draw_offer = None
        self._start_clock(saved_clock)
        self.valid_moves = self.game_state.get_valid_moves()
        self._reset_selection()
        self.move_made = False
        self.animate = False
        self.ui.reset_timer()
        self._stop_ai()

    # -- gestion des événements --------------------------------------
    def handle_event(self, e):
        if e.type == p.QUIT:
            self._stop_ai()  # ne pas attendre la fin de la recherche (B45)
            p.quit()
            sys.exit()
        if e.type == p.MOUSEWHEEL:
            self.ui.handle_scroll(e, p.mouse.get_pos())
            return
        if self.promotion_popup:
            self._handle_promotion_event(e)
            return
        if e.type == p.MOUSEBUTTONDOWN:
            self._handle_board_click(e.pos)
        elif e.type == p.KEYDOWN:
            self._handle_keydown(e)

    def _close_promotion_popup(self):
        self.promotion_popup = None
        self.promotion_moves = []

    def _handle_promotion_event(self, e):
        assert self.promotion_popup is not None
        if e.type == p.KEYDOWN and e.key == p.K_ESCAPE:
            self._close_promotion_popup()
            return
        if e.type != p.MOUSEBUTTONDOWN:
            return
        if not self.promotion_popup.rect.collidepoint(e.pos):
            self._close_promotion_popup()
            return
        for btn in self.promotion_popup.buttons:
            if btn.rect.collidepoint(e.pos):
                # Le coup joué est celui que le moteur a généré pour cette pièce :
                # historique, sauvegarde et plateau restent cohérents (B29).
                move = next(m for m in self.promotion_moves if m.promotion_piece == btn.text)
                self.game_state.make_move(move)
                _play_move_sound(move)
                logger.info("Coup joué : %s", move)
                self.move_made = True
                self.animate = True
                self._close_promotion_popup()
                return

    def _handle_board_click(self, pos):
        if self.game_over or not self.human_turn():
            return
        square = self.renderer.square_from_pixel(pos)
        if square is None:
            return
        row, col = square
        my_color = "w" if self.game_state.white_to_move else "b"
        piece = self.game_state.board[row][col]

        if not self.player_clicks:
            if piece == "--" or piece[0] != my_color:
                self._reset_selection()
                return
            self.square_selected = (row, col)
            self.player_clicks.append(self.square_selected)
            return

        # deuxième clic : re-sélection si on clique une de ses pièces
        if piece != "--" and piece[0] == my_color:
            self.square_selected = (row, col)
            self.player_clicks = [self.square_selected]
            return

        self.square_selected = (row, col)
        self.player_clicks.append(self.square_selected)
        if len(self.player_clicks) == 2:
            self._try_move(self.player_clicks[0], self.player_clicks[1])

    def _try_move(self, start, end):
        move = engine.Move(start, end, self.game_state.board)
        for valid_move in self.valid_moves:
            if move != valid_move:
                continue
            if valid_move.is_pawn_promotion:
                self.promotion_moves = [
                    m
                    for m in self.valid_moves
                    if m.is_pawn_promotion
                    and (m.start_row, m.start_col, m.end_row, m.end_col)
                    == (start[0], start[1], end[0], end[1])
                ]
                self.promotion_popup = PromotionPopup(
                    (BOARD_WIDTH // 2 - 150 + LEFT_PANEL_WIDTH, BOARD_HEIGHT // 2 - 50),
                    (300, 100),
                )
            else:
                self.game_state.make_move(valid_move)
                self.move_made = True
                _play_move_sound(valid_move)
                logger.info("Coup joué : %s", valid_move)
            self._reset_selection()
            return

    def _handle_keydown(self, e):
        if e.key == p.K_z:  # Retour en arrière
            if self.game_state.move_log:
                self.game_state.undo_move()
                logger.info("Undo effectué")
            # Contre l'IA seulement : annuler aussi le coup de l'IA pour rendre
            # la main au joueur. En PvP/CvC, un seul undo.
            if self.mode == "PvC" and self.game_state.move_log and not self.human_turn():
                self.game_state.undo_move()
            self.external_result = None  # annuler rouvre une partie abandonnée ou nulle
            self.draw_offer = None
            self.move_made = True
            self.animate = False
            self._stop_ai()
        elif e.key == p.K_r:  # Réinitialiser
            self._new_game(engine.GameState())
            logger.info("Partie réinitialisée")
        elif e.key == p.K_s:  # Sauvegarder
            serialization.save_game(
                self.game_state,
                flip_board=self.flip_board,
                filename=str(paths.save_file()),
                mode=self.mode,
                human_white=self.player_one,
                human_black=self.player_two,
                level=self.ai_level,
                clock=self.chess_clock.to_dict(),
                result=self.external_result,
            )
        elif e.key == p.K_l:  # Charger
            try:
                saved = serialization.load_save(str(paths.existing_save_file()))
            except Exception as ex:  # noqa: BLE001 - fichier absent, illisible ou illégal
                logger.error("Erreur lors du chargement : %s", ex)
                return
            self.renderer.flip_board = saved.flip_board
            if saved.mode is not None:
                self.mode = saved.mode
                self.player_one = bool(saved.human_white)
                self.player_two = bool(saved.human_black)
            if saved.level in levels.LEVELS_BY_NAME:
                self.ai_level = saved.level
            self._new_game(saved.game_state, saved.clock)
            self.external_result = saved.result
        elif e.key == p.K_e:  # Exporter en PGN
            self._export_pgn()
        elif e.key == p.K_i:  # Importer un PGN
            self._import_pgn()
        elif e.key == p.K_a:  # Abandonner
            self._resign()
        elif e.key == p.K_n:  # Proposer / accepter la nulle
            self._offer_draw()
        elif e.key == p.K_c:  # Couleurs
            with self._paused():
                customization_menu(self.screen, self.ui)
        elif e.key == p.K_h:  # Raccourcis
            with self._paused():
                show_shortcuts_menu(self.screen)

    def _player_name(self, white):
        human = self.player_one if white else self.player_two
        return "Humain" if human else f"ChessProject ({self.ai_level})"

    def _export_pgn(self):
        headers = {
            "Event": "Partie ChessProject",
            "Date": time.strftime("%Y.%m.%d"),
            "White": self._player_name(True),
            "Black": self._player_name(False),
        }
        if not self.time_control.is_unlimited:
            headers["TimeControl"] = self.time_control.pgn_tag
        text = pgn.export_pgn(self.game_state, result=self.result, headers=headers)
        path = paths.pgn_file()
        try:
            path.write_text(text, encoding="utf-8")
            logger.info("Partie exportée en PGN dans %s", path)
        except OSError as ex:
            logger.error("Export PGN impossible : %s", ex)

    def _import_pgn(self):
        try:
            game = pgn.read_pgn_file(paths.pgn_file())[-1]
            state = game.replay()
        except (OSError, IndexError, pgn.PgnError) as ex:
            logger.error("Import PGN impossible : %s", ex)
            return
        # La partie continue avec les règles du jeu (nulles automatiques).
        state.automatic_draws = True
        state._valid_moves = None
        self._new_game(state)
        logger.info("Partie importée (%d coups)", len(state.move_log))

    def _human_color(self):
        """Camp de l'humain qui agit : celui au trait en PvP, l'unique humain en PvC."""
        if self.mode == "PvC":
            return engine.Color.WHITE if self.player_one else engine.Color.BLACK
        if self.mode == "PvP":
            return engine.Color.WHITE if self.game_state.white_to_move else engine.Color.BLACK
        return None  # IA contre IA : personne n'abandonne

    def _resign(self):
        color = self._human_color()
        if color is None or self.game_over:
            return
        winner = engine.Color.BLACK if color is engine.Color.WHITE else engine.Color.WHITE
        self.external_result = engine.GameResult(engine.Termination.RESIGNATION, winner)
        self._stop_ai()
        logger.info("Abandon : %s", self.external_result.description)

    def _offer_draw(self):
        color = self._human_color()
        if color is None or self.game_over:
            return
        plies = len(self.game_state.move_log)
        if self.mode == "PvC":
            ai_is_white = not self.player_one
            accepted = ai_accepts_draw(self.game_state, ai_is_white)
            logger.info("Nulle proposée à l'IA : %s", "acceptée" if accepted else "refusée")
            if accepted:
                self.external_result = engine.GameResult(engine.Termination.DRAW_AGREEMENT)
                self._stop_ai()
            return
        # PvP : l'adversaire accepte en appuyant à son tour sur N, avant de jouer.
        offer = self.draw_offer
        if offer is not None and offer[0] is not color and offer[1] == plies - 1:
            self.external_result = engine.GameResult(engine.Termination.DRAW_AGREEMENT)
            self.draw_offer = None
        else:
            self.draw_offer = (color, plies)

    # -- IA ----------------------------------------------------------
    def update_ai(self):
        if self.game_over or self.human_turn() or self.promotion_popup:
            return
        # Toujours partir de la liste légale de la position courante (mise en
        # cache par le moteur), jamais d'une liste potentiellement périmée.
        valid_moves = self.game_state.get_valid_moves()
        if not self.ai_thinking:
            self.ai_thinking = True
            self.ai_started_at = time.monotonic()
            self._ai_requested_ms = self._ai_think_time_ms()
            self.return_queue = Queue()
            # daemon : le processus est tué avec l'application au lieu d'être attendu.
            self.move_finder_process = Process(
                target=search.find_best_move,
                args=(
                    self.game_state,
                    valid_moves,
                    self.return_queue,
                    self.ai_level,
                    self._ai_requested_ms,
                ),
                daemon=True,
            )
            self.move_finder_process.start()
        if self.move_finder_process is None:
            return
        if self.move_finder_process.is_alive():
            if time.monotonic() - self.ai_started_at < AI_MAX_THINK_SECONDS:
                return
            logger.error("IA arrêtée : plus de %.0f s de réflexion", AI_MAX_THINK_SECONDS)
            self.move_finder_process.terminate()
            ai_move = None
        else:
            ai_move = self._collect_ai_move()
        if ai_move not in valid_moves:
            if ai_move is not None:
                logger.error("Coup de l'IA illégal ignoré : %s", ai_move)
            ai_move = search.find_random_move(valid_moves)
        self._measure_ai_overhead()
        self.game_state.make_move(ai_move)
        _play_move_sound(ai_move)
        self.move_made = True
        self.animate = True
        self.ai_thinking = False
        logger.info("Coup joué par l'IA : %s", ai_move)

    def _ai_think_time_ms(self):
        """Plafond de réflexion de l'IA selon sa pendule (None sans cadence, J4.2)."""
        if self.chess_clock.is_unlimited:
            return None
        color = engine.Color.WHITE if self.game_state.white_to_move else engine.Color.BLACK
        remaining = self.chess_clock.remaining_ms(color) or 0
        budget = chess_clock_module.allocate_think_time_ms(
            remaining,
            self.time_control.increment_ms,
            len(self.game_state.move_log),
            max_ms=levels.LEVELS_BY_NAME[self.ai_level].movetime_ms,
        )
        # Le surcoût mesuré se paie sur la pendule : on le retranche du temps de réflexion.
        return max(10, int(budget - self.ai_overhead_ms))

    def _measure_ai_overhead(self):
        """Met à jour l'estimation du surcoût (temps réel - temps de réflexion demandé)."""
        if self._ai_requested_ms is None:
            return
        actual_ms = (time.monotonic() - self.ai_started_at) * 1000
        overhead = max(0.0, actual_ms - self._ai_requested_ms)
        self.ai_overhead_ms += AI_OVERHEAD_SMOOTHING * (overhead - self.ai_overhead_ms)

    def _collect_ai_move(self):
        """Récupère le coup d'un processus d'IA terminé, ou None s'il n'en a pas rendu."""
        assert self.return_queue is not None and self.move_finder_process is not None
        try:
            # Délai court : le processus est terminé, son résultat est déjà en route.
            return self.return_queue.get(timeout=AI_RESULT_TIMEOUT_SECONDS)
        except queue.Empty:
            logger.error(
                "Le processus d'IA s'est terminé sans coup (code %s)",
                self.move_finder_process.exitcode,
            )
            return None

    # -- rendu -----------------------------------------------------
    def draw(self):
        self.renderer.draw_board()
        self.renderer.draw_pieces(self.game_state.board)
        self.renderer.highlight_squares(self.game_state, self.valid_moves, self.square_selected)
        self.ui.draw_move_log(self.screen, self.game_state, self.move_log_font)
        if self.ai_thinking:
            self.ui.draw_loading_indicator(self.screen)
        if self.promotion_popup:
            self.promotion_popup.draw(self.screen)
        self._draw_status()
        result = self.result
        if result.is_over:
            self.renderer.draw_end_game_text(result.description)

    def _draw_status(self):
        """Panneau de gauche, sous la pendule : niveau de l'IA, nulle proposée."""
        font = self.move_log_font
        lines = []
        if self.mode in ("PvC", "CvC"):
            lines.append(f"IA : {self.ai_level}")
        if self.draw_offer is not None and not self.game_over:
            camp = "Blancs" if self.draw_offer[0] is engine.Color.WHITE else "Noirs"
            lines.append(f"Nulle proposée par les {camp}")
            lines.append("(N pour accepter)")
        for i, text in enumerate(lines):
            self.screen.blit(font.render(text, True, p.Color("white")), (20, 125 + 20 * i))

    # -- boucle principale --------------------------------------
    def update(self):
        """Une étape de logique de jeu (sans dessin) : appelée à chaque image."""
        # Rafraîchir la liste des coups légaux AVANT de lancer l'IA : sinon
        # l'IA reçoit la liste du camp précédent (coup humain déjà joué) et
        # renvoie un coup rejeté par make_move (« Mouvement non valide »).
        self._sync_clock()
        if not self.game_over:
            flagged = self.chess_clock.flagged()
            if flagged is not None:
                self.external_result = chess_clock_module.timeout_result(self.game_state, flagged)
                self._stop_ai()
                logger.info("Fin au temps : %s", self.external_result.description)
        # Partie terminée : la pendule est figée (une annulation la relance).
        if self.game_over:
            self.chess_clock.pause()
        else:
            self.chess_clock.resume()
        if self.move_made:
            if self.animate and self.game_state.move_log:
                with self._paused():
                    self.renderer.animate_move(
                        self.game_state.move_log[-1], self.game_state.board, self.clock
                    )
            self.valid_moves = self.game_state.get_valid_moves()
            self.move_made = False
            self.animate = False

        self.update_ai()

    def run(self):
        while True:
            if not self.game_over:
                self.ui.update_timer(self.game_state.white_to_move)
            else:
                self.ui.is_running = False

            for e in p.event.get():
                self.handle_event(e)

            self.update()

            self.draw()
            self.clock.tick(MAX_FPS)
            p.display.flip()


# --------------------------------------------------
# Fonction principale
# --------------------------------------------------
def main():
    _configure_logging()
    p.init()
    _load_sounds()
    screen = p.display.set_mode(
        (BOARD_WIDTH + MOVE_LOG_PANEL_WIDTH + LEFT_PANEL_WIDTH, BOARD_HEIGHT), p.RESIZABLE
    )
    clock = p.time.Clock()
    ui_manager = UIManager(BOARD_WIDTH, BOARD_HEIGHT, MOVE_LOG_PANEL_WIDTH, MOVE_LOG_PANEL_HEIGHT)
    resource_manager = ResourceManager(SQ_SIZE)

    mode, player_one, player_two = game_mode_menu(screen)
    # En PvC, si le joueur humain a les noirs, on retourne le plateau.
    flip_board = mode == "PvC" and not player_one

    level = level_menu(screen) if mode in ("PvC", "CvC") else levels.DEFAULT_LEVEL.name
    time_control = time_control_menu(screen)

    controller = GameController(
        screen,
        clock,
        ui_manager,
        resource_manager,
        mode,
        player_one,
        player_two,
        flip_board,
        time_control=time_control,
    )
    controller.ai_level = level
    controller.run()


if __name__ == "__main__":
    main()
