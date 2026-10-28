"""Tests du mode analyse (J9.1) : variante principale envoyée pendant la réflexion."""

import queue
import unittest

from chessproject.ai import analysis, search
from chessproject.core import engine, notation
from chessproject.core.fen import load_fen


def run_lines(game_state, depth):
    """Lignes déposées par ``analysis.run`` (sans le marqueur de fin)."""
    q: queue.Queue = queue.Queue()
    analysis.run(game_state, q, limits=search.SearchLimits(depth=depth))
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    assert items and items[-1] is None, items
    return items[:-1]


class TestRun(unittest.TestCase):
    def test_one_line_per_depth_with_legal_san(self):
        gs = engine.GameState()
        lines = run_lines(gs, 3)
        self.assertEqual([line.depth for line in lines], [1, 2, 3])
        for line in lines:
            self.assertTrue(line.pv)
            state = load_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
            for san in line.pv:
                state.make_move(notation.parse_san(state, san), validate=False)

    def test_score_is_from_white_point_of_view(self):
        # Noirs au trait avec une dame de plus : score négatif (avantage noir).
        gs = load_fen("q3k3/8/8/8/8/8/8/4K3 b - - 0 1")
        lines = run_lines(gs, 2)
        self.assertLess(lines[-1].score, 0)

    def test_mate_line(self):
        gs = load_fen("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
        lines = run_lines(gs, 3)
        self.assertEqual(lines[-1].pv[0], "Ra8#")
        self.assertGreaterEqual(lines[-1].score, search.MATE_THRESHOLD)

    def test_position_is_numbered(self):
        gs = load_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 12")
        line = run_lines(gs, 2)[-1]
        self.assertEqual((line.fullmove, line.white_to_move), (12, False))

    def test_finished_game_sends_only_the_end_marker(self):
        gs = load_fen("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
        gs.make_move(notation.parse_san(gs, "Ra8#"))
        self.assertEqual(run_lines(gs, 3), [])

    def test_position_is_left_unchanged(self):
        gs = engine.GameState()
        gs.make_move(notation.parse_san(gs, "e4"))
        run_lines(gs, 2)
        self.assertEqual(len(gs.move_log), 1)
        self.assertFalse(gs.white_to_move)


class TestFormat(unittest.TestCase):
    def test_white_to_move(self):
        line = analysis.AnalysisLine(5, 40, ("e4", "e5", "Nf3"), 1, True)
        self.assertEqual(analysis.format_pv(line), "1. e4 e5 2. Nf3")

    def test_black_to_move(self):
        line = analysis.AnalysisLine(5, -40, ("Nf6", "Nc3"), 12, False)
        self.assertEqual(analysis.format_pv(line), "12... Nf6 13. Nc3")


class _FakeProcess:
    started: list["_FakeProcess"] = []

    def __init__(self, target, args=(), daemon=False):
        self.args = args
        self.alive = False
        self.terminated = False

    def start(self):
        self.alive = True
        _FakeProcess.started.append(self)

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.alive = False
        self.terminated = True


class TestAnalyzer(unittest.TestCase):
    def setUp(self):
        _FakeProcess.started = []
        self.analyzer = analysis.Analyzer(process=_FakeProcess, make_queue=queue.Queue)

    def test_start_then_poll_keeps_the_deepest_line(self):
        self.analyzer.start(engine.GameState(), "a")
        process = _FakeProcess.started[-1]
        out = process.args[1]
        out.put(analysis.AnalysisLine(1, 10, ("e4",), 1, True))
        out.put(analysis.AnalysisLine(2, 20, ("d4", "d5"), 1, True))
        self.assertEqual(self.analyzer.poll().depth, 2)
        self.assertEqual(self.analyzer.poll().depth, 2)  # rien de neuf : dernière ligne
        self.assertTrue(self.analyzer.running)
        out.put(None)
        self.assertEqual(self.analyzer.poll().depth, 2)
        self.assertFalse(self.analyzer.running)

    def test_same_key_does_not_restart(self):
        self.analyzer.start(engine.GameState(), "a")
        self.analyzer.start(engine.GameState(), "a")
        self.assertEqual(len(_FakeProcess.started), 1)

    def test_new_key_stops_the_previous_analysis(self):
        self.analyzer.start(engine.GameState(), "a")
        first = _FakeProcess.started[-1]
        first.args[1].put(analysis.AnalysisLine(1, 10, ("e4",), 1, True))
        self.analyzer.poll()
        self.analyzer.start(engine.GameState(), "b")
        self.assertTrue(first.terminated)
        self.assertEqual(len(_FakeProcess.started), 2)
        self.assertIsNone(self.analyzer.poll())  # l'ancienne ligne n'est plus affichée

    def test_stop(self):
        self.analyzer.start(engine.GameState(), "a")
        self.analyzer.stop()
        self.assertTrue(_FakeProcess.started[-1].terminated)
        self.assertIsNone(self.analyzer.key)
        self.assertIsNone(self.analyzer.poll())


class TestAnalyzerProcess(unittest.TestCase):
    """Un vrai processus : la ligne arrive pendant la réflexion, puis la fin."""

    def test_real_process(self):
        import time

        analyzer = analysis.Analyzer(limits=search.SearchLimits(depth=3))
        analyzer.start(engine.GameState(), "x")
        deadline = time.monotonic() + 20
        line = None
        while analyzer.running and time.monotonic() < deadline:
            line = analyzer.poll() or line
            time.sleep(0.02)
        line = analyzer.poll() or line
        analyzer.stop()
        self.assertIsNotNone(line)
        assert line is not None
        self.assertEqual(line.depth, 3)


if __name__ == "__main__":
    unittest.main()
