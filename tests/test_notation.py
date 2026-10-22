"""Tests de la notation SAN et UCI (module ``notation``, J2.5 : B19, B35).

Deux volets :
- cas unitaires (roques, désambiguïsation, en passant, promotions, échec, mat, pat,
  tolérance de ``parse_san`` / ``parse_uci``, position laissée intacte) ;
- comparaison différentielle avec python-chess (paquet ``chess``) sur des parties
  aléatoires jouées par notre moteur.
"""

import copy
import importlib.util
import random
import unittest

import pytest

from chessproject.core import engine
from chessproject.core.fen import load_fen
from chessproject.core.notation import (
    NotationError,
    format_move_lines,
    move_list_to_san,
    parse_san,
    parse_square,
    parse_uci,
    san_history,
    square_name,
    to_san,
    to_uci,
)

HAS_PYTHON_CHESS = importlib.util.find_spec("chess") is not None
if HAS_PYTHON_CHESS:
    import chess

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
KIWIPETE = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"


def _move(gs, uci):
    return parse_uci(gs, uci)


def _san(fen, uci):
    gs = load_fen(fen)
    return to_san(gs, _move(gs, uci))


def _snapshot(gs):
    """État observable d'une position, pour vérifier qu'elle est rendue intacte."""
    cr = gs.current_castling_rights
    return (
        copy.deepcopy(gs.board),
        gs.white_to_move,
        list(gs.move_log),
        gs.white_king_location,
        gs.black_king_location,
        gs.enpassant_possible,
        (cr.wks, cr.bks, cr.wqs, cr.bqs),
        gs.fifty_move_counter,
        len(gs.undo_stack),
        list(gs.position_keys),
        dict(gs.position_history),
        gs.termination,
        gs.checkmate,
        gs.stalemate,
        gs.in_check,
        sorted(m.move_id for m in gs.get_valid_moves()),
    )


class SquareTests(unittest.TestCase):
    def test_square_mapping(self):
        self.assertEqual(square_name(7, 4), "e1")
        self.assertEqual(square_name(0, 0), "a8")
        self.assertEqual(parse_square("h1"), (7, 7))
        self.assertEqual(parse_square("a8"), (0, 0))
        with self.assertRaises(NotationError):
            parse_square("i9")


class UciTests(unittest.TestCase):
    def test_simple_and_castle(self):
        gs = engine.GameState()
        self.assertEqual(to_uci(_move(gs, "e2e4")), "e2e4")
        gs = load_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        castle = parse_uci(gs, "e1g1")
        self.assertTrue(castle.is_castle_move)
        self.assertEqual(to_uci(castle), "e1g1")
        self.assertTrue(parse_uci(gs, "e1c1").is_castle_move)

    def test_promotion(self):
        gs = load_fen("8/4P3/8/8/8/8/k7/7K w - - 0 1")
        move = parse_uci(gs, "e7e8n")
        self.assertEqual(move.promotion_piece, "N")
        self.assertEqual(to_uci(move), "e7e8n")
        self.assertEqual(parse_uci(gs, "E7E8Q").promotion_piece, "Q")
        with self.assertRaises(NotationError):
            parse_uci(gs, "e7e8")  # promotion sans pièce
        with self.assertRaises(NotationError):
            parse_uci(gs, "h1h2q")  # pièce de promotion sur un coup normal

    def test_errors(self):
        gs = engine.GameState()
        for text in ("e2e5", "e7e5", "e2", "e2e4x", "", "z9z9"):
            with self.subTest(text=text), self.assertRaises(NotationError):
                parse_uci(gs, text)
        self.assertTrue(issubclass(NotationError, ValueError))


