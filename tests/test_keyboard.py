"""Interface au clavier seul (J12.2 et J12.3), sans écran ni souris.

J12.2 : chaque fenêtre et l'écran « Nouvelle partie » se parcourent avec Tab et
Maj+Tab, un bouton à la fois dans l'ordre de lecture ; Entrée ou Espace l'activent
comme un clic. J12.3 : en mode « échiquier » (K), les flèches déplacent un curseur de
case et Entrée prend puis pose la pièce ; une partie se joue ainsi de bout en bout.
"""

import os
import queue
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as p

try:
    p.init()
    p.display.set_mode((1280, 800))
    _PYGAME_OK = True
except Exception:  # pragma: no cover - environnement sans SDL
    _PYGAME_OK = False

from chessproject.ai import review
from chessproject.core import engine, notation, pgn
from chessproject.core.fen import load_fen
from chessproject.settings import Settings
from chessproject.ui import app, files, overlays, widgets
from chessproject.ui import theme as th
from chessproject.ui.board_view import PieceSet
from chessproject.ui.new_game import NewGameMenu

PIECES: PieceSet = PieceSet() if _PYGAME_OK else None  # type: ignore[assignment]


def _key(key, mod=0):
    return p.event.Event(p.KEYDOWN, {"key": key, "mod": mod, "unicode": ""})


def _focused(window) -> widgets.Button:
    button = window.focus.current(window.buttons)
    assert button is not None, "aucun bouton n'a le focus"
    return button


TAB = _key(p.K_TAB)
SHIFT_TAB = _key(p.K_TAB, p.KMOD_LSHIFT)
ENTER = _key(p.K_RETURN)
SPACE = _key(p.K_SPACE)


class _InlineProcess:
    """Processus d'analyse exécuté sur place (bilan de partie sans multiprocessing)."""

    def __init__(self, target, args, daemon=True):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)

    def terminate(self):
        pass

    def join(self, timeout=None):
        pass

    def is_alive(self):
        return False


