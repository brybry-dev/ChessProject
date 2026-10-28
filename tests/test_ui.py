"""Tests de l'interface J5 : mise en page, préférences, scènes, interactions.

Tout tourne sans écran (pilote SDL « dummy ») : on envoie de vrais événements
pygame au contrôleur et on vérifie l'état de la partie, pas les pixels.
"""

import os
import queue
import random
import tempfile
import unittest
from dataclasses import replace
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

from chessproject import settings as settings_module
from chessproject.ai import analysis, levels, review, search
from chessproject.core import clock, engine, notation, pgn
from chessproject.core.fen import load_fen
from chessproject.settings import Settings
from chessproject.ui import app, layout, new_game, widgets
from chessproject.ui.board_view import PieceSet
from chessproject.ui.new_game import GameConfig, NewGameMenu, config_from

PIECES: PieceSet = PieceSet() if _PYGAME_OK else None  # type: ignore[assignment]


def _opaque_pixels(image: p.Surface) -> int:
    """Nombre de pixels visibles (alpha >= 128) : une image transparente n'en a aucun."""
    width, height = image.get_size()
    return sum(image.get_at((x, y)).a >= 128 for x in range(width) for y in range(height))


def _event(kind, **data):
    return p.event.Event(kind, data)


class LayoutTests(unittest.TestCase):
    SIZES = [(960, 640), (1024, 768), (1280, 800), (1366, 700), (1920, 1080), (2560, 1440)]

    def test_board_and_panel_fit_in_the_window_without_overlapping(self):
        for width, height in self.SIZES:
            for show_eval in (True, False):
                with self.subTest(size=(width, height), show_eval=show_eval):
                    lay = layout.compute(width, height, show_eval)
                    window = p.Rect(0, 0, width, height)
                    self.assertEqual(lay.board.width % 8, 0)
                    self.assertEqual(lay.board.width, lay.board.height)
                    self.assertTrue(window.contains(lay.board))
                    self.assertTrue(window.contains(lay.panel))
                    self.assertGreaterEqual(lay.board.top, lay.header.bottom)
                    self.assertFalse(lay.board.colliderect(lay.panel))
                    self.assertGreaterEqual(lay.panel.width, layout.PANEL_MIN_WIDTH)
                    self.assertEqual(lay.eval_bar is not None, show_eval)
                    if lay.eval_bar is not None:
                        self.assertLessEqual(lay.eval_bar.right, lay.board.left)

    def test_board_grows_with_the_window(self):
        small = layout.compute(1024, 700).board.width
        large = layout.compute(1920, 1080).board.width
        self.assertGreater(large, small)

    def test_window_is_never_smaller_than_the_minimum(self):
        self.assertEqual(layout.clamp_window_size(400, 300), layout.MIN_SIZE)
        self.assertEqual(layout.initial_window_size(1366, 768)[1], int(768 * 0.88))
        self.assertEqual(layout.initial_window_size(0, 0), layout.DEFAULT_SIZE)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "settings.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_roundtrip(self):
        s = Settings(
            theme="clair",
            board="Noyer",
            show_eval=False,
            show_analysis=True,
            mode="PvP",
            level="Expert",
            time_control=clock.RAPID_10_5.pgn_tag,
        )
        self.assertTrue(settings_module.save(s, self.path))
        self.assertEqual(settings_module.load(self.path), s)
        self.assertFalse(self.path.with_name("settings.json.tmp").exists())

    def test_invalid_fields_fall_back_to_their_default(self):
        data = {"theme": "fluo", "show_eval": "oui", "level": "Moyen", "time_control": "40/9000"}
        s = settings_module.from_dict(data)
        self.assertEqual(s.theme, Settings().theme)
        self.assertEqual(s.show_eval, Settings().show_eval)
        self.assertEqual(s.time_control, Settings().time_control)
        self.assertEqual(s.level, "Moyen")
        self.assertEqual(settings_module.from_dict([1, 2]), Settings())

    def test_missing_or_unreadable_file_gives_defaults(self):
        self.assertEqual(settings_module.load(self.path), Settings())
        self.path.write_text("{pas du json", encoding="utf-8")
        self.assertEqual(settings_module.load(self.path), Settings())

    def test_time_control_is_the_matching_preset(self):
        self.assertEqual(Settings(time_control="180+2").control.name, "Blitz 3+2")
        self.assertTrue(Settings(time_control="-").control.is_unlimited)
        self.assertEqual(Settings(time_control="420+1").control.label, "7+1")


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class NewGameMenuTests(unittest.TestCase):
    def test_level_cards_show_the_measured_strength(self):
        level = levels.Level("Test", 1500, 3, 0, 0.0, 1)
        self.assertEqual(new_game._strength_label(level), "1,5 s")  # pas encore mesuré
        measured = levels.Level("Test", 1500, 3, 0, 0.0, 1, elo=1450, elo_margin=60)
        self.assertEqual(new_game._strength_label(measured), "≈ 1450 Elo")

    def test_choices_become_the_game_configuration(self):
        menu = NewGameMenu(Settings(), can_cancel=False, pieces=PIECES)
        menu.choose("color", "b")
        menu.choose("level", "Expert")
        menu.choose("time_control", clock.BULLET_1_0.pgn_tag)
        action = menu.handle_event(_event(p.KEYDOWN, key=p.K_RETURN))
        self.assertEqual(action[0], "start")
        config = action[1]
        self.assertEqual((config.human_white, config.human_black), (False, True))
        self.assertTrue(config.flip_board)
        self.assertEqual(config.level, "Expert")
        self.assertEqual(config.time_control, clock.BULLET_1_0)

    def test_random_colour_is_drawn_when_the_game_starts(self):
        colours = {
            config_from(Settings(color="r"), random.Random(seed)).human_white for seed in range(20)
        }
        self.assertEqual(colours, {True, False})

    def test_modes(self):
        self.assertEqual(config_from(Settings(mode="PvP")).human_black, True)
        cvc = config_from(Settings(mode="CvC"))
        self.assertEqual((cvc.human_white, cvc.human_black), (False, False))

    def test_clicking_an_option_selects_it(self):
        menu = NewGameMenu(Settings(), can_cancel=False, pieces=PIECES)
        menu.draw(p.display.get_surface(), app.th.theme("sombre"), (0, 0), 0)
        expert = next(b for b in menu.buttons if b.action == ("choose", "level", "Expert"))
        self.assertIsNone(
            menu.handle_event(_event(p.MOUSEBUTTONDOWN, pos=expert.rect.center, button=1))
        )
        self.assertEqual(menu.settings.level, "Expert")

    def test_escape_returns_to_the_game_only_if_there_is_one(self):
        esc = _event(p.KEYDOWN, key=p.K_ESCAPE)
        self.assertIsNone(NewGameMenu(Settings(), False, PIECES).handle_event(esc))
        self.assertEqual(NewGameMenu(Settings(), True, PIECES).handle_event(esc), "cancel")

    def test_summary(self):
        menu = NewGameMenu(
            Settings(mode="PvC", color="w", level="Facile", time_control="-"), False, PIECES
        )
        self.assertEqual(menu.summary(), "Vous jouez les blancs contre l'IA Facile, sans pendule.")


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
class BoardInteractionTests(unittest.TestCase):
    def setUp(self):
        self.gc = _controller()

    def _center(self, square):
        return self.gc.renderer.square_rect(*square).center

    def _down(self, square, button=1):
        self.gc.handle_event(_event(p.MOUSEBUTTONDOWN, pos=self._center(square), button=button))

    def _move(self, square, buttons=(1, 0, 0)):
        self.gc.handle_event(
            _event(p.MOUSEMOTION, pos=self._center(square), rel=(0, 0), buttons=buttons)
        )

    def _up(self, square, button=1):
        self.gc.handle_event(_event(p.MOUSEBUTTONUP, pos=self._center(square), button=button))

    def test_drag_and_drop_plays_the_move_without_animation(self):
        self._down((6, 4))
        self._move((5, 4))
        self._move((4, 4))
        self.assertTrue(self.gc.drag.active)
        self._up((4, 4))
        self.assertEqual(str(self.gc.game_state.move_log[-1]), "e4")
        self.assertFalse(self.gc.animate)
        self.assertIsNone(self.gc.drag)
        self.assertEqual(self.gc.square_selected, ())

    def test_drop_on_an_illegal_square_keeps_the_position(self):
        self._down((6, 4))
        self._move((3, 4))
        self._up((3, 4))  # e5 : deux cases de trop
        self.assertEqual(self.gc.game_state.move_log, [])
        self.assertEqual(self.gc.square_selected, (6, 4))  # pièce toujours choisie

    def test_click_then_click_still_works_with_real_button_releases(self):
        self._down((7, 6))
        self._up((7, 6))
        self.assertEqual(self.gc.square_selected, (7, 6))
        self._down((5, 5))
        self._up((5, 5))
        self.assertEqual(str(self.gc.game_state.move_log[-1]), "Nf3")
        self.assertTrue(self.gc.animate)

    def test_clicking_the_selected_piece_again_deselects_it(self):
        self._down((6, 3))
        self._up((6, 3))
        self._down((6, 3))
        self._up((6, 3))
        self.assertEqual(self.gc.square_selected, ())

    def test_right_click_draws_arrows_and_marks_and_left_click_clears_them(self):
        self._down((6, 4), button=3)
        self._move((4, 4), buttons=(0, 0, 1))
        self._up((4, 4), button=3)
        self._down((3, 3), button=3)
        self._up((3, 3), button=3)
        self.assertEqual(self.gc.arrows, {((6, 4), (4, 4))})
        self.assertEqual(self.gc.marks, {(3, 3)})
        # Le même tracé une deuxième fois efface la flèche.
        self._down((6, 4), button=3)
        self._up((4, 4), button=3)
        self.assertEqual(self.gc.arrows, set())
        self._down((4, 4))
        self.assertEqual(self.gc.marks, set())

    def test_promotion_with_the_keyboard(self):
        self.gc._new_game(load_fen("7k/P7/8/8/8/8/8/K7 w - - 0 1"))
        self._down((1, 0))
        self._down((0, 0))
        self.assertIsNotNone(self.gc.promotion_popup)
        self.gc.handle_event(_event(p.KEYDOWN, key=p.K_c))  # C = cavalier
        self.assertEqual(self.gc.game_state.board[0][0], "wN")
        self.assertIsNone(self.gc.promotion_popup)

    def test_flip_rotates_the_view_only(self):
        before = [row[:] for row in self.gc.game_state.board]
        self.gc.handle_event(_event(p.KEYDOWN, key=p.K_f))
        self.assertTrue(self.gc.flip_board)
        self.assertEqual(self.gc.game_state.board, before)
        self.assertEqual(self.gc.renderer.square_from_pixel(self._center((7, 4))), (7, 4))


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class TypedMoveTests(unittest.TestCase):
    """J11.2 : Entrée (ou Espace) ouvre la saisie, le coup tapé est joué à Entrée."""

    def setUp(self):
        self.gc = _controller()

    def _key(self, key):
        self.gc.handle_event(_event(p.KEYDOWN, key=key, mod=0, unicode=""))

    def _type(self, text):
        # Comme au clavier : une touche (KEYDOWN) puis le caractère (TEXTINPUT).
        for char in text:
            self.gc.handle_event(_event(p.KEYDOWN, key=ord(char.lower()), mod=0, unicode=char))
            self.gc.handle_event(_event(p.TEXTINPUT, text=char))

    def _play(self, text):
        self._key(p.K_RETURN)
        self._type(text)
        self._key(p.K_RETURN)

    def _sans(self):
        return notation.san_history(self.gc.game_state)

    def test_typed_moves_are_played(self):
        for text in ("e4", "e5", "nf3", "Cc6", "Bb5", "a6", "O-O"):
            self._play(text)
        self.assertEqual(self._sans(), ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "O-O"])
        self.assertIsNone(self.gc.move_input)

    def test_space_opens_the_input_too(self):
        self._key(p.K_SPACE)
        self.gc.handle_event(_event(p.TEXTINPUT, text=" "))
        self.assertEqual(self.gc.move_input, "")
        self._type("d4")
        self._key(p.K_RETURN)
        self.assertEqual(self._sans(), ["d4"])

    def test_shortcut_letters_are_typed_not_run(self):
        self._key(p.K_RETURN)
        self._type("bfeacn")  # B indice, F retourner, E exporter, A abandon, N nulle…
        self.assertFalse(self.gc.flip_board)
        self.assertIsNone(self.gc.overlay)
        self.assertIsNone(self.gc.draw_offer)
        self.assertEqual(self.gc.move_input, "bfeacn")

    def test_illegal_move_is_reported_and_can_be_corrected(self):
        self._play("e5")
        self.assertEqual(self.gc.game_state.move_log, [])
        self.assertEqual(self.gc.move_input, "e5", "la saisie reste ouverte")
        self.assertEqual(self.gc.move_input_error, "Coup illégal : e5")
        model = self.gc._panel_model(self.gc.game_state)
        self.assertEqual(model.move_input, ("e5", "Coup illégal : e5"))
        self._key(p.K_BACKSPACE)
        self.assertIsNone(self.gc.move_input_error)
        self._type("4")
        self._key(p.K_RETURN)
        self.assertEqual(self._sans(), ["e4"])

    def test_unreadable_and_ambiguous_moves_are_explained(self):
        self._play("xyz")
        self.assertEqual(self.gc.move_input_error, "Notation non reconnue : xyz")
        self.gc._close_move_input()
        self.gc._new_game(load_fen("4k3/8/8/8/8/8/8/1N1K1N2 w - - 0 1"))
        self._play("Nd2")
        self.assertEqual(self.gc.move_input_error, "Coup ambigu : Nbd2 ou Nfd2 ?")

    def test_promotion_without_a_piece_opens_the_choice(self):
        self.gc._new_game(load_fen("7k/P7/8/8/8/8/8/K7 w - - 0 1"))
        self._play("a8")
        self.assertIsNotNone(self.gc.promotion_popup)
        self.gc.handle_event(_event(p.KEYDOWN, key=p.K_n, mod=0, unicode="n"))
        self.assertEqual(self.gc.game_state.board[0][0], "wN")

    def test_promotion_with_a_piece_is_played_directly(self):
        self.gc._new_game(load_fen("7k/P7/8/8/8/8/8/K7 w - - 0 1"))
        self._play("a8=R")
        self.assertIsNone(self.gc.promotion_popup)
        self.assertEqual(self.gc.game_state.board[0][0], "wR")

    def test_escape_backspace_or_a_click_close_the_input(self):
        self._key(p.K_RETURN)
        self._key(p.K_ESCAPE)
        self.assertIsNone(self.gc.move_input)
        self._key(p.K_RETURN)
        self._key(p.K_BACKSPACE)
        self.assertIsNone(self.gc.move_input, "effacer une saisie vide la ferme")
        self._key(p.K_RETURN)
        center = self.gc.renderer.square_rect(6, 4).center
        self.gc.handle_event(_event(p.MOUSEBUTTONDOWN, pos=center, button=1))
        self.assertIsNone(self.gc.move_input)
        self.assertEqual(self.gc.square_selected, (6, 4), "le clic garde son effet")

    def test_input_returns_to_the_live_position(self):
        self._play("e4")
        self._play("e5")
        self._key(p.K_LEFT)
        self.assertIsNotNone(self.gc.view_ply)
        self._key(p.K_RETURN)
        self.assertIsNone(self.gc.view_ply)

    def test_not_available_when_it_is_not_the_players_turn(self):
        gc = _controller("PvC", True, False)
        gc.game_state.make_move(notation.parse_san(gc.game_state, "e4"))
        gc.handle_event(_event(p.KEYDOWN, key=p.K_RETURN, mod=0, unicode=""))
        self.assertIsNone(gc.move_input)
        assert gc.notice is not None
        self.assertEqual(gc.notice[0], "Ce n'est pas à vous de jouer")

    def test_the_panel_draws_the_input(self):
        self._key(p.K_RETURN)
        self._type("Nf")
        self.gc.draw()
        self.gc.move_input_error = "Coup illégal : Nf"
        self.gc.draw()


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class HistoryNavigationTests(unittest.TestCase):
    MOVES = ["e4", "e5", "Nf3", "Nc6", "Bb5"]

    def setUp(self):
        self.gc = _controller()
        for san in self.MOVES:
            self.gc.game_state.make_move(notation.parse_san(self.gc.game_state, san))
        self.gc.move_made = True
        self.gc.update()

    def _key(self, key):
        self.gc.handle_event(_event(p.KEYDOWN, key=key))

    def test_arrow_keys_walk_through_the_game_without_changing_it(self):
        live = [row[:] for row in self.gc.game_state.board]
        self._key(p.K_LEFT)
        self._key(p.K_LEFT)
        self.assertEqual(self.gc.current_ply, 3)
        expected = engine.GameState()
        for san in self.MOVES[:3]:
            expected.make_move(notation.parse_san(expected, san))
        self.assertEqual(self.gc.state_at(3).board, expected.board)
        self.assertEqual(self.gc.game_state.board, live)
        self._key(p.K_HOME)
        self.assertEqual(self.gc.current_ply, 0)
        self.assertEqual(self.gc.state_at(0).board, engine.GameState().board)
        self._key(p.K_END)
        self.assertIsNone(self.gc.view_ply)

    def test_clicking_a_move_in_the_list_shows_that_position(self):
        self.gc.draw()
        rect, ply = next((r, ply) for r, ply in self.gc.panel._cells if ply == 2)
        self.gc.handle_event(_event(p.MOUSEBUTTONDOWN, pos=rect.center, button=1))
        self.assertEqual(self.gc.view_ply, 2)

    def test_the_board_is_read_only_while_reviewing(self):
        self._key(p.K_LEFT)
        pos = self.gc.renderer.square_rect(6, 3).center
        self.gc.handle_event(_event(p.MOUSEBUTTONDOWN, pos=pos, button=1))
        self.assertIsNone(self.gc.view_ply)  # retour à la partie, sans sélection
        self.assertEqual(self.gc.square_selected, ())
        self.assertEqual(len(self.gc.game_state.move_log), len(self.MOVES))

    def test_move_rows_follow_the_fullmove_numbers(self):
        rows = self.gc._move_rows()
        self.assertEqual([r.number for r in rows], [1, 2, 3])
        self.assertEqual(rows[2].white, ("Bb5", 5))
        self.assertIsNone(rows[2].black)

    def test_game_started_by_black_begins_with_an_ellipsis(self):
        gc = _controller()
        gc._new_game(load_fen("4k3/8/8/8/8/8/4P3/4K3 b - - 0 12"))
        for san in ["Kd7", "e4"]:
            gc.game_state.make_move(notation.parse_san(gc.game_state, san))
        rows = gc._move_rows()
        self.assertEqual((rows[0].number, rows[0].white, rows[0].black), (12, None, ("Kd7", 1)))
        self.assertEqual(rows[1].white, ("e4", 2))


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class PanelContentTests(unittest.TestCase):
    def test_captured_pieces_and_material(self):
        gc = _controller()
        for san in ["e4", "d5", "exd5", "Qxd5", "Nc3"]:
            gc.game_state.make_move(notation.parse_san(gc.game_state, san))
        taken = gc._captures(gc.live_ply)
        self.assertEqual(taken, {"w": ["bp"], "b": ["wp"]})
        self.assertEqual(gc._material(gc.game_state.board), 0)

    def test_evaluation_display(self):
        self.assertEqual(app.eval_text(42), "+0,4")
        self.assertEqual(app.eval_text(-150), "−1,5")
        self.assertEqual(app.eval_text(app.search.MATE - 5), "#3")
        self.assertEqual(app.eval_text(-(app.search.MATE - 1)), "−#1")
        self.assertAlmostEqual(app.eval_share(0), 0.5)
        self.assertGreater(app.eval_share(300), 0.8)
        self.assertEqual(app.eval_share(app.search.MATE - 3), 1.0)

    def test_evaluation_does_not_touch_the_game(self):
        gs = load_fen("r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4")
        before = (gs.board, gs.zobrist_key, len(gs.move_log))
        cp = app.evaluate_for_display(gs)
        self.assertGreater(cp, app.search.MATE_THRESHOLD)  # Dxf7#
        self.assertEqual((gs.board, gs.zobrist_key, len(gs.move_log)), before)

    def test_status_line(self):
        gc = _controller("PvC", True, False)
        self.assertEqual(gc._status()[0], "À vous de jouer")
        gc._notify("Partie sauvegardée", "accent")
        self.assertEqual(gc._status(), ("Partie sauvegardée", "accent"))


