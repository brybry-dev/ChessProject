"""
Interface du jeu (J5)
---------------------
Machine à états des scènes (:class:`App`) : écran « Nouvelle partie », puis partie
(:class:`GameController`) avec ses fenêtres superposées. Aucune boucle bloquante :
chaque scène reçoit les événements, avance d'une étape, puis se dessine.

Le contrôleur de partie gère l'échiquier (clic-clic et glisser-déposer, flèches et
marques au clic droit), l'historique navigable, la pendule, l'IA dans un processus
séparé, la sauvegarde et le PGN.
"""

import contextlib
import copy
import logging
import logging.handlers
import queue
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from multiprocessing import Process, Queue
from pathlib import Path
from typing import Any

import pygame as p

from chessproject import __version__, paths, serialization
from chessproject import settings as settings_module
from chessproject.ai import levels, search
from chessproject.core import clock as chess_clock_module
from chessproject.core import engine, notation, pgn
from chessproject.settings import Settings
from chessproject.ui import layout as layout_module
from chessproject.ui import theme as th
from chessproject.ui import widgets as w
from chessproject.ui.board_view import BoardScene, Drag, PieceSet, Renderer
from chessproject.ui.new_game import GameConfig, NewGameMenu, config_from
from chessproject.ui.overlays import (
    AppearanceOverlay,
    ConfirmOverlay,
    EndGameOverlay,
    Overlay,
    PromotionPopup,
    ShortcutsOverlay,
)
from chessproject.ui.panel import Header, MoveRow, PanelModel, PlayerCard, SidePanel

# Ancien nom de la classe des images de pièces.
ResourceManager = PieceSet

DIMENSION = engine.DIMENSION
MAX_FPS = 60
# Garde-fous du processus d'IA (B33) : au-delà, il est arrêté et un coup de repli est joué.
AI_MAX_THINK_SECONDS = 30.0
AI_RESULT_TIMEOUT_SECONDS = 1.0
# Surcoût d'un coup de l'IA hors réflexion (lancement du processus, transmission du
# résultat, dépassement de l'échéance) : estimé au départ, puis mesuré en jeu.
AI_INITIAL_OVERHEAD_MS = 250.0
AI_OVERHEAD_SMOOTHING = 0.3
DRAG_THRESHOLD_PX = 4
NOTICE_MS = 3500
LOW_TIME_MS = 20_000
EVAL_MOVETIME_MS = 25
PIECE_VALUES = {"p": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0}

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
# Chronomètre des parties sans cadence
# --------------------------------------------------
class UIManager:
    """Temps écoulé de chaque camp, affiché quand la partie n'a pas de pendule."""

    def __init__(self, now=None):
        # Source de temps en millisecondes, injectable pour les tests.
        self.now = now or p.time.get_ticks
        self.white_time: float = 0
        self.black_time: float = 0
        self.last_time = self.now()
        self.is_running = True

    def reset_timer(self):
        """Remet les compteurs à zéro et resynchronise l'horloge de référence."""
        self.white_time = 0
        self.black_time = 0
        self.last_time = self.now()
        self.is_running = True

    def skip(self):
        """Le temps écoulé depuis la dernière mesure n'est pas compté."""
        self.last_time = self.now()

    def update_timer(self, white_to_move):
        current_time = self.now()
        elapsed = (current_time - self.last_time) / 1000
        self.last_time = current_time
        if self.is_running:
            if white_to_move:
                self.white_time += elapsed
            else:
                self.black_time += elapsed


def format_elapsed(seconds: float) -> str:
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}:{rest:02d}"


# --------------------------------------------------
# Sons
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
# IA : nulle et évaluation affichée
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


def evaluate_for_display(game_state) -> int:
    """Évaluation rapide (centipions, point de vue des blancs) pour la barre
    d'évaluation ; un mat vaut ±search.MATE."""
    result = game_state.result()
    if result.is_over:
        if result.winner is engine.Color.WHITE:
            return search.MATE
        if result.winner is engine.Color.BLACK:
            return -search.MATE
        return 0
    # Sur une copie : la recherche laisse dans l'état des indicateurs (échec, mat) de la
    # dernière position visitée.
    found = search.think(
        copy.deepcopy(game_state), search.SearchLimits(depth=2, movetime_ms=EVAL_MOVETIME_MS)
    )
    return found.score if game_state.white_to_move else -found.score


