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

import ChessAI
import ChessEngine
import notation
import paths
import serialization

# --------------------------------------------------
# Constantes d'affichage
# --------------------------------------------------
DIMENSION = ChessEngine.DIMENSION
BOARD_WIDTH = BOARD_HEIGHT = 512
MOVE_LOG_PANEL_WIDTH = 250
LEFT_PANEL_WIDTH = 250
MOVE_LOG_PANEL_HEIGHT = BOARD_HEIGHT
MAX_FPS = 30
# Garde-fous du processus d'IA (B33) : au-delà, il est arrêté et un coup de
# repli est joué. La limite de réflexion pilotée par niveau viendra en J3.
AI_MAX_THINK_SECONDS = 30.0
AI_RESULT_TIMEOUT_SECONDS = 1.0
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
        key = (id(game_state), tuple(m.moveID for m in game_state.move_log))
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
def gameModeMenu(screen):
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
class GameController:
    """Boucle de jeu : événements, IA, rendu. Extrait de l'ancienne fonction
    ``main()`` monolithique (cf. rapport d'analyse : découpage de main())."""

    def __init__(
        self, screen, clock, ui_manager, resource_manager, mode, player_one, player_two, flip_board
    ):
        self.screen = screen
        self.clock = clock
        self.ui = ui_manager
        self.mode = mode
        self.player_one = player_one  # humain joue les blancs
        self.player_two = player_two  # humain joue les noirs
        self.renderer = Renderer(screen, SQ_SIZE, ui_manager, resource_manager, flip_board)
        self.move_log_font = p.font.SysFont("Arial", 14)

        self.game_state = ChessEngine.GameState()
        self.valid_moves = self.game_state.getValidMoves()
        self.ui.reset_timer()

        self.square_selected: tuple[int, int] | tuple[()] = ()
        self.player_clicks: list[tuple[int, int]] = []
        self.move_made = False
        self.animate = False

        self.ai_thinking = False
        self.ai_started_at = 0.0
        self.move_finder_process = None
        self.return_queue = None

        self.promotion_popup: PromotionPopup | None = None
        # Les 4 coups légaux de promotion (Q, R, B, N) de la case choisie.
        self.promotion_moves: list[ChessEngine.Move] = []

    # -- helpers -------------------------------------------------------
    @property
    def game_over(self):
        """Dérivé du moteur (mat, pat ou nulle) : aucun drapeau à resynchroniser."""
        return self.game_state.result().is_over

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

    def _new_game(self, game_state):
        self.game_state = game_state
        self.valid_moves = self.game_state.getValidMoves()
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
                self.game_state.makeMove(move)
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
        move = ChessEngine.Move(start, end, self.game_state.board)
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
                self.game_state.makeMove(valid_move)
                self.move_made = True
                _play_move_sound(valid_move)
                logger.info("Coup joué : %s", valid_move)
            self._reset_selection()
            return

    def _handle_keydown(self, e):
        if e.key == p.K_z:  # Retour en arrière
            if self.game_state.move_log:
                self.game_state.undoMove()
                logger.info("Undo effectué")
            # Contre l'IA seulement : annuler aussi le coup de l'IA pour rendre
            # la main au joueur. En PvP/CvC, un seul undo.
            if self.mode == "PvC" and self.game_state.move_log and not self.human_turn():
                self.game_state.undoMove()
            self.move_made = True
            self.animate = False
            self._stop_ai()
        elif e.key == p.K_r:  # Réinitialiser
            self._new_game(ChessEngine.GameState())
            logger.info("Partie réinitialisée")
        elif e.key == p.K_s:  # Sauvegarder
            serialization.save_game(
                self.game_state, flip_board=self.flip_board, filename=str(paths.save_file())
            )
        elif e.key == p.K_l:  # Charger
            try:
                loaded, flip = serialization.load_game(str(paths.existing_save_file()))
                self.renderer.flip_board = flip
                self._new_game(loaded)
            except Exception as ex:
                logger.error("Erreur lors du chargement : %s", ex)
        elif e.key == p.K_c:  # Couleurs
            with self.ui.timer_paused():
                customization_menu(self.screen, self.ui)
        elif e.key == p.K_h:  # Raccourcis
            with self.ui.timer_paused():
                show_shortcuts_menu(self.screen)

    # -- IA ----------------------------------------------------------
    def update_ai(self):
        if self.game_over or self.human_turn() or self.promotion_popup:
            return
        # Toujours partir de la liste légale de la position courante (mise en
        # cache par le moteur), jamais d'une liste potentiellement périmée.
        valid_moves = self.game_state.getValidMoves()
        if not self.ai_thinking:
            self.ai_thinking = True
            self.ai_started_at = time.monotonic()
            self.return_queue = Queue()
            # daemon : le processus est tué avec l'application au lieu d'être attendu.
            self.move_finder_process = Process(
                target=ChessAI.findBestMove,
                args=(self.game_state, valid_moves, self.return_queue),
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
            ai_move = ChessAI.findRandomMove(valid_moves)
        self.game_state.makeMove(ai_move)
        _play_move_sound(ai_move)
        self.move_made = True
        self.animate = True
        self.ai_thinking = False
        logger.info("Coup joué par l'IA : %s", ai_move)

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
        result = self.game_state.result()
        if result.is_over:
            self.renderer.draw_end_game_text(result.description)

    # -- boucle principale --------------------------------------
    def update(self):
        """Une étape de logique de jeu (sans dessin) : appelée à chaque image."""
        # Rafraîchir la liste des coups légaux AVANT de lancer l'IA : sinon
        # l'IA reçoit la liste du camp précédent (coup humain déjà joué) et
        # renvoie un coup rejeté par makeMove (« Mouvement non valide »).
        if self.move_made:
            if self.animate and self.game_state.move_log:
                with self.ui.timer_paused():
                    self.renderer.animate_move(
                        self.game_state.move_log[-1], self.game_state.board, self.clock
                    )
            self.valid_moves = self.game_state.getValidMoves()
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

    mode, player_one, player_two = gameModeMenu(screen)
    # En PvC, si le joueur humain a les noirs, on retourne le plateau.
    flip_board = mode == "PvC" and not player_one

    controller = GameController(
        screen, clock, ui_manager, resource_manager, mode, player_one, player_two, flip_board
    )
    controller.run()


if __name__ == "__main__":
    main()
