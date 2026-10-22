"""
Tests de l'IA (chessproject.ai.search)
-----------------------
Verrouille les corrections des tâches J1.4 et J1.5 :
  - B27 : le pat (et toute nulle) n'est plus pris pour une victoire ; mat au plus court ;
  - B31 : la racine renvoie toujours un coup légal, même quand tous les coups perdent ;
  - B30 : évaluation en centipions entiers, nulle sur la position initiale, antisymétrique
    par miroir des couleurs.
"""

import unittest
from unittest import mock

from chessproject.ai import search
from chessproject.core import engine
from chessproject.core.fen import load_fen


class FakeQueue:
    """Remplace la multiprocessing.Queue : retient ce que l'IA y dépose."""

    def __init__(self) -> None:
        self.items: list[engine.Move | None] = []

    def put(self, item: engine.Move | None) -> None:
        self.items.append(item)


def ai_move(game_state: engine.GameState, depth: int) -> engine.Move | None:
    """Coup choisi par ``find_best_move`` à la profondeur ``depth``."""
    queue = FakeQueue()
    with mock.patch.object(search, "DEPTH", depth):
        search.find_best_move(game_state, game_state.get_valid_moves(), queue)
    assert len(queue.items) == 1
    return queue.items[0]


def outcome(game_state: engine.GameState, move: engine.Move) -> tuple[bool, bool]:
    """(mat, nulle) dans la position obtenue après ``move`` ; la position est restaurée."""
    game_state.make_move(move, validate=False)
    game_state.get_valid_moves()
    result = (game_state.checkmate, game_state.stalemate)
    game_state.undo_move()
    return result


def mirror_fen(fen: str) -> str:
    """FEN miroir : rangées inversées, couleurs inversées, trait, roques et en passant."""
    board, turn, castling, ep, *counters = fen.split()
    board = "/".join(row.swapcase() for row in reversed(board.split("/")))
    turn = "b" if turn == "w" else "w"
    if castling != "-":
        castling = "".join(ch for ch in "KQkq" if ch.swapcase() in castling)
    if ep != "-":
        ep = ep[0] + str(9 - int(ep[1]))
    return " ".join([board, turn, castling, ep, *counters])


class TestMirrorHelper(unittest.TestCase):
    def test_mirror_fen(self):
        self.assertEqual(
            mirror_fen("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w Kq e6 0 2"),
            "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR b Qk e3 0 2",
        )
        fen = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
        self.assertEqual(mirror_fen(mirror_fen(fen)), fen)


class TestStalemateIsNotAWin(unittest.TestCase):
    """B27 : l'IA gagnante mate et ne pate pas."""

    def test_kq_vs_k_mates_at_every_depth(self):
        for depth in (1, 2, 3):
            with self.subTest(depth=depth):
                gs = load_fen("7k/8/6K1/8/8/8/8/5Q2 w - - 0 1")
                move = ai_move(gs, depth)
                self.assertIsNotNone(move)
                assert move is not None
                gs.make_move(move)
                gs.get_valid_moves()
                self.assertTrue(gs.checkmate, f"profondeur {depth} : {move} ne mate pas")
                self.assertFalse(gs.stalemate)

    def test_does_not_stalemate_when_material_can_be_won(self):
        # Prendre la dernière pièce noire pate ; d'autres coups gardent un gain décisif.
        for fen in (
            "k7/8/1b6/2Q5/8/8/4K3/8 w - - 0 1",  # Dxb6 pat
            "7k/5Q2/6b1/8/K7/8/8/8 w - - 0 1",  # Dxg6 pat
        ):
            for depth in (2, 3):
                with self.subTest(fen=fen, depth=depth):
                    gs = load_fen(fen)
                    move = ai_move(gs, depth)
                    assert move is not None
                    _, draw = outcome(gs, move)
                    self.assertFalse(draw, f"{move} pate")


class TestRootAlwaysReturnsAMove(unittest.TestCase):
    """B31 : même perdante, la racine renvoie un coup légal."""

    def test_losing_root_returns_a_move(self):
        gs = load_fen("k7/8/1K6/8/8/8/8/7R b - - 0 1")
        legal = list(gs.get_valid_moves())
        move = ai_move(gs, 2)
        self.assertIsNotNone(move)
        self.assertIn(move, legal)

    def test_negamax_root_move_not_none_when_all_moves_lose(self):
        gs = load_fen("k7/8/1K6/8/8/8/8/7R b - - 0 1")
        tt: search.TranspositionTable = {}
        for depth in (1, 2, 3):
            score, move = search.negamax(
                gs, gs.get_valid_moves(), depth, -search.INF, search.INF, 0, tt
            )
            self.assertIsNotNone(move)
        # Rh8# suit Kb8 : mat en 2 demi-coups depuis la racine.
        self.assertEqual(score, -search.MATE + 2)


