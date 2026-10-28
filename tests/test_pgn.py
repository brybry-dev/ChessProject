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
import os
import random
import tempfile
import unittest
from pathlib import Path

import pytest

from chessproject.core import pgn
from chessproject.core.engine import Color, GameResult, GameState, Termination
from chessproject.core.fen import load_fen
from chessproject.core.notation import parse_san, san_history
from chessproject.core.pgn import (
    SEVEN_TAG_ROSTER,
    STANDARD_START_FEN,
    TERMINATION_TAGS,
    PgnError,
    PgnGame,
    export_pgn,
    load_pgn_game,
    parse_pgn,
    read_pgn_file,
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
        game = parse_pgn(text)[0]
        self.assertEqual(game.headers["White"], value)

    def test_game_state_left_untouched(self):
        gs = _play(load_fen(KIWIPETE), "O-O", "O-O-O", "a3")
        before = (to_fen(gs), len(gs.move_log), list(gs.position_keys))
        export_pgn(gs)
        self.assertEqual(before, (to_fen(gs), len(gs.move_log), list(gs.position_keys)))


# --------------------------------------------------------------------------
# Aller-retour
# --------------------------------------------------------------------------
class TestRoundTrip(unittest.TestCase):
    def _check(self, games: list[GameState]) -> None:
        for index, gs in enumerate(games):
            with self.subTest(game=index):
                text = export_pgn(gs, headers={"Round": str(index)})
                parsed = parse_pgn(text)
                self.assertEqual(len(parsed), 1)
                game = parsed[0]
                self.assertEqual(game.moves, san_history(gs))
                self.assertEqual(game.result, gs.result().pgn)
                self.assertEqual(game.headers["Round"], str(index))
                replayed = game.replay()
                self.assertEqual(to_fen(replayed), to_fen(gs))
                # La relecture suit les règles FIDE strictes (nulles à réclamer) ; la
                # partie d'origine, jouée dans le jeu, a les nulles automatiques.
                replayed.automatic_draws = gs.automatic_draws
                replayed._valid_moves = None
                self.assertEqual(replayed.result(), gs.result())
                # Réexport identique (point fixe).
                self.assertEqual(export_pgn(replayed, headers={"Round": str(index)}), text)

    def test_random_games(self):
        self._check(_random_games(30, seed=2026))

    def test_several_games_in_one_text(self):
        games = _random_games(5, seed=11, max_plies=30)
        text = "\n".join(export_pgn(gs) for gs in games)
        parsed = parse_pgn(text)
        self.assertEqual([g.moves for g in parsed], [san_history(gs) for gs in games])
        self.assertEqual([to_fen(g.replay()) for g in parsed], [to_fen(gs) for gs in games])

    @pytest.mark.slow
    def test_random_games_long(self):
        self._check(_random_games(300, seed=1858, max_plies=300))


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

    def _annotated_game(self, rng: random.Random, start_fen: str | None) -> tuple[str, list[str]]:
        """PGN écrit par python-chess avec commentaires, variantes imbriquées et NAG."""
        board = chess.Board() if start_fen is None else chess.Board(start_fen)
        game = chess.pgn.Game()
        if start_fen is not None:
            game.setup(board)
        game.headers["White"] = 'Réf "python-chess"'
        node: chess.pgn.GameNode = game
        mainline: list[str] = []
        for ply in range(rng.randint(5, 60)):
            moves = list(board.legal_moves)
            if not moves or board.is_game_over(claim_draw=True):
                break
            move = rng.choice(moves)
            alternatives = [m for m in moves if m != move]
            mainline.append(board.san(move))
            next_node = node.add_main_variation(move)
            if ply % 3 == 0:
                next_node.comment = f"commentaire {ply} (avec parenthèses) ; et point-virgule"
            if ply % 4 == 1:
                next_node.nags.add(rng.choice([1, 2, 3, 4, 5, 6, 14]))
            if alternatives and ply % 5 == 2:
                variation = node.add_variation(rng.choice(alternatives))
                variation.comment = "variante"
                variation.nags.add(chess.pgn.NAG_DUBIOUS_MOVE)
                vboard = variation.board()
                sub = list(vboard.legal_moves)
                if len(sub) >= 2:
                    # Variante imbriquée : deux suites possibles à l'intérieur de la variante.
                    variation.add_main_variation(sub[0]).comment = "suite"
                    variation.add_variation(sub[1]).comment = "sous-variante"
            board.push(move)
            node = next_node
        game.headers["Result"] = board.result(claim_draw=False)
        return str(game), mainline

    def test_we_read_python_chess_output(self):
        rng = random.Random(1851)
        fens = [None, START_FENS[1], START_FENS[2], START_FENS[3]]
        for index in range(20):
            start_fen = fens[index % len(fens)]
            text, mainline = self._annotated_game(rng, start_fen)
            with self.subTest(game=index):
                self.assertIn("{", text)
                self.assertIn("(", text)
                self.assertIn("$", text)
                # La ligne s'arrête dès qu'une nulle est réclamable (claim_draw) : nos
                # nulles automatiques ne peuvent donc pas finir la partie plus tôt.
                game = parse_pgn(text)[0]
                self.assertEqual(game.moves, mainline)
                # python-chess 1.11 n'échappe pas les guillemets : lecture tolérante.
                self.assertEqual(game.headers["White"], 'Réf "python-chess"')
                ref = _read_reference(io.StringIO(text))
                end = ref.end().board()
                self.assertEqual(to_fen(game.replay()), end.fen(en_passant="fen"))
                self.assertEqual(game.result, ref.headers["Result"])


# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------
VALID_CORPUS = {
    # fichier : [(Blancs, nombre de demi-coups, résultat), ...]
    "morphy_opera_1858.pgn": [("Morphy, Paul", 33, "1-0")],
    "anderssen_kieseritzky_1851.pgn": [("Anderssen, Adolf", 45, "1-0")],
    "anderssen_dufresne_1852_annotee.pgn": [("Anderssen, Adolf", 47, "1-0")],
    "morphy_opera_depuis_fen.pgn": [("Morphy, Paul", 10, "1-0")],
    "berger_formats_varies.pgn": [("Blancs", 7, "1-0")],
    "miniatures.pgn": [
        ("?", 7, "1-0"),
        ("?", 4, "0-1"),
        ("Legall de Kermeur, François", 13, "1-0"),
        ("Reti, Richard", 21, "1-0"),
        ("Lasker, Edward", 35, "1-0"),
        ('Joueur "humain"', 3, "*"),
    ],
}


class TestCorpus(unittest.TestCase):
    def test_valid_files(self):
        for name, expected in VALID_CORPUS.items():
            with self.subTest(file=name):
                games = read_pgn_file(DATA_DIR / name)
                self.assertEqual(
                    [(g.headers["White"], len(g.moves), g.result) for g in games], expected
                )
                for game in games:
                    final = game.replay()
                    if game.result != "*":
                        # Toutes les parties décisives du corpus finissent par un mat.
                        self.assertEqual(final.result().termination, Termination.CHECKMATE)
                        self.assertEqual(final.result().pgn, game.result)
                    self.assertEqual(list(game.headers)[:7], list(SEVEN_TAG_ROSTER))

    @unittest.skipUnless(HAS_PYTHON_CHESS, "python-chess (paquet chess) non installé")
    def test_valid_files_match_python_chess(self):
        for name in VALID_CORPUS:
            with self.subTest(file=name):
                handle = io.StringIO((DATA_DIR / name).read_text(encoding="utf-8"))
                for game in read_pgn_file(DATA_DIR / name):
                    ref = _read_reference(handle)
                    self.assertEqual(ref.errors, [])
                    board = ref.board()
                    sans = []
                    for move in ref.mainline_moves():
                        sans.append(board.san(move))
                        board.push(move)
                    self.assertEqual(game.moves, sans)
                    self.assertEqual(to_fen(game.replay()), board.fen(en_passant="fen"))

    def test_opera_from_fen(self):
        game = read_pgn_file(DATA_DIR / "morphy_opera_depuis_fen.pgn")[0]
        self.assertEqual(
            game.start_fen, "r3kb1r/p2nqppp/5n2/1B2p1B1/4P3/1Q6/PPP2PPP/2KR3R b kq - 2 12"
        )
        full = read_pgn_file(DATA_DIR / "morphy_opera_1858.pgn")[0]
        self.assertEqual(to_fen(game.replay()), to_fen(full.replay()))
        self.assertIn("12... Rd8", export_pgn(game.replay()))

    def test_annotated_file_keeps_only_mainline(self):
        game = read_pgn_file(DATA_DIR / "anderssen_dufresne_1852_annotee.pgn")[0]
        self.assertEqual(game.moves[12:15], ["O-O", "d3", "Qb3"])
        self.assertEqual(game.moves[-1], "Bxe7#")
        self.assertNotIn("Ng3", game.moves)

    def test_time_control_header_read(self):
        game = read_pgn_file(DATA_DIR / "berger_formats_varies.pgn")[0]
        self.assertEqual(game.headers["TimeControl"], "300+2")

    def test_illegal_move_file(self):
        with self.assertRaises(PgnError) as ctx:
            read_pgn_file(DATA_DIR / "coup_illegal.pgn")
        message = str(ctx.exception)
        self.assertIn("Partie n° 1", message)
        self.assertIn("13.", message)
        self.assertIn("Rxd7", message)

    def test_invalid_fen_file(self):
        with self.assertRaises(PgnError) as ctx:
            read_pgn_file(DATA_DIR / "fen_invalide.pgn")
        self.assertIn("FEN", str(ctx.exception))
        self.assertIn("roi", str(ctx.exception))

    def test_load_pgn_game(self):
        path = DATA_DIR / "miniatures.pgn"
        final = load_pgn_game(path, index=3)
        self.assertEqual(final.result().termination, Termination.CHECKMATE)
        self.assertEqual(to_fen(load_pgn_game(str(path), index=3)), to_fen(final))
        text = path.read_text(encoding="utf-8")
        self.assertEqual(to_fen(load_pgn_game(text, index=3)), to_fen(final))
        with self.assertRaises(PgnError):
            load_pgn_game(path, index=6)


# --------------------------------------------------------------------------
# Robustesse et limites
# --------------------------------------------------------------------------
class TestRobustness(unittest.TestCase):
    def test_comments_variations_nags(self):
        text = (
            '[Event "x"]\n\n'
            "1. e4 {un { commentaire ; sur\ndeux lignes} ; jusqu'à la fin e6 (e5)\n"
            "1... e5 $1 (1... c5 2. Nf3 (2. c3 d5 (2... Nf6)) 2... d6) 2. Nf3!? Nc6?! "
            "3.Bb5 a6 4. Ba4 $14 1/2-1/2"
        )
        game = parse_pgn(text)[0]
        self.assertEqual(game.moves, ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4"])
        self.assertEqual(game.result, "1/2-1/2")
        self.assertEqual(game.headers["Result"], "1/2-1/2")
        self.assertEqual(game.headers["White"], "?")

    def test_movetext_without_headers_and_without_result(self):
        games = parse_pgn("1. d4 d5 2. c4")
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].moves, ["d4", "d5", "c4"])
        self.assertEqual(games[0].result, "*")

    def test_game_without_result_token_ends_at_next_header(self):
        text = '[Result "1-0"]\n\n1. e4 e5\n\n[Event "b"]\n\n1. d4 *\n'
        games = parse_pgn(text)
        self.assertEqual([g.moves for g in games], [["e4", "e5"], ["d4"]])
        self.assertEqual([g.result for g in games], ["1-0", "*"])

    def test_empty_text(self):
        self.assertEqual(parse_pgn(""), [])
        self.assertEqual(parse_pgn("  \n% rien\n"), [])

    def test_malformed_inputs(self):
        cases = [
            "1. e4 { jamais fermé",
            "1. e4 (1. d4 d5",
            "1. e4 ) e5",
            "1. e4 -- 2. d4",
            "1. e4 e4",
            "1. Nd2",
            '[Event "x\n',
            "[Event x]\n1. e4",
            "1. e4 $ e5",
            '[SetUp "1"]\n\n1. e4 *',
            '[Variant "Chess960"]\n\n1. e4 *',
            '[FEN "pas une fen"]\n\n*',
        ]
        for text in cases:
            with self.subTest(text=text), self.assertRaises(PgnError):
                parse_pgn(text)

    def test_ambiguous_move(self):
        fen = "4k3/8/8/8/8/8/8/N1N1K3 w - - 0 1"
        with self.assertRaises(PgnError) as ctx:
            parse_pgn(f'[SetUp "1"]\n[FEN "{fen}"]\n\n1. Nb3 *')
        self.assertIn("ambigu", str(ctx.exception))

    def test_move_after_game_end(self):
        with self.assertRaises(PgnError) as ctx:
            parse_pgn("1. f3 e5 2. g4 Qh4# 3. a3 0-1")
        self.assertIn("après la fin de la partie", str(ctx.exception))

    def test_fen_header_never_trusted(self):
        # En passant impossible, roque incohérent : refusés par load_fen.
        for fen in (
            "4k3/8/8/8/8/8/8/4K3 w - e6 0 1",
            "4k3/8/8/8/8/8/8/4K3 w K - 0 1",
        ):
            with self.subTest(fen=fen), self.assertRaises(PgnError):
                parse_pgn(f'[SetUp "1"]\n[FEN "{fen}"]\n\n*')

    def test_standard_fen_header_means_initial_position(self):
        game = parse_pgn(f'[SetUp "1"]\n[FEN "{STANDARD_START_FEN}"]\n\n1. e4 *')[0]
        self.assertIsNone(game.start_fen)

    def test_too_many_moves(self):
        self.assertEqual(len(parse_pgn("1. e4 e5 2. Nf3 Nc6", max_moves=4)[0].moves), 4)
        with self.assertRaises(PgnError) as ctx:
            parse_pgn("1. e4 e5 2. Nf3 Nc6 3. Bb5 a6", max_moves=4)
        self.assertIn("4 demi-coups", str(ctx.exception))
        self.assertIn("3. 'Bb5'", str(ctx.exception))

    def test_too_many_games(self):
        text = "\n".join(["1. e4 *"] * 3)
        self.assertEqual(len(parse_pgn(text, max_games=3)), 3)
        with self.assertRaises(PgnError):
            parse_pgn(text, max_games=2)

    def test_file_too_big(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "gros.pgn")
            Path(path).write_text("1. e4 e5 *\n" * 100, encoding="utf-8")
            self.assertEqual(len(read_pgn_file(path)), 100)
            with self.assertRaises(PgnError) as ctx:
                read_pgn_file(path, max_bytes=500)
            self.assertIn("trop volumineux", str(ctx.exception))

    def test_latin1_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "latin1.pgn"
            path.write_bytes('[White "François"]\n\n1. e4 *\n'.encode("latin-1"))
            self.assertEqual(read_pgn_file(path)[0].headers["White"], "François")

    def test_replay_rejects_bad_moves(self):
        with self.assertRaises(PgnError):
            PgnGame(moves=["e4", "e4"]).replay()
        with self.assertRaises(PgnError):
            PgnGame(start_fen="nimporte quoi").replay()


if __name__ == "__main__":
    unittest.main()


class StrictFideDrawsOnImportTests(unittest.TestCase):
    """Une partie réelle peut continuer après une triple répétition non réclamée."""

    def test_game_continuing_after_a_threefold_repetition_is_imported(self):
        shuffle = "1. Nf3 Nf6 2. Ng1 Ng8 3. Nf3 Nf6 4. Ng1 Ng8 5. e4 e5 1/2-1/2"
        game = pgn.parse_pgn(shuffle)[0]
        self.assertEqual(len(game.moves), 10)
        self.assertEqual(game.replay().board[4][4], "wp")

    def test_fivefold_repetition_still_ends_the_game(self):
        moves = " ".join(f"{2 * i + 1}. Nf3 Nf6 {2 * i + 2}. Ng1 Ng8" for i in range(4))
        with self.assertRaises(pgn.PgnError):
            pgn.parse_pgn(moves + " 9. e4 1/2-1/2")
