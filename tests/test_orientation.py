"""Tests de l'orientation du plateau (B26).

Jouer les Noirs retourne l'affichage, jamais la position : le moteur garde la
position standard et la vue applique une rotation de 180° (rangées et colonnes).
"""

import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as p

try:
    p.init()
    p.display.set_mode((1012, 512))
    _PYGAME_OK = True
except Exception:  # pragma: no cover - environnement sans SDL
    _PYGAME_OK = False

from chessproject.core import engine
from chessproject.ui import app

START_BOARD = engine.GameState().board


BOARD = p.Rect(100, 60, 512, 512)


def _renderer(flip_board: bool) -> "app.Renderer":
    return app.Renderer(p.display.get_surface(), app.ResourceManager(), BOARD, flip_board)


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class RendererRotationTests(unittest.TestCase):
    def test_pixel_to_square_roundtrip_in_both_orientations(self):
        for flip in (False, True):
            r = _renderer(flip)
            for row in range(8):
                for col in range(8):
                    with self.subTest(flip=flip, row=row, col=col):
                        center = r.square_rect(row, col).center
                        self.assertEqual(r.square_from_pixel(center), (row, col))

    def test_flipped_view_is_a_180_degree_rotation(self):
        r = _renderer(True)
        top_left = (BOARD.x + 5, BOARD.y + 5)
        bottom_right = (BOARD.right - 5, BOARD.bottom - 5)
        self.assertEqual(r.square_from_pixel(top_left), (7, 7))  # h1 en haut à gauche
        self.assertEqual(r.square_from_pixel(bottom_right), (0, 0))  # a8 en bas à droite

    def test_coordinate_labels_follow_the_orientation(self):
        normal, flipped = _renderer(False), _renderer(True)
        self.assertEqual([normal.file_label(c) for c in range(8)], list("abcdefgh"))
        self.assertEqual([flipped.file_label(c) for c in range(8)], list("hgfedcba"))
        self.assertEqual([normal.rank_label(r) for r in range(8)], list("87654321"))
        self.assertEqual([flipped.rank_label(r) for r in range(8)], list("12345678"))


class _InlineProcess:
    def __init__(self, target, args=(), **kwargs):
        self._target, self._args, self._ran = target, args, False

    def start(self):
        self._target(*self._args)
        self._ran = True

    def is_alive(self):
        return not self._ran

    def terminate(self):
        self._ran = True


class _ListQueue:
    def __init__(self):
        self._items = []

    def put(self, x):
        self._items.append(x)

    def get(self, *args, **kwargs):
        return self._items.pop(0)


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class PlayingBlackTests(unittest.TestCase):
    """Partie Joueur (Noirs) contre IA : plateau retourné."""

    def setUp(self):
        self._orig = (app.Process, app.Queue)
        app.Process = _InlineProcess  # type: ignore[misc, assignment]
        app.Queue = _ListQueue  # type: ignore[misc, assignment]
        self.gc = app.GameController(
            p.display.get_surface(),
            p.time.Clock(),
            app.UIManager(),
            app.ResourceManager(),
            "PvC",
            False,
            True,
            True,
        )

    def tearDown(self):
        app.Process, app.Queue = self._orig  # type: ignore[misc]

    def _click(self, row, col):
        pos = self.gc.renderer.square_rect(row, col).center
        self.gc.handle_event(p.event.Event(p.MOUSEBUTTONDOWN, {"pos": pos, "button": 1}))

    def test_engine_position_is_the_standard_one(self):
        gs = self.gc.game_state
        self.assertEqual(gs.board, START_BOARD)
        self.assertEqual(gs.board[7][4], "wK")
        self.assertEqual(gs.white_king_location, (7, 4))
        self.assertEqual(gs.black_king_location, (0, 4))

    def test_check_is_detected_and_only_the_king_castles(self):
        gs = self.gc.game_state
        # Dégager f1/g1, puis vérifier que le roque est un coup du roi.
        gs.board[7][5] = gs.board[7][6] = "--"
        gs._valid_moves = None
        castles = [m for m in gs.get_valid_moves() if m.is_castle_move]
        self.assertEqual([m.piece_moved for m in castles], ["wK"])
        # Tour noire sur la colonne e, pion e2 retiré : le roi blanc est en échec.
        gs.board[6][4] = "--"
        gs.board[3][4] = "bR"
        gs._valid_moves = None
        gs.get_valid_moves()
        self.assertTrue(gs.in_check)

    def test_human_black_can_play_after_the_ai(self):
        self.gc.update_ai()  # l'IA (Blancs) joue le premier coup
        self.gc.valid_moves = self.gc.game_state.get_valid_moves()
        self.gc.move_made = False
        self.assertEqual(len(self.gc.game_state.move_log), 1)
        self._click(1, 4)  # e7
        self._click(3, 4)  # e5
        self.assertEqual(len(self.gc.game_state.move_log), 2)
        self.assertEqual(self.gc.game_state.board[3][4], "bp")


if __name__ == "__main__":
    unittest.main()
