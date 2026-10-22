"""Tests de la FEN de production (J2.6 : validation B41, compteurs B36)."""

import json
import os
import tempfile
import unittest

import ChessEngine
import serialization
from fen_utils import FenError, load_fen, start_fullmove

EMPTY_KINGS = "4k3/8/8/8/8/8/8/4K3"


class TestFenValidation(unittest.TestCase):
    INVALID = {
        "trop peu de champs": "4k3/8/8/8/8/8/8/4K3 w -",
        "cinq champs": "4k3/8/8/8/8/8/8/4K3 w - - 0",
        "sept champs": "4k3/8/8/8/8/8/8/4K3 w - - 0 1 x",
        "7 rangées": "4k3/8/8/8/8/8/4K3 w - - 0 1",
        "rangée de 9 cases": "4k4/8/8/8/8/8/8/4K3 w - - 0 1",
        "rangée de 7 cases": "4k2/8/8/8/8/8/8/4K3 w - - 0 1",
        "caractère de pièce invalide": "4k3/8/8/8/8/8/8/4K2X w - - 0 1",
        "chiffre 0 invalide": "4k3/08/8/8/8/8/8/4K3 w - - 0 1",
        "deux rois blancs": "4k3/8/8/8/8/8/8/3KK3 w - - 0 1",
        "pas de roi noir": "8/8/8/8/8/8/8/4K3 w - - 0 1",
        "pion sur la rangée 8": "P3k3/8/8/8/8/8/8/4K3 w - - 0 1",
        "pion sur la rangée 1": "4k3/8/8/8/8/8/8/p3K3 w - - 0 1",
        "trait invalide": "4k3/8/8/8/8/8/8/4K3 x - - 0 1",
        "roque : caractère invalide": "r3k2r/8/8/8/8/8/8/R3K2R w KX - 0 1",
        "roque : doublon": "r3k2r/8/8/8/8/8/8/R3K2R w KKq - 0 1",
        "roque : '-' mélangé": "r3k2r/8/8/8/8/8/8/R3K2R w K- - 0 1",
        "roque K sans tour en h1 (B41)": "4k3/p7/8/8/8/8/P7/4K3 w K - 0 1",
        "roque Q sans roi en e1": "r3k2r/8/8/8/8/8/8/R2K3R w Q - 0 1",
        "roque q sans tour en a8": "4k2r/8/8/8/8/8/8/R3K2R w q - 0 1",
        "en passant : syntaxe": "4k3/8/8/8/8/8/8/4K3 w - e9 0 1",
        "en passant : colonne": "4k3/8/8/8/8/8/8/4K3 w - z6 0 1",
        "en passant : rangée selon le trait": "4k3/8/8/8/4P3/8/8/4K3 w - e3 0 1",
        "en passant : pas de pion adverse": "4k3/8/8/8/8/8/8/4K3 w - e6 0 1",
        "en passant : case occupée": "4k3/8/4n3/4p3/8/8/8/4K3 w - e6 0 1",
        "en passant : case de départ occupée": "4k3/4n3/8/4p3/8/8/8/4K3 w - e6 0 1",
        "camp sans trait en échec": "4k3/8/8/8/8/8/4Q3/4K3 w - - 0 1",
        "rois adjacents": "8/8/8/3kK3/8/8/8/8 b - - 0 1",
        "demi-coups négatif": "4k3/8/8/8/8/8/8/4K3 w - - -1 1",
        "demi-coups non entier": "4k3/8/8/8/8/8/8/4K3 w - - x 1",
        "numéro de coup 0": "4k3/8/8/8/8/8/8/4K3 w - - 0 0",
        "numéro de coup non entier": "4k3/8/8/8/8/8/8/4K3 w - - 0 1.5",
    }

    def test_invalid_fens_are_rejected(self):
        for rule, fen in self.INVALID.items():
            with self.subTest(rule=rule, fen=fen), self.assertRaises(FenError):
                load_fen(fen)

    def test_fen_error_is_a_value_error_with_clear_message(self):
        self.assertTrue(issubclass(FenError, ValueError))
        with self.assertRaisesRegex(FenError, "roi noir"):
            load_fen("8/8/8/8/8/8/8/4K3 w - - 0 1")
        with self.assertRaisesRegex(FenError, "h1"):
            load_fen("4k3/p7/8/8/8/8/P7/4K3 w K - 0 1")

    def test_four_fields_default_counters(self):
        gs = load_fen(f"{EMPTY_KINGS} b - -")
        self.assertEqual(gs.fifty_move_counter, 0)
        self.assertEqual(start_fullmove(gs), 1)
        self.assertEqual(serialization.to_fen(gs), f"{EMPTY_KINGS} b - - 0 1")

    def test_side_to_move_may_be_in_check(self):
        gs = load_fen("4k3/8/8/8/8/8/4Q3/4K3 b - - 0 1")
        self.assertTrue(gs.king_in_check())

    def test_plausible_en_passant_for_black(self):
        gs = load_fen("4k3/8/8/8/3pP3/8/8/4K3 b - e3 0 1")
        self.assertEqual(gs.enpassant_possible, (5, 4))


