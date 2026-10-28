"""Optimisations du moteur sans changement de résultat (J10.1).

Les optimisations de vitesse ne doivent changer ni les coups légaux, ni l'évaluation, ni
l'arbre de recherche. Les valeurs de référence ci-dessous ont été calculées avec le code
d'avant J10 : si l'une change, c'est un changement d'algorithme, à mesurer en
mini-ligue (J10.2) et à reporter ici.
"""

import random
import unittest

from chessproject.ai import evaluate
from chessproject.ai.search import Searcher, SearchLimits
from chessproject.core.fen import load_fen, to_fen

FENS = [
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
    "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
]


def _random_positions():
    """Positions de 40 parties aléatoires (graine fixe), fins de partie comprises."""
    rng = random.Random(20261028)
    for fen in FENS:
        for _ in range(10):
            gs = load_fen(fen)
            for _ in range(60):
                yield gs
                moves = gs.get_valid_moves()
                if not moves:
                    break
                gs.make_move(rng.choice(moves), validate=False)


class HasLegalMovesTests(unittest.TestCase):
    def test_agrees_with_the_full_generation(self):
        checked = 0
        for gs in _random_positions():
            gs._valid_moves = None
            expected_in_check = gs.king_in_check()
            has_moves = gs.has_legal_moves()
            self.assertEqual(gs.in_check, expected_in_check)
            gs._valid_moves = None
            self.assertEqual(has_moves, bool(gs.get_valid_moves()))
            checked += 1
        self.assertGreater(checked, 2000)

    def test_draws_count_as_no_legal_move(self):
        gs = load_fen("8/8/8/4k3/8/8/8/4K3 w - - 0 1")  # roi contre roi
        self.assertFalse(gs.has_legal_moves())
        gs = load_fen("4k3/8/8/8/8/8/8/R3K3 w - - 100 80")  # 50 coups
        self.assertFalse(gs.has_legal_moves())

    def test_mate_is_recognised(self):
        gs = load_fen("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
        self.assertFalse(gs.has_legal_moves())
        self.assertTrue(gs.checkmate)


class EvaluationTests(unittest.TestCase):
    def test_scores_match_the_reference(self):
        evaluate._pawn_cache.clear()
        scores = [evaluate.evaluate(gs) for gs in _random_positions()]
        # Calculé avant J10 (sans tables fusionnées ni cache des pions).
        self.assertEqual(
            (len(scores), sum(scores), sum(i * s for i, s in enumerate(scores))),
            (2312, 136914, 226010254),
        )

    def test_the_pawn_cache_gives_the_same_score(self):
        positions = [load_fen(to_fen(gs)) for gs in _random_positions()][::7]
        warm = [evaluate.evaluate(gs) for gs in positions]
        cold = []
        for gs in positions:
            evaluate._pawn_cache.clear()
            cold.append(evaluate.evaluate(gs))
        self.assertEqual(warm, cold)


# Nœuds à profondeur 3 sur FENS, avant J10.
REFERENCE_NODES_DEPTH_3: list[int] = [633, 25638, 592, 15183]


class SearchTreeTests(unittest.TestCase):
    def test_node_counts_match_the_reference(self):
        # Signature de l'arbre : nombre de nœuds à profondeur 3 (cf. tools/bench.py).
        nodes = [Searcher().think(load_fen(fen), SearchLimits(depth=3)).nodes for fen in FENS]
        self.assertEqual(nodes, REFERENCE_NODES_DEPTH_3)