class SanTests(unittest.TestCase):
    def test_castling_both_sides_both_colors(self):
        white = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        black = "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1"
        self.assertEqual(_san(white, "e1g1"), "O-O")
        self.assertEqual(_san(white, "e1c1"), "O-O-O")
        self.assertEqual(_san(black, "e8g8"), "O-O")
        self.assertEqual(_san(black, "e8c8"), "O-O-O")
        for fen, king_from in ((white, "e1"), (black, "e8")):
            gs = load_fen(fen)
            for text, to_file in (("O-O", "g"), ("0-0", "g"), ("O-O-O", "c"), ("0-0-0+", "c")):
                with self.subTest(fen=fen, text=text):
                    self.assertEqual(
                        to_uci(parse_san(gs, text)), king_from + to_file + king_from[1]
                    )

    def test_castle_with_check(self):
        # Après O-O-O, la tour d1 fait échec au roi noir d8.
        self.assertEqual(_san("3k4/8/8/8/8/8/8/R3K3 w Q - 0 1", "e1c1"), "O-O-O+")

    def test_disambiguation_by_file(self):
        fen = "4k3/8/8/8/8/5N2/8/1N2K3 w - - 0 1"
        self.assertEqual(_san(fen, "b1d2"), "Nbd2")
        self.assertEqual(_san(fen, "f3d2"), "Nfd2")
        self.assertEqual(_san(fen, "f3e5"), "Ne5")  # pas d'ambiguïté inutile
        gs = load_fen(fen)
        with self.assertRaises(NotationError):
            parse_san(gs, "Nd2")  # ambigu
        self.assertEqual(to_uci(parse_san(gs, "Nbd2")), "b1d2")
        self.assertEqual(to_uci(parse_san(gs, "Nb1d2")), "b1d2")  # sur-désambiguïsé

    def test_disambiguation_by_rank(self):
        fen = "4k3/8/8/R7/8/8/8/R3K3 w - - 0 1"
        self.assertEqual(_san(fen, "a1a3"), "R1a3")
        self.assertEqual(_san(fen, "a5a3"), "R5a3")
        gs = load_fen(fen)
        with self.assertRaises(NotationError):
            parse_san(gs, "Ra3")
        self.assertEqual(to_uci(parse_san(gs, "R5a3")), "a5a3")

    def test_disambiguation_by_file_and_rank(self):
        # Trois dames peuvent aller en e1 : h4 (diagonale), e4 (colonne), h1 (rangée).
        fen = "8/8/k7/8/4Q2Q/8/K7/7Q w - - 0 1"
        self.assertEqual(_san(fen, "h4e1"), "Qh4e1")
        self.assertEqual(_san(fen, "e4e1"), "Qee1")
        self.assertEqual(_san(fen, "h1e1"), "Q1e1")
        gs = load_fen(fen)
        for text in ("Qe1", "Qhe1", "Q4e1"):
            with self.subTest(text=text), self.assertRaises(NotationError):
                parse_san(gs, text)
        self.assertEqual(to_uci(parse_san(gs, "Qh4e1")), "h4e1")

    def test_disambiguation_ignores_pinned_piece(self):
        # Le cavalier e2, cloué par la tour e7, ne peut pas aller en g3 : seuls les coups
        # LÉGAUX comptent pour la désambiguïsation, donc « Ng3 » et non « Nhg3 ».
        fen = "4k3/4r3/8/7N/8/8/4N3/4K3 w - - 0 1"
        self.assertEqual(_san(fen, "h5g3"), "Ng3")

    def test_en_passant(self):
        fen = "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1"
        self.assertEqual(_san(fen, "e5d6"), "exd6")
        gs = load_fen(fen)
        for text in ("exd6", "exd6 e.p.", "exd6e.p.", "exd6 ep", "exd6+"):
            with self.subTest(text=text):
                move = parse_san(gs, text)
                self.assertTrue(move.is_enpassant_move)

    def test_pawn_moves(self):
        gs = load_fen("4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1")
        self.assertEqual(to_san(gs, _move(gs, "e4d5")), "exd5")
        self.assertEqual(to_san(gs, _move(gs, "e4e5")), "e5")
        self.assertEqual(to_uci(parse_san(gs, "exd5")), "e4d5")
        self.assertEqual(to_uci(parse_san(gs, "e5")), "e4e5")
        with self.assertRaises(NotationError):
            parse_san(gs, "exe5")
        # Sans colonne de départ, un coup de pion est une poussée : « c3 » ne désigne
        # pas la prise dxc3.
        gs = load_fen("4k3/8/8/8/8/2n5/2PP4/4K3 w - - 0 1")
        self.assertEqual(to_uci(parse_san(gs, "dxc3")), "d2c3")
        with self.assertRaises(NotationError):
            parse_san(gs, "c3")  # c2-c3 bloqué, d2xc3 exige la colonne

    def test_capture_promotion_and_underpromotion(self):
        fen = "3r2k1/4P3/8/8/8/8/8/4K3 w - - 0 1"
        self.assertEqual(_san(fen, "e7d8q"), "exd8=Q+")
        self.assertEqual(_san(fen, "e7d8n"), "exd8=N")
        self.assertEqual(_san(fen, "e7d8r"), "exd8=R+")
        fen = "8/4P3/8/8/8/8/k7/7K w - - 0 1"
        for piece in "QRBN":
            with self.subTest(piece=piece):
                self.assertEqual(_san(fen, "e7e8" + piece.lower()), "e8=" + piece)
        gs = load_fen(fen)
        for text, piece in (("e8=N", "N"), ("e8N", "N"), ("e8=b", "B"), ("e8R+", "R")):
            with self.subTest(text=text):
                self.assertEqual(parse_san(gs, text).promotion_piece, piece)
        with self.assertRaises(NotationError):
            parse_san(gs, "e8")  # pièce de promotion manquante : 4 coups possibles
        with self.assertRaises(NotationError):
            parse_san(gs, "Ke8=Q")

    def test_check(self):
        self.assertEqual(_san("4k3/8/8/8/8/8/8/R3K3 w Q - 0 1", "a1a8"), "Ra8+")
        self.assertEqual(_san("4k3/8/8/8/8/8/8/R3K3 w Q - 0 1", "a1a7"), "Ra7")

    def test_scholars_mate(self):
        gs = engine.GameState()
        sans = ["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7#"]
        moves = []
        for text in sans[:-1]:
            move = parse_san(gs, text)
            moves.append(move)
            gs.make_move(move)
        self.assertEqual(to_san(gs, _move(gs, "h5f7")), "Qxf7#")
        moves.append(parse_san(gs, "Qxf7#"))
        self.assertEqual(move_list_to_san(engine.GameState(), moves), sans)

    def test_mate_on_hundredth_half_move_is_still_mate(self):
        # Le mat prime sur la règle des 50 coups (FIDE 9.3), en SAN comme dans le moteur.
        gs = load_fen("6k1/5ppp/8/8/8/8/8/R5K1 w - - 99 1")
        self.assertEqual(to_san(gs, _move(gs, "a1a8")), "Ra8#")

    def test_stalemate_has_no_suffix(self):
        gs = load_fen("7k/8/6Q1/8/8/8/8/K7 w - - 0 1")
        move = _move(gs, "g6f7")
        self.assertEqual(to_san(gs, move), "Qf7")
        gs.make_move(move)
        self.assertEqual(gs.get_valid_moves(), [])
        self.assertTrue(gs.stalemate)

    def test_position_left_intact(self):
        for fen in (START, KIWIPETE, "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1"):
            gs = load_fen(fen)
            gs.make_move(gs.get_valid_moves()[0])
            before = _snapshot(gs)
            for move in list(gs.get_valid_moves()):
                to_san(gs, move)
            self.assertEqual(_snapshot(gs), before)

    def test_move_list_to_san_leaves_start_intact(self):
        gs = engine.GameState()
        before = _snapshot(gs)
        moves = [parse_uci(gs, "g1f3")]
        self.assertEqual(move_list_to_san(gs, moves), ["Nf3"])
        self.assertEqual(_snapshot(gs), before)
        with self.assertRaises(NotationError):
            move_list_to_san(gs, [moves[0], moves[0]])  # Nf3 illégal pour les Noirs

    def test_illegal_or_malformed(self):
        gs = engine.GameState()
        for text in ("Nf4", "e5", "Ke2", "O-O", "Bxe3", "Pe4", "e9", "xyz", "", "Nxf3"):
            with self.subTest(text=text), self.assertRaises(NotationError):
                parse_san(gs, text)
        illegal = engine.Move((7, 4), (5, 4), gs.board)
        with self.assertRaises(NotationError):
            to_san(gs, illegal)

    def test_annotations_tolerated(self):
        gs = engine.GameState()
        for text in ("Nf3", "Nf3!", "Nf3?!", "Nf3+", "Nf3#", " Nf3 ", "Ng1f3", "Ngf3"):
            with self.subTest(text=text):
                self.assertEqual(to_uci(parse_san(gs, text)), "g1f3")


