"""
Tests perft
-----------
Comptage des nœuds de l'arbre des coups légaux et comparaison aux valeurs de
référence publiées (Chess Programming Wiki). C'est la validation de référence du
générateur de coups : broches, échecs, roque, en passant, promotions, échec à la
découverte en prise en passant.

Les cas profonds (lents) portent le marqueur ``slow`` : ``pytest -m slow``.
"""
import unittest

import pytest

from fen_utils import load_fen, perft

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
KIWIPETE = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
POS3 = "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"
POS4 = "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1"
POS5 = "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8"
POS6 = "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10"


class TestPerft(unittest.TestCase):
    def _check(self, fen, cases):
        for depth, expected in cases:
            with self.subTest(fen=fen, depth=depth):
                self.assertEqual(perft(load_fen(fen), depth), expected)

    def test_startpos(self):
        self._check(START, [(1, 20), (2, 400), (3, 8902), (4, 197281)])

    def test_kiwipete(self):
        self._check(KIWIPETE, [(1, 48), (2, 2039), (3, 97862)])

    def test_position_3(self):
        self._check(POS3, [(1, 14), (2, 191), (3, 2812), (4, 43238)])

    def test_position_4(self):
        self._check(POS4, [(1, 6), (2, 264), (3, 9467)])

    def test_position_5(self):
        self._check(POS5, [(1, 44), (2, 1486), (3, 62379)])

    def test_position_6(self):
        self._check(POS6, [(1, 46), (2, 2079), (3, 89890)])

    @pytest.mark.slow
    def test_slow_deep(self):
        self._check(START, [(5, 4865609)])
        self._check(KIWIPETE, [(4, 4085603)])
        self._check(POS3, [(5, 674624)])
        self._check(POS4, [(4, 422333)])
        self._check(POS5, [(4, 2103487)])


if __name__ == "__main__":
    unittest.main()
