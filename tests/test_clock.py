"""Tests de la pendule (J4.1, B44) et de l'allocation du temps de l'IA (J4.2), à temps
simulé : aucune attente réelle."""

import json
import unittest

from chessproject.core import clock as clk
from chessproject.core.clock import (
    PRESETS,
    ChessClock,
    TimeControl,
    allocate_think_time_ms,
    format_ms,
    timeout_result,
)
from chessproject.core.engine import Color, GameState, Termination
from chessproject.core.fen import load_fen

W, B = Color.WHITE, Color.BLACK


class FakeTime:
    """Horloge factice en secondes, avancée à la main."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance_ms(self, ms: float) -> None:
        self.t += ms / 1000


def _clock(minutes=5, inc=0):
    now = FakeTime()
    return ChessClock(TimeControl.from_minutes(minutes, inc), now), now


class CountdownTests(unittest.TestCase):
    def test_not_counting_before_start(self):
        c, now = _clock(1)
        now.advance_ms(5000)
        self.assertEqual(c.remaining_ms(W), 60_000)
        self.assertFalse(c.running)

    def test_simple_countdown(self):
        c, now = _clock(5)
        c.start()
        now.advance_ms(1500)
        self.assertEqual(c.remaining_ms(W), 298_500)
        self.assertEqual(c.remaining_ms(B), 300_000)
        # remaining_ms ne mute pas l'état.
        self.assertEqual(c.remaining_ms(W), 298_500)
        self.assertEqual(c.press(), 1500)
        self.assertIs(c.turn, B)
        now.advance_ms(2000)
        self.assertEqual(c.remaining_ms(W), 298_500)
        self.assertEqual(c.remaining_ms(B), 298_000)

    def test_start_black(self):
        c, now = _clock(5)
        c.start(white_to_move=False)
        now.advance_ms(1000)
        self.assertEqual(c.remaining_ms(B), 299_000)
        self.assertEqual(c.remaining_ms(W), 300_000)

    def test_double_start_and_press_before_start(self):
        c, _ = _clock(5)
        with self.assertRaises(RuntimeError):
            c.press()
        c.start()
        with self.assertRaises(RuntimeError):
            c.start()

    def test_increment_credited_after_move(self):
        c, now = _clock(3, 2)
        c.start()
        now.advance_ms(5000)
        # Pendant la réflexion, pas d'incrément.
        self.assertEqual(c.remaining_ms(W), 175_000)
        self.assertEqual(c.press(), 5000)
        self.assertEqual(c.remaining_ms(W), 177_000)
        self.assertEqual(c.remaining_ms(B), 180_000)
        now.advance_ms(1000)
        c.press()
        self.assertEqual(c.remaining_ms(B), 181_000)

    def test_increment_can_exceed_initial(self):
        c, _ = _clock(1, 10)
        c.start()
        c.press()
        self.assertEqual(c.remaining_ms(W), 70_000)


class FlagTests(unittest.TestCase):
    def test_flag_at_right_time_then_stopped(self):
        c, now = _clock(1)
        c.start()
        now.advance_ms(59_999)
        self.assertIsNone(c.flagged())
        self.assertEqual(c.remaining_ms(W), 1)
        now.advance_ms(1)
        self.assertIs(c.flagged(), W)
        self.assertFalse(c.running)
        now.advance_ms(10_000)
        self.assertIs(c.flagged(), W)
        self.assertEqual(c.remaining_ms(W), 0)
        self.assertEqual(c.remaining_ms(B), 60_000)
        with self.assertRaises(RuntimeError):
            c.press()

    def test_late_detection_keeps_zero(self):
        c, now = _clock(1)
        c.start()
        now.advance_ms(90_000)  # dépassement constaté en retard
        self.assertEqual(c.remaining_ms(W), 0)
        self.assertIs(c.flagged(), W)
        self.assertEqual(c.remaining_ms(W), 0)

    def test_press_after_time_ran_out_flags_without_increment(self):
        c, now = _clock(1, 5)
        c.start()
        now.advance_ms(61_000)
        c.press()
        self.assertIs(c.flagged(), W)
        self.assertEqual(c.remaining_ms(W), 0)
        self.assertIs(c.turn, W)

    def test_black_flags(self):
        c, now = _clock(1)
        c.start()
        now.advance_ms(1000)
        c.press()
        now.advance_ms(60_000)
        self.assertIs(c.flagged(), B)
        self.assertEqual(c.remaining_ms(W), 59_000)

    def test_stop(self):
        c, now = _clock(1)
        c.start()
        now.advance_ms(1000)
        c.stop()
        now.advance_ms(120_000)
        self.assertEqual(c.remaining_ms(W), 59_000)
        self.assertIsNone(c.flagged())


class TimeoutResultTests(unittest.TestCase):
    def test_forfeit_by_default(self):
        result = timeout_result(GameState(), W)
        self.assertEqual(result.termination, Termination.TIME_FORFEIT)
        self.assertIs(result.winner, B)
        self.assertEqual(result.pgn, "0-1")

    def test_draw_vs_lone_king(self):
        # Les Blancs tombent ; les Noirs n'ont que leur roi.
        gs = load_fen("4k3/8/8/8/8/8/8/R3K3 w - - 0 1")
        result = timeout_result(gs, W)
        self.assertEqual(result.termination, Termination.TIMEOUT_VS_INSUFFICIENT_MATERIAL)
        self.assertIsNone(result.winner)
        self.assertEqual(result.pgn, "1/2-1/2")

    def test_draw_vs_king_and_knight(self):
        gs = load_fen("4k3/8/8/8/8/2n5/8/R3K3 w - - 0 1")
        result = timeout_result(gs, W)
        self.assertEqual(result.termination, Termination.TIMEOUT_VS_INSUFFICIENT_MATERIAL)

    def test_loss_vs_king_and_pawn(self):
        gs = load_fen("4k3/8/8/8/8/2p5/8/R3K3 w - - 0 1")
        result = timeout_result(gs, W)
        self.assertEqual(result.termination, Termination.TIME_FORFEIT)
        self.assertIs(result.winner, B)

    def test_flagging_side_with_lone_king_still_loses(self):
        # Seul le matériel de l'adversaire compte.
        gs = load_fen("4k3/8/8/8/8/8/8/R3K3 w - - 0 1")
        result = timeout_result(gs, B)
        self.assertEqual(result.termination, Termination.TIME_FORFEIT)
        self.assertIs(result.winner, W)


class PauseTests(unittest.TestCase):
    def test_paused_time_not_counted(self):
        c, now = _clock(5)
        c.start()
        now.advance_ms(1000)
        c.pause()
        self.assertTrue(c.is_paused)
        now.advance_ms(10_000)  # 10 s dans un menu
        self.assertEqual(c.remaining_ms(W), 299_000)
        c.resume()
        now.advance_ms(1000)
        self.assertEqual(c.remaining_ms(W), 298_000)

    def test_pause_idempotent(self):
        c, now = _clock(5)
        c.start()
        now.advance_ms(1000)
        c.pause()
        now.advance_ms(5000)
        c.pause()
        now.advance_ms(5000)
        c.resume()
        c.resume()
        now.advance_ms(1000)
        self.assertEqual(c.remaining_ms(W), 298_000)

    def test_context_manager(self):
        c, now = _clock(5)
        c.start()
        with c.paused():
            now.advance_ms(10_000)
            with c.paused():  # imbrication : reste en pause à la sortie interne
                now.advance_ms(1000)
            self.assertTrue(c.is_paused)
            now.advance_ms(1000)
        self.assertFalse(c.is_paused)
        now.advance_ms(500)
        self.assertEqual(c.remaining_ms(W), 299_500)

    def test_context_manager_keeps_existing_pause(self):
        c, _ = _clock(5)
        c.start()
        c.pause()
        with c.paused():
            pass
        self.assertTrue(c.is_paused)

    def test_no_flag_while_paused(self):
        c, now = _clock(1)
        c.start()
        now.advance_ms(59_000)
        c.pause()
        now.advance_ms(60_000)
        self.assertIsNone(c.flagged())
        c.resume()
        now.advance_ms(1000)
        self.assertIs(c.flagged(), W)

    def test_press_while_paused(self):
        c, now = _clock(5, 2)
        c.start()
        now.advance_ms(1000)
        c.pause()
        now.advance_ms(5000)
        self.assertEqual(c.press(), 0)  # le temps a été décompté à la pause
        self.assertEqual(c.remaining_ms(W), 301_000)
        now.advance_ms(5000)
        self.assertEqual(c.remaining_ms(B), 300_000)
        c.resume()
        now.advance_ms(1000)
        self.assertEqual(c.remaining_ms(B), 299_000)

    def test_pause_before_start(self):
        c, now = _clock(5)
        c.pause()
        c.start()
        now.advance_ms(3000)
        self.assertEqual(c.remaining_ms(W), 300_000)
        c.resume()
        now.advance_ms(1000)
        self.assertEqual(c.remaining_ms(W), 299_000)


class UndoTests(unittest.TestCase):
    def test_undo_restores_both_times_and_turn(self):
        c, now = _clock(3, 2)
        c.start()
        now.advance_ms(4000)
        c.press()  # Blancs : 176 + 2
        now.advance_ms(7000)
        c.press()  # Noirs : 173 + 2
        self.assertEqual((c.remaining_ms(W), c.remaining_ms(B)), (178_000, 175_000))
        now.advance_ms(3000)
        self.assertTrue(c.undo_press())
        self.assertIs(c.turn, B)
        self.assertEqual((c.remaining_ms(W), c.remaining_ms(B)), (178_000, 180_000))
        self.assertTrue(c.undo_press())
        self.assertIs(c.turn, W)
        self.assertEqual((c.remaining_ms(W), c.remaining_ms(B)), (180_000, 180_000))
        self.assertFalse(c.undo_press())
        # Le décompte repart de l'instant de l'annulation.
        now.advance_ms(1000)
        self.assertEqual(c.remaining_ms(W), 179_000)

    def test_press_count(self):
        c, _ = _clock(5)
        c.start()
        c.press()
        c.press()
        self.assertEqual(c.press_count, 2)
        c.undo_press()
        self.assertEqual(c.press_count, 1)

    def test_undo_after_flag_on_press_restarts(self):
        c, now = _clock(1)
        c.start()
        now.advance_ms(61_000)
        c.press()
        self.assertIs(c.flagged(), W)
        self.assertTrue(c.undo_press())
        self.assertIsNone(c.flagged())
        self.assertTrue(c.running)
        self.assertEqual(c.remaining_ms(W), 60_000)


class UnlimitedTests(unittest.TestCase):
    def test_nothing_counted(self):
        now = FakeTime()
        c = ChessClock(clk.DEFAULT, now)
        self.assertTrue(c.is_unlimited)
        c.start()
        now.advance_ms(10**9)
        self.assertIsNone(c.remaining_ms(W))
        self.assertIsNone(c.flagged())
        self.assertEqual(c.press(), 0)
        self.assertIs(c.turn, B)
        self.assertTrue(c.undo_press())
        self.assertIs(c.turn, W)
        self.assertEqual(format_ms(c.remaining_ms(W)), "∞")


class SerializationTests(unittest.TestCase):
    def test_round_trip(self):
        c, now = _clock(3, 2)
        c.start()
        now.advance_ms(4000)
        c.press()
        now.advance_ms(2500)
        data = json.loads(json.dumps(c.to_dict()))
        self.assertEqual(data["black_ms"], 177_500)

        now2 = FakeTime()
        restored = ChessClock.from_dict(data, now2)
        self.assertEqual(restored.control, c.control)
        self.assertEqual(restored.control.name, "3+2")
        self.assertEqual(restored.remaining_ms(W), 178_000)
        self.assertEqual(restored.remaining_ms(B), 177_500)
        self.assertIs(restored.turn, B)
        self.assertTrue(restored.running)
        now2.advance_ms(500)
        self.assertEqual(restored.remaining_ms(B), 177_000)
        self.assertTrue(restored.undo_press())
        self.assertEqual(restored.remaining_ms(W), 180_000)
        self.assertEqual(restored.to_dict()["history"], [])

    def test_round_trip_flagged_and_paused(self):
        c, now = _clock(1)
        c.start()
        now.advance_ms(60_000)
        c.flagged()
        restored = ChessClock.from_dict(c.to_dict(), FakeTime())
        self.assertIs(restored.flagged(), W)
        self.assertFalse(restored.running)

        c2, _ = _clock(1)
        c2.start()
        c2.pause()
        restored2 = ChessClock.from_dict(c2.to_dict(), FakeTime())
        self.assertTrue(restored2.is_paused)

    def test_round_trip_unlimited(self):
        c = ChessClock(clk.UNLIMITED, FakeTime())
        restored = ChessClock.from_dict(c.to_dict(), FakeTime())
        self.assertTrue(restored.is_unlimited)

    def test_to_dict_does_not_mutate(self):
        c, now = _clock(1)
        c.start()
        now.advance_ms(1000)
        c.to_dict()
        now.advance_ms(1000)
        self.assertEqual(c.remaining_ms(W), 58_000)

    def test_invalid_data(self):
        c, _ = _clock(1)
        good = c.to_dict()
        for key, value in (
            ("version", 99),
            ("white_ms", "abc"),
            ("turn", "x"),
            ("initial_ms", True),
            ("increment_ms", -5),
        ):
            bad = dict(good, **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                ChessClock.from_dict(bad)
        bad = dict(good)
        del bad["turn"]
        with self.assertRaises(ValueError):
            ChessClock.from_dict(bad)


class FormatTests(unittest.TestCase):
    def test_format(self):
        cases = {
            None: "∞",
            0: "0:00.0",
            -50: "0:00.0",
            9_750: "0:09.7",
            9_999: "0:09.9",
            10_000: "0:10",
            62_000: "1:02",
            299_999: "4:59",
            300_000: "5:00",
            3_599_999: "59:59",
            3_723_000: "1:02:03",
        }
        for ms, expected in cases.items():
            with self.subTest(ms=ms):
                self.assertEqual(format_ms(ms), expected)


class TimeControlTests(unittest.TestCase):
    def test_from_minutes(self):
        tc = TimeControl.from_minutes(5, 3)
        self.assertEqual((tc.initial_ms, tc.increment_ms), (300_000, 3000))
        self.assertEqual(tc.label, "5+3")
        self.assertEqual(tc.pgn_tag, "300+3")
        self.assertTrue(TimeControl.from_minutes(0).is_unlimited)

    def test_pgn_round_trip(self):
        for text in ("300+2", "180", "60+0.5", "-", "5400+30"):
            with self.subTest(text=text):
                self.assertEqual(TimeControl.from_pgn(text).pgn_tag, text)
        for preset in PRESETS:
            with self.subTest(preset=preset.name):
                self.assertEqual(TimeControl.from_pgn(preset.pgn_tag), preset)

    def test_pgn_equivalences(self):
        self.assertEqual(TimeControl.from_pgn("180+2"), clk.BLITZ_3_2)
        self.assertEqual(TimeControl.from_pgn("300+0").pgn_tag, "300")
        self.assertTrue(TimeControl.from_pgn(" - ").is_unlimited)

    def test_pgn_invalid(self):
        for text in ("", "abc", "40/9000", "*60", "?", "300+", "-5", "0", "nan", "inf"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                TimeControl.from_pgn(text)

    def test_invalid_values(self):
        with self.assertRaises(ValueError):
            TimeControl(60_000, -1)
        with self.assertRaises(ValueError):
            TimeControl.from_minutes(-1)

    def test_presets(self):
        expected = [
            ("Bullet 1+0", 60_000, 0),
            ("Blitz 3+2", 180_000, 2000),
            ("Blitz 5+0", 300_000, 0),
            ("Rapide 10+5", 600_000, 5000),
            ("Rapide 15+10", 900_000, 10_000),
            ("Sans limite", 0, 0),
        ]
        self.assertEqual([(p.name, p.initial_ms, p.increment_ms) for p in PRESETS], expected)
        self.assertEqual(len({p.name for p in PRESETS}), len(PRESETS))
        self.assertTrue(clk.DEFAULT.is_unlimited)
        self.assertIn(clk.DEFAULT, PRESETS)
        self.assertEqual(clk.UNLIMITED.pgn_tag, "-")


class AllocateThinkTimeTests(unittest.TestCase):
    def test_typical_values(self):
        # 5+0, début de partie : 300 s / 40.
        self.assertEqual(allocate_think_time_ms(300_000, 0, 0), 7500)
        # Milieu de partie avec incrément : 100 s / 20 + 0,75 × 2 s.
        self.assertEqual(allocate_think_time_ms(100_000, 2000, 60), 6500)

    def test_bounds(self):
        for remaining in (0, 1, 30, 60, 100, 500, 1000, 5000, 60_000, 600_000):
            for inc in (0, 1000, 10_000, 60_000):
                for played in (0, 10, 40, 200):
                    with self.subTest(remaining=remaining, inc=inc, played=played):
                        t = allocate_think_time_ms(remaining, inc, played)
                        self.assertGreaterEqual(t, 10)
                        if remaining >= 200:
                            self.assertLessEqual(t, remaining // 3)
                            self.assertLessEqual(t, remaining - 50)

    def test_large_increment_capped_by_third(self):
        self.assertEqual(allocate_think_time_ms(3000, 60_000, 0), 1000)

    def test_negative_inputs(self):
        self.assertEqual(allocate_think_time_ms(-100, -5, -3), 10)

    def test_monotonic(self):
        previous = 0
        for remaining in range(0, 400_000, 997):
            t = allocate_think_time_ms(remaining, 2000, 30)
            self.assertGreaterEqual(t, previous)
            previous = t
        previous = 0
        for inc in range(0, 30_000, 250):
            t = allocate_think_time_ms(60_000, inc, 30)
            self.assertGreaterEqual(t, previous)
            previous = t
        previous = 0
        for played in range(0, 200):
            t = allocate_think_time_ms(60_000, 0, played)
            self.assertGreaterEqual(t, previous)
            previous = t

    def test_max_ms_cap(self):
        self.assertEqual(allocate_think_time_ms(300_000, 0, 0, max_ms=1000), 1000)
        self.assertEqual(allocate_think_time_ms(300_000, 0, 0, max_ms=10_000), 7500)
        self.assertEqual(allocate_think_time_ms(300_000, 0, 0, max_ms=0), 10)
        self.assertEqual(allocate_think_time_ms(300_000, 0, 0, max_ms=None), 7500)

    def test_moves_to_go(self):
        # Partagé avec le moteur UCI (J10.3) : coups restants avant le prochain contrôle.
        self.assertEqual(allocate_think_time_ms(60_000, 0, 0, moves_to_go=10), 6000)
        self.assertEqual(allocate_think_time_ms(60_000, 1000, 0, moves_to_go=10), 6750)
        # Dernier coup avant le contrôle : tout sauf la marge de sécurité.
        self.assertEqual(allocate_think_time_ms(10_000, 0, 80, moves_to_go=1), 9950)
        self.assertEqual(allocate_think_time_ms(100, 5000, 0, moves_to_go=1), 50)
        # moves_to_go absent ou nul : formule de la partie à temps fixe.
        self.assertEqual(allocate_think_time_ms(300_000, 0, 0, moves_to_go=0), 7500)
        self.assertEqual(allocate_think_time_ms(300_000, 0, 0, moves_to_go=None), 7500)

    def test_moves_to_go_bounds_and_monotonic(self):
        for moves_to_go in (1, 2, 5, 30):
            previous = 0
            for remaining in range(0, 120_000, 499):
                t = allocate_think_time_ms(remaining, 500, 0, moves_to_go=moves_to_go)
                self.assertGreaterEqual(t, max(previous, 10))
                if remaining >= 200:
                    self.assertLessEqual(t, remaining - 50)
                previous = t

    def test_never_flags_simulation(self):
        # 5+0 : en dépensant exactement le budget à chaque coup, on finit 150 coups
        # sans épuiser la pendule.
        remaining = 300_000
        for ply in range(0, 300, 2):
            spent = allocate_think_time_ms(remaining, 0, ply)
            remaining -= spent
            self.assertGreater(remaining, 0)


if __name__ == "__main__":
    unittest.main()