class _InlineProcess:
    """Faux multiprocessing.Process : exécute la cible au démarrage."""

    def __init__(self, target, args=(), daemon=False):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)

    def is_alive(self):
        return False

    def terminate(self):
        pass


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class AnalysisTests(unittest.TestCase):
    """J9.1 : variante principale de la position affichée, désactivée par défaut."""

    def setUp(self):
        self.gc = _controller()
        self.gc.analyzer = analysis.Analyzer(
            process=_InlineProcess, make_queue=queue.Queue, limits=search.SearchLimits(depth=2)
        )
        for san in ["e4", "e5", "Nf3"]:
            self.gc.game_state.make_move(notation.parse_san(self.gc.game_state, san))
        self.gc.move_made = True

    def _analysis(self):
        self.gc.update()
        return self.gc._panel_model(self.gc.state_at(self.gc.current_ply)).analysis

    def test_off_by_default(self):
        self.assertFalse(Settings().show_analysis)
        self.assertIsNone(self._analysis())
        self.assertIsNone(self.gc.analyzer.key)

    def test_v_shows_the_line_of_the_current_position(self):
        changes: list[Settings] = []
        self.gc.on_settings_change = changes.append
        self.gc.handle_event(_event(p.KEYDOWN, key=p.K_v))
        self.assertTrue(changes[-1].show_analysis)
        line, info = self._analysis()
        self.assertTrue(line.startswith("2... "), line)  # les noirs au trait
        self.assertIn("prof. 2", info)
        self.gc.draw()

    def test_the_evaluation_comes_from_the_analysis(self):
        self.gc.set_setting("show_analysis", True)
        self._analysis()
        ply = self.gc.current_ply
        self.gc.analyzer.line = replace(self.gc.analyzer.line, score=-321)
        self.assertEqual(self.gc._eval(self.gc.state_at(ply), ply), -321)
        self.gc._navigate("first")  # autre position : pas encore analysée
        self.assertNotEqual(self.gc._eval(self.gc.state_at(0), 0), -321)

    def test_the_line_follows_the_reviewed_position(self):
        self.gc.set_setting("show_analysis", True)
        self._analysis()
        self.gc._navigate("first")
        line, _ = self._analysis()
        self.assertTrue(line.startswith("1. "), line)
        self.assertEqual(self.gc.live_ply, 3)  # la partie n'a pas bougé

    def test_turning_it_off_stops_the_analysis(self):
        self.gc.set_setting("show_analysis", True)
        self._analysis()
        self.gc.handle_event(_event(p.KEYDOWN, key=p.K_v))
        self.assertIsNone(self._analysis())
        self.assertIsNone(self.gc.analyzer.key)

    def test_finished_game_has_no_line(self):
        self.gc._new_game(load_fen("R5k1/5ppp/8/8/8/8/8/6K1 b - - 0 1"))
        self.gc.set_setting("show_analysis", True)
        self.assertIsNone(self._analysis())


