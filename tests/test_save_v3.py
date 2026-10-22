"""Sauvegarde v3 (J4.5, B37) : métadonnées de partie, coups UCI, écriture atomique."""

import json
import os
import tempfile
import unittest
from unittest import mock

from chessproject import serialization
from chessproject.core import engine
from chessproject.core.engine import Color, GameResult, Termination
from chessproject.core.fen import load_fen
from chessproject.core.notation import parse_san


def _play(gs, sans):
    for san in sans:
        gs.make_move(parse_san(gs, san))


class SaveV3Tests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)

    def tearDown(self):
        for path in (self.path, self.path + ".tmp"):
            if os.path.exists(path):
                os.remove(path)

    def _text(self):
        with open(self.path, encoding="utf-8") as f:
            return f.read()

    def _read(self):
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def test_moves_are_stored_in_uci_with_game_metadata(self):
        gs = engine.GameState()
        _play(gs, ["e4", "e5", "Nf3"])
        clock = {"white_ms": 1000, "black_ms": 2000}
        self.assertTrue(
            serialization.save_game(
                gs,
                flip_board=True,
                filename=self.path,
                mode="PvC",
                human_white=False,
                human_black=True,
                level="Moyen",
                clock=clock,
            )
        )
        data = self._read()
        self.assertEqual(data["version"], 3)
        self.assertEqual(data["moves"], ["e2e4", "e7e5", "g1f3"])
        saved = serialization.load_save(self.path)
        self.assertEqual(saved.mode, "PvC")
        self.assertEqual((saved.human_white, saved.human_black), (False, True))
        self.assertEqual(saved.level, "Moyen")
        self.assertEqual(saved.clock, clock)
        self.assertTrue(saved.flip_board)
        self.assertEqual(serialization.to_fen(saved.game_state), serialization.to_fen(gs))

    def test_game_started_from_a_fen_keeps_its_start_position(self):
        start = "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 4 20"
        gs = load_fen(start)
        _play(gs, ["O-O", "Kd1"])
        serialization.save_game(gs, filename=self.path)
        self.assertEqual(self._read()["start_fen"], start)
        loaded = serialization.load_save(self.path).game_state
        self.assertEqual(serialization.to_fen(loaded), serialization.to_fen(gs))

    def test_external_result_is_restored(self):
        gs = engine.GameState()
        _play(gs, ["e4"])
        resign = GameResult(Termination.RESIGNATION, Color.WHITE)
        serialization.save_game(gs, filename=self.path, result=resign)
        self.assertEqual(serialization.load_save(self.path).result, resign)

    def test_position_result_is_not_stored_as_external(self):
        gs = engine.GameState()
        _play(gs, ["f3", "e5", "g4", "Qh4#"])
        serialization.save_game(gs, filename=self.path, result=gs.result())
        saved = serialization.load_save(self.path)
        self.assertIsNone(saved.result)  # le mat se déduit de la position rejouée
        self.assertTrue(saved.game_state.checkmate)

    def test_write_is_atomic(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"version": 3, "moves": ["e2e4"]}')
        before = self._text()
        with mock.patch("json.dump", side_effect=RuntimeError("disque")):
            self.assertFalse(serialization.save_game(engine.GameState(), filename=self.path))
        # L'ancienne sauvegarde est intacte et aucun fichier temporaire ne traîne.
        self.assertEqual(self._text(), before)
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_malformed_saves_raise_a_clear_error(self):
        cases = [
            {"version": 3, "moves": ["e2e5"]},  # coup illégal
            {"version": 3, "moves": ["zz"]},  # coup illisible
            {"version": 3, "moves": "e2e4"},  # mauvais type
            {"version": 3, "moves": [], "mode": 42},
            {"version": 3, "moves": [], "result": {"termination": "inconnue"}},
            [],  # pas un objet
        ]
        for data in cases:
            with self.subTest(data=data):
                with open(self.path, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                with self.assertRaises(serialization.SaveFormatError):
                    serialization.load_save(self.path)

    def test_invalid_json_raises_a_save_format_error(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{pas du json")
        with self.assertRaises(serialization.SaveFormatError):
            serialization.load_save(self.path)

    def test_v2_saves_still_load(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "version": 2,
                    "flip_board": False,
                    "start_fen": serialization.to_fen(engine.GameState()),
                    "moves": [[6, 4, 4, 4, None], [1, 4, 3, 4, None]],
                },
                f,
            )
        saved = serialization.load_save(self.path)
        self.assertEqual(len(saved.game_state.move_log), 2)
        self.assertIsNone(saved.mode)


if __name__ == "__main__":
    unittest.main()
