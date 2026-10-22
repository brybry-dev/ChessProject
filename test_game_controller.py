"""Tests de régression pour la boucle de jeu (``ChessMain.GameController``).

Vérifie notamment que l'IA reçoit toujours la liste des coups légaux de la
position courante après le coup de l'humain — un décalage d'une itération
faisait auparavant planter la partie avec « Mouvement non valide » dès le
premier coup en mode Joueur (blancs) vs IA.
"""

import os
import queue
import unittest

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


class _InlineProcess:
    """Faux multiprocessing.Process : exécute la cible immédiatement."""

    def __init__(self, target, args=()):
        self._target, self._args = target, args
        self._ran = False

    def start(self):
        self._target(*self._args)
        self._ran = True

    def is_alive(self):
        return not self._ran

    def terminate(self):
        self._ran = True


class _SyncQueue:
    def __init__(self):
        self._q: queue.Queue[object] = queue.Queue()

    def put(self, x):
        self._q.put(x)

    def get(self):
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


if __name__ == "__main__":
    unittest.main()
