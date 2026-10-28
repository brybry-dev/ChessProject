"""Tests de la recherche (J3.2 – J3.5) : limites, table de transposition à bornes,
ordonnancement, quiescence, ligne principale."""

import unittest

from chessproject.ai import search
from chessproject.ai.search import Searcher, SearchLimits
from chessproject.core import engine
from chessproject.core.fen import load_fen
from chessproject.core.notation import to_san

KIWIPETE = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
# Position plus calme (partie italienne) : recherches à profondeur 3 en ~0,3 s.
ITALIAN = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"


class FakeClock:
    """Horloge qui avance d'un pas fixe à chaque lecture : rend les tests de temps
    déterministes."""

    def __init__(self, step_s: float) -> None:
        self.now = 0.0
        self.step_s = step_s

    def __call__(self) -> float:
        self.now += self.step_s
        return self.now


def _state(gs):
    return (
        [row[:] for row in gs.board],
        gs.white_to_move,
        len(gs.move_log),
        gs.zobrist_key,
        dict(gs.position_history),
        gs.fifty_move_counter,
    )


class LimitsTests(unittest.TestCase):
    def test_depth_limit(self):
        result = search.think(engine.GameState(), SearchLimits(depth=2))
        self.assertEqual(result.depth, 2)
        self.assertIn(result.move, engine.GameState().get_valid_moves())

    def test_node_limit_is_respected_and_still_returns_a_move(self):
        gs = load_fen(KIWIPETE)
        result = search.think(gs, SearchLimits(nodes=500))
        self.assertLessEqual(result.nodes, 500)
        self.assertIn(result.move, gs.get_valid_moves())

    def test_time_limit_is_respected(self):
        # Chaque lecture d'horloge avance de 50 ms ; limite de 200 ms.
        gs = load_fen(KIWIPETE)
        searcher = Searcher(clock=FakeClock(0.050))
        result = searcher.think(gs, SearchLimits(movetime_ms=200))
        self.assertIn(result.move, gs.get_valid_moves())
        self.assertLess(result.depth, search.MAX_PLY)
        # Dépassement borné : au plus une lecture d'horloge après l'échéance (+ la lecture finale).
        self.assertLessEqual(result.elapsed_ms, 200 + 2 * 50)

    def test_aborted_search_leaves_the_position_intact(self):
        gs = load_fen(KIWIPETE)
        before = _state(gs)
        search.think(gs, SearchLimits(nodes=3000))
        self.assertEqual(_state(gs), before)

    def test_deeper_search_only_replaces_the_move_when_completed(self):
        # Avec un budget minuscule, la profondeur 1 n'est même pas finie : on garde le
        # premier coup ordonné, qui est légal.
        gs = engine.GameState()
        result = search.think(gs, SearchLimits(nodes=3))
        self.assertEqual(result.depth, 0)
        self.assertIn(result.move, gs.get_valid_moves())


class TranspositionTableTests(unittest.TestCase):
    def test_mate_scores_are_stored_relative_to_the_node(self):
        for ply in (0, 3, 17):
            for score in (search.MATE - 5, -search.MATE + 9, 123, -40):
                stored = search._to_tt_score(score, ply)
                self.assertEqual(search._from_tt_score(stored, ply), score)
        # Un mat en 2 vu à 3 demi-coups de la racine vaut un mat en 5 depuis la racine.
        self.assertEqual(
            search._from_tt_score(search._to_tt_score(search.MATE - 5, 3), 1), search.MATE - 3
        )

    def test_reusing_the_table_gives_the_same_answer(self):
        gs = load_fen(ITALIAN)
        searcher = Searcher()
        first = searcher.think(gs, SearchLimits(depth=3))
        second = searcher.think(gs, SearchLimits(depth=3))
        self.assertEqual(first.score, second.score)
        self.assertLess(second.nodes, first.nodes)


class QuiescenceTests(unittest.TestCase):
    def test_does_not_grab_a_defended_pawn_with_the_queen(self):
        # Dxd5 gagne un pion à profondeur 1… mais e6xd5 reprend la dame (effet d'horizon).
        gs = load_fen("4k3/8/4p3/3p4/8/8/3Q4/4K3 w - - 0 1")
        result = search.think(gs, SearchLimits(depth=1))
        assert result.move is not None
        self.assertNotEqual(to_san(gs, result.move), "Qxd5")

    def test_quiet_position_evaluates_like_the_static_evaluation(self):
        gs = engine.GameState()
        searcher = Searcher()
        score = searcher.quiescence(gs, gs.get_valid_moves(), -search.INF, search.INF, 0)
        self.assertEqual(score, search.score_board(gs))


