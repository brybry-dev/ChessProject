"""Choix de fichier et de partie (J11.1), parcourus avec le contrôleur sans écran.

On envoie de vrais événements pygame (touches, texte tapé, clics) au contrôleur : S, L,
E et I ouvrent un dialogue de fichiers ; un PGN de plusieurs parties ouvre la liste
des parties. Le dossier de données est un dossier temporaire.
"""

import os
import tempfile
import time
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

from chessproject import paths
from chessproject.core import notation
from chessproject.ui import app, files
from chessproject.ui.board_view import PieceSet

PIECES: PieceSet = PieceSet() if _PYGAME_OK else None  # type: ignore[assignment]

THREE_GAMES = """[Event "Club"]
[White "Alice"]
[Black "Bob"]
[Result "1-0"]

1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0

[Event "Club"]
[White "Carole"]
[Black "David"]
[Result "*"]

1. d4 d5 2. c4 *

[Event "Club"]
[White "Eve"]
[Black "Frank"]
[Result "1/2-1/2"]

1. Nf3 1/2-1/2
"""


def _key(key, **data):
    return p.event.Event(p.KEYDOWN, {"key": key, **data})


def _type(gc, text):
    gc.handle_event(p.event.Event(p.TEXTINPUT, {"text": text}))


class ListingTests(unittest.TestCase):
    def test_folders_first_then_files_newest_first_without_hidden_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b_dossier").mkdir()
            (root / "A_dossier").mkdir()
            (root / ".cache").mkdir()
            old, new = root / "ancienne.pgn", root / "recente.PGN"
            old.write_text("")
            new.write_text("")
            os.utime(old, (time.time() - 100, time.time() - 100))
            (root / "notes.txt").write_text("")
            (root / ".cachee.pgn").write_text("")
            labels = [e.label for e in files.list_directory(root, (".pgn",))]
        self.assertEqual(labels, ["..", "A_dossier", "b_dossier", "recente.PGN", "ancienne.pgn"])

    def test_typed_names_lose_forbidden_characters(self):
        self.assertEqual(files.clean_name("  ma/partie:du*jour?  "), "mapartiedujour")


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class _ControllerTest(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.TemporaryDirectory()
        self.addCleanup(self.data.cleanup)
        patcher = mock.patch.dict(os.environ, {"CHESSPROJECT_DATA_DIR": self.data.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.gc = self._controller()

    def _controller(self, mode="PvP"):
        return app.GameController(
            p.display.get_surface(),
            p.time.Clock(),
            app.UIManager(),
            PIECES,
            mode,
            mode != "CvC",
            mode == "PvP",
            False,
        )

    def _play(self, gc, *sans):
        for san in sans:
            gc.game_state.make_move(notation.parse_san(gc.game_state, san))

    def _draw(self, gc):
        gc.draw()  # le dialogue place ses boutons et sa liste en se dessinant

    def _click(self, gc, pos):
        gc.handle_event(p.event.Event(p.MOUSEBUTTONDOWN, {"pos": pos, "button": 1}))

    def _row_center(self, dialog, index):
        rect = dialog.list.rect
        y = rect.y + (index - dialog.list.scroll) * files.ROW_HEIGHT + files.ROW_HEIGHT // 2
        return rect.centerx, y


class SaveAndLoad(_ControllerTest):
    def test_typed_name_is_saved_in_the_saves_folder(self):
        self._play(self.gc, "e4", "e5")
        self.gc.handle_event(_key(p.K_s))
        dialog = self.gc.overlay
        self.assertIsInstance(dialog, files.FileDialog)
        self.assertTrue(self.gc.frozen, "la pendule s'arrête pendant le choix")
        dialog.name = ""
        _type(self.gc, "ouverture")
        _type(self.gc, " 1")
        self.gc.handle_event(_key(p.K_BACKSPACE))
        _type(self.gc, "2")
        self.gc.handle_event(_key(p.K_RETURN))
        self.assertIsNone(self.gc.overlay)
        self.assertTrue((paths.saves_dir() / "ouverture 2.json").exists())
        assert self.gc.notice is not None
        self.assertIn("ouverture 2.json", self.gc.notice[0])

    def test_overwriting_a_save_asks_for_confirmation(self):
        target = paths.saves_dir() / "partie.json"
        target.write_text("{}")
        self._play(self.gc, "d4")
        self.gc.handle_event(_key(p.K_s))
        self.gc.overlay.name = "partie"
        self.gc.handle_event(_key(p.K_RETURN))
        self.assertIsNotNone(self.gc.overlay, "le fichier existe : confirmation demandée")
        self.assertEqual(target.read_text(), "{}")
        self.gc.handle_event(_key(p.K_RETURN))
        self.assertIsNone(self.gc.overlay)
        self.assertIn("d2d4", target.read_text())

    def test_several_saves_and_choice_of_the_one_to_load(self):
        self._play(self.gc, "e4")
        self.gc._save_to(paths.saves_dir() / "un coup.json")
        self._play(self.gc, "e5", "Nf3")
        self.gc._save_to(paths.saves_dir() / "trois coups.json")
        old = paths.saves_dir() / "un coup.json"
        os.utime(old, (time.time() - 60, time.time() - 60))

        other = self._controller()
        other.handle_event(_key(p.K_l))
        dialog = other.overlay
        self.assertIsInstance(dialog, files.FileDialog)
        names = [e.label for e in dialog.entries if not e.is_dir]
        self.assertEqual(names, ["trois coups.json", "un coup.json"])
        self.assertEqual(dialog.selected_entry.label, "trois coups.json", "la plus récente")
        other.handle_event(_key(p.K_DOWN))
        other.handle_event(_key(p.K_RETURN))
        self.assertIsNone(other.overlay)
        self.assertEqual(len(other.game_state.move_log), 1)

    def test_loading_with_the_mouse(self):
        self._play(self.gc, "e4", "c5")
        self.gc._save_to(paths.saves_dir() / "sicilienne.json")
        other = self._controller()
        other.handle_event(_key(p.K_l))
        self._draw(other)
        dialog = other.overlay
        index = next(i for i, e in enumerate(dialog.entries) if e.label == "sicilienne.json")
        dialog.list.selected = None
        self._click(other, self._row_center(dialog, index))
        self.assertIs(other.overlay, dialog, "un premier clic choisit le fichier")
        self._click(other, self._row_center(dialog, index))
        self.assertIsNone(other.overlay, "un second clic le charge")
        self.assertEqual(len(other.game_state.move_log), 2)

    def test_a_save_can_be_deleted_after_confirmation(self):
        for name in ("a.json", "b.json"):
            self.gc._save_to(paths.saves_dir() / name)
        self.gc.handle_event(_key(p.K_l))
        selected = self.gc.overlay.selected_entry.path
        self.gc.handle_event(_key(p.K_DELETE))
        self.assertTrue(selected.exists(), "premier appui : confirmation demandée")
        self.gc.handle_event(_key(p.K_DELETE))
        self.assertFalse(selected.exists())
        self.assertEqual(len(list(paths.saves_dir().glob("*.json"))), 1)

    def test_old_single_save_is_offered_too(self):
        self.gc._save_to(paths.save_file())  # emplacement des versions 1.3 et antérieures
        other = self._controller()
        other.handle_event(_key(p.K_l))
        self.assertEqual(other.overlay.selected_entry.label, paths.SAVE_FILE_NAME)
        self.assertTrue(paths.save_file().exists(), "l'original reste en place")

    def test_escape_closes_the_dialog_without_saving(self):
        self.gc.handle_event(_key(p.K_s))
        self.gc.handle_event(_key(p.K_ESCAPE))
        self.assertIsNone(self.gc.overlay)
        self.assertEqual(list(paths.saves_dir().iterdir()), [])

    def test_a_corrupt_save_is_reported(self):
        (paths.saves_dir() / "abimee.json").write_text("{pas du json")
        self.gc.handle_event(_key(p.K_l))
        self.gc.handle_event(_key(p.K_RETURN))
        assert self.gc.notice is not None
        self.assertEqual(self.gc.notice[1], "warning")
        self.assertEqual(self.gc.game_state.move_log, [])


class ExportAndImport(_ControllerTest):
    def test_export_where_the_player_chooses_and_import_from_there(self):
        folder = Path(self.data.name) / "mes parties"
        folder.mkdir()
        self._play(self.gc, "e4", "e5", "Nf3")
        self.gc.handle_event(_key(p.K_e))
        dialog = self.gc.overlay
        index = next(i for i, e in enumerate(dialog.entries) if e.label == "mes parties")
        self._draw(self.gc)
        self._click(self.gc, self._row_center(dialog, index))  # un clic ouvre le dossier
        self.assertEqual(dialog.directory, folder)
        dialog.name = "italienne"
        self.gc.handle_event(_key(p.K_RETURN))
        self.assertTrue((folder / "italienne.pgn").exists())
        self.assertEqual(self.gc.settings.pgn_dir, str(folder), "dossier retenu")

        # L'import suivant s'ouvre dans ce dossier, le fichier le plus récent choisi.
        self.gc.handle_event(_key(p.K_i))
        self.assertEqual(self.gc.overlay.directory, folder)
        self.gc._restart()
        self.gc.handle_event(_key(p.K_i))
        self.gc.handle_event(_key(p.K_RETURN))
        self.assertEqual(len(self.gc.game_state.move_log), 3)

    def test_choice_of_one_game_in_a_multi_game_pgn(self):
        source = Path(self.data.name) / "club.pgn"
        source.write_text(THREE_GAMES, encoding="utf-8")
        self.gc.handle_event(_key(p.K_i))
        self.gc.handle_event(_key(p.K_RETURN))
        picker = self.gc.overlay
        self.assertIsInstance(picker, files.GamePickerOverlay)
        self.assertEqual(picker.labels[0][0], "1. Alice – Bob · 1-0")
        self.assertEqual(picker.labels[1][1], "Club · 2 coups")
        self.gc.handle_event(_key(p.K_DOWN))
        self.gc.handle_event(_key(p.K_RETURN))
        self.assertIsNone(self.gc.overlay)
        sans = notation.san_history(self.gc.game_state)
        self.assertEqual(sans, ["d4", "d5", "c4"])

    def test_choice_of_a_game_with_the_mouse(self):
        source = Path(self.data.name) / "club.pgn"
        source.write_text(THREE_GAMES, encoding="utf-8")
        self.gc._import_from(source)
        picker = self.gc.overlay
        self._draw(self.gc)
        self._click(self.gc, self._row_center(picker, 2))
        self._click(self.gc, self._row_center(picker, 2))
        self.assertEqual(notation.san_history(self.gc.game_state), ["Nf3"])

    def test_cancelling_the_game_choice_keeps_the_current_game(self):
        source = Path(self.data.name) / "club.pgn"
        source.write_text(THREE_GAMES, encoding="utf-8")
        self._play(self.gc, "c4")
        self.gc._import_from(source)
        self.gc.handle_event(_key(p.K_ESCAPE))
        self.assertIsNone(self.gc.overlay)
        self.assertEqual(notation.san_history(self.gc.game_state), ["c4"])

    def test_invalid_pgn_is_reported(self):
        source = Path(self.data.name) / "faux.pgn"
        source.write_text("1. e4 e5 2. Ke3 *", encoding="utf-8")
        self.assertFalse(self.gc._import_from(source))
        assert self.gc.notice is not None
        self.assertEqual(self.gc.notice[1], "warning")

    def test_place_buttons_change_folder(self):
        self.gc.handle_event(_key(p.K_i))
        self._draw(self.gc)
        dialog = self.gc.overlay
        home = next(b for b in dialog.buttons if b.action == ("place", Path.home()))
        self._click(self.gc, home.rect.center)
        self.assertEqual(dialog.directory, Path.home())


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class FromTheNewGameScreen(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.TemporaryDirectory()
        self.addCleanup(self.data.cleanup)
        patcher = mock.patch.dict(os.environ, {"CHESSPROJECT_DATA_DIR": self.data.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        with mock.patch.object(app.settings_module, "save"):
            self.app = app.App(p.display.get_surface(), app.Settings(mode="PvP"), PIECES)

    def test_import_button_opens_the_pgn_dialog_over_the_game(self):
        (Path(self.data.name) / "club.pgn").write_text(THREE_GAMES, encoding="utf-8")
        with mock.patch.object(app.settings_module, "save"):
            self.app.handle_event(_key(p.K_i))
            game = self.app.scene
            assert isinstance(game, app.GameController)
            self.assertIsInstance(game.overlay, files.FileDialog)
            self.app.step()
            self.app.handle_event(_key(p.K_RETURN))
            self.app.handle_event(_key(p.K_RETURN))
        self.assertEqual(len(game.game_state.move_log), 7)


if __name__ == "__main__":
    unittest.main()
