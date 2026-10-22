"""Tests de régression pour la boucle de jeu (``app.GameController``).

Vérifie notamment que l'IA reçoit toujours la liste des coups légaux de la
position courante après le coup de l'humain — un décalage d'une itération
faisait auparavant planter la partie avec « Mouvement non valide » dès le
premier coup en mode Joueur (blancs) vs IA.
"""

import os
import queue
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as p

try:
    p.init()
    p.display.set_mode((900, 512))
    _PYGAME_OK = True
except Exception:  # pragma: no cover - environnement sans SDL
    _PYGAME_OK = False

from chessproject import serialization
from chessproject.ai import levels
from chessproject.core import clock, engine, notation
from chessproject.core.fen import load_fen
from chessproject.ui import app


class _InlineProcess:
    """Faux multiprocessing.Process : exécute la cible immédiatement."""

    def __init__(self, target, args=(), **kwargs):
        self._target, self._args = target, args
        self.kwargs = kwargs
        self._ran = False
        self.exitcode = None

    def start(self):
        self._target(*self._args)
        self._ran = True
        self.exitcode = 0

    def is_alive(self):
        return not self._ran

    def terminate(self):
        self._ran = True


class _SyncQueue:
    def __init__(self):
        self._q: queue.Queue[object] = queue.Queue()

    def put(self, x):
        self._q.put(x)

    def get(self, block=True, timeout=None):
        # Ne bloque jamais : un appel bloquant ferait pendre le test au lieu d'échouer.
        return self._q.get_nowait()


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class AITurnAfterHumanMove(unittest.TestCase):
    def setUp(self):
        self.screen = p.display.get_surface()
        self.clock = p.time.Clock()
        ui = app.UIManager(512, 512, 250, 512)
        rm = app.ResourceManager(64)
        # Humain = blancs, IA = noirs, plateau non retourné.
        self.gc = app.GameController(self.screen, self.clock, ui, rm, "PvC", True, False, False)
        self._orig_process = app.Process
        self._orig_queue = app.Queue
        # Monkeypatch volontaire de doublures (duck typing) : mypy refuse de
        # réaffecter une classe importée, d'où ces ignores ciblés.
        app.Process = _InlineProcess  # type: ignore[misc, assignment]
        app.Queue = _SyncQueue  # type: ignore[misc, assignment]

    def tearDown(self):
        app.Process = self._orig_process  # type: ignore[misc]  # restauration du monkeypatch
        app.Queue = self._orig_queue  # type: ignore[misc]  # restauration du monkeypatch

    def _click_square(self, row, col):
        pos = self.gc.renderer.square_rect(row, col).center
        self.gc.handle_event(p.event.Event(p.MOUSEBUTTONDOWN, {"pos": pos, "button": 1}))

    def test_ai_replies_with_legal_move_after_first_white_move(self):
        self._click_square(6, 4)  # e2
        self._click_square(4, 4)  # e4
        self.assertTrue(self.gc.move_made)
        self.assertEqual(len(self.gc.game_state.move_log), 1)

        # `valid_moves` volontairement laissé périmé (liste des coups blancs) et
        # `move_made` encore vrai : update_ai doit repartir de la position
        # courante et non de cette liste.
        stale = list(self.gc.valid_moves)

        self.gc.update_ai()  # ne doit pas lever « Mouvement non valide »
        self.assertTrue(stale)  # la liste périmée existait bien

        self.assertEqual(len(self.gc.game_state.move_log), 2)
        ai_move = self.gc.game_state.move_log[-1]
        self.assertEqual(ai_move.piece_moved[0], "b")


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class NewGameWhenAIToMove(unittest.TestCase):
    """B28 : après R (réinitialiser) ou L (charger), l'IA doit jouer si elle a le trait."""

    def setUp(self):
        self._orig = (app.Process, app.Queue)
        app.Process = _InlineProcess  # type: ignore[misc, assignment]
        app.Queue = _SyncQueue  # type: ignore[misc, assignment]

    def tearDown(self):
        app.Process, app.Queue = self._orig  # type: ignore[misc]

    def _controller(self, mode, white_human, black_human):
        ui = app.UIManager(512, 512, 250, 512)
        rm = app.ResourceManager(64)
        flip = mode == "PvC" and not white_human
        return app.GameController(
            p.display.get_surface(), p.time.Clock(), ui, rm, mode, white_human, black_human, flip
        )

    def _frames(self, gc, n=3):
        for _ in range(n):
            gc.animate = False  # pas d'animation dans les tests
            gc.update()

    def _press(self, gc, key):
        gc.handle_event(p.event.Event(p.KEYDOWN, {"key": key}))

    def test_reset_with_ai_playing_white(self):
        gc = self._controller("PvC", False, True)
        self._frames(gc)
        self.assertEqual(len(gc.game_state.move_log), 1)
        self._press(gc, p.K_r)
        self._frames(gc)
        self.assertEqual(len(gc.game_state.move_log), 1, "l'IA doit rejouer après R")
        self.assertFalse(gc.game_state.white_to_move)

    def test_reset_in_ai_vs_ai(self):
        gc = self._controller("CvC", False, False)
        self._frames(gc, 2)
        self._press(gc, p.K_r)
        self._frames(gc, 4)
        self.assertGreaterEqual(len(gc.game_state.move_log), 2, "la partie IA/IA doit reprendre")

    def test_load_with_ai_to_move(self):
        gc = self._controller("PvC", True, False)
        # Partie chargée où les noirs (IA) ont le trait.
        loaded = engine.GameState()
        loaded.make_move([m for m in loaded.get_valid_moves() if str(m) == "e4"][0])
        gc._new_game(loaded)
        self._frames(gc)
        self.assertEqual(len(gc.game_state.move_log), 2, "l'IA doit jouer après L")


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class PromotionThroughTheUI(unittest.TestCase):
    """B29 / B40 : le choix du popup doit être le coup joué, enregistré et sauvegardé."""

    FEN = "7k/P7/8/8/8/8/8/K7 w - - 0 1"

    def setUp(self):
        ui = app.UIManager(512, 512, 250, 512)
        rm = app.ResourceManager(64)
        self.gc = app.GameController(
            p.display.get_surface(), p.time.Clock(), ui, rm, "PvP", True, True, False
        )
        self.gc._new_game(load_fen(self.FEN))

    def _click_pos(self, pos):
        self.gc.handle_event(p.event.Event(p.MOUSEBUTTONDOWN, {"pos": pos, "button": 1}))

    def _click_square(self, row, col):
        self._click_pos(self.gc.renderer.square_rect(row, col).center)

    def _open_popup(self):
        self._click_square(1, 0)  # a7
        self._click_square(0, 0)  # a8
        self.assertIsNotNone(self.gc.promotion_popup)

    def _choose(self, piece):
        assert self.gc.promotion_popup is not None
        btn = next(b for b in self.gc.promotion_popup.buttons if b.text == piece)
        self._click_pos(btn.rect.center)

    def test_knight_promotion_is_recorded_and_saved(self):
        self._open_popup()
        self._choose("N")
        gs = self.gc.game_state
        self.assertEqual(gs.board[0][0], "wN")
        self.assertEqual(gs.move_log[-1].promotion_piece, "N")
        self.assertEqual(str(gs.move_log[-1]), "a8=N")

        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            serialization.save_game(gs, filename=path, start_fen=self.FEN)
            loaded, _ = serialization.load_game(path)
        finally:
            os.remove(path)
        self.assertEqual(loaded.board[0][0], "wN")

    def test_escape_cancels_the_promotion(self):
        self._open_popup()
        self.gc.handle_event(p.event.Event(p.KEYDOWN, {"key": p.K_ESCAPE}))
        self.assertIsNone(self.gc.promotion_popup)
        self.assertEqual(self.gc.game_state.move_log, [])
        self.assertEqual(self.gc.game_state.board[1][0], "wp")

    def test_click_outside_the_popup_cancels_the_promotion(self):
        self._open_popup()
        self._click_pos((5, 5))  # panneau de gauche, hors du popup
        self.assertIsNone(self.gc.promotion_popup)
        self.assertEqual(self.gc.game_state.move_log, [])