# --------------------------------------------------------------------------
# Comparaison avec python-chess
# --------------------------------------------------------------------------
def _differential(test, n_games, seed, full_every=0):
    """Parties aléatoires de ≤ 80 demi-coups jouées par NOTRE moteur.

    À chaque demi-coup : SAN et UCI identiques à python-chess, et aller-retour
    parse_san / parse_uci. Si ``full_every`` > 0, la SAN de TOUS les coups légaux est
    comparée un demi-coup sur ``full_every``.
    """
    plies = 0
    for fen in (START, KIWIPETE):
        rng = random.Random(seed)
        for game in range(n_games):
            gs = load_fen(fen)
            board = chess.Board(fen)
            for ply in range(80):
                legal = list(gs.get_valid_moves())
                if not legal:
                    break
                if full_every and ply % full_every == 0:
                    for move in legal:
                        cm = chess.Move.from_uci(to_uci(move))
                        test.assertEqual(to_san(gs, move), board.san(cm), board.fen())
                move = rng.choice(legal)
                uci = to_uci(move)
                chess_move = chess.Move.from_uci(uci)
                where = f"{fen} partie {game} demi-coup {ply} ({board.fen()}, {uci})"
                test.assertIn(chess_move, board.legal_moves, where)
                san = to_san(gs, move)
                test.assertEqual(san, board.san(chess_move), where)
                test.assertEqual(uci, chess_move.uci(), where)
                test.assertEqual(parse_san(gs, san), move, where)
                test.assertEqual(parse_uci(gs, uci), move, where)
                gs.make_move(move, validate=False)
                board.push(chess_move)
                plies += 1
    return plies


