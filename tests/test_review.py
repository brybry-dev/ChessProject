"""Tests du bilan de partie (J9.3) : seuils, parties de référence, pilotage du processus."""

import queue
import unittest

import pytest

from chessproject.ai import review, search
from chessproject.core import engine, notation

MATE = search.MATE


def play(sans):
    """(position de départ, coups) de la partie ``sans``."""
    gs = engine.GameState()
    moves = []
    for san in sans:
        move = notation.parse_san(gs, san)
        moves.append(move)
        gs.make_move(move)
    return engine.GameState(), moves


def evaluate_game(sans, nodes=review.REVIEW_NODES):
    start, moves = play(sans)
    q: queue.Queue = queue.Queue()
    review.run(start, moves, q, nodes)
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    assert items[-1] is None, items
    assert [item[0] for item in items[:-1]] == list(range(len(sans) + 1))
    evals = [item[1] for item in items[:-1]]
    played = [item[2] for item in items[:-2]]
    assert items[-2][2] is None
    return review.build(evals, sans, True, 1, played)


class TestThresholds(unittest.TestCase):
    def test_expected_score(self):
        self.assertAlmostEqual(review.expected_score(0), 0.5)
        self.assertEqual(review.expected_score(MATE - 3), 1.0)
        self.assertEqual(review.expected_score(-(MATE - 3)), 0.0)
        self.assertAlmostEqual(review.expected_score(400), 10 / 11)

    def test_classify_on_the_drop_of_expected_score(self):
        self.assertIsNone(review.classify(0.1999))
        self.assertEqual(review.classify(0.20), review.INACCURACY)
        self.assertEqual(review.classify(0.2999), review.INACCURACY)
        self.assertEqual(review.classify(0.30), review.MISTAKE)
        self.assertEqual(review.classify(0.40), review.BLUNDER)
        self.assertEqual(review.classify(1.0), review.BLUNDER)

    def test_same_centipawns_matter_less_when_the_game_is_decided(self):
        # -400 cp depuis l'égalité : gaffe ; depuis +900 : rien.
        level = review.build([0, -400], ["Qh5"], True, 1).moves[0]
        winning = review.build([900, 500], ["Qh5"], True, 1).moves[0]
        self.assertEqual(level.judgement, review.BLUNDER)
        self.assertIsNone(winning.judgement)
        self.assertEqual((level.loss_cp, winning.loss_cp), (400, 400))

    def test_the_played_move_is_compared_with_the_best_one(self):
        # Position suivante à +50 mais coup joué évalué à -300 au même horizon.
        r = review.build([0, 50], ["Qh5"], True, 1, played=[-300])
        self.assertEqual((r.moves[0].loss_cp, r.moves[0].judgement), (300, review.MISTAKE))

    def test_loss_is_from_the_mover_point_of_view(self):
        # Les noirs jouent : le score blanc qui monte est une perte pour eux.
        r = review.build([0, 0, 250], ["e4", "f6"], True, 1)
        self.assertEqual(r.moves[0].loss_cp, 0)
        self.assertEqual(r.moves[1].loss_cp, 250)
        self.assertFalse(r.moves[1].white)
        self.assertEqual(r.moves[1].judgement, review.MISTAKE)
        self.assertEqual((r.black.mistakes, r.black.acpl), (1, 250))
        self.assertEqual((r.white.mistakes, r.white.acpl), (0, 0))

    def test_improving_moves_cost_nothing_and_mates_are_capped(self):
        r = review.build([0, 80, -(MATE - 1)], ["e4", "Qh4#"], True, 1)
        self.assertEqual(r.moves[0].loss_cp, 0)
        r = review.build([0, -(MATE - 2)], ["g4"], True, 1)
        self.assertEqual(r.moves[0].loss_cp, review.EVAL_CAP_CP)

    def test_numbering_and_symbols(self):
        r = review.build([0, 250, 250], ["Nf6", "Qxf7"], False, 12)
        self.assertEqual([m.label for m in r.moves], ["12... Nf6", "13. Qxf7"])
        self.assertEqual([m.symbol for m in r.moves], ["?", ""])
        self.assertEqual(review.SYMBOLS, {"inaccuracy": "?!", "mistake": "?", "blunder": "??"})


