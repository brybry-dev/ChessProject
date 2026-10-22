"""Tests du hachage de Zobrist (J3.1).

La clé est mise à jour de façon incrémentale à chaque coup et restaurée à
l'annulation : elle doit toujours être égale au recalcul complet, quelles que
soient les règles spéciales (roques, en passant, promotions, perte des droits de
roque), et identique d'un processus Python à l'autre (B32).
"""

import os
import random
import subprocess
import sys
import unittest

from chessproject.core import engine
from chessproject.core.fen import load_fen

FENS = [
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
    "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
    "8/PPP4k/8/8/8/8/4Kppp/8 w - - 0 1",
]


class ZobristTests(unittest.TestCase):
    def test_incremental_key_matches_full_recomputation(self):
        positions = 0
        for fen_index, fen in enumerate(FENS):
            for game in range(8):
                rng = random.Random(100 * fen_index + game)
                gs = load_fen(fen)
                keys = [gs.zobrist_key]
                self.assertEqual(gs.zobrist_key, gs.compute_zobrist_key())
                for _ in range(80):
                    moves = gs.get_valid_moves()
                    if not moves:
                        break
                    gs.make_move(rng.choice(moves), validate=False)
                    positions += 1
                    with self.subTest(fen=fen, game=game, ply=len(gs.move_log)):
                        self.assertEqual(gs.zobrist_key, gs.compute_zobrist_key())
                    keys.append(gs.zobrist_key)
                # L'annulation restaure exactement chaque clé précédente.
                while gs.move_log:
                    keys.pop()
                    gs.undo_move()
                    self.assertEqual(gs.zobrist_key, keys[-1])
        self.assertGreater(positions, 1000)

    def test_key_distinguishes_side_castling_rights_and_en_passant(self):
        base = "r3k2r/8/8/3pP3/8/8/8/R3K2R w KQkq d6 0 1"
        variants = [
            base,
            "r3k2r/8/8/3pP3/8/8/8/R3K2R w Kkq d6 0 1",
            "r3k2r/8/8/3pP3/8/8/8/R3K2R w KQkq - 0 1",
            "r3k2r/8/8/3pP3/8/8/8/R3K2R b KQkq - 0 1",
        ]
        keys = {load_fen(fen).zobrist_key for fen in variants}
        self.assertEqual(len(keys), len(variants))

    def test_transposition_gives_the_same_key(self):
        a, b = engine.GameState(), engine.GameState()
        for gs, order in ((a, ("g1f3", "g8f6", "b1c3")), (b, ("b1c3", "g8f6", "g1f3"))):
            for uci in order:
                start = (8 - int(uci[1]), "abcdefgh".index(uci[0]))
                end = (8 - int(uci[3]), "abcdefgh".index(uci[2]))
                gs.make_move(
                    next(
                        m
                        for m in gs.get_valid_moves()
                        if (m.start_row, m.start_col, m.end_row, m.end_col) == (*start, *end)
                    )
                )
        self.assertEqual(a.zobrist_key, b.zobrist_key)

    def test_key_is_the_same_in_every_process(self):
        script = (
            "from chessproject.core import engine;"
            "g = engine.GameState();"
            "g.make_move([m for m in g.get_valid_moves() if str(m) == 'e4'][0]);"
            "print(g.zobrist_key)"
        )
        outputs = {
            subprocess.run(
                [sys.executable, "-c", script],
                env=dict(os.environ, PYTHONHASHSEED=str(seed)),
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            for seed in (1, 2)
        }
        self.assertEqual(len(outputs), 1)


if __name__ == "__main__":
    unittest.main()