@unittest.skipUnless(HAS_PYTHON_CHESS, "python-chess (paquet « chess ») non installé")
class PythonChessReferenceTests(unittest.TestCase):
    def test_random_games_match_python_chess(self):
        # 2 × 100 parties : ~16 000 demi-coups, ~9 s.
        plies = _differential(self, n_games=100, seed=20251022, full_every=25)
        self.assertGreater(plies, 10_000)

    def test_disambiguation_matches_python_chess(self):
        for fen in ("8/8/k7/8/4Q2Q/8/K7/7Q w - - 0 1", "4k3/8/8/R7/8/8/8/R3K3 w - - 0 1"):
            gs = load_fen(fen)
            board = chess.Board(fen)
            for move in gs.get_valid_moves():
                with self.subTest(fen=fen, move=to_uci(move)):
                    self.assertEqual(to_san(gs, move), board.san(chess.Move.from_uci(to_uci(move))))

    # Positions trouvées par cette comparaison avant la correction de B46 (pion cloué
    # qui avance vers son roi), gardées en non-régression.
    def test_pinned_pawn_pushing_towards_its_king(self):
        for fen in (
            # Dame f7, pion f6, roi noir f3 : f6-f5 est légal.
            "5bn1/4pQ2/pP2np1r/6p1/1P5p/2Np1k2/3P2R1/R1B1K3 b Q - 1 37",
            # Tour h1, pion h2, roi blanc h4 : h2-h3 est légal.
            "5r2/p3kN2/Bq1p2p1/1P6/b2bP2K/P2n4/R4P1P/7r w - - 7 37",
        ):
            gs = load_fen(fen)
            ours = {to_uci(m) for m in gs.get_valid_moves()}
            theirs = {m.uci() for m in chess.Board(fen).legal_moves}
            self.assertEqual(ours, theirs, fen)

    @pytest.mark.slow
    def test_random_games_match_python_chess_long(self):
        # 2 × 1 000 parties (~160 000 demi-coups), ~1 min 30.
        _differential(self, n_games=1000, seed=1, full_every=20)


class HistoryTests(unittest.TestCase):
    def test_san_history_replays_the_whole_game_and_leaves_it_intact(self):
        gs = engine.GameState()
        for san in ("e4", "e5", "Nf3", "Nc6", "Bb5", "a6"):
            gs.make_move(parse_san(gs, san))
        before = _snapshot(gs)
        self.assertEqual(san_history(gs), ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"])
        self.assertEqual(_snapshot(gs), before)

    def test_move_lines_are_numbered_from_the_fen(self):
        self.assertEqual(format_move_lines(["e4", "e5", "Nf3"], 1, True), ["1. e4 e5", "2. Nf3"])
        self.assertEqual(
            format_move_lines(["Nf6", "d4", "d5"], 12, False), ["12... Nf6", "13. d4 d5"]
        )
        self.assertEqual(format_move_lines([], 5, False), [])


if __name__ == "__main__":
    unittest.main()