class _IdleProcess(_InlineProcess):
    """Faux processus qui ne rend jamais rien (recherche en cours)."""

    def start(self):
        pass

    def is_alive(self):
        return True


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class HintTests(unittest.TestCase):
    """J9.2 : bouton « Indice », meilleur coup en flèche."""

    def _controller(self, *args, process=_InlineProcess, **kwargs):
        gc = _controller(*args, **kwargs)
        gc.hinter = analysis.Analyzer(
            process=process, make_queue=queue.Queue, limits=search.SearchLimits(depth=2)
        )
        return gc

    def _hint_button(self, gc):
        gc.draw()
        return next(b for b in gc.header.buttons if b.action == "hint")

    def test_b_draws_the_best_move_as_an_arrow(self):
        gc = self._controller()
        gc._new_game(load_fen("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"))
        gc.handle_event(_event(p.KEYDOWN, key=p.K_b))
        gc.update()
        self.assertEqual(gc.arrows, {((7, 0), (0, 0))})  # Ra8#
        self.assertEqual(gc._status()[0], "Indice : Ra8#")
        self.assertEqual(gc.live_ply, 0)  # l'indice ne joue pas le coup

    def test_the_header_button_asks_for_a_hint(self):
        gc = self._controller()
        button = self._hint_button(gc)
        self.assertTrue(button.enabled)
        gc.handle_event(_event(p.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
        gc.update()
        self.assertEqual(len(gc.arrows), 1)
        ((start, end),) = gc.arrows
        legal = {((m.start_row, m.start_col), (m.end_row, m.end_col)) for m in gc.valid_moves}
        self.assertIn((start, end), legal)

    def test_hint_from_the_review_comes_back_to_the_game(self):
        gc = self._controller()
        gc.game_state.make_move(notation.parse_san(gc.game_state, "e4"))
        gc._navigate("first")
        gc._hint()
        self.assertIsNone(gc.view_ply)

    def test_status_while_searching_and_a_move_cancels_the_hint(self):
        gc = self._controller(process=_IdleProcess)
        gc._hint()
        gc.update()
        self.assertEqual(gc._status()[0], "Recherche d'un indice…")
        gc.game_state.make_move(notation.parse_san(gc.game_state, "e4"))
        gc.move_made = True
        gc.update()
        self.assertIsNone(gc.hinter.key)
        self.assertFalse(gc.arrows)
        self.assertNotEqual(gc._status()[0], "Recherche d'un indice…")

    def test_not_available_on_the_ai_turn_or_after_the_game(self):
        gc = self._controller("PvC", False, True)  # l'IA a les blancs et le trait
        self.assertFalse(gc._can_hint())
        gc = self._controller("CvC", False, False)
        self.assertFalse(gc._can_hint())
        gc = self._controller()
        gc._resign()
        self.assertFalse(self._hint_button(gc).enabled)

    def test_can_be_turned_off_against_the_ai(self):
        gc = self._controller("PvC", True, False, settings=Settings(hints_vs_ai=False))
        self.assertFalse(self._hint_button(gc).enabled)
        gc.handle_event(_event(p.KEYDOWN, key=p.K_b))
        gc.update()
        self.assertFalse(gc.arrows)
        self.assertIsNone(gc.hinter.key)
        # Entre deux joueurs, l'option ne s'applique pas.
        gc = self._controller(settings=Settings(hints_vs_ai=False))
        self.assertTrue(gc._can_hint())


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class GameReviewTests(unittest.TestCase):
    """J9.3 : courbe d'évaluation et bilan de la partie."""

    def setUp(self):
        self.gc = _controller()
        self.gc.reviewer = review.Reviewer(
            process=_InlineProcess, make_queue=queue.Queue, nodes=2000
        )

    def _play(self, sans):
        for san in sans:
            self.gc.game_state.make_move(notation.parse_san(self.gc.game_state, san))
        self.gc.move_made = True
        self.gc.update()

    def test_nothing_to_review_before_the_first_move(self):
        self.gc.handle_event(_event(p.KEYDOWN, key=p.K_g))
        self.assertIsNone(self.gc.overlay)
        self.assertEqual(self.gc._status()[0], "Aucun coup à analyser")

    def test_end_card_opens_the_review_and_marks_the_moves(self):
        self._play(["f3", "e5", "g4", "Qh4#"])
        self.gc.draw()
        self.assertIsInstance(self.gc.overlay, app.EndGameOverlay)
        button = next(b for b in self.gc.overlay.buttons if b.action == "game_review")
        self.gc.handle_event(_event(p.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
        self.assertIsInstance(self.gc.overlay, app.ReviewOverlay)
        self.gc.update()
        result = self.gc.reviewer.result()
        assert result is not None
        self.assertEqual(result.white.blunders, 1)
        rows = self.gc._move_rows()
        self.assertEqual(rows[1].white, ("g4??", 3))
        for theme in ("sombre", "clair"):
            self.gc.set_setting("theme", theme)
            self.gc.draw()

    def test_clicking_the_curve_shows_that_position(self):
        self._play(["e4", "e5", "Nf3", "Nc6"])
        self.gc.handle_event(_event(p.KEYDOWN, key=p.K_g))
        self.gc.update()
        self.gc.draw()
        chart = self.gc.overlay.chart
        x = chart.x + chart.width // 2  # demi-coup 2 sur 4
        self.gc.handle_event(_event(p.MOUSEBUTTONDOWN, pos=(x, chart.centery), button=1))
        self.assertIsNone(self.gc.overlay)
        self.assertEqual(self.gc.view_ply, 2)
        self.assertEqual(self.gc.live_ply, 4)

    def _open_finished_review(self, sans):
        self._play(sans)
        self.gc.overlay = None
        self.gc.end_dismissed = True
        self.gc.handle_event(_event(p.KEYDOWN, key=p.K_g))
        self.gc.update()
        self.gc.draw()

    def _assert_best_move_shown(self, ply):
        fault = self.gc.reviewer.result().moves[ply - 1]
        self.assertIsNone(self.gc.overlay)
        self.assertEqual(self.gc.view_ply, ply - 1)
        state = self.gc.state_at(ply - 1)
        best = notation.parse_san(state, fault.best[0])  # légal dans la position montrée
        scene = self.gc._board_scene(state)
        arrow = ((best.start_row, best.start_col), (best.end_row, best.end_col))
        self.assertIn(arrow, scene.arrows)
        self.assertNotIn(arrow, self.gc.arrows)  # pas mêlée aux flèches du joueur
        line, info = self.gc._analysis_text()
        self.assertEqual(line, "Meilleur coup : " + fault.best_line)
        self.assertEqual(info, "au lieu de " + fault.san + fault.symbol)
        self.gc.draw()
        return arrow

    def test_clicking_a_fault_shows_the_best_move_and_its_line(self):
        """J13.1 : position d'avant la faute, meilleur coup en flèche, variante."""
        self._open_finished_review(["f3", "e5", "g4", "Qh4#"])
        dots = [b for b in self.gc.overlay.buttons if b.action[0] == "review_best"]
        self.assertEqual([b.action for b in dots], [("review_best", 3)])  # g4??
        self.gc.handle_event(_event(p.MOUSEBUTTONDOWN, pos=dots[0].rect.center, button=1))
        arrow = self._assert_best_move_shown(3)
        self.assertTrue(self.gc._move_rows())
        # Ailleurs dans la partie, la flèche et la variante disparaissent.
        self.gc._navigate("next")
        self.assertNotIn(arrow, self.gc._board_scene(self.gc.state_at(3)).arrows)
        self.assertIsNone(self.gc._analysis_text())
        self.gc._navigate("prev")
        self.assertIn(arrow, self.gc._board_scene(self.gc.state_at(2)).arrows)
        # Un coup annulé change la partie : la faute n'est plus montrée.
        self.gc._navigate("last")
        self.gc._undo()
        self.gc._view(2)
        self.assertIsNone(self.gc._shown_fault())

    def test_faults_are_reached_with_tab_in_move_order(self):
        self._open_finished_review(["e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6", "Qxf7#"])
        overlay = self.gc.overlay
        faults = [m.ply for m in self.gc.reviewer.result().moves if m.judgement]
        self.assertIn(6, faults)  # Nf6??
        visited = []
        for _ in range(len(overlay.buttons)):
            self.gc.handle_event(_event(p.KEYDOWN, key=p.K_TAB, mod=0))
            self.gc.draw()
            action = overlay.focus.current(overlay.buttons).action
            if action[0] == "review_best":
                visited.append(action[1])
        # Le × d'abord (en haut de la carte), puis les pastilles de gauche à droite.
        self.assertEqual(visited, faults)
        while overlay.focus.current(overlay.buttons).action != ("review_best", 6):
            self.gc.handle_event(_event(p.KEYDOWN, key=p.K_TAB, mod=0))
            self.gc.draw()
        self.gc.handle_event(_event(p.KEYDOWN, key=p.K_RETURN))
        self._assert_best_move_shown(6)

    def test_export_from_the_review_is_annotated(self):
        """J13.2 : bouton (ou E) de la fenêtre de bilan, symboles et évaluations."""
        self._play(["f3", "e5"])
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        self.gc._export_to(folder / "brut.pgn")  # pas de bilan : PGN simple
        self.assertNotIn("{", (folder / "brut.pgn").read_text())
        self._open_finished_review(["g4", "Qh4#"])
        export = next(b for b in self.gc.overlay.buttons if b.action == "export")
        self.assertTrue(export.enabled)
        self.gc.handle_event(_event(p.KEYDOWN, key=p.K_e))
        self.assertIsInstance(self.gc.overlay, app.FileDialog)
        self.gc._export_to(folder / "annote.pgn")
        text = (folder / "annote.pgn").read_text()
        self.assertIn('[Annotator "ChessProject"]', text)
        self.assertIn("g4 $4 {[%eval", text)
        self.assertTrue(self.gc._status()[0].startswith("PGN annoté exporté"))
        self.assertEqual(pgn.parse_pgn(text)[0].moves, ["f3", "e5", "g4", "Qh4#"])

    def test_export_waits_for_the_complete_review(self):
        self.gc.reviewer = review.Reviewer(process=_IdleProcess, make_queue=queue.Queue)
        self._play(["e4"])
        self.gc.handle_event(_event(p.KEYDOWN, key=p.K_g))
        self.gc.draw()
        export = next(b for b in self.gc.overlay.buttons if b.action == "export")
        self.assertFalse(export.enabled)
        self.gc.handle_event(_event(p.KEYDOWN, key=p.K_e))
        self.assertIsInstance(self.gc.overlay, app.ReviewOverlay)

    def test_progress_is_drawn_while_the_review_runs(self):
        self.gc.reviewer = review.Reviewer(process=_IdleProcess, make_queue=queue.Queue)
        self._play(["e4"])
        self.gc.handle_event(_event(p.KEYDOWN, key=p.K_g))
        self.gc.update()
        self.gc.draw()
        self.assertEqual(self.gc._move_rows()[0].white, ("e4", 1))

    def test_a_new_move_makes_the_review_stale(self):
        self._play(["f3", "e5", "g4"])
        self.gc.handle_event(_event(p.KEYDOWN, key=p.K_g))
        self.gc.update()
        self.assertEqual(self.gc._move_rows()[1].white, ("g4??", 3))
        self.gc.overlay = None
        self._undo_and_update()
        self.assertEqual(
            [(r.white, r.black) for r in self.gc._move_rows()], [(("f3", 1), ("e5", 2))]
        )
        self.assertIsNone(self.gc.reviewer.key)

    def _undo_and_update(self):
        self.gc._undo()
        self.gc.update()


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class OverlayTests(unittest.TestCase):
    def test_appearance_changes_are_applied_and_reported(self):
        gc = _controller()
        changes: list[Settings] = []
        gc.on_settings_change = changes.append
        gc.handle_event(_event(p.KEYDOWN, key=p.K_c))
        gc.draw()
        button = next(b for b in gc.overlay.buttons if b.action == ("setting", "board", "Noyer"))
        gc.handle_event(_event(p.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
        self.assertEqual(gc.settings.board, "Noyer")
        self.assertEqual(gc.renderer.palette.name, "Noyer")
        self.assertEqual(changes[-1].board, "Noyer")
        gc._run_action(("setting", "show_eval", False))
        self.assertIsNone(gc.layout.eval_bar)

    def test_end_of_game_card_offers_a_new_game_and_a_review(self):
        gc = _controller()
        gc._new_game(load_fen("R5k1/5ppp/8/8/8/8/8/6K1 b - - 0 1"))
        gc.update()
        self.assertIsInstance(gc.overlay, app.EndGameOverlay)
        self.assertEqual(gc.overlay.title, "Victoire des blancs")
        gc.handle_event(_event(p.KEYDOWN, key=p.K_ESCAPE))  # revoir la partie
        gc.update()
        self.assertIsNone(gc.overlay)  # ne se rouvre pas d'elle-même
        gc._run_action("rematch")
        self.assertFalse(gc.game_over)
        self.assertEqual(gc.game_state.board, engine.GameState().board)

    def test_end_card_grows_with_a_long_reason(self):
        # Motif sur deux lignes : les boutons restent dans la carte, sous le texte.
        short = app.EndGameOverlay("Partie nulle", "Pat", None, PIECES)
        long = app.EndGameOverlay(
            "Victoire des blancs",
            "Les Blancs gagnent par échec et mat · 1-0 · 17 coups, après une très longue partie",
            "wK",
            PIECES,
        )
        surface = p.display.get_surface()
        heights = []
        for overlay in (short, long):
            overlay.draw(surface, app.th.theme("sombre"), (0, 0), 0)
            for button in overlay.buttons:
                self.assertTrue(overlay.card.contains(button.rect), button.label)
            heights.append(overlay.card.height)
        self.assertGreater(heights[1], heights[0])

    def test_human_defeat_against_the_ai(self):
        gc = _controller("PvC", True, False)
        gc._resign()
        gc.update()
        self.assertEqual(gc.overlay.title, "Défaite")

    def test_every_screen_draws_in_both_themes(self):
        for theme in ("sombre", "clair"):
            with self.subTest(theme=theme):
                gc = _controller(
                    settings=Settings(theme=theme), flip=True, time_control=clock.BLITZ_3_2
                )
                gc.game_state.make_move(notation.parse_san(gc.game_state, "e4"))
                gc.move_made = gc.animate = True
                gc.update()
                gc.arrows.add(((1, 4), (3, 4)))
                gc.marks.add((4, 4))
                gc.square_selected = (1, 3)
                gc.draw()
                for key in (p.K_h, p.K_c, p.K_a):
                    gc.handle_event(_event(p.KEYDOWN, key=key))
                    gc.draw()
                    gc.handle_event(_event(p.KEYDOWN, key=p.K_ESCAPE))
                gc._resign()
                gc.update()
                gc.draw()

    def test_icons_render(self):
        for name in widgets.ICONS:
            with self.subTest(icon=name):
                image = widgets.icon(name, 20, (255, 255, 255))
                self.assertEqual(image.get_size(), (20, 20))
                self.assertGreater(_opaque_pixels(image), 0)

    def test_discs_render(self):
        disc = widgets._disc((255, 255, 255, 255), 10, 0)
        self.assertGreater(_opaque_pixels(disc), 0)

    def test_smoothscale_keeps_the_image_whatever_the_native_filter(self):
        # Sous Windows, les filtres MMX / SSE de pygame rendaient pièces et icônes
        # invisibles : widgets.smoothscale doit donner la même image quel que soit le
        # filtre choisi auparavant.
        source = p.Surface((80, 80), p.SRCALPHA)
        source.fill((200, 30, 30, 255))
        for backend in ("GENERIC", "MMX", "SSE"):
            with self.subTest(backend=backend):
                try:
                    p.transform.set_smoothscale_backend(backend)
                except ValueError:
                    continue  # filtre absent sur cette machine
                image = widgets.smoothscale(source, (20, 20))
                self.assertEqual(tuple(image.get_at((10, 10))), (200, 30, 30, 255))


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class PieceSetTests(unittest.TestCase):
    def test_vector_pieces_are_rendered_at_the_requested_size(self):
        for size in (24, 77, 120):
            image = PIECES.get_image("bQ", size)
            self.assertEqual(image.get_size(), (size, size))
            self.assertGreater(_opaque_pixels(image), size * size // 10)

    def test_transparent_svg_falls_back_to_the_png_images(self):
        # Constaté sur la CI Windows : le SVG est chargé à la bonne taille, mais sans
        # aucun pixel visible. La pièce doit rester visible (image PNG).
        real_load = p.image.load

        def load(source, namehint=""):
            if namehint == "piece.svg":
                return p.Surface((60, 60), p.SRCALPHA)
            return real_load(source)

        with (
            mock.patch("chessproject.ui.board_view.p.image.load", side_effect=load),
            self.assertLogs("chessproject.ui.board_view", "WARNING") as logs,
        ):
            pieces = PieceSet()
            image = pieces.get_image("wK", 60)
            other = pieces.get_image("bQ", 40)
        self.assertGreater(_opaque_pixels(image), 60 * 60 // 10)
        self.assertGreater(_opaque_pixels(other), 40 * 40 // 10)
        self.assertEqual(len(logs.output), 1)  # un seul avertissement
        self.assertIn("transparente", logs.output[0])

    def test_falls_back_to_the_png_images(self):
        pieces = PieceSet(pieces_dir=Path("/inexistant"))
        with self.assertLogs("chessproject.ui.board_view", "WARNING"):
            image = pieces.get_image("wK", 50)
        self.assertEqual(image.get_size(), (50, 50))
        self.assertGreater(_opaque_pixels(image), 50 * 50 // 10)


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class AppSceneTests(unittest.TestCase):
    """J5.1 : écran « Nouvelle partie » -> partie -> « Nouvelle partie » -> retour."""

    def setUp(self):
        self.data = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {"CHESSPROJECT_DATA_DIR": self.data.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.data.cleanup)
        self.screen = p.display.set_mode((1280, 800))
        self.app = app.App(self.screen, Settings(mode="PvP", time_control="300"), PIECES)

    def _key(self, key):
        self.app.handle_event(_event(p.KEYDOWN, key=key))

    def _game(self) -> app.GameController:
        assert isinstance(self.app.scene, app.GameController)
        return self.app.scene

    def _menu(self) -> NewGameMenu:
        assert isinstance(self.app.scene, NewGameMenu)
        return self.app.scene

    def test_start_open_menu_and_come_back(self):
        self.assertIsInstance(self.app.scene, NewGameMenu)
        self.app.step()
        self._key(p.K_RETURN)
        game = self._game()
        self.assertIsInstance(game, app.GameController)
        self.assertEqual(game.mode, "PvP")
        self.assertEqual(game.time_control, clock.BLITZ_5_0)
        self.assertEqual(settings_module.load().mode, "PvP")  # choix mémorisés
        self.app.step()

        game._run_action("new_game")
        self.app.handle_event(_event(p.MOUSEMOTION, pos=(1, 1), rel=(0, 0), buttons=(0, 0, 0)))
        self.assertIsInstance(self.app.scene, NewGameMenu)
        self.assertTrue(game.suspended)
        self.assertTrue(game.chess_clock.is_paused)
        self.app.step()
        self._key(p.K_ESCAPE)
        self.assertIs(self.app.scene, game)
        self.assertFalse(game.suspended)

    def test_new_game_from_the_menu_reuses_the_game_scene(self):
        self._key(p.K_RETURN)
        game = self._game()
        game.game_state.make_move(notation.parse_san(game.game_state, "e4"))
        self.app.open_new_game()
        self._menu().choose("mode", "PvC")
        self._menu().choose("color", "b")
        with mock.patch.object(app.GameController, "update_ai"):
            self._key(p.K_RETURN)
            self.assertIs(self.app.scene, game)
            self.assertEqual(game.game_state.move_log, [])
            self.assertTrue(game.flip_board)
            self.assertEqual((game.player_one, game.player_two), (False, True))

    def test_window_resize_updates_the_layout(self):
        self._key(p.K_RETURN)
        game = self._game()
        self.app.handle_event(_event(p.VIDEORESIZE, w=1600, h=1000, size=(1600, 1000)))
        self.screen = p.display.set_mode((1600, 1000))
        self.app.handle_event(_event(p.VIDEORESIZE, w=1600, h=1000, size=(1600, 1000)))
        self.assertEqual(game.layout.width, 1600)
        self.assertEqual(game.renderer.board_rect, game.layout.board)
        self.app.step()

    def test_load_from_the_menu_without_a_save_shows_a_notice(self):
        self._key(p.K_l)
        game = self._game()
        assert game.notice is not None
        self.assertEqual(game.notice[0], "Aucune sauvegarde à charger")

    def test_config_flip(self):
        self.assertTrue(GameConfig("PvC", False, True, "Moyen", clock.UNLIMITED).flip_board)
        self.assertFalse(GameConfig("PvP", True, True, "Moyen", clock.UNLIMITED).flip_board)


if __name__ == "__main__":
    unittest.main()
