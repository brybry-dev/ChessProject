"""Tests de régression pour la boucle de jeu (``ChessMain.GameController``).

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

import ChessEngine
import ChessMain
import serialization
from fen_utils import load_fen


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
        ui = ChessMain.UIManager(512, 512, 250, 512)
        rm = ChessMain.ResourceManager(64)
        # Humain = blancs, IA = noirs, plateau non retourné.
        self.gc = ChessMain.GameController(
            self.screen, self.clock, ui, rm, "PvC", True, False, False
        )
        self._orig_process = ChessMain.Process
        self._orig_queue = ChessMain.Queue
        # Monkeypatch volontaire de doublures (duck typing) : mypy refuse de
        # réaffecter une classe importée, d'où ces ignores ciblés.
        ChessMain.Process = _InlineProcess  # type: ignore[misc, assignment]
        ChessMain.Queue = _SyncQueue  # type: ignore[misc, assignment]

    def tearDown(self):
        ChessMain.Process = self._orig_process  # type: ignore[misc]  # restauration du monkeypatch
        ChessMain.Queue = self._orig_queue  # type: ignore[misc]  # restauration du monkeypatch

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
        self._orig = (ChessMain.Process, ChessMain.Queue)
        ChessMain.Process = _InlineProcess  # type: ignore[misc, assignment]
        ChessMain.Queue = _SyncQueue  # type: ignore[misc, assignment]

    def tearDown(self):
        ChessMain.Process, ChessMain.Queue = self._orig  # type: ignore[misc]

    def _controller(self, mode, white_human, black_human):
        ui = ChessMain.UIManager(512, 512, 250, 512)
        rm = ChessMain.ResourceManager(64)
        flip = mode == "PvC" and not white_human
        return ChessMain.GameController(
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
        loaded = ChessEngine.GameState()
        loaded.makeMove([m for m in loaded.getValidMoves() if str(m) == "e4"][0])
        gc._new_game(loaded)
        self._frames(gc)
        self.assertEqual(len(gc.game_state.move_log), 2, "l'IA doit jouer après L")


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class PromotionThroughTheUI(unittest.TestCase):
    """B29 / B40 : le choix du popup doit être le coup joué, enregistré et sauvegardé."""

    FEN = "7k/P7/8/8/8/8/8/K7 w - - 0 1"

    def setUp(self):
        ui = ChessMain.UIManager(512, 512, 250, 512)
        rm = ChessMain.ResourceManager(64)
        self.gc = ChessMain.GameController(
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
        self._args[2].put(ChessEngine.Move((6, 4), (4, 4), ChessEngine.GameState().board))
        self._ran = True
        self.exitcode = 0


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class AIProcessRobustness(unittest.TestCase):
    """B33 / B45 : un processus d'IA défaillant ne doit ni figer ni bloquer l'UI."""

    def setUp(self):
        self._orig = (ChessMain.Process, ChessMain.Queue)
        ChessMain.Queue = _SyncQueue  # type: ignore[misc, assignment]
        ui = ChessMain.UIManager(512, 512, 250, 512)
        rm = ChessMain.ResourceManager(64)
        # Humain = blancs ; on joue e4 pour donner le trait à l'IA.
        self.gc = ChessMain.GameController(
            p.display.get_surface(), p.time.Clock(), ui, rm, "PvC", True, False, False
        )
        gs = self.gc.game_state
        gs.makeMove([m for m in gs.getValidMoves() if str(m) == "e4"][0])
        self.gc.valid_moves = gs.getValidMoves()

    def tearDown(self):
        ChessMain.Process, ChessMain.Queue = self._orig  # type: ignore[misc]

    def _use(self, process_cls):
        ChessMain.Process = process_cls  # type: ignore[misc]

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
        self.gc.ai_started_at -= ChessMain.AI_MAX_THINK_SECONDS + 1
        self.gc.update_ai()
        self.assertTrue(_HangingProcess.instances[-1].terminated)
        self._assert_black_played_a_legal_move()

    def test_quitting_while_the_ai_thinks_stops_it(self):
        self._use(_HangingProcess)
        self.gc.update_ai()
        with mock.patch.object(ChessMain.p, "quit"), self.assertRaises(SystemExit):
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
        self.ui = ChessMain.UIManager(512, 512, 250, 512, now=self.now)
        self.gc = ChessMain.GameController(
            p.display.get_surface(),
            p.time.Clock(),
            self.ui,
            ChessMain.ResourceManager(64),
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
        with mock.patch.object(ChessMain, "customization_menu", self._ten_seconds_in_a_menu):
            self.gc.handle_event(p.event.Event(p.KEYDOWN, {"key": p.K_c}))
        self.now.ms += 1000
        self.ui.update_timer(white_to_move=True)
        self.assertAlmostEqual(self.ui.white_time, 1.0)

    def test_time_in_shortcuts_menu_is_not_counted(self):
        with mock.patch.object(ChessMain, "show_shortcuts_menu", self._ten_seconds_in_a_menu):
            self.gc.handle_event(p.event.Event(p.KEYDOWN, {"key": p.K_h}))
        self.ui.update_timer(white_to_move=True)
        self.assertAlmostEqual(self.ui.white_time, 0.0)

    def test_time_during_move_animation_is_not_counted(self):
        gs = self.gc.game_state
        gs.makeMove([m for m in gs.getValidMoves() if str(m) == "e4"][0])
        self.gc.move_made = self.gc.animate = True
        with mock.patch.object(
            self.gc.renderer, "animate_move", lambda *a: self._ten_seconds_in_a_menu()
        ):
            self.gc.update()
        self.ui.update_timer(white_to_move=False)
        self.assertAlmostEqual(self.ui.black_time, 0.0)


if __name__ == "__main__":
    unittest.main()