class PrincipalVariationTests(unittest.TestCase):
    def test_pv_is_legal_and_starts_with_the_best_move(self):
        gs = load_fen(ITALIAN)
        before = _state(gs)
        result = search.think(gs, SearchLimits(depth=3))
        self.assertTrue(result.pv)
        self.assertEqual(result.pv[0], result.move)
        self.assertEqual(_state(gs), before)
        for move in result.pv:
            self.assertIn(move, gs.get_valid_moves())
            gs.make_move(move, validate=False)


class OrderingTests(unittest.TestCase):
    def test_ordering_puts_the_tt_move_then_captures_first(self):
        gs = load_fen(KIWIPETE)
        moves = gs.get_valid_moves()
        quiet = next(m for m in moves if not m.is_capture)
        ordered = Searcher()._ordered(gs, moves, quiet, 0)
        self.assertEqual(ordered[0], quiet)
        n_captures = sum(m.is_capture or m.is_pawn_promotion for m in moves)
        self.assertTrue(
            all(m.is_capture or m.is_pawn_promotion for m in ordered[1 : 1 + n_captures])
        )
        self.assertEqual(sorted(m.move_id for m in ordered), sorted(m.move_id for m in moves))


class FeaturesTests(unittest.TestCase):
    """Techniques d'élagage (J10.2)."""

    def test_parse(self):
        parse = search.SearchFeatures.parse
        self.assertEqual(parse("none"), search.NO_FEATURES)
        self.assertEqual(parse("pvs, lmr"), search.SearchFeatures(pvs=True, lmr=True))
        self.assertEqual(str(parse("all")), "pvs,aspiration,null_move,lmr")
        self.assertEqual(str(search.NO_FEATURES), "none")
        with self.assertRaises(ValueError):
            parse("pvs,futility")

    def test_pvs_gives_the_same_score_with_fewer_nodes(self):
        for fen in (KIWIPETE, ITALIAN):
            plain = Searcher(features=search.NO_FEATURES).think(
                load_fen(fen), SearchLimits(depth=3)
            )
            pvs = Searcher(features=search.SearchFeatures(pvs=True)).think(
                load_fen(fen), SearchLimits(depth=3)
            )
            self.assertEqual(pvs.score, plain.score)
            self.assertLessEqual(pvs.nodes, plain.nodes)

    def test_all_features_leave_the_position_intact_and_find_the_mate(self):
        gs = load_fen("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1")  # Rd8#
        before = _state(gs)
        result = Searcher(features=search.SearchFeatures.parse("all")).think(
            gs, SearchLimits(depth=4)
        )
        self.assertEqual(to_san(gs, result.move), "Rd8#")
        self.assertEqual(_state(gs), before)
        gs = load_fen(KIWIPETE)
        before = _state(gs)
        Searcher(features=search.SearchFeatures.parse("all")).think(gs, SearchLimits(depth=4))
        self.assertEqual(_state(gs), before)

    def test_null_move_is_undone_exactly(self):
        gs = engine.GameState()
        gs.make_move(next(m for m in gs.get_valid_moves() if to_san(gs, m) == "e4"))
        self.assertIsNotNone(gs.enpassant_possible)  # case d'en passant à effacer
        before = (_state(gs), gs.enpassant_possible, list(gs.position_keys))
        old = gs.make_null_move()
        self.assertTrue(gs.white_to_move)
        self.assertIsNone(gs.enpassant_possible)
        self.assertEqual(gs.zobrist_key, gs.compute_zobrist_key())
        gs.make_move(gs.get_valid_moves()[0], validate=False)
        gs.undo_move()
        gs.undo_null_move(old)
        self.assertEqual((_state(gs), gs.enpassant_possible, list(gs.position_keys)), before)

    def test_null_move_is_not_tried_without_pieces(self):
        # Finale de pions : zugzwang fréquent, le coup nul fausserait la recherche.
        self.assertFalse(search._has_pieces(load_fen("8/2k5/3p4/p2P1p2/P4P2/8/6K1/8 w - - 0 50")))
        self.assertTrue(search._has_pieces(load_fen(KIWIPETE)))


if __name__ == "__main__":
    unittest.main()
