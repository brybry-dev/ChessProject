"""Tests du bilan de partie (J9.3) : seuils, parties de référence, pilotage du processus."""

import io
import queue
import unittest

import pytest

from chessproject.ai import review, search
from chessproject.core import engine, notation, pgn

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
    lines = [item[3] for item in items[:-1]]
    assert items[-2][2] is None
    return review.build(evals, sans, True, 1, played, lines)


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


class TestBestLine(unittest.TestCase):
    """J13.1 : pour chaque faute, le meilleur coup du moteur et sa variante."""

    def assert_legal(self, sans, ply, line):
        """La variante se rejoue depuis la position qui précède le coup ``ply``."""
        gs = engine.GameState()
        for san in sans[: ply - 1]:
            gs.make_move(notation.parse_san(gs, san))
        for san in line:
            move = notation.parse_san(gs, san)
            self.assertEqual(notation.to_san(gs, move), san)
            gs.make_move(move)

    def test_every_fault_comes_with_a_legal_better_line(self):
        sans = ["e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6", "Qxf7#"]
        r = evaluate_game(sans)
        nf6 = r.moves[5]
        self.assertEqual(nf6.judgement, review.BLUNDER)
        self.assertTrue(nf6.best)
        self.assertNotEqual(nf6.best[0], "Nf6")
        self.assert_legal(sans, nf6.ply, nf6.best)
        # Le meilleur coup pare le mat : aucun coup des Blancs ne mate ensuite.
        gs = engine.GameState()
        for san in sans[:5]:
            gs.make_move(notation.parse_san(gs, san))
        gs.make_move(notation.parse_san(gs, nf6.best[0]))
        for move in list(gs.get_valid_moves()):
            self.assertFalse(notation.to_san(gs, move).endswith("#"))
        self.assertTrue(nf6.best_line.startswith(f"3... {nf6.best[0]}"))
        for move in r.moves:
            with self.subTest(move=move.label):
                self.assert_legal(sans, move.ply, move.best)

    def test_the_line_stops_at_the_first_illegal_move(self):
        gs = engine.GameState()
        e4 = notation.parse_san(gs, "e4")
        gs.make_move(e4)
        e5 = notation.parse_san(gs, "e5")
        gs.undo_move()
        before = [row[:] for row in gs.board]
        # e5 n'est pas jouable par les Blancs : la variante s'arrête là.
        self.assertEqual(review.legal_line(gs, [e4, e5, e4]), ("e4", "e5"))
        self.assertEqual(review.legal_line(gs, [e5, e4]), ())
        self.assertEqual(gs.board, before)
        self.assertEqual(gs.move_log, [])

    def test_numbered_line(self):
        r = review.build([0, 250, 250], ["Nf6", "Qxf7"], False, 12, lines=[("Nc6", "d4"), ()])
        self.assertEqual(r.moves[0].best_line, "12... Nc6 13. d4")
        self.assertEqual(r.moves[1].best_line, "")
        with self.assertRaises(ValueError):
            review.build([0, 250, 250], ["Nf6", "Qxf7"], False, 12, lines=[()])


class TestPgnAnnotations(unittest.TestCase):
    """J13.2 : symboles en NAG et évaluations en commentaires ``[%eval]``."""

    def test_eval_format(self):
        self.assertEqual(review.pgn_eval(42), "0.42")
        self.assertEqual(review.pgn_eval(-130), "-1.30")
        self.assertEqual(review.pgn_eval(0), "0.00")
        self.assertEqual(review.pgn_eval(MATE - 1), "#1")
        self.assertEqual(review.pgn_eval(MATE - 5), "#3")
        self.assertEqual(review.pgn_eval(-(MATE - 4)), "#-2")
        self.assertIsNone(review.pgn_eval(-MATE))  # position matée : rien à évaluer
        self.assertEqual(review.NAGS, {"inaccuracy": 6, "mistake": 2, "blunder": 4})

    def test_annotated_game_read_back_by_python_chess(self):
        chess_pgn = pytest.importorskip("chess.pgn")
        sans = ["f3", "e5", "g4", "Qh4#"]
        r = evaluate_game(sans)
        gs = engine.GameState()
        for san in sans:
            gs.make_move(notation.parse_san(gs, san))
        text = pgn.export_pgn(gs, annotations=review.pgn_annotations(r))
        game = chess_pgn.read_game(io.StringIO(text))
        self.assertEqual(game.errors, [])
        nodes = list(game.mainline())
        self.assertEqual([n.san() for n in nodes], sans)
        self.assertEqual(nodes[2].nags, {4})  # g4??
        self.assertEqual(nodes[2].eval().white().mate(), -1)  # mat en 1 pour les Noirs
        self.assertIsNone(nodes[3].eval())  # mat sur l'échiquier : pas d'évaluation
        for node, move in zip(nodes[:3], r.moves[:3], strict=True):
            self.assertEqual(node.nags, {review.NAGS[move.judgement]} if move.judgement else set())
        self.assertEqual(nodes[0].eval().white().score(), r.evals[1])
        # Et notre import relit le fichier.
        self.assertEqual(pgn.parse_pgn(text)[0].moves, sans)


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
        self.assertTrue(result.moves[2].best)  # variante gardée (J13.1)
        self.assertEqual(result.moves[3].best[0], "Qh4#")
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