class _CrashingProcess(_InlineProcess):
    """Processus d'IA mort sans rien écrire dans la file (exception dans l'enfant)."""

    def start(self):
        self._ran = True
        self.exitcode = 1


class _HangingProcess(_InlineProcess):
    """Processus d'IA qui ne rend jamais la main."""

    instances: list["_HangingProcess"] = []

    def start(self):
        _HangingProcess.instances.append(self)
        self.terminated = False

    def is_alive(self):
        return not self.terminated

    def terminate(self):
        self.terminated = True


class _IllegalMoveProcess(_InlineProcess):
    def start(self):
        # Coup légal dans la position initiale mais pas pour les Noirs : e2-e4.
        self._args[2].put(engine.Move((6, 4), (4, 4), engine.GameState().board))
        self._ran = True
        self.exitcode = 0


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class AIProcessRobustness(unittest.TestCase):
    """B33 / B45 : un processus d'IA défaillant ne doit ni figer ni bloquer l'UI."""

    def setUp(self):
        self._orig = (app.Process, app.Queue)
        app.Queue = _SyncQueue  # type: ignore[misc, assignment]
        ui = app.UIManager(512, 512, 250, 512)
        rm = app.ResourceManager(64)
        # Humain = blancs ; on joue e4 pour donner le trait à l'IA.
        self.gc = app.GameController(
            p.display.get_surface(), p.time.Clock(), ui, rm, "PvC", True, False, False
        )
        gs = self.gc.game_state
        gs.make_move([m for m in gs.get_valid_moves() if str(m) == "e4"][0])
        self.gc.valid_moves = gs.get_valid_moves()

    def tearDown(self):
        app.Process, app.Queue = self._orig  # type: ignore[misc]

    def _use(self, process_cls):
        app.Process = process_cls  # type: ignore[misc]

    def _assert_black_played_a_legal_move(self):
        gs = self.gc.game_state
        self.assertEqual(len(gs.move_log), 2)
        self.assertEqual(gs.move_log[-1].piece_moved[0], "b")
        self.assertFalse(self.gc.ai_thinking)

    def test_crashed_ai_process_falls_back_to_a_legal_move(self):
        self._use(_CrashingProcess)
        self.gc.update_ai()
        self._assert_black_played_a_legal_move()

    def test_illegal_ai_move_is_replaced_by_a_legal_one(self):
        self._use(_IllegalMoveProcess)
        self.gc.update_ai()
        self._assert_black_played_a_legal_move()

    def test_ai_process_is_a_daemon(self):
        self._use(_HangingProcess)
        self.gc.update_ai()
        self.assertTrue(_HangingProcess.instances[-1].kwargs.get("daemon"))

    def test_ai_exceeding_its_time_limit_is_stopped(self):
        self._use(_HangingProcess)
        self.gc.update_ai()
        self.assertTrue(self.gc.ai_thinking)
        self.gc.ai_started_at -= app.AI_MAX_THINK_SECONDS + 1
        self.gc.update_ai()
        self.assertTrue(_HangingProcess.instances[-1].terminated)
        self._assert_black_played_a_legal_move()

    def test_quitting_while_the_ai_thinks_stops_it(self):
        self._use(_HangingProcess)
        self.gc.update_ai()
        with mock.patch.object(app.p, "quit"), self.assertRaises(SystemExit):
            self.gc.handle_event(p.event.Event(p.QUIT, {}))
        self.assertTrue(_HangingProcess.instances[-1].terminated)