def _controller(mode="PvP", white=True, black=True, flip=False, **kwargs):
    return app.GameController(
        p.display.get_surface(),
        p.time.Clock(),
        app.UIManager(),
        PIECES,
        mode,
        white,
        black,
        flip,
        **kwargs,
    )


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class FocusInEveryWindowTests(unittest.TestCase):
    """Tab visite chaque bouton actif une fois par tour, Maj+Tab dans l'ordre inverse."""

    def setUp(self):
        self.surface = p.display.get_surface()
        self.theme = th.theme("sombre")
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        folder = Path(self.dir.name)
        (folder / "partie.pgn").write_text("")
        (folder / "sous-dossier").mkdir()
        self.folder = folder

    def _windows(self):
        reviewer = review.Reviewer(process=_InlineProcess, make_queue=queue.Queue, nodes=500)
        state = engine.GameState()
        for san in ("f3", "e5", "g4", "Qh4#"):
            state.make_move(notation.parse_san(state, san))
        reviewer.start(engine.GameState(), list(state.move_log), "clé")
        reviewer.poll()
        games = pgn.parse_pgn("1. e4 *\n\n1. d4 *\n")
        places = [("Dossier", self.folder)]
        return {
            "raccourcis": overlays.ShortcutsOverlay(),
            "apparence": overlays.AppearanceOverlay(Settings()),
            "confirmation": overlays.ConfirmOverlay("Abandonner ?", "", "Abandonner", "x"),
            "fin de partie": overlays.EndGameOverlay("Victoire", "Mat", "wK", PIECES),
            "bilan": overlays.ReviewOverlay(reviewer, str),
            "ouvrir": files.FileDialog("load", "open", "Charger", self.folder, ".pgn", places),
            "enregistrer": files.FileDialog(
                "save", "save", "Sauver", self.folder, ".pgn", places, allow_delete=True
            ),
            "choix d'une partie": files.GamePickerOverlay("deux.pgn", games),
        }

    def _draw(self, window):
        if isinstance(window, NewGameMenu):
            window.draw(self.surface, self.theme, (0, 0), 0)
        else:
            window.draw(self.surface, self.theme, (0, 0), 0)
            window.focus.draw(self.surface, self.theme, window.buttons)

    def _walk(self, window, event):
        """Boutons qui reçoivent le focus, Tab après Tab, sur un tour complet."""
        enabled = [b for b in window.buttons if b.enabled]
        visited = []
        for _ in enabled:
            self.assertIsNone(window.handle_event(event))
            self._draw(window)
            button = window.focus.current(window.buttons)
            self.assertIsNotNone(button)
            visited.append((button.action, button.label, button.icon))
        return enabled, visited

    def _check(self, window):
        self._draw(window)
        self.assertIsNone(window.focus.current(window.buttons))  # invisible avant Tab
        enabled, forward = self._walk(window, TAB)
        self.assertEqual(len(set(forward)), len(enabled))  # chacun une fois
        # Ordre de lecture : de haut en bas, puis de gauche à droite.
        rects = {(b.action, b.label, b.icon): b.rect for b in enabled}
        tops = [(rects[k].y, rects[k].x) for k in forward]
        self.assertEqual(tops, sorted(tops))
        window.handle_event(TAB)  # le tour recommence au premier bouton
        self._draw(window)
        button = window.focus.current(window.buttons)
        self.assertEqual((button.action, button.label, button.icon), forward[0])
        _, backward = self._walk(window, SHIFT_TAB)
        self.assertEqual(backward, forward[-1::-1][: len(backward)])

    def test_every_window_is_walked_with_tab(self):
        for name, window in self._windows().items():
            with self.subTest(window=name):
                self._check(window)

    def test_new_game_screen_is_walked_with_tab(self):
        for mode in ("PvC", "PvP", "CvC"):
            with self.subTest(mode=mode):
                self._check(NewGameMenu(Settings(mode=mode), can_cancel=True, pieces=PIECES))

    def test_focus_ring_is_drawn_in_the_focus_color(self):
        for name in ("sombre", "clair"):
            with self.subTest(theme=name):
                t = th.theme(name)
                window = overlays.ConfirmOverlay("Abandonner ?", "", "Abandonner", "x")
                window.draw(self.surface, t, (0, 0), 0)
                window.handle_event(TAB)
                window.draw(self.surface, t, (0, 0), 0)
                window.focus.draw(self.surface, t, window.buttons)
                ring = _focused(window).rect.inflate(8, 8)
                self.assertEqual(tuple(self.surface.get_at(ring.midtop))[:3], t.focus)
                self.assertEqual(tuple(self.surface.get_at(ring.midleft))[:3], t.focus)

    def test_enter_or_space_activate_the_focused_button(self):
        window = overlays.ConfirmOverlay("Abandonner ?", "", "Abandonner", "confirm_resign")
        self._draw(window)
        self.assertEqual(window.handle_event(ENTER), "confirm_resign")  # sans focus
        window.handle_event(TAB)  # « Annuler », à gauche de « Abandonner »
        self.assertEqual(window.handle_event(SPACE), "close")
        self.assertEqual(window.handle_event(ENTER), "close")

    def test_space_writes_in_a_file_name_instead_of_pressing_a_button(self):
        dialog = files.FileDialog("save", "save", "Sauver", self.folder, ".pgn")
        self._draw(dialog)
        dialog.handle_event(TAB)
        self.assertIsNone(dialog.handle_event(SPACE))
        dialog.handle_event(p.event.Event(p.TEXTINPUT, {"text": "a"}))
        self.assertIsNone(dialog.focus.current(dialog.buttons))  # retour au nom
        self.assertEqual(dialog.name, "a")

    def test_buttons_that_change_the_dialog_work_from_the_keyboard(self):
        dialog = files.FileDialog(
            "load", "open", "Charger", self.folder / "sous-dossier", ".pgn", [("D", self.folder)]
        )
        self._draw(dialog)
        dialog.handle_event(TAB)  # le × de fermeture, tout en haut
        dialog.handle_event(TAB)  # puis le bouton du dossier « D »
        self._draw(dialog)
        self.assertEqual(_focused(dialog).action, ("place", self.folder))
        self.assertIsNone(dialog.handle_event(ENTER))
        self.assertEqual(dialog.directory, self.folder)
        self._draw(dialog)
        while _focused(dialog).action != "confirm":
            dialog.handle_event(TAB)
            self._draw(dialog)
        self.assertEqual(dialog.handle_event(ENTER), ("file", "load", self.folder / "partie.pgn"))

    def test_promotion_choice_with_the_arrows(self):
        gc = _controller()
        gc._new_game(load_fen("7k/P7/8/8/8/8/8/K7 w - - 0 1"))
        gc._try_move((1, 0), (0, 0), animate=False)
        for key in (p.K_DOWN, p.K_DOWN, p.K_DOWN, p.K_UP):  # dame, tour, fou, puis tour
            gc.handle_event(_key(key))
        gc.draw()
        gc.handle_event(ENTER)
        self.assertEqual(gc.game_state.board[0][0], "wR")
        self.assertIsNone(gc.promotion_popup)


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class BoardCursorTests(unittest.TestCase):
    def setUp(self):
        self.gc = _controller()

    def _press(self, key):
        self.gc.handle_event(_key(key))

    def _goto(self, square):
        """Amène le curseur sur ``square`` avec les flèches, comme le ferait le joueur."""
        gc = self.gc
        for _ in range(16):
            row, col = gc.cursor
            if (row, col) == square:
                return
            sign = -1 if gc.flip_board else 1
            if row != square[0]:
                down = (square[0] - row) * sign > 0
                self._press(p.K_DOWN if down else p.K_UP)
            else:
                right = (square[1] - col) * sign > 0
                self._press(p.K_RIGHT if right else p.K_LEFT)
        self.fail(f"curseur bloqué en {gc.cursor}")

    def _move(self, start, end):
        self._goto(start)
        self._press(p.K_RETURN)
        self._goto(end)
        self._press(p.K_SPACE)

    def test_k_toggles_the_cursor_on_the_king_of_the_side_to_move(self):
        self._press(p.K_k)
        self.assertEqual(self.gc.cursor, (7, 4))
        self.gc.draw()
        self._press(p.K_k)
        self.assertIsNone(self.gc.cursor)

    def test_arrows_follow_the_board_as_displayed(self):
        self._press(p.K_k)
        self._press(p.K_UP)
        self._press(p.K_LEFT)
        self.assertEqual(self.gc.cursor, (6, 3))
        self._press(p.K_f)  # échiquier retourné : haut et bas, gauche et droite s'inversent
        self._press(p.K_UP)
        self._press(p.K_LEFT)
        self.assertEqual(self.gc.cursor, (7, 4))
        for _ in range(10):
            self._press(p.K_UP)
        self.assertEqual(self.gc.cursor, (7, 4))  # bloqué au bord

    def test_a_whole_game_is_played_with_the_cursor(self):
        self._press(p.K_k)
        for start, end in (((6, 5), (5, 5)), ((1, 4), (3, 4)), ((6, 6), (4, 6)), ((0, 3), (4, 7))):
            self._move(start, end)
            self.gc.update()
            self.gc.draw()
        self.assertEqual(notation.san_history(self.gc.game_state), ["f3", "e5", "g4", "Qh4#"])
        self.gc.renderer.animation = None  # fin de l'animation du dernier coup
        self.gc.update()
        self.assertTrue(self.gc.game_over)
        self.assertIsInstance(self.gc.overlay, app.EndGameOverlay)

    def test_illegal_target_keeps_the_piece_in_hand(self):
        self._press(p.K_k)
        self._goto((6, 4))
        self._press(p.K_RETURN)
        self._goto((3, 4))  # e5 : trop loin
        self._press(p.K_RETURN)
        self.assertEqual(self.gc.game_state.move_log, [])
        self.assertEqual(self.gc.square_selected, (6, 4))
        self.assertEqual(self.gc.notice[0], "Coup impossible")
        self._goto((6, 4))
        self._press(p.K_RETURN)  # reposer la pièce annule le choix
        self.assertEqual(self.gc.square_selected, ())

    def test_escape_drops_the_piece_then_leaves_board_mode(self):
        self._press(p.K_k)
        self._press(p.K_RETURN)  # le roi
        self.assertEqual(self.gc.square_selected, (7, 4))
        self._press(p.K_ESCAPE)
        self.assertEqual(self.gc.square_selected, ())
        self.assertIsNotNone(self.gc.cursor)
        self._press(p.K_ESCAPE)
        self.assertIsNone(self.gc.cursor)
        self._press(p.K_LEFT)  # hors du mode « échiquier », les flèches parcourent l'historique
        self.assertIsNone(self.gc.cursor)

    def test_not_your_turn_against_the_ai(self):
        gc = self.gc = _controller("PvC", False, True, flip=True)
        with mock.patch.object(app.GameController, "update_ai"):
            self._press(p.K_k)
            self._press(p.K_RETURN)
        self.assertEqual(gc.notice[0], "Ce n'est pas à vous de jouer")
        self.assertEqual(gc.square_selected, ())


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class KeyboardOnlyAppTests(unittest.TestCase):
    """Du choix des réglages à la fin de la partie, sans souris."""

    def setUp(self):
        self.data = tempfile.TemporaryDirectory()
        self.addCleanup(self.data.cleanup)
        patcher = mock.patch.dict(os.environ, {"CHESSPROJECT_DATA_DIR": self.data.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = app.App(p.display.set_mode((1280, 800)), Settings(mode="PvC"), PIECES)

    def _key(self, event):
        self.app.handle_event(event)
        self.app.step()

    def _tab_to(self, scene, action):
        for _ in range(40):
            self._key(TAB)
            focused = scene.focus.current(scene.buttons)
            if focused is not None and focused.action == action:
                return
        self.fail(f"bouton {action!r} jamais atteint")

    def test_settings_game_and_end_card_without_the_mouse(self):
        menu = self.app.scene
        assert isinstance(menu, NewGameMenu)
        self.app.step()
        self._tab_to(menu, ("choose", "mode", "PvP"))
        self._key(SPACE)
        self.assertEqual(menu.settings.mode, "PvP")
        self._tab_to(menu, "start")
        self._key(ENTER)
        game = self.app.scene
        assert isinstance(game, app.GameController)
        self.assertEqual(game.mode, "PvP")

        # Apparence : une option changée au clavier.
        self._key(_key(p.K_c))
        self._tab_to(game.overlay, ("setting", "show_coordinates", False))
        self._key(SPACE)
        self.assertFalse(game.settings.show_coordinates)
        self._key(_key(p.K_ESCAPE))
        self.assertIsNone(game.overlay)

        tester = BoardCursorTests()
        tester.gc = game
        self._key(_key(p.K_k))
        for start, end in (((6, 5), (5, 5)), ((1, 4), (3, 4)), ((6, 6), (4, 6)), ((0, 3), (4, 7))):
            tester._move(start, end)
            self.app.step()
        game.renderer.animation = None  # fin de l'animation du dernier coup
        self.app.step()
        self.assertTrue(game.game_over)
        self.assertIsInstance(game.overlay, app.EndGameOverlay)
        self._tab_to(game.overlay, "new_game")
        self._key(ENTER)
        self.assertIsInstance(self.app.scene, NewGameMenu)


if __name__ == "__main__":
    unittest.main()
