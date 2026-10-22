import time
import unittest
from enum import Enum
from multiprocessing import Process, Queue

import ChessAI
import ChessEngine


class Color(Enum):
    WHITE = "w"
    BLACK = "b"


class TestChessRules(unittest.TestCase):
    def setUp(self):
        self.game = ChessEngine.GameState()

    def test_insufficient_material(self):
        # Test : roi seul vs roi seul
        self.game.board = [["--"] * 8 for _ in range(8)]
        self.game.board[0][0] = "wK"
        self.game.board[7][7] = "bK"
        self.assertTrue(
            self.game.insufficient_material(), "Devrait détecter une insuffisance de matériel"
        )

    def test_en_passant(self):
        # Met en place une situation d'en passant
        self.game.board = [["--"] * 8 for _ in range(8)]
        self.game.board[3][4] = "wp"  # pion blanc
        self.game.board[1][3] = "bp"  # pion noir prêt à avancer de 2
        self.game.board[7][4] = "wK"
        self.game.board[0][4] = "bK"
        self.game.white_to_move = False  # noir à jouer
        move = ChessEngine.Move((1, 3), (3, 3), self.game.board)
        self.game.makeMove(move, validate=False)
        # La case d'en passant doit être mise à jour
        expected = ((1 + 3) // 2, 3)
        self.assertEqual(self.game.enpassant_possible, expected, "En passant non mis à jour")
        valid_moves = self.game.getValidMoves()
        en_passant_moves = [m for m in valid_moves if m.is_enpassant_move]
        self.assertTrue(len(en_passant_moves) > 0, "Le coup en passant devrait être valide")

    def test_castling(self):
        # Test de roque : création d'un plateau simplifié pour le roque
        self.game.board = [["--"] * 8 for _ in range(8)]
        self.game.board[7] = ["wR", "--", "--", "--", "wK", "--", "--", "wR"]
        self.game.white_king_location = (7, 4)
        self.game.current_castling_rights = ChessEngine.CastleRights(True, True, True, True)
        self.game.white_to_move = True
        valid_moves = self.game.getValidMoves()
        castling_moves = [m for m in valid_moves if m.is_castle_move]
        self.assertTrue(len(castling_moves) >= 1, "Au moins un roque devrait être possible")

    def test_repetition(self):
        # Simule la répétition de la position
        initial_hash = self.game.get_board_hash_str()
        move = self.game.getValidMoves()[0]
        self.game.makeMove(move, validate=False)
        self.game.undoMove()
        # Effectue deux fois le même coup pour simuler une répétition
        self.game.makeMove(move, validate=False)
        self.game.undoMove()
        rep_count = self.game.position_history.get(initial_hash, 0)
        self.assertTrue(rep_count >= 1, "La répétition de position doit être comptabilisée")

    def test_fifty_move_rule(self):
        # Simule le compteur des 50 coups
        self.game.fifty_move_counter = 100
        valid_moves = self.game.getValidMoves()
        self.assertEqual(
            len(valid_moves), 0, "La règle des 50 coups doit provoquer un draw (aucun mouvement)"
        )


class TestAI(unittest.TestCase):
    def setUp(self):
        self.game = ChessEngine.GameState()

    def test_ai_performance(self):
        # Teste que l'IA renvoie un coup en moins de 5 secondes
        valid_moves = self.game.getValidMoves()
        q = Queue()
        start_time = time.time()
        p_process = Process(target=ChessAI.findBestMove, args=(self.game, valid_moves, q))
        p_process.start()
        p_process.join(timeout=5)
        end_time = time.time()
        self.assertTrue(end_time - start_time < 5, "L'IA doit répondre en moins de 5 secondes")
        if not q.empty():
            best_move = q.get()
            self.assertIsNotNone(best_move, "L'IA doit renvoyer un coup")
        else:
            self.fail("Aucun coup n'a été renvoyé par l'IA")


if __name__ == "__main__":
    unittest.main()