class _FakeClock:
    """Horloge en millisecondes, avancée à la main."""

    def __init__(self):
        self.ms = 0

    def __call__(self):
        return self.ms


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class ClockIgnoresMenusAndAnimation(unittest.TestCase):
    """B44 : le temps passé dans un menu ou une animation n'est pas décompté."""

    def setUp(self):
        self.now = _FakeClock()
        self.ui = app.UIManager(512, 512, 250, 512, now=self.now)
        self.gc = app.GameController(
            p.display.get_surface(),
            p.time.Clock(),
            self.ui,
            app.ResourceManager(64),
            "PvP",
            True,
            True,
            False,
        )

    def test_normal_time_is_counted(self):
        self.now.ms += 3000
        self.ui.update_timer(white_to_move=True)
        self.assertAlmostEqual(self.ui.white_time, 3.0)

    def _ten_seconds_in_a_menu(self, *args):
        self.now.ms += 10_000

    def test_time_in_colour_menu_is_not_counted(self):
        with mock.patch.object(app, "customization_menu", self._ten_seconds_in_a_menu):
            self.gc.handle_event(p.event.Event(p.KEYDOWN, {"key": p.K_c}))
        self.now.ms += 1000
        self.ui.update_timer(white_to_move=True)
        self.assertAlmostEqual(self.ui.white_time, 1.0)

    def test_time_in_shortcuts_menu_is_not_counted(self):
        with mock.patch.object(app, "show_shortcuts_menu", self._ten_seconds_in_a_menu):
            self.gc.handle_event(p.event.Event(p.KEYDOWN, {"key": p.K_h}))
        self.ui.update_timer(white_to_move=True)
        self.assertAlmostEqual(self.ui.white_time, 0.0)

    def test_time_during_move_animation_is_not_counted(self):
        gs = self.gc.game_state
        gs.make_move([m for m in gs.get_valid_moves() if str(m) == "e4"][0])
        self.gc.move_made = self.gc.animate = True
        with mock.patch.object(
            self.gc.renderer, "animate_move", lambda *a: self._ten_seconds_in_a_menu()
        ):
            self.gc.update()
        self.ui.update_timer(white_to_move=False)
        self.assertAlmostEqual(self.ui.black_time, 0.0)


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class EndOfGameDisplay(unittest.TestCase):
    """J2.2 / B34 : le motif de fin est affiché et la partie est verrouillée."""

    def _controller(self, fen):
        gc = app.GameController(
            p.display.get_surface(),
            p.time.Clock(),
            app.UIManager(512, 512, 250, 512),
            app.ResourceManager(64),
            "PvP",
            True,
            True,
            False,
        )
        gc._new_game(load_fen(fen))
        return gc

    def _end_text(self, gc):
        with mock.patch.object(gc.renderer, "draw_end_game_text") as draw_text:
            gc.draw()
        return draw_text.call_args.args[0] if draw_text.called else None

    def test_draw_reason_is_displayed(self):
        gc = self._controller("8/8/4k3/8/8/3NK3/8/8 w - - 0 1")
        self.assertTrue(gc.game_over)
        self.assertEqual(self._end_text(gc), "Nulle par matériel insuffisant")

    def test_checkmate_winner_is_displayed(self):
        gc = self._controller("R5k1/5ppp/8/8/8/8/8/6K1 b - - 0 1")
        self.assertEqual(self._end_text(gc), "Les Blancs gagnent par échec et mat")

    def test_ongoing_game_shows_no_end_text(self):
        gc = self._controller("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        self.assertFalse(gc.game_over)
        self.assertIsNone(self._end_text(gc))

    def test_undo_after_mate_reopens_the_game(self):
        gc = self._controller("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
        gs = gc.game_state
        gs.make_move(next(m for m in gs.get_valid_moves() if (m.end_row, m.end_col) == (0, 0)))
        self.assertTrue(gc.game_over)
        gc.handle_event(p.event.Event(p.KEYDOWN, {"key": p.K_z}))
        self.assertFalse(gc.game_over)


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class ResignAndDrawOffers(unittest.TestCase):
    """J4.6 : abandon (A) et proposition de nulle (N)."""

    def _controller(self, mode, white_human, black_human):
        return app.GameController(
            p.display.get_surface(),
            p.time.Clock(),
            app.UIManager(512, 512, 250, 512),
            app.ResourceManager(64),
            mode,
            white_human,
            black_human,
            mode == "PvC" and not white_human,
        )

    def _press(self, gc, key):
        gc.handle_event(p.event.Event(p.KEYDOWN, {"key": key}))

    def test_human_resigns_against_the_ai(self):
        gc = self._controller("PvC", False, True)  # humain = Noirs
        self._press(gc, p.K_a)
        self.assertTrue(gc.game_over)
        self.assertEqual(
            gc.result, engine.GameResult(engine.Termination.RESIGNATION, engine.Color.WHITE)
        )

    def test_side_to_move_resigns_in_pvp(self):
        gc = self._controller("PvP", True, True)
        self._press(gc, p.K_a)
        self.assertEqual(gc.result.winner, engine.Color.BLACK)

    def test_undo_cancels_a_resignation(self):
        gc = self._controller("PvP", True, True)
        gc.game_state.make_move(gc.game_state.get_valid_moves()[0])
        self._press(gc, p.K_a)
        self.assertTrue(gc.game_over)
        self._press(gc, p.K_z)
        self.assertFalse(gc.game_over)

    def test_ai_accepts_a_draw_only_when_it_is_not_better(self):
        gc = self._controller("PvC", True, False)
        with mock.patch.object(app, "ai_accepts_draw", return_value=False):
            self._press(gc, p.K_n)
        self.assertFalse(gc.game_over)
        with mock.patch.object(app, "ai_accepts_draw", return_value=True):
            self._press(gc, p.K_n)
        self.assertEqual(gc.result, engine.GameResult(engine.Termination.DRAW_AGREEMENT))

    def test_ai_draw_decision_follows_the_evaluation(self):
        # Les Noirs (IA) ont une dame de plus : refus ; une dame de moins : acceptation.
        black_better = load_fen("q3k3/8/8/8/8/8/8/4K3 w - - 0 1")
        white_better = load_fen("4k3/8/8/8/8/8/8/Q3K3 w - - 0 1")
        self.assertFalse(app.ai_accepts_draw(black_better, ai_is_white=False))
        self.assertTrue(app.ai_accepts_draw(white_better, ai_is_white=False))

    def test_draw_agreement_in_pvp_needs_the_opponent(self):
        gc = self._controller("PvP", True, True)
        self._press(gc, p.K_n)  # les Blancs proposent
        self.assertFalse(gc.game_over)
        self._press(gc, p.K_n)  # même camp : sans effet
        self.assertFalse(gc.game_over)
        gc.game_state.make_move(next(m for m in gc.game_state.get_valid_moves() if str(m) == "e4"))
        self._press(gc, p.K_n)  # les Noirs acceptent
        self.assertEqual(gc.result.termination, engine.Termination.DRAW_AGREEMENT)

    def test_a_move_declines_a_pending_offer(self):
        gc = self._controller("PvP", True, True)
        self._press(gc, p.K_n)  # les Blancs proposent
        gc.game_state.make_move(next(m for m in gc.game_state.get_valid_moves() if str(m) == "e4"))
        gc.game_state.make_move(next(m for m in gc.game_state.get_valid_moves() if str(m) == "e5"))
        self._press(gc, p.K_n)  # nouvelle proposition des Blancs, pas une acceptation
        self.assertFalse(gc.game_over)


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class SaveRestoresTheGameContext(unittest.TestCase):
    """J4.5 / B37 : L restaure le mode, la couleur de l'humain, le niveau et la fin."""

    def test_load_restores_mode_colour_level_and_result(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            gc = app.GameController(
                p.display.get_surface(),
                p.time.Clock(),
                app.UIManager(512, 512, 250, 512),
                app.ResourceManager(64),
                "PvC",
                False,
                True,
                True,
            )
            gc.ai_level = "Facile"
            gc.external_result = engine.GameResult(
                engine.Termination.RESIGNATION, engine.Color.WHITE
            )
            with mock.patch.object(app.paths, "save_file", return_value=path):
                gc.handle_event(p.event.Event(p.KEYDOWN, {"key": p.K_s}))
            other = app.GameController(
                p.display.get_surface(),
                p.time.Clock(),
                app.UIManager(512, 512, 250, 512),
                app.ResourceManager(64),
                "PvP",
                True,
                True,
                False,
            )
            with mock.patch.object(app.paths, "existing_save_file", return_value=path):
                other.handle_event(p.event.Event(p.KEYDOWN, {"key": p.K_l}))
            self.assertEqual((other.mode, other.player_one, other.player_two), ("PvC", False, True))
            self.assertEqual(other.ai_level, "Facile")
            self.assertTrue(other.flip_board)
            self.assertEqual(other.result.termination, engine.Termination.RESIGNATION)
        finally:
            os.remove(path)


class _Seconds:
    """Source de temps en secondes (comme time.monotonic), avancée à la main."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class ClockInTheGame(unittest.TestCase):
    """J4.1 / J4.2 / J4.6 : pendule à cadence dans la partie."""

    def _controller(self, control, mode="PvP", white=True, black=True):
        self.now = _Seconds()
        return app.GameController(
            p.display.get_surface(),
            p.time.Clock(),
            app.UIManager(512, 512, 250, 512),
            app.ResourceManager(64),
            mode,
            white,
            black,
            False,
            time_control=control,
            clock_now=self.now,
        )

    def _play(self, gc, san):
        gc.game_state.make_move(notation.parse_san(gc.game_state, san))
        gc.move_made = True
        gc.animate = False
        gc.update()

    def test_moves_press_the_clock_and_credit_the_increment(self):
        gc = self._controller(clock.TimeControl.from_minutes(3, 2))
        self.now.t += 10
        self._play(gc, "e4")
        self.assertEqual(gc.chess_clock.remaining_ms(engine.Color.WHITE), 180_000 - 10_000 + 2_000)
        self.now.t += 5
        self.assertEqual(gc.chess_clock.remaining_ms(engine.Color.BLACK), 175_000)

    def test_flag_fall_ends_the_game(self):
        gc = self._controller(clock.TimeControl.from_minutes(1))
        self.now.t += 61
        gc.update()
        self.assertEqual(
            gc.result, engine.GameResult(engine.Termination.TIME_FORFEIT, engine.Color.BLACK)
        )

    def test_undo_restores_the_clock(self):
        gc = self._controller(clock.TimeControl.from_minutes(3, 2))
        self.now.t += 10
        self._play(gc, "e4")
        gc.handle_event(p.event.Event(p.KEYDOWN, {"key": p.K_z}))
        gc.update()
        self.assertEqual(gc.chess_clock.remaining_ms(engine.Color.WHITE), 180_000)
        self.assertEqual(gc.chess_clock.turn, engine.Color.WHITE)

    def test_clock_is_paused_in_menus(self):
        gc = self._controller(clock.TimeControl.from_minutes(3))

        def ten_minutes(*args):
            self.now.t += 600

        with mock.patch.object(app, "show_shortcuts_menu", ten_minutes):
            gc.handle_event(p.event.Event(p.KEYDOWN, {"key": p.K_h}))
        gc.update()
        self.assertEqual(gc.chess_clock.remaining_ms(engine.Color.WHITE), 180_000)
        self.assertFalse(gc.game_over)

    def test_ai_think_time_is_capped_by_its_clock(self):
        gc = self._controller(clock.TimeControl.from_minutes(1), "PvC", True, False)
        captured = {}

        class Recorder(_InlineProcess):
            def __init__(self, target, args=(), **kwargs):
                captured["args"] = args
                super().__init__(target, args, **kwargs)

        with (
            mock.patch.object(app, "Process", Recorder),
            mock.patch.object(app, "Queue", _SyncQueue),
        ):
            self._play(gc, "e4")  # update() lance l'IA, qui a le trait
        movetime = captured["args"][4]
        level = levels.LEVELS_BY_NAME[gc.ai_level]
        self.assertLessEqual(movetime, level.movetime_ms)
        self.assertLessEqual(movetime, 60_000 // 3)

    def test_measured_overhead_is_taken_off_the_think_time(self):
        gc = self._controller(clock.TimeControl.from_minutes(1), "PvC", True, False)
        gc.game_state.make_move(notation.parse_san(gc.game_state, "e4"))
        gc.ai_overhead_ms = 0.0
        without = gc._ai_think_time_ms()
        gc.ai_overhead_ms = 400.0
        self.assertEqual(gc._ai_think_time_ms(), max(10, without - 400))
        # Mesure : 900 ms réels pour 500 ms demandés -> surcoût observé 400 ms.
        gc.ai_overhead_ms = 0.0
        gc._ai_requested_ms = 500
        with mock.patch.object(app.time, "monotonic", return_value=gc.ai_started_at + 0.9):
            gc._measure_ai_overhead()
        self.assertAlmostEqual(gc.ai_overhead_ms, app.AI_OVERHEAD_SMOOTHING * 400, places=3)

    def test_unlimited_games_never_flag(self):
        gc = self._controller(clock.UNLIMITED)
        self.now.t += 10_000
        gc.update()
        self.assertFalse(gc.game_over)
        self.assertIsNone(gc.chess_clock.remaining_ms(engine.Color.WHITE))

    def test_clock_is_saved_and_restored(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            gc = self._controller(clock.TimeControl.from_minutes(3, 2))
            self.now.t += 10
            self._play(gc, "e4")
            with mock.patch.object(app.paths, "save_file", return_value=path):
                gc.handle_event(p.event.Event(p.KEYDOWN, {"key": p.K_s}))
            other = self._controller(clock.UNLIMITED)
            with mock.patch.object(app.paths, "existing_save_file", return_value=path):
                other.handle_event(p.event.Event(p.KEYDOWN, {"key": p.K_l}))
            self.assertEqual(other.chess_clock.remaining_ms(engine.Color.WHITE), 172_000)
            self.assertEqual(other.time_control, clock.TimeControl.from_minutes(3, 2))
            # Un coup après le chargement est bien décompté (pendule synchronisée).
            self.now.t += 3
            self._play(other, "e5")
            self.assertEqual(other.chess_clock.remaining_ms(engine.Color.BLACK), 177_000 + 2_000)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