class TestMateSearch(unittest.TestCase):
    MATE_IN_2 = "kbK5/pp6/1P6/8/8/8/8/R7 w - - 0 1"  # 1. Ta6 ! bxa6 2. b7#

    def test_mate_in_two_found(self):
        gs = load_fen(self.MATE_IN_2)
        score, move = search.negamax(gs, gs.get_valid_moves(), 3, -search.INF, search.INF, 0, {})
        self.assertEqual(score, search.MATE - 3)
        self.assertEqual(str(move), "Ra6")

    def test_mate_in_two_played_through(self):
        gs = load_fen(self.MATE_IN_2)
        move = ai_move(gs, 3)
        assert move is not None
        gs.make_move(move)
        for reply in list(gs.get_valid_moves()):
            with self.subTest(reply=str(reply)):
                gs.make_move(reply)
                finisher = ai_move(gs, 1)
                assert finisher is not None
                mate, _ = outcome(gs, finisher)
                self.assertTrue(mate, f"après {reply}, {finisher} ne mate pas")
                gs.undo_move()

    def test_prefers_shortest_mate(self):
        # Des mats en 1 (Dc8#, Df8#) coexistent avec des mats en 2 : l'IA prend le plus court.
        for fen in (
            "k7/1p6/1K6/2Q5/8/8/8/7n w - - 0 1",
            "7k/8/6K1/8/8/8/8/5Q2 w - - 0 1",
        ):
            with self.subTest(fen=fen):
                gs = load_fen(fen)
                move = ai_move(gs, 3)
                assert move is not None
                mate, _ = outcome(gs, move)
                self.assertTrue(mate, f"{move} n'est pas un mat en 1")


class TestEvaluation(unittest.TestCase):
    """B30 : centipions entiers, symétrie."""

    POSITIONS = (
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2",
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
        "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
        "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
        "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10",
        "7k/8/6K1/8/8/8/8/5Q2 w - - 0 1",
        "k7/1p6/1K6/2Q5/8/8/8/7n w - - 0 1",
        "4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1",
        "2kr3r/ppp2ppp/2n5/3qp3/1b1P4/2N1BN2/PPP2PPP/R2QK2R b KQ - 3 9",
        "8/8/4k3/3n4/3K4/8/5P2/8 b - - 0 50",
    )

    def test_initial_position_is_zero(self):
        score = search.score_board(engine.GameState())
        self.assertIsInstance(score, int)
        self.assertEqual(score, 0)

    def test_mirror_symmetry(self):
        for fen in self.POSITIONS:
            with self.subTest(fen=fen):
                score = search.score_board(load_fen(fen))
                mirrored = search.score_board(load_fen(mirror_fen(fen)))
                self.assertIsInstance(score, int)
                self.assertEqual(score, -mirrored)

    def test_centipawn_scale(self):
        # Un pion e2 (bonus de table nul) d'avance : exactement 100 centipions.
        self.assertEqual(search.score_board(load_fen("4k3/8/8/8/8/8/4P3/4K3 w - - 0 1")), 100)
        self.assertEqual(search.score_board(load_fen("4k3/4p3/8/8/8/8/8/4K3 w - - 0 1")), -100)

    def test_positional_bonus_not_truncated(self):
        # 1. e4 : table du pion e2 → e4 (0 → 0,2 pion) + bonus de centre (0,5) = 70 centipions,
        # qui disparaissaient avec l'ancienne troncature en unités de pion.
        gs = engine.GameState()
        gs.make_move(engine.Move((6, 4), (4, 4), gs.board))
        self.assertEqual(search.score_board(gs), 70)

    def test_static_eval_does_not_depend_on_side_to_move(self):
        # Pas de terme calculé pour le seul camp au trait (mobilité, sécurité du roi d'un camp).
        for fen in self.POSITIONS:
            with self.subTest(fen=fen):
                gs = load_fen(fen)
                other = load_fen(fen)
                other.white_to_move = not other.white_to_move
                self.assertEqual(search.score_board(gs), search.score_board(other))


class TestSearchSideEffects(unittest.TestCase):
    def test_search_does_not_modify_valid_moves_list(self):
        # B39 : la liste reçue (cache du moteur) n'est pas triée en place.
        gs = load_fen("4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1")
        moves = gs.get_valid_moves()
        before = [m.move_id for m in moves]
        ai_move(gs, 2)
        self.assertEqual([m.move_id for m in moves], before)


class TestTactics(unittest.TestCase):
    def test_takes_free_queen(self):
        for fen, expected in (
            ("4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1", "Rxd5"),
            ("3rk3/8/8/8/3Q4/8/8/4K3 b - - 0 1", "Rxd4"),
        ):
            with self.subTest(fen=fen):
                move = ai_move(load_fen(fen), 2)
                self.assertEqual(str(move), expected)

    def test_find_best_move_puts_a_legal_move(self):
        gs = engine.GameState()
        legal = list(gs.get_valid_moves())
        move = ai_move(gs, 2)
        self.assertIn(move, legal)

    def test_find_best_move_without_legal_move_puts_none(self):
        gs = load_fen("k7/8/1Q6/2K5/8/8/8/8 b - - 0 1")  # pat
        self.assertIsNone(ai_move(gs, 2))


if __name__ == "__main__":
    unittest.main()