class TestReferenceGames(unittest.TestCase):
    """Parties de référence jouées par le moteur (budget de nœuds : résultats stables)."""

    def test_fools_mate(self):
        r = evaluate_game(["f3", "e5", "g4", "Qh4#"])
        self.assertEqual(r.moves[2].judgement, review.BLUNDER)  # g4??
        self.assertIsNone(r.moves[3].judgement)
        self.assertEqual(r.evals[-1], -MATE)
        self.assertEqual(r.white.blunders, 1)
        self.assertEqual(r.black.blunders + r.black.mistakes, 0)

    def test_scholars_mate(self):
        r = evaluate_game(["e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6", "Qxf7#"])
        self.assertEqual(r.moves[5].judgement, review.BLUNDER)  # Nf6??
        self.assertEqual(r.black.blunders, 1)
        self.assertEqual(r.evals[-1], MATE)

    def test_hanging_bishop(self):
        r = evaluate_game(["d4", "e5", "Bg5", "Qxg5"])
        self.assertIn(r.moves[2].judgement, (review.MISTAKE, review.BLUNDER))  # Bg5
        self.assertIsNone(r.moves[3].judgement)  # Qxg5 est le bon coup

    def assert_no_error(self, games):
        # Parties de théorie : ces coups sont corrects, le bilan ne doit rien signaler
        # (c'est ce qui fixe le seuil d'imprécision, cf. le module).
        for game in games:
            with self.subTest(game=game[:20]):
                r = evaluate_game(game.split())
                flagged = [m.label for m in r.moves if m.judgement]
                self.assertEqual(flagged, [])

    def test_ruy_lopez_has_no_error(self):
        # La plus piégeuse à profondeur 3 (Bxc6 puis Nxe5 semble gagner un pion).
        self.assert_no_error(
            ["e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O h3 Nb8 d4 Nbd7"]
        )

    @pytest.mark.slow
    def test_more_theory_games_have_no_error(self):
        self.assert_no_error(
            [
                "d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7 e3 O-O Nf3 Nbd7 Rc1 c6 Bd3 dxc4 Bxc4 Nd5",
                "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6 Be3 e5 Nb3 Be6 f3 Be7 Qd2 O-O O-O-O Nbd7",
                "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d3 d6 O-O O-O Re1 a6 Bb3 Ba7 h3 h6 Nbd2 Re8",
            ]
        )


class _InlineProcess:
    def __init__(self, target, args=(), daemon=False):
        self._target, self._args = target, args
        self.terminated = False

    def start(self):
        self._target(*self._args)

    def is_alive(self):
        return False

    def terminate(self):
        self.terminated = True


class TestReviewer(unittest.TestCase):
    def test_collects_every_position_then_builds_the_review(self):
        start, moves = play(["f3", "e5", "g4", "Qh4#"])
        reviewer = review.Reviewer(process=_InlineProcess, make_queue=queue.Queue, nodes=500)
        reviewer.start(start, moves, "k")
        self.assertEqual(reviewer.poll(), 5)
        self.assertTrue(reviewer.done)
        result = reviewer.result()
        assert result is not None
        self.assertEqual(result.moves[2].san, "g4")
        reviewer.start(start, moves, "k")  # même partie : rien n'est relancé
        self.assertTrue(reviewer.done)

    def test_result_waits_for_every_position(self):
        start, moves = play(["e4"])
        reviewer = review.Reviewer(process=_InlineProcess, make_queue=queue.Queue)
        reviewer.key, reviewer.evals, reviewer.sans = "k", [0], ["e4"]
        self.assertIsNone(reviewer.result())

    def test_stop(self):
        start, moves = play(["e4"])
        reviewer = review.Reviewer(process=_InlineProcess, make_queue=queue.Queue, nodes=200)
        reviewer.start(start, moves, "k")
        reviewer.stop()
        self.assertIsNone(reviewer.key)
        self.assertEqual(reviewer.evals, [])


if __name__ == "__main__":
    unittest.main()