def eval_text(cp: int) -> str:
    """« +0,4 », « −1,2 » ou « #3 » / « −#3 » (mat en 3 coups)."""
    if abs(cp) >= search.MATE_THRESHOLD:
        moves = max(1, (search.MATE - abs(cp) + 1) // 2)
        return f"#{moves}" if cp > 0 else f"−#{moves}"
    value = f"{abs(cp) / 100:.1f}".replace(".", ",")
    return ("+" if cp >= 0 else "−") + value


def eval_share(cp: int) -> float:
    """Part de la barre revenant aux blancs (probabilité de gain logistique)."""
    if abs(cp) >= search.MATE_THRESHOLD:
        return 1.0 if cp > 0 else 0.0
    share = 1 / (1 + 10 ** (-cp / 400))
    return max(0.04, min(0.96, share))


# --------------------------------------------------
# Contrôleur de partie
# --------------------------------------------------
class GameController:
    """Scène de partie : événements, IA, pendule, rendu."""

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
        settings: Settings | None = None,
        level: str | None = None,
        now_ms=None,
    ):
        self.screen = screen
        self.clock = clock
        self.ui = ui_manager
        self.pieces = resource_manager
        self.mode = mode
        self.player_one = player_one  # humain joue les blancs
        self.player_two = player_two  # humain joue les noirs
        self.settings = settings or Settings()
        # Rappel de l'application (persistance des préférences).
        self.on_settings_change: Callable[[Settings], None] | None = None
        self._now_ms = now_ms or p.time.get_ticks

        width, height = screen.get_size()
        self.layout = layout_module.compute(width, height, self.settings.show_eval)
        self.renderer = Renderer(screen, resource_manager, self.layout.board, flip_board)
        self._apply_settings()
        self.header = Header()
        self.panel = SidePanel()

        self.game_state = engine.GameState()
        self.valid_moves = self.game_state.get_valid_moves()
        self.ui.reset_timer()

        # Pendule à cadence (J4.1) : un appui par coup joué, synchronisé dans update().
        self.time_control = time_control or chess_clock_module.DEFAULT
        self._clock_now = clock_now or time.monotonic
        self._start_clock()

        self.square_selected: tuple[int, int] | tuple[()] = ()
        self.drag: Drag | None = None
        self._deselect_on_release = False
        self.arrows: set[tuple[tuple[int, int], tuple[int, int]]] = set()
        self.marks: set[tuple[int, int]] = set()
        self._right_start: tuple[int, int] | None = None
        self._right_end: tuple[int, int] | None = None
        self.move_made = False
        self.animate = False
        # Position affichée (None = position actuelle ; sinon nombre de demi-coups).
        self.view_ply: int | None = None
        self._history_key = None
        self._history_states: dict[int, engine.GameState] = {}
        self._eval_cache: dict[tuple[object, int], int] = {}
        self._eval_shown = 0.5

        self.ai_thinking = False
        self.ai_started_at = 0.0
        self.ai_overhead_ms = AI_INITIAL_OVERHEAD_MS
        self._ai_requested_ms = None
        self.ai_level = level or levels.DEFAULT_LEVEL.name
        self.move_finder_process: Any = None
        self.return_queue: Any = None

        self.promotion_popup: PromotionPopup | None = None
        # Les 4 coups légaux de promotion (Q, R, B, N) de la case choisie.
        self.promotion_moves: list[engine.Move] = []

        self.overlay: Overlay | None = None
        self.end_dismissed = False
        self.notice: tuple[str, str, int] | None = None
        # Scène suspendue (écran « Nouvelle partie » ouvert par-dessus) : rien ne tourne.
        self.suspended = False
        self._frozen_since: float | None = None
        # Demandes adressées à l'application (changement de scène).
        self.requests: list[str] = []

        # Fin de partie décidée hors de l'échiquier (abandon, accord, temps : J4).
        self.external_result: engine.GameResult | None = None
        # Proposition de nulle en attente (PvP) : (camp qui propose, nombre de demi-coups
        # joués au moment de la proposition). Un coup de l'adversaire la décline.
        self.draw_offer: tuple[engine.Color, int] | None = None

    # -- état dérivé ---------------------------------------------------
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

    @property
    def frozen(self) -> bool:
        """Partie suspendue : scène en arrière-plan ou fenêtre modale ouverte."""
        return self.suspended or (self.overlay is not None and self.overlay.pauses_clock)

    @property
    def live_ply(self) -> int:
        return len(self.game_state.move_log)

    @property
    def current_ply(self) -> int:
        return self.live_ply if self.view_ply is None else self.view_ply

    def human_turn(self):
        return (self.game_state.white_to_move and self.player_one) or (
            not self.game_state.white_to_move and self.player_two
        )

    # -- réglages et mise en page ------------------------------------
    def _apply_settings(self):
        self.renderer.palette = th.palette(self.settings.board)
        self.renderer.show_coordinates = self.settings.show_coordinates
        self.renderer.show_legal_moves = self.settings.show_legal_moves

    def set_setting(self, name, value):
        self.settings = replace(self.settings, **{name: value})
        self._apply_settings()
        if name == "show_eval":
            self.resize(self.screen.get_size())
        if isinstance(self.overlay, AppearanceOverlay):
            self.overlay.settings = self.settings
        if self.on_settings_change:
            self.on_settings_change(self.settings)

    def resize(self, size):
        self.layout = layout_module.compute(size[0], size[1], self.settings.show_eval)
        self.renderer.board_rect = p.Rect(self.layout.board)
        self.renderer.animation = None

    # -- helpers -------------------------------------------------------
    def _reset_selection(self):
        self.square_selected = ()
        self.drag = None
        self._deselect_on_release = False

    def _clear_annotations(self):
        self.arrows.clear()
        self.marks.clear()
        self._right_start = self._right_end = None

    def _stop_ai(self):
        if self.ai_thinking and self.move_finder_process:
            self.move_finder_process.terminate()
        self.ai_thinking = False

    def _notify(self, text, kind="info"):
        self.notice = (text, kind, self._now_ms() + NOTICE_MS)

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

    def _sync_clock(self):
        """Un appui par coup joué, un retour arrière par coup annulé."""
        target = len(self.game_state.move_log) - self._clock_base_plies
        while self.chess_clock.press_count < target:
            self.chess_clock.press()
        while self.chess_clock.press_count > max(target, 0):
            if not self.chess_clock.undo_press():
                break

    def _new_game(self, game_state, saved_clock=None):
        self.game_state = game_state
        self.external_result = None
        self.draw_offer = None
        self._start_clock(saved_clock)
        self.valid_moves = self.game_state.get_valid_moves()
        self._reset_selection()
        self._clear_annotations()
        self.view_ply = None
        self.move_made = False
        self.animate = False
        self.renderer.animation = None
        self.end_dismissed = False
        if isinstance(self.overlay, EndGameOverlay):
            self.overlay = None
        self.ui.reset_timer()
        self._stop_ai()

    def apply_config(self, config: GameConfig):
        """Nouvelle partie avec les réglages de l'écran « Nouvelle partie »."""
        self.mode = config.mode
        self.player_one, self.player_two = config.human_white, config.human_black
        self.ai_level = config.level
        self.time_control = config.time_control
        self.renderer.flip_board = config.flip_board
        self._new_game(engine.GameState())

    # -- événements ----------------------------------------------------
    def handle_event(self, e):
        if e.type == p.QUIT:
            self._stop_ai()  # ne pas attendre la fin de la recherche (B45)
            p.quit()
            sys.exit()
        if self.promotion_popup:
            self._handle_promotion_event(e)
            return
        if self.overlay is not None:
            action = self.overlay.handle_event(e)
            if action is not None:
                self._run_action(action)
            return
        if e.type == p.MOUSEWHEEL:
            self.panel.scroll_by(p.mouse.get_pos(), e.y)
        elif e.type == p.MOUSEBUTTONDOWN:
            if e.button == 1:
                action = self.header.hit(e.pos) or self.panel.hit(e.pos)
                if action is not None:
                    self._run_action(action)
                else:
                    self._handle_board_press(e.pos)
            elif e.button == 3:
                self._handle_right_press(e.pos)
        elif e.type == p.MOUSEMOTION:
            self._handle_motion(e.pos)
        elif e.type == p.MOUSEBUTTONUP:
            if e.button == 1:
                self._handle_board_release(e.pos)
            elif e.button == 3:
                self._handle_right_release(e.pos)
        elif e.type == p.KEYDOWN:
            self._handle_keydown(e)

    def _run_action(self, action):
        if isinstance(action, tuple):
            kind = action[0]
            if kind == "nav":
                self._navigate(action[1])
            elif kind == "goto":
                self._view(action[1])
            elif kind == "setting":
                self.set_setting(action[1], action[2])
            return
        simple = {
            "new_game": lambda: self.requests.append("new_game"),
            "save": self._save,
            "load": self._load,
            "export": self._export_pgn,
            "import": self._import_pgn,
            "flip": self._flip,
            "appearance": lambda: self._open(AppearanceOverlay(self.settings)),
            "shortcuts": lambda: self._open(ShortcutsOverlay()),
            "undo": self._undo,
            "draw": self._offer_draw,
            "resign": self._ask_resign,
            "rematch": self._restart,
            "confirm_resign": self._resign,
            "confirm_restart": self._restart,
        }
        if action in ("close", "review"):
            if isinstance(self.overlay, EndGameOverlay):
                self.end_dismissed = True
            self.overlay = None
            return
        handler = simple.get(action)
        if handler is not None:
            if isinstance(self.overlay, (ConfirmOverlay, EndGameOverlay)):
                self.end_dismissed = self.end_dismissed or isinstance(self.overlay, EndGameOverlay)
                self.overlay = None
            handler()

    def _open(self, overlay):
        self._reset_selection()
        self.overlay = overlay
        if overlay.pauses_clock:
            self.freeze_clock()

    def freeze_clock(self):
        """Arrête tout de suite la pendule (fenêtre modale, scène suspendue) ; update()
        la relance quand plus rien ne la retient."""
        self.chess_clock.pause()
        self.ui.skip()

    # -- promotion -----------------------------------------------------
    def _close_promotion_popup(self):
        self.promotion_popup = None
        self.promotion_moves = []

    def _handle_promotion_event(self, e):
        assert self.promotion_popup is not None
        choice = self.promotion_popup.choice_for(e)
        if choice is None:
            return
        if choice == "cancel":
            self._close_promotion_popup()
            return
        # Le coup joué est celui que le moteur a généré pour cette pièce :
        # historique, sauvegarde et plateau restent cohérents (B29).
        move = next(m for m in self.promotion_moves if m.promotion_piece == choice)
        self._close_promotion_popup()
        self._play(move, animate=False)

    # -- échiquier : souris ------------------------------------------
    def _targets(self, square):
        return [m for m in self.valid_moves if (m.start_row, m.start_col) == square]

    def _handle_board_press(self, pos):
        square = self.renderer.square_from_pixel(pos)
        if square is None:
            self._reset_selection()
            return
        self._clear_annotations()
        if self.view_ply is not None:
            self.view_ply = None  # un clic sur l'échiquier ramène à la position actuelle
            return
        if self.game_over or not self.human_turn():
            return
        row, col = square
        my_color = "w" if self.game_state.white_to_move else "b"
        piece = self.game_state.board[row][col]

        if piece != "--" and piece[0] == my_color:
            # Ré-appuyer sur la pièce choisie la reprend : la relâcher sans la déplacer
            # annule la sélection.
            self._deselect_on_release = self.square_selected == square
            self.square_selected = square
            self.drag = Drag(square, piece, pos)
            return
        if self.square_selected:
            self._try_move(self.square_selected, square, animate=True)
        self._reset_selection()

    def _handle_motion(self, pos):
        if self.drag is not None:
            self.drag.pos = pos
            ox, oy = self.renderer.square_rect(*self.drag.origin).center
            if not self.drag.active and max(abs(pos[0] - ox), abs(pos[1] - oy)) > max(
                DRAG_THRESHOLD_PX, self.renderer.sq_size // 2
            ):
                self.drag.active = True
        if self._right_start is not None:
            self._right_end = self.renderer.square_from_pixel(pos)

    def _handle_board_release(self, pos):
        drag, self.drag = self.drag, None
        if drag is None:
            return
        if drag.active:
            target = self.renderer.square_from_pixel(pos)
            if target is not None and target != drag.origin:
                if self._try_move(drag.origin, target, animate=False):
                    self._reset_selection()
            return
        if self._deselect_on_release:
            self._reset_selection()

    def _handle_right_press(self, pos):
        self._reset_selection()
        self._right_start = self.renderer.square_from_pixel(pos)
        self._right_end = self._right_start

    def _handle_right_release(self, pos):
        start, self._right_start = self._right_start, None
        end = self.renderer.square_from_pixel(pos)
        self._right_end = None
        if start is None or end is None:
            return
        if start == end:
            self.marks ^= {start}
        else:
            self.arrows ^= {(start, end)}

    def _try_move(self, start, end, animate):
        """Joue le coup start -> end s'il est légal (ou ouvre le choix de promotion) ;
        renvoie True si le coup est accepté."""
        candidates = [
            m
            for m in self.valid_moves
            if (m.start_row, m.start_col, m.end_row, m.end_col)
            == (start[0], start[1], end[0], end[1])
        ]
        if not candidates:
            return False
        if candidates[0].is_pawn_promotion:
            self.promotion_moves = candidates
            disp_row = self.renderer.display_row(end[0])
            self.promotion_popup = PromotionPopup(
                self.renderer.square_rect(*end),
                downward=disp_row == 0,
                color=candidates[0].piece_moved[0],
                pieces=self.pieces,
            )
        else:
            self._play(candidates[0], animate)
        self._reset_selection()
        return True

    def _play(self, move, animate):
        self.game_state.make_move(move)
        if self.settings.sound:
            _play_move_sound(move)
        logger.info("Coup joué : %s", move)
        self.move_made = True
        self.animate = animate
        self._clear_annotations()

    # -- clavier -------------------------------------------------------
    def _handle_keydown(self, e):
        keys = {
            p.K_z: self._undo,
            p.K_r: self._ask_restart,
            p.K_s: self._save,
            p.K_l: self._load,
            p.K_e: self._export_pgn,
            p.K_i: self._import_pgn,
            p.K_a: self._ask_resign,
            p.K_n: self._offer_draw,
            p.K_f: self._flip,
            p.K_c: lambda: self._open(AppearanceOverlay(self.settings)),
            p.K_h: lambda: self._open(ShortcutsOverlay()),
            p.K_LEFT: lambda: self._navigate("prev"),
            p.K_RIGHT: lambda: self._navigate("next"),
            p.K_UP: lambda: self._navigate("first"),
            p.K_HOME: lambda: self._navigate("first"),
            p.K_DOWN: lambda: self._navigate("last"),
            p.K_END: lambda: self._navigate("last"),
            p.K_ESCAPE: self._escape,
        }
        handler = keys.get(e.key)
        if handler is not None:
            handler()

    def _escape(self):
        if self.square_selected:
            self._reset_selection()
        elif self.arrows or self.marks:
            self._clear_annotations()
        elif self.view_ply is not None:
            self.view_ply = None

    # -- historique (J5.5) ---------------------------------------------
    def _view(self, ply):
        ply = max(0, min(self.live_ply, ply))
        self.view_ply = None if ply == self.live_ply else ply
        self._reset_selection()

    def _navigate(self, where):
        target = {
            "first": 0,
            "prev": self.current_ply - 1,
            "next": self.current_ply + 1,
            "last": self.live_ply,
        }[where]
        self._view(target)

    def _key(self):
        return (id(self.game_state), tuple(m.move_id for m in self.game_state.move_log))

    def state_at(self, ply):
        """Position après ``ply`` demi-coups (copie ; la partie n'est pas modifiée)."""
        if ply >= self.live_ply:
            return self.game_state
        key = self._key()
        if key != self._history_key:
            self._history_key, self._history_states = key, {}
        if ply not in self._history_states:
            state = copy.deepcopy(self.game_state)
            for _ in range(self.live_ply - ply):
                state.undo_move()
            self._history_states[ply] = state
        return self._history_states[ply]

    # -- actions de partie ---------------------------------------------
    def _undo(self):
        if self.game_state.move_log:
            self.game_state.undo_move()
            logger.info("Undo effectué")
        # Contre l'IA seulement : annuler aussi le coup de l'IA pour rendre la main au
        # joueur. En PvP/CvC, un seul undo.
        if self.mode == "PvC" and self.game_state.move_log and not self.human_turn():
            self.game_state.undo_move()
        self.external_result = None  # annuler rouvre une partie abandonnée ou nulle
        self.draw_offer = None
        self.end_dismissed = False
        self.view_ply = None
        self.move_made = True
        self.animate = False
        self.renderer.animation = None
        self._reset_selection()
        self._clear_annotations()
        self._stop_ai()

    def _in_progress(self):
        return bool(self.game_state.move_log) and not self.game_over

    def _ask_restart(self):
        if self._in_progress():
            self._open(
                ConfirmOverlay(
                    "Recommencer la partie ?",
                    "La partie en cours sera perdue si elle n'a pas été sauvegardée.",
                    "Recommencer",
                    "confirm_restart",
                )
            )
        else:
            self._restart()

    def _restart(self):
        self._new_game(engine.GameState())
        logger.info("Partie réinitialisée")

    def _flip(self):
        self.renderer.flip_board = not self.renderer.flip_board
        self.renderer.animation = None

    def _save(self):
        saved = serialization.save_game(
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
        if saved:
            self._notify("Partie sauvegardée", "accent")
        else:
            self._notify("Échec de la sauvegarde (voir le journal)", "warning")

    def _load(self):
        path = Path(paths.existing_save_file())
        if not path.exists():
            self._notify("Aucune sauvegarde à charger", "warning")
            return False
        try:
            saved = serialization.load_save(str(path))
        except Exception as ex:  # noqa: BLE001 - fichier illisible ou illégal
            logger.error("Erreur lors du chargement : %s", ex)
            self._notify("Sauvegarde illisible : chargement impossible", "warning")
            return False
        self.renderer.flip_board = saved.flip_board
        if saved.mode is not None:
            self.mode = saved.mode
            self.player_one = bool(saved.human_white)
            self.player_two = bool(saved.human_black)
        if saved.level in levels.LEVELS_BY_NAME:
            self.ai_level = saved.level
        self._new_game(saved.game_state, saved.clock)
        self.external_result = saved.result
        self._notify(f"Partie chargée ({len(saved.game_state.move_log)} demi-coups)", "accent")
        return True

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
            self._notify(f"PGN exporté : {path}", "accent")
        except OSError as ex:
            logger.error("Export PGN impossible : %s", ex)
            self._notify("Export PGN impossible (voir le journal)", "warning")

    def _import_pgn(self):
        path = paths.pgn_file()
        try:
            game = pgn.read_pgn_file(path)[-1]
            state = game.replay()
        except (OSError, IndexError, pgn.PgnError) as ex:
            logger.error("Import PGN impossible : %s", ex)
            self._notify(f"Import impossible : {path.name} absent ou invalide", "warning")
            return False
        # La partie continue avec les règles du jeu (nulles automatiques).
        state.automatic_draws = True
        state._valid_moves = None
        self._new_game(state)
        logger.info("Partie importée (%d coups)", len(state.move_log))
        self._notify(f"PGN importé ({len(state.move_log)} demi-coups)", "accent")
        return True

    def _human_color(self):
        """Camp de l'humain qui agit : celui au trait en PvP, l'unique humain en PvC."""
        if self.mode == "PvC":
            return engine.Color.WHITE if self.player_one else engine.Color.BLACK
        if self.mode == "PvP":
            return engine.Color.WHITE if self.game_state.white_to_move else engine.Color.BLACK
        return None  # IA contre IA : personne n'abandonne

    def _ask_resign(self):
        if self._human_color() is None or self.game_over:
            return
        self._open(
            ConfirmOverlay(
                "Abandonner la partie ?",
                "La victoire sera attribuée à l'adversaire.",
                "Abandonner",
                "confirm_resign",
            )
        )

    def _resign(self):
        color = self._human_color()
        if color is None or self.game_over:
            return
        winner = engine.Color.BLACK if color is engine.Color.WHITE else engine.Color.WHITE
        self.external_result = engine.GameResult(engine.Termination.RESIGNATION, winner)
        self._stop_ai()
        logger.info("Abandon : %s", self.external_result.description)

    def _pending_offer_for(self, color):
        """Vrai si l'adversaire de ``color`` vient de proposer la nulle (PvP)."""
        offer = self.draw_offer
        return offer is not None and offer[0] is not color and offer[1] == self.live_ply - 1

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
            else:
                self._notify("L'IA refuse la nulle : elle estime sa position meilleure")
            return
        # PvP : l'adversaire accepte en appuyant à son tour sur N, avant de jouer.
        if self._pending_offer_for(color):
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
        self.ai_thinking = False
        self._play(ai_move, animate=True)
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

    # -- boucle ------------------------------------------------------
    def update(self):
        """Une étape de logique de jeu (sans dessin) : appelée à chaque image."""
        now = self._now_ms()
        self._sync_clock()
        frozen = self.frozen
        if frozen and self._frozen_since is None:
            self._frozen_since = time.monotonic()
        elif not frozen and self._frozen_since is not None:
            # Le temps de pause ne compte pas dans la limite de réflexion de l'IA.
            self.ai_started_at += time.monotonic() - self._frozen_since
            self._frozen_since = None

        if not self.game_over:
            flagged = self.chess_clock.flagged()
            if flagged is not None:
                self.external_result = chess_clock_module.timeout_result(self.game_state, flagged)
                self._stop_ai()
                logger.info("Fin au temps : %s", self.external_result.description)
        # Partie terminée ou suspendue : la pendule est figée (une annulation la relance).
        if self.game_over or frozen:
            self.chess_clock.pause()
            self.ui.skip()
        else:
            self.chess_clock.resume()
            self.ui.update_timer(self.game_state.white_to_move)

        if self.move_made:
            # Rafraîchir la liste des coups légaux AVANT de relancer l'IA : sinon elle
            # recevrait la liste du camp précédent (« Mouvement non valide »).
            if self.animate and self.game_state.move_log and self.view_ply is None:
                self.renderer.start_animation(self.game_state.move_log[-1], now)
            self.valid_moves = self.game_state.get_valid_moves()
            self.move_made = False
            self.animate = False
            if self.game_over and self.settings.sound and gameover_sound:
                gameover_sound.play()

        if not frozen:
            self.update_ai()

        if (
            self.game_over
            and self.overlay is None
            and not self.end_dismissed
            and not self.renderer.animating(now)
        ):
            self.overlay = self._end_game_overlay()
        if self.notice is not None and now >= self.notice[2]:
            self.notice = None

    def _end_game_overlay(self):
        result = self.result
        if result.winner is None:
            title, piece = "Partie nulle", None
        else:
            white = result.winner is engine.Color.WHITE
            title = "Victoire des blancs" if white else "Victoire des noirs"
            if self.mode == "PvC":
                human_won = white == bool(self.player_one)
                title = "Victoire !" if human_won else "Défaite"
            piece = "wK" if white else "bK"
        moves = (self.live_ply + 1) // 2
        subtitle = f"{result.description} · {result.pgn} · {moves} coup{'s' if moves > 1 else ''}"
        return EndGameOverlay(title, subtitle, piece, self.pieces, result.description)

    # -- rendu -----------------------------------------------------
    def draw(self):
        t = th.theme(self.settings.theme)
        now = self._now_ms()
        mouse = p.mouse.get_pos()
        self.screen.fill(t.bg)
        logo = self.pieces.get_image("wN", 30)
        self.header.draw(self.screen, self.layout.header, t, logo, self._info_text(), mouse, now)
        state = self.state_at(self.current_ply)
        if self.layout.eval_bar is not None:
            self._draw_eval_bar(t, state)
        self.renderer.draw(self._board_scene(state), now)
        self.panel.draw(
            self.screen, self.layout.panel, self._panel_model(state), t, self.pieces, mouse, now
        )
        if self.promotion_popup:
            self.promotion_popup.draw(self.screen, t, mouse)
        if self.overlay is not None:
            self.overlay.draw(self.screen, t, mouse, now)

    def _info_text(self):
        mode = {"PvC": "Joueur vs IA", "PvP": "Joueur vs Joueur", "CvC": "IA vs IA"}[self.mode]
        parts = [mode]
        if self.mode != "PvP":
            parts.append(f"Niveau {self.ai_level}")
        tc = self.time_control
        parts.append("Sans limite" if tc.is_unlimited else (tc.name or tc.label))
        return " · ".join(parts)

    def _board_scene(self, state):
        ply = self.current_ply
        last = None
        if ply > 0:
            m = self.game_state.move_log[ply - 1]
            last = ((m.start_row, m.start_col), (m.end_row, m.end_col))
        check = None
        if state.king_in_check():
            check = state.white_king_location if state.white_to_move else state.black_king_location
        selected = self.square_selected or None
        targets = []
        if selected and self.view_ply is None:
            targets = [
                ((m.end_row, m.end_col), m.is_capture)
                for m in self._targets(selected)
                if not (m.is_pawn_promotion and m.promotion_piece != "Q")
            ]
        pending = None
        if self._right_start is not None and self._right_end not in (None, self._right_start):
            pending = (self._right_start, self._right_end)
        return BoardScene(
            board=state.board,
            last_move=last,
            selected=selected,
            targets=targets,
            check=check,
            drag=self.drag,
            arrows=self.arrows,
            marks=self.marks,
            pending_arrow=pending,
        )

    def _eval(self, state, ply):
        key = (self._key(), ply)
        if key not in self._eval_cache:
            if len(self._eval_cache) > 512:
                self._eval_cache.clear()
            self._eval_cache[key] = evaluate_for_display(state)
        return self._eval_cache[key]

    def _draw_eval_bar(self, t, state):
        rect = self.layout.eval_bar
        assert rect is not None
        cp = self._eval(state, self.current_ply)
        target = eval_share(cp)
        self._eval_shown += (target - self._eval_shown) * 0.25
        w.rounded(self.screen, th.EVAL_BLACK, rect, 6)
        white_h = round(rect.height * self._eval_shown)
        white = p.Rect(rect.x, 0, rect.width, white_h)
        if self.flip_board:
            white.top = rect.top
        else:
            white.bottom = rect.bottom
        if white_h > 0:
            p.draw.rect(self.screen, th.EVAL_WHITE, white, border_radius=6)
        p.draw.line(self.screen, t.accent, (rect.x, rect.centery), (rect.right - 1, rect.centery))

    def _captures(self, ply):
        taken: dict[str, list[str]] = {"w": [], "b": []}
        for move in self.game_state.move_log[:ply]:
            if move.piece_captured != "--":
                taken[move.piece_moved[0]].append(move.piece_captured)
        for pieces in taken.values():
            pieces.sort(key=lambda pc: -PIECE_VALUES[pc[1]])
        return taken

    @staticmethod
    def _material(board):
        score = 0
        for row in board:
            for piece in row:
                if piece != "--":
                    value = PIECE_VALUES[piece[1]]
                    score += value if piece[0] == "w" else -value
        return score

    def _player_card(self, white, state, taken, material):
        color = engine.Color.WHITE if white else engine.Color.BLACK
        human = self.player_one if white else self.player_two
        side = "Blancs" if white else "Noirs"
        if self.mode == "PvC":
            name = "Vous" if human else f"IA · {self.ai_level}"
        elif self.mode == "PvP":
            name = "Joueur blanc" if white else "Joueur noir"
        else:
            name = f"IA · {self.ai_level}"
        to_move = self.game_state.white_to_move == white and not self.game_over
        if self.chess_clock.is_unlimited:
            clock_text = format_elapsed(self.ui.white_time if white else self.ui.black_time)
            remaining = None
        else:
            remaining = self.chess_clock.remaining_ms(color)
            clock_text = chess_clock_module.format_ms(remaining)
        state_name = "idle"
        if to_move:
            state_name = "active"
            if remaining is not None and remaining < LOW_TIME_MS:
                state_name = "low"
            if self.frozen:
                state_name = "paused"
        advantage = material if white else -material
        return PlayerCard(
            name=name,
            subtitle=side,
            white=white,
            is_ai=not human,
            clock=clock_text,
            clock_state=state_name,
            captured=taken["w" if white else "b"],
            advantage=max(0, advantage),
            thinking=self.ai_thinking and to_move and not human,
            highlighted=to_move,
        )

    def _move_rows(self):
        sans = self._sans()
        rows: list[MoveRow] = []
        start_white = self.game_state.white_to_move == (len(sans) % 2 == 0)
        number = self.game_state.start_fullmove
        ply = 1
        index = 0
        if not start_white and sans:
            rows.append(MoveRow(number, None, (sans[0], 1)))
            number, ply, index = number + 1, 2, 1
        while index < len(sans):
            white = (sans[index], ply)
            black = (sans[index + 1], ply + 1) if index + 1 < len(sans) else None
            rows.append(MoveRow(number, white, black))
            number, ply, index = number + 1, ply + 2, index + 2
        return rows

    def _sans(self):
        key = self._key()
        if getattr(self, "_san_key", None) != key:
            self._san_key, self._san_cache = key, notation.san_history(self.game_state)
        return self._san_cache

    def _status(self):
        if self.view_ply is not None:
            sans = self._sans()
            ply = self.view_ply
            if ply == 0:
                where = "position de départ"
            else:
                where = f"après {sans[ply - 1]}"
            return f"Revue : {where} · Fin pour revenir à la partie", "accent"
        if self.notice is not None:
            return self.notice[0], self.notice[1]
        if self.game_over:
            return self.result.description, "accent"
        side = "blancs" if self.game_state.white_to_move else "noirs"
        mover = engine.Color.WHITE if self.game_state.white_to_move else engine.Color.BLACK
        if self.mode == "PvP" and self._pending_offer_for(mover):
            proposer = "Noirs" if self.game_state.white_to_move else "Blancs"
            return f"Les {proposer} proposent la nulle · N pour accepter", "accent"
        if self.ai_thinking:
            return "L'IA réfléchit…", "info"
        prefix = "Échec ! " if self.game_state.king_in_check() else ""
        if self.mode == "PvC" and self.human_turn():
            return prefix + "À vous de jouer", "warning" if prefix else "accent"
        return prefix + f"Aux {side} de jouer", "warning" if prefix else "info"

    def _panel_model(self, state):
        ply = self.current_ply
        taken = self._captures(ply)
        material = self._material(state.board)
        white_card = self._player_card(True, state, taken, material)
        black_card = self._player_card(False, state, taken, material)
        top, bottom = (white_card, black_card) if self.flip_board else (black_card, white_card)
        status, kind = self._status()
        human = self._human_color()
        can_act = human is not None and not self.game_over
        draw_label = (
            "Accepter"
            if (self.mode == "PvP" and human is not None and self._pending_offer_for(human))
            else "Nulle"
        )
        eval_label = None
        if self.layout.eval_bar is not None:
            eval_label = eval_text(self._eval(state, ply))
        return PanelModel(
            top=top,
            bottom=bottom,
            rows=self._move_rows(),
            current_ply=ply,
            live_ply=self.live_ply,
            status=status,
            status_kind=kind,
            eval_text=eval_label,
            can_undo=bool(self.game_state.move_log),
            can_draw=can_act,
            can_resign=can_act,
            draw_label=draw_label,
        )


# --------------------------------------------------
# Application : machine à états des scènes (J5.1)
# --------------------------------------------------
class App:
    """Scène courante (écran « Nouvelle partie » ou partie) et boucle principale."""

    def __init__(self, screen, settings: Settings, pieces=None, clock=None):
        self.screen = screen
        self.settings = settings
        self.pieces = pieces or PieceSet()
        self.clock = clock or p.time.Clock()
        self.game: GameController | None = None
        self.scene: NewGameMenu | GameController = NewGameMenu(
            settings, can_cancel=False, pieces=self.pieces
        )

    # -- transitions -----------------------------------------------------
    def _persist(self, settings: Settings):
        self.settings = settings
        settings_module.save(settings)

    def _ensure_game(self, config: GameConfig) -> GameController:
        if self.game is None:
            self.game = GameController(
                self.screen,
                self.clock,
                UIManager(),
                self.pieces,
                config.mode,
                config.human_white,
                config.human_black,
                config.flip_board,
                time_control=config.time_control,
                settings=self.settings,
                level=config.level,
            )
            self.game.on_settings_change = self._persist
        else:
            self.game.settings = self.settings
            self.game._apply_settings()
            self.game.resize(self.screen.get_size())
            self.game.apply_config(config)
        return self.game

    def open_new_game(self):
        if self.game is not None:
            self.game.suspended = True
            self.game.freeze_clock()
        self.scene = NewGameMenu(
            self.settings, can_cancel=self.game is not None, pieces=self.pieces
        )

    def _resume_game(self):
        assert self.game is not None
        self.game.suspended = False
        self.game.resize(self.screen.get_size())
        self.scene = self.game

    def _menu_action(self, action):
        menu = self.scene
        assert isinstance(menu, NewGameMenu)
        if action == "cancel" and self.game is not None:
            self._resume_game()
            return
        if action not in ("load", "import") and not (
            isinstance(action, tuple) and action[0] == "start"
        ):
            return
        self._persist(
            replace(
                self.settings,
                mode=menu.settings.mode,
                color=menu.settings.color,
                level=menu.settings.level,
                time_control=menu.settings.time_control,
            )
        )
        config = action[1] if isinstance(action, tuple) else config_from(self.settings)
        game = self._ensure_game(config)
        game.suspended = False
        self.scene = game
        if action == "load":
            game._load()
        elif action == "import":
            game._import_pgn()

    # -- boucle ----------------------------------------------------------
    def handle_event(self, e):
        if e.type == p.QUIT:
            if self.game is not None:
                self.game._stop_ai()  # ne pas attendre la fin de la recherche (B45)
            p.quit()
            sys.exit()
        if e.type == p.VIDEORESIZE:
            size = layout_module.clamp_window_size(e.w, e.h)
            if size != (e.w, e.h):
                self.screen = p.display.set_mode(size, p.RESIZABLE)
            if self.game is not None:
                self.game.screen = self.screen
                self.game.renderer.screen = self.screen
                self.game.resize(self.screen.get_size())
            return
        if isinstance(self.scene, NewGameMenu):
            action = self.scene.handle_event(e)
            if action is not None:
                self._menu_action(action)
        else:
            self.scene.handle_event(e)
            if self.scene.requests:
                request = self.scene.requests.pop(0)
                if request == "new_game":
                    self.open_new_game()

    def step(self):
        """Une image : logique puis dessin de la scène courante."""
        if isinstance(self.scene, NewGameMenu):
            if self.game is not None:
                self.game.update()  # suspendue : seule la pendule est tenue à l'arrêt
            self.scene.draw(
                self.screen, th.theme(self.settings.theme), p.mouse.get_pos(), p.time.get_ticks()
            )
        else:
            self.scene.update()
            self.scene.draw()

    def run(self):
        while True:
            for e in p.event.get():
                self.handle_event(e)
            self.step()
            p.display.flip()
            self.clock.tick(MAX_FPS)


# --------------------------------------------------
# Fonction principale
# --------------------------------------------------
SMOKE_TEST_TIMEOUT_S = 30.0


def smoke_test(screen, pieces) -> bool:
    """Test de démarrage (exécutables J6.2) : écran « Nouvelle partie », partie contre
    l'IA dans son processus séparé, fenêtres superposées. Renvoie True si tout marche."""
    settings = Settings(mode="PvC", color="w", level="Débutant", time_control="-")
    application = App(screen, settings, pieces)
    application.step()
    application.handle_event(p.event.Event(p.KEYDOWN, {"key": p.K_RETURN}))
    game = application.scene
    if not isinstance(game, GameController):
        return False
    game._try_move((6, 4), (4, 4), animate=True)  # e4
    deadline = time.monotonic() + SMOKE_TEST_TIMEOUT_S
    while len(game.game_state.move_log) < 2 and time.monotonic() < deadline:
        application.step()
        p.display.flip()
        time.sleep(0.01)
    for key in (p.K_h, p.K_c):
        game.handle_event(p.event.Event(p.KEYDOWN, {"key": key}))
        application.step()
        game.handle_event(p.event.Event(p.KEYDOWN, {"key": p.K_ESCAPE}))
    game._stop_ai()
    replied = len(game.game_state.move_log) == 2
    logger.info("Test de démarrage : %s", "réussi" if replied else "l'IA n'a pas joué")
    return replied


def main(argv: list[str] | None = None) -> None:
    import argparse
    import multiprocessing
    import os
    import tempfile

    # Indispensable dans un exécutable (PyInstaller) : le processus d'IA relance le
    # programme lui-même sous Windows et macOS.
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(prog="chessproject", description="Jeu d'échecs ChessProject.")
    parser.add_argument("--version", action="version", version=f"ChessProject {__version__}")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="lance une partie automatique de deux coups puis quitte (code 0 si tout marche)",
    )
    args = parser.parse_args(argv)
    if args.smoke_test and "CHESSPROJECT_DATA_DIR" not in os.environ:
        # Ni préférences ni journal de l'utilisateur ne sont touchés par le test.
        os.environ["CHESSPROJECT_DATA_DIR"] = tempfile.mkdtemp(prefix="chessproject-smoke-")

    _configure_logging()
    p.init()
    if not args.smoke_test:
        _load_sounds()
    info = p.display.Info()
    size = layout_module.initial_window_size(info.current_w, info.current_h)
    screen = p.display.set_mode(size, p.RESIZABLE)
    p.display.set_caption("ChessProject")
    pieces = PieceSet()
    with contextlib.suppress(OSError, p.error):  # icône facultative
        p.display.set_icon(p.image.load(str(paths.ASSETS_DIR / "icon.png")))
    if args.smoke_test:
        ok = smoke_test(screen, pieces)
        if sys.stdout is not None:  # None dans un exécutable fenêtré sous Windows
            print("smoke test:", "ok" if ok else "ÉCHEC")
        p.quit()
        sys.exit(0 if ok else 1)
    p.key.set_repeat(350, 60)
    App(screen, settings_module.load(), pieces).run()


if __name__ == "__main__":
    main()
