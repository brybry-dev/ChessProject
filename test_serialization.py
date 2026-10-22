"""Tests de la sérialisation JSON des parties (module ``serialization``)."""

import os
import tempfile
import unittest

import ChessEngine
import serialization
from fen_utils import load_fen


def _play(game_state, coords):
    """Joue une suite de coords (start_row, start_col, end_row, end_col)."""
    for sr, sc, er, ec in coords:
        move = serialization._find_move(game_state, sr, sc, er, ec, None)
        game_state.makeMove(move, validate=False)


class ToFenTests(unittest.TestCase):
    def test_start_position_fen(self):
        gs = ChessEngine.GameState()
        self.assertEqual(
            serialization.to_fen(gs),
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        )

    def test_fen_after_e4(self):
        gs = ChessEngine.GameState()
        _play(gs, [(6, 4, 4, 4)])
        self.assertEqual(
            serialization.to_fen(gs),
            "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        )

    def test_fen_roundtrips_through_load_fen(self):
        gs = ChessEngine.GameState()
        _play(gs, [(6, 4, 4, 4), (1, 2, 3, 2), (7, 6, 5, 5)])
        fen = serialization.to_fen(gs)
        reloaded = load_fen(fen)
        self.assertEqual(reloaded.board, gs.board)
        self.assertEqual(reloaded.white_to_move, gs.white_to_move)


class SaveLoadTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_roundtrip_preserves_position_and_history(self):
        gs = ChessEngine.GameState()
        _play(gs, [(6, 4, 4, 4), (1, 4, 3, 4), (7, 1, 5, 2), (0, 1, 2, 2)])
        serialization.save_game(gs, flip_board=False, filename=self.path)

        loaded, flip = serialization.load_game(self.path)
        self.assertFalse(flip)
        self.assertEqual(loaded.board, gs.board)
        self.assertEqual(loaded.white_to_move, gs.white_to_move)
        self.assertEqual(len(loaded.move_log), 4)
        self.assertEqual(serialization.to_fen(loaded), serialization.to_fen(gs))

    def test_roundtrip_preserves_flip_board(self):
        gs = ChessEngine.GameState(flip_board=True)
        serialization.save_game(gs, flip_board=True, filename=self.path)
        loaded, flip = serialization.load_game(self.path)
        self.assertTrue(flip)
        self.assertEqual(loaded.board, gs.board)

    def test_roundtrip_preserves_promotion_choice(self):
        # Position où les blancs peuvent promouvoir en b8.
        gs = load_fen("1n6/P6k/8/8/8/8/7K/8 w - - 0 1")
        start_fen = serialization.to_fen(gs)
        move = serialization._find_move(gs, 1, 0, 0, 1, "N")  # promotion cavalier, capture
        gs.makeMove(move, validate=False)
        self.assertEqual(gs.board[0][1], "wN")

        serialization.save_game(gs, filename=self.path, start_fen=start_fen)
        loaded, _ = serialization.load_game(self.path)
        self.assertEqual(loaded.board[0][1], "wN")

    def test_load_rejects_unknown_version(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"version": 999, "moves": []}')
        with self.assertRaises(ValueError):
            serialization.load_game(self.path)

    def test_checkmate_flag_recomputed_on_load(self):
        gs = ChessEngine.GameState()
        # Mat du berger
        _play(
            gs,
            [
                (6, 4, 4, 4),
                (1, 4, 3, 4),
                (7, 5, 4, 2),
                (0, 1, 2, 2),
                (7, 3, 3, 7),
                (0, 6, 2, 5),
                (3, 7, 1, 5),
            ],
        )
        gs.getValidMoves()  # calcule les drapeaux de fin de partie
        self.assertTrue(gs.checkmate)
        serialization.save_game(gs, filename=self.path)
        loaded, _ = serialization.load_game(self.path)
        self.assertTrue(loaded.checkmate)


if __name__ == "__main__":
    unittest.main()
