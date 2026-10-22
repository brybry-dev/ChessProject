"""Tests des termes de l'évaluation (J3.6).

Chaque test compare deux positions qui ne diffèrent que par le terme visé ; la symétrie
par miroir des couleurs est vérifiée dans tests/test_ai.py.
"""

import unittest

from chessproject.ai.evaluate import evaluate
from chessproject.core.fen import load_fen


def ev(fen: str) -> int:
    return evaluate(load_fen(fen))


class PhaseTests(unittest.TestCase):
    def test_king_is_centralised_in_the_endgame(self):
        # Finale de pions : roi blanc au centre plutôt que dans le coin.
        self.assertGreater(ev("7k/8/8/8/3K4/8/P7/8 w - - 0 1"), ev("7k/8/8/8/8/8/P7/K7 w - - 0 1"))

    def test_king_stays_sheltered_in_the_middlegame(self):
        start_like = "r1bq1rk1/pppp1ppp/2n2n2/2b1p3/2B1P3/2N2N2/PPPP1PPP/R1BQ{} w - - 0 1"
        castled = ev(start_like.format("1RK1"))
        exposed = ev("r1bq1rk1/pppp1ppp/2n2n2/2b1p3/2B1P3/2N1KN2/PPPP1PPP/R1BQ3R w - - 0 1")
        self.assertGreater(castled, exposed)


class PawnStructureTests(unittest.TestCase):
    def test_passed_pawn_bonus_grows_with_its_rank(self):
        scores = [
            ev("7k/8/8/8/8/8/8/K7 w - - 0 1".replace("8/8/8/8/8/8", rows))
            for rows in (
                "8/8/8/8/8/P7",  # a3
                "8/8/8/P7/8/8",  # a5
                "P7/8/8/8/8/8",  # a7
            )
        ]
        self.assertLess(scores[0], scores[1])
        self.assertLess(scores[1], scores[2])

    def test_passed_pawn_is_worth_more_than_a_blocked_one(self):
        passed = ev("7k/8/8/8/P7/8/7p/K7 w - - 0 1")
        blocked = ev("7k/8/p7/8/P7/8/8/K7 w - - 0 1")
        self.assertGreater(
            passed - ev("7k/8/8/8/8/8/7p/K7 w - - 0 1"),
            blocked - ev("7k/8/p7/8/8/8/8/K7 w - - 0 1"),
        )

    def test_doubled_pawns_are_penalised(self):
        doubled = ev("4k3/pp6/8/8/8/2P5/2P5/4K3 w - - 0 1")
        healthy = ev("4k3/pp6/8/8/8/8/2PP4/4K3 w - - 0 1")
        self.assertLess(doubled, healthy)

    def test_isolated_pawn_is_penalised(self):
        isolated = ev("4k3/8/8/8/8/8/P1P5/4K3 w - - 0 1")
        connected = ev("4k3/8/8/8/8/8/PP6/4K3 w - - 0 1")
        self.assertLess(isolated, connected)


class PieceTermsTests(unittest.TestCase):
    def test_bishop_pair_bonus(self):
        pair = ev("4k3/pppppppp/8/8/8/8/PPPPPPPP/2B1KB2 w - - 0 1")
        bishop_knight = ev("4k3/pppppppp/8/8/8/8/PPPPPPPP/2B1KN2 w - - 0 1")
        self.assertGreater(pair - bishop_knight, 0)

    def test_rook_prefers_an_open_file(self):
        open_file = ev("4k3/pp4pp/8/8/8/8/PP4PP/3RK3 w - - 0 1")
        closed_file = ev("4k3/pp1p2pp/8/8/8/8/PP1P2PP/3RK3 w - - 0 1")
        # La différence de matériel (deux pions d) s'annule ; reste le bonus de colonne.
        self.assertGreater(open_file, closed_file)


if __name__ == "__main__":
    unittest.main()