class TestFenRoundTrip(unittest.TestCase):
    VALID = [
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2",
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
        "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
        "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10",
        "2kr3r/ppp2ppp/2n5/3qp3/1b1P4/2N1BN2/PPP2PPP/R2QK2R b KQ - 3 9",
        "8/8/4k3/3n4/3K4/8/5P2/8 b - - 0 50",
        "r3k2r/8/8/8/8/8/8/R3K2R w Kq - 42 87",
        "8/8/8/KppP3r/8/8/8/7k w - b6 0 1",
    ]

    def test_load_then_to_fen_is_exact(self):
        for fen in self.VALID:
            with self.subTest(fen=fen):
                self.assertEqual(serialization.to_fen(load_fen(fen)), fen)

    def test_halfmove_counter_is_loaded(self):
        gs = load_fen("r3k2r/8/8/8/8/8/8/R3K2R w Kq - 42 87")
        self.assertEqual(gs.fifty_move_counter, 42)
        gs.make_move(gs.get_valid_moves()[0], validate=False)
        gs.undo_move()
        self.assertEqual(gs.fifty_move_counter, 42, "le compteur chargé doit survivre à un undo")
        self.assertEqual(start_fullmove(gs), 87)

    def test_standard_game_state_fullmove(self):
        gs = ChessEngine.GameState()
        self.assertEqual(serialization.fullmove_number(gs), 1)


def _play(gs, start, end):
    for move in gs.get_valid_moves():
        if (move.start_row, move.start_col) == start and (move.end_row, move.end_col) == end:
            gs.make_move(move)
            return
    raise AssertionError(f"coup introuvable {start}->{end}")


class TestFullmoveNumber(unittest.TestCase):
    START = "4k3/8/8/8/8/8/8/R3K3 b Q - 5 12"

    def test_counters_after_moves_from_black_to_move(self):
        gs = load_fen(self.START)
        _play(gs, (0, 4), (0, 3))  # ...Kd8
        self.assertTrue(serialization.to_fen(gs).endswith(" w Q - 6 13"))
        _play(gs, (7, 0), (6, 0))  # Ta2 : perd le droit Q
        self.assertTrue(serialization.to_fen(gs).endswith(" b - - 7 13"))
        _play(gs, (0, 3), (0, 2))  # ...Kc8
        self.assertEqual(serialization.to_fen(gs), "2k5/8/8/8/8/8/R7/4K3 w - - 8 14")
        for _ in range(3):
            gs.undo_move()
        self.assertEqual(serialization.to_fen(gs), self.START)

    def test_fullmove_from_white_to_move(self):
        gs = load_fen("4k3/8/8/8/8/8/8/R3K3 w Q - 0 30")
        _play(gs, (7, 0), (6, 0))
        self.assertTrue(serialization.to_fen(gs).endswith(" b - - 1 30"))
        _play(gs, (0, 4), (0, 3))
        self.assertTrue(serialization.to_fen(gs).endswith(" w - - 2 31"))

    def test_save_and_load_keep_counters(self):
        gs = load_fen(self.START)
        _play(gs, (0, 4), (0, 3))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "game.json")
            serialization.save_game(gs, filename=path, start_fen=self.START)
            loaded, _ = serialization.load_game(path)
        self.assertEqual(serialization.to_fen(loaded), serialization.to_fen(gs))


class TestSaveWithInvalidStartFen(unittest.TestCase):
    def test_load_game_rejects_invalid_start_fen(self):
        data = {
            "version": serialization.SAVE_VERSION,
            "flip_board": False,
            "start_fen": "8/8/8/8/8/8/8/4K3 w - - 0 1",  # pas de roi noir
            "moves": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            with self.assertRaises(FenError):
                serialization.load_game(path)


if __name__ == "__main__":
    unittest.main()
