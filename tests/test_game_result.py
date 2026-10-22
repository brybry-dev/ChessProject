"""Tests du résultat de partie (J2.2, B34) : vainqueur, motif de fin, notation PGN."""

import unittest

from chessproject.core import engine
from chessproject.core.engine import Color, GameResult, Termination
from chessproject.core.fen import load_fen


def _play_uci(gs, ucis):
    files = "abcdefgh"
    for uci in ucis:
        start = (8 - int(uci[1]), files.index(uci[0]))
        end = (8 - int(uci[3]), files.index(uci[2]))
        move = next(
            m
            for m in gs.get_valid_moves()
            if (m.start_row, m.start_col, m.end_row, m.end_col) == (*start, *end)
            and (len(uci) == 4 or m.promotion_piece == uci[4].upper())
        )
        gs.make_move(move, validate=False)


class GameResultTests(unittest.TestCase):
    def _result(self, fen):
        gs = load_fen(fen)
        gs.get_valid_moves()
        return gs.result()

    def test_ongoing_game(self):
        result = engine.GameState().result()
        self.assertEqual(result, GameResult.ongoing())
        self.assertFalse(result.is_over)
        self.assertEqual(result.pgn, "*")

    def test_checkmate_names_the_winner(self):
        gs = engine.GameState()
        _play_uci(gs, ["f2f3", "e7e5", "g2g4", "d8h4"])  # mat du lion
        result = gs.result()
        self.assertEqual(result.termination, Termination.CHECKMATE)
        self.assertEqual(result.winner, Color.BLACK)
        self.assertEqual(result.pgn, "0-1")
        self.assertEqual(result.description, "Les Noirs gagnent par échec et mat")

    def test_stalemate(self):
        result = self._result("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
        self.assertEqual(result.termination, Termination.STALEMATE)
        self.assertIsNone(result.winner)
        self.assertEqual(result.pgn, "1/2-1/2")
        self.assertEqual(result.description, "Nulle par pat")

    def test_insufficient_material(self):
        result = self._result("8/8/4k3/8/8/3NK3/8/8 w - - 0 1")
        self.assertEqual(result.termination, Termination.INSUFFICIENT_MATERIAL)
        self.assertEqual(result.description, "Nulle par matériel insuffisant")

    def test_fifty_move_rule(self):
        gs = load_fen("8/8/4k3/8/8/4K3/8/R7 w - - 0 1")
        gs.fifty_move_counter = 100
        gs.get_valid_moves()
        self.assertEqual(gs.result().termination, Termination.FIFTY_MOVES)
        self.assertEqual(gs.result().description, "Nulle par la règle des 50 coups")

    def test_threefold_repetition(self):
        gs = engine.GameState()
        _play_uci(gs, ["g1f3", "g8f6", "f3g1", "f6g8"] * 2)
        gs.get_valid_moves()
        self.assertEqual(gs.result().termination, Termination.THREEFOLD_REPETITION)
        self.assertEqual(gs.result().description, "Nulle par triple répétition")

    def test_checkmate_takes_precedence_over_the_fifty_move_rule(self):
        # FIDE 9.3 : un mat donné au coup qui atteint 50 coups compte comme un mat.
        gs = load_fen("6k1/5ppp/8/8/8/8/8/R5K1 w - - 99 80")
        gs.fifty_move_counter = 99
        _play_uci(gs, ["a1a8"])
        self.assertEqual(gs.fifty_move_counter, 100)
        gs.get_valid_moves()
        self.assertTrue(gs.checkmate)
        self.assertEqual(gs.result().termination, Termination.CHECKMATE)
        self.assertEqual(gs.result().winner, Color.WHITE)

    def test_undo_clears_the_result(self):
        gs = engine.GameState()
        _play_uci(gs, ["f2f3", "e7e5", "g2g4", "d8h4"])
        gs.undo_move()
        gs.get_valid_moves()
        self.assertFalse(gs.result().is_over)


class ExternalTerminationTests(unittest.TestCase):
    """Fins hors règles de position (J4) : temps, abandon, accord."""

    def test_descriptions_and_pgn(self):
        cases = [
            (
                GameResult(Termination.TIME_FORFEIT, Color.WHITE),
                "Les Blancs gagnent au temps",
                "1-0",
            ),
            (
                GameResult(Termination.RESIGNATION, Color.BLACK),
                "Les Noirs gagnent par abandon",
                "0-1",
            ),
            (GameResult(Termination.DRAW_AGREEMENT), "Nulle par accord mutuel", "1/2-1/2"),
            (
                GameResult(Termination.TIMEOUT_VS_INSUFFICIENT_MATERIAL),
                "Nulle au temps (matériel insuffisant pour mater)",
                "1/2-1/2",
            ),
        ]
        for result, description, pgn in cases:
            with self.subTest(result=result):
                self.assertTrue(result.is_over)
                self.assertEqual(result.description, description)
                self.assertEqual(result.pgn, pgn)

    def test_mating_material(self):
        def mating(fen, color=Color.WHITE):
            return load_fen(fen).has_mating_material(color)

        self.assertFalse(mating("4k3/8/8/8/8/8/8/4K3 w - - 0 1"))
        self.assertFalse(mating("4k3/8/8/8/8/8/8/3NK3 w - - 0 1"))
        self.assertFalse(mating("4k3/8/8/8/8/8/8/3BK3 w - - 0 1"))
        self.assertTrue(mating("4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"))
        self.assertTrue(mating("4k3/8/8/8/8/8/8/2NNK3 w - - 0 1"))
        self.assertTrue(mating("4k3/8/8/8/8/8/8/3RK3 w - - 0 1"))
        self.assertFalse(mating("4k3/8/8/8/8/8/8/3RK3 w - - 0 1", Color.BLACK))


if __name__ == "__main__":
    unittest.main()
