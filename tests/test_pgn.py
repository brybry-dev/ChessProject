"""Tests du module PGN (``chessproject.core.pgn`` : J4.3 export, J4.4 import).

- export : Seven Tag Roster et ordre, SetUp/FEN, numérotation « 12... », Termination,
  lignes ≤ 80 caractères, échappement des en-têtes ;
- aller-retour export → import → rejeu sur des parties aléatoires de notre moteur ;
- référence python-chess dans les deux sens (si le paquet ``chess`` est installé) ;
- corpus ``tests/data/pgn`` (parties célèbres vérifiées, fichiers invalides) ;
- robustesse et limites (taille, nombre de parties et de coups).
"""

import importlib.util
import io
import random
import unittest
from pathlib import Path

from chessproject.core.engine import Color, GameResult, GameState, Termination
from chessproject.core.fen import load_fen
from chessproject.core.notation import parse_san, san_history
from chessproject.core.pgn import (
    SEVEN_TAG_ROSTER,
    STANDARD_START_FEN,
    TERMINATION_TAGS,
    export_pgn,
    wrap_tokens,
)
from chessproject.serialization import to_fen

HAS_PYTHON_CHESS = importlib.util.find_spec("chess") is not None
if HAS_PYTHON_CHESS:
    import chess
    import chess.pgn

DATA_DIR = Path(__file__).parent / "data" / "pgn"

# Positions de départ des parties aléatoires : trait aux deux camps, roques partiels,
# case en passant, numéros de coup différents de 1.
KIWIPETE = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
START_FENS: list[str | None] = [
    None,
    KIWIPETE,
    "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 2 12",
    "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3",
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 40",
    "r3k2r/8/8/8/8/8/8/R3K2R b Kq - 5 30",
    "4k3/1P6/8/8/8/8/6p1/4K3 b - - 0 57",
]


def _random_game(rng: random.Random, start_fen: str | None, max_plies: int) -> GameState:
    gs = GameState() if start_fen is None else load_fen(start_fen)
    for _ in range(max_plies):
        moves = gs.get_valid_moves()
        if not moves:
            break
        gs.make_move(rng.choice(moves), validate=False)
    return gs


def _random_games(count: int, seed: int, max_plies: int = 80) -> list[GameState]:
    rng = random.Random(seed)
    return [
        _random_game(rng, START_FENS[i % len(START_FENS)], rng.randint(0, max_plies))
        for i in range(count)
    ]


def _read_reference(handle: io.StringIO) -> "chess.pgn.Game":
    """Partie suivante lue par python-chess (échoue s'il n'y en a plus)."""
    game = chess.pgn.read_game(handle)
    assert game is not None
    return game


def _play(gs: GameState, *sans: str) -> GameState:
    for san in sans:
        gs.make_move(parse_san(gs, san), validate=False)
    return gs


def _tag_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("[")]


def _tag_names(text: str) -> list[str]:
    return [line[1:].split(" ", 1)[0] for line in _tag_lines(text)]


