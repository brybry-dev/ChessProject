"""
Tests de non-régression sur les règles
--------------------------------------
Verrouille les bugs corrigés lors de l'étape « règles justes » :
  - détection du pat (auparavant jamais signalé) ;
  - échec et mat ;
  - matériel insuffisant resserré (K+Q vs K n'est PAS une nulle) ;
  - triple répétition avec clé de position complète ;
  - roque interdit à travers une case contrôlée par un pion ;
  - broches recalculées avant la génération des coups ;
  - sous-promotions générées ;
  - prise en passant interdite si elle expose le roi (échec à la découverte).
"""

import unittest

import ChessEngine
from fen_utils import load_fen


class TestEndOfGame(unittest.TestCase):
    def test_stalemate_detected(self):
        gs = load_fen("k7/8/1Q6/2K5/8/8/8/8 b - - 0 1")
        moves = gs.getValidMoves()
        self.assertEqual(moves, [])
        self.assertTrue(gs.stalemate)
        self.assertFalse(gs.checkmate)

    def test_checkmate_detected(self):
        gs = load_fen("r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4")
        gs.getValidMoves()
        self.assertTrue(gs.checkmate)
        self.assertFalse(gs.stalemate)

    def test_king_and_queen_vs_king_is_not_a_draw(self):
        gs = load_fen("8/8/8/4k3/8/8/4Q3/4K3 w - - 0 1")
        self.assertFalse(gs.insufficient_material())

    def test_same_colour_bishops_is_a_draw(self):
        self.assertTrue(load_fen("8/8/4k3/8/2b5/8/4B3/4K3 w - - 0 1").insufficient_material())

    def test_opposite_colour_bishops_is_not_a_draw(self):
        self.assertFalse(load_fen("8/8/4k3/8/1b6/8/4B3/4K3 w - - 0 1").insufficient_material())


class TestThreefoldRepetition(unittest.TestCase):
    def test_shuffling_knights_three_times_is_a_draw(self):
        gs = ChessEngine.GameState()

        def play(notation):
            for m in gs.getValidMoves():
                if str(m) == notation:
                    gs.makeMove(m, validate=False)
                    return
            raise AssertionError(f"coup introuvable : {notation}")

        for notation in ["Nf3", "Nf6", "Ng1", "Ng8"] * 2:
            play(notation)
        gs.getValidMoves()
        self.assertTrue(gs.stalemate, "la triple répétition doit être réclamée comme nulle")


class TestCastlingSafety(unittest.TestCase):
    def test_cannot_castle_through_square_attacked_by_pawn(self):
        # Pion noir en g2 : il contrôle f1 (case vide). Le petit roque passe par f1.
        gs = load_fen("4k3/8/8/8/8/8/6p1/4K2R w K - 0 1")
        castles = [m for m in gs.getValidMoves() if m.is_castle_move]
        self.assertEqual(castles, [])

    def test_can_castle_when_path_is_clear(self):
        gs = load_fen("4k3/8/8/8/8/8/8/4K2R w K - 0 1")
        castles = [m for m in gs.getValidMoves() if m.is_castle_move]
        self.assertEqual(len(castles), 1)


class TestPinsRecomputed(unittest.TestCase):
    def test_pinned_knight_has_no_moves_on_first_evaluation(self):
        # Cavalier e2 cloué par la tour e8 sur le roi e1.
        gs = load_fen("4r2k/8/8/8/8/8/4N3/4K3 w - - 0 1")
        knight_moves = [m for m in gs.getValidMoves() if m.piece_moved == "wN"]
        self.assertEqual(knight_moves, [])

    def test_get_valid_moves_is_idempotent(self):
        gs = load_fen("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1")
        first = len(gs.getValidMoves())
        gs._valid_moves = None
        second = len(gs.getValidMoves())
        self.assertEqual(first, second)


class TestPromotion(unittest.TestCase):
    def test_all_four_promotions_are_generated(self):
        gs = load_fen("8/P7/8/8/8/8/8/K6k w - - 0 1")
        promos = {m.promotion_piece for m in gs.getValidMoves() if m.is_pawn_promotion}
        self.assertEqual(promos, {"Q", "R", "B", "N"})

    def test_underpromotion_to_knight_is_applied(self):
        gs = load_fen("8/P7/8/8/8/8/8/K6k w - - 0 1")
        move = next(
            m for m in gs.getValidMoves() if m.is_pawn_promotion and m.promotion_piece == "N"
        )
        gs.makeMove(move, validate=False)
        self.assertEqual(gs.board[0][0], "wN")


class TestEnPassantDiscoveredCheck(unittest.TestCase):
    def test_en_passant_forbidden_when_it_exposes_the_king_on_the_rank(self):
        gs = load_fen("8/8/8/KppP3r/8/8/8/7k w - b6 0 1")
        ep = [m for m in gs.getValidMoves() if m.is_enpassant_move]
        self.assertEqual(ep, [])

    def test_en_passant_allowed_when_no_discovered_check(self):
        gs = load_fen("8/8/8/K1pP4/7r/8/8/7k w - c6 0 1")
        ep = [m for m in gs.getValidMoves() if m.is_enpassant_move]
        self.assertEqual(len(ep), 1)


if __name__ == "__main__":
    unittest.main()