# --------------------------------------------------------------------------
# Export (J4.3)
# --------------------------------------------------------------------------
class TestExport(unittest.TestCase):
    def test_seven_tag_roster_order_and_defaults(self):
        text = export_pgn(_play(GameState(), "e4", "e5"))
        self.assertEqual(_tag_names(text), list(SEVEN_TAG_ROSTER))
        self.assertEqual(
            _tag_lines(text),
            [
                '[Event "?"]',
                '[Site "?"]',
                '[Date "????.??.??"]',
                '[Round "?"]',
                '[White "?"]',
                '[Black "?"]',
                '[Result "*"]',
            ],
        )
        self.assertTrue(text.endswith("\n\n1. e4 e5 *\n"))

    def test_given_headers_and_time_control(self):
        text = export_pgn(
            GameState(),
            headers={
                "TimeControl": "300+2",
                "White": "Alice",
                "Date": "2026.10.22",
                "Annotator": "Moi",
            },
        )
        self.assertEqual(_tag_names(text), [*SEVEN_TAG_ROSTER, "TimeControl", "Annotator"])
        self.assertIn('[White "Alice"]', text)
        self.assertIn('[Date "2026.10.22"]', text)
        self.assertIn('[TimeControl "300+2"]', text)
        self.assertNotIn("SetUp", text)

    def test_result_and_setup_cannot_be_forced_by_headers(self):
        gs = _play(GameState(), "f3", "e5", "g4", "Qh4#")
        text = export_pgn(gs, headers={"Result": "1-0", "SetUp": "1", "FEN": "x"})
        self.assertIn('[Result "0-1"]', text)
        self.assertNotIn("SetUp", text)
        self.assertNotIn("FEN", text)

    def test_invalid_date_or_tag_name(self):
        with self.assertRaises(ValueError):
            export_pgn(GameState(), headers={"Date": "22/10/2026"})
        with self.assertRaises(ValueError):
            export_pgn(GameState(), headers={"Bad Name": "x"})

    def test_from_fen_black_to_move(self):
        fen = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 2 12"
        gs = _play(load_fen(fen), "Nf6", "Nc3", "Bc5")
        text = export_pgn(gs)
        names = _tag_names(text)
        self.assertEqual(names[:7], list(SEVEN_TAG_ROSTER))
        self.assertEqual(names[7:9], ["SetUp", "FEN"])
        self.assertIn('[SetUp "1"]', text)
        self.assertIn(f'[FEN "{fen}"]', text)
        self.assertIn("12... Nf6 13. Nc3 Bc5 *", text)

    def test_setup_when_only_move_number_differs(self):
        gs = load_fen(STANDARD_START_FEN.replace(" 0 1", " 0 7"))
        text = export_pgn(_play(gs, "d4"))
        self.assertIn('[SetUp "1"]', text)
        self.assertIn("7. d4 *", text)

    def test_checkmate_result_and_termination(self):
        gs = _play(GameState(), "e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7#")
        text = export_pgn(gs)
        self.assertIn('[Result "1-0"]', text)
        self.assertIn('[Termination "normal"]', text)
        self.assertTrue(text.rstrip().endswith("4. Qxf7# 1-0"))

    def test_termination_mapping(self):
        gs = _play(GameState(), "e4")
        cases = [
            (GameResult(Termination.RESIGNATION, Color.BLACK), "0-1", "normal"),
            (GameResult(Termination.DRAW_AGREEMENT), "1/2-1/2", "normal"),
            (GameResult(Termination.TIME_FORFEIT, Color.WHITE), "1-0", "time forfeit"),
            (GameResult(Termination.TIMEOUT_VS_INSUFFICIENT_MATERIAL), "1/2-1/2", "time forfeit"),
        ]
        for result, pgn_result, tag in cases:
            with self.subTest(result=result):
                text = export_pgn(gs, result)
                self.assertIn(f'[Result "{pgn_result}"]', text)
                self.assertIn(f'[Termination "{tag}"]', text)
                self.assertTrue(text.rstrip().endswith(pgn_result))
        self.assertEqual(set(TERMINATION_TAGS), set(Termination))
        self.assertNotIn("Termination", export_pgn(gs))
        custom = export_pgn(gs, cases[0][0], headers={"Termination": "abandoned"})
        self.assertIn('[Termination "abandoned"]', custom)

    def test_stalemate_draw(self):
        gs = _play(load_fen("k7/8/2K5/8/8/8/8/1Q6 w - - 0 1"), "Qb6")
        self.assertEqual(gs.result().termination, Termination.STALEMATE)
        text = export_pgn(gs)
        self.assertIn('[Result "1/2-1/2"]', text)
        self.assertIn('[Termination "normal"]', text)

    def test_lines_at_most_80_chars(self):
        for gs in _random_games(6, seed=7, max_plies=200):
            text = export_pgn(gs, headers={"Event": "x"})
            movetext = text.split("\n\n", 1)[1]
            for line in movetext.splitlines():
                self.assertLessEqual(len(line), 80, line)
                self.assertEqual(line, line.strip())

    def test_wrap_tokens_never_splits_a_token(self):
        tokens = ["1.", "e4", "x" * 90, "e5", "2.", "Nf3"]
        lines = wrap_tokens(tokens, width=10)
        self.assertEqual(" ".join(lines).split(), tokens)
        self.assertIn("x" * 90, lines)

    def test_header_escaping(self):
        value = 'Joueur "fou" \\ C:\\chemin'
        text = export_pgn(GameState(), headers={"White": value, "Black": "a\nb"})
        self.assertIn('[White "Joueur \\"fou\\" \\\\ C:\\\\chemin"]', text)
        self.assertIn('[Black "a b"]', text)

    def test_game_state_left_untouched(self):
        gs = _play(load_fen(KIWIPETE), "O-O", "O-O-O", "a3")
        before = (to_fen(gs), len(gs.move_log), list(gs.position_keys))
        export_pgn(gs)
        self.assertEqual(before, (to_fen(gs), len(gs.move_log), list(gs.position_keys)))


# --------------------------------------------------------------------------
# Référence python-chess
# --------------------------------------------------------------------------
@unittest.skipUnless(HAS_PYTHON_CHESS, "python-chess (paquet chess) non installé")
class TestPythonChessReference(unittest.TestCase):
    def test_python_chess_reads_our_export(self):
        for index, gs in enumerate(_random_games(30, seed=99)):
            with self.subTest(game=index):
                text = export_pgn(gs, headers={"White": "Nous", "TimeControl": "180+2"})
                game = _read_reference(io.StringIO(text))
                self.assertEqual(game.errors, [])
                board = game.board()
                sans = []
                for move in game.mainline_moves():
                    sans.append(board.san(move))
                    board.push(move)
                self.assertEqual(sans, san_history(gs))
                self.assertEqual(board.fen(en_passant="fen"), to_fen(gs))
                self.assertEqual(game.headers["Result"], gs.result().pgn)
                self.assertEqual(game.headers["TimeControl"], "180+2")
                self.assertEqual(list(game.headers)[:7], list(SEVEN_TAG_ROSTER))


if __name__ == "__main__":
    unittest.main()
