"""Tests du livre d'ouvertures (J8.3)."""

import io
import random
from collections import Counter

import pytest

from chessproject import uci
from chessproject.ai import book, levels
from chessproject.core.engine import GameState, Move
from chessproject.core.fen import load_fen
from chessproject.core.notation import parse_san, to_uci

try:
    import chess

    _CHESS_OK = True
except ImportError:  # pragma: no cover - dépendance de développement absente
    _CHESS_OK = False


def _play(sans: str) -> GameState:
    game_state = GameState()
    for san in sans.split():
        game_state.make_move(parse_san(game_state, san), validate=False)
    return game_state


def _uci(move: Move | None) -> str:
    assert move is not None
    return to_uci(move)


def _rows() -> list[list[str]]:
    lines = book.book_path().read_text(encoding="utf-8").splitlines()
    return [line.split("\t") for line in lines if line.strip() and not line.startswith("#")]


# --------------------------------------------------------------------------
# Contenu du fichier livré
# --------------------------------------------------------------------------
def test_shipped_book_loads_and_has_a_few_hundred_lines() -> None:
    shipped = book.default_book()
    assert 200 <= shipped.lines <= 1000
    assert shipped.max_ply <= 24


def test_shipped_lines_are_distinct_and_named() -> None:
    rows = _rows()
    sequences = [row[2] for row in rows]
    assert len(sequences) == len(set(sequences)), "ligne en double"
    for _eco, name, _ in rows:
        assert name == name.strip() and name[0].isupper(), name


@pytest.mark.skipif(not _CHESS_OK, reason="python-chess absent")
def test_shipped_lines_are_legal_for_python_chess() -> None:
    for _eco, _name, sans in _rows():
        board = chess.Board()
        for san in sans.split():
            board.push_san(san)  # lève ValueError sur un coup illégal ou ambigu


# --------------------------------------------------------------------------
# Construction et erreurs
# --------------------------------------------------------------------------
def test_invalid_lines_are_rejected_with_their_number() -> None:
    cases = {
        "C20\tPartie\te4 e5\nC20\tPartie\te4 e5 Ke3": "ligne 2",
        "Z99\tPartie\te4": "ECO",
        "C20\tPartie": "trois champs",
        "C20\t \te4": "trois champs",
    }
    for text, message in cases.items():
        with pytest.raises(book.BookError, match=message):
            book.OpeningBook.from_lines(io.StringIO(text))


def test_comments_and_blank_lines_are_ignored() -> None:
    small = book.OpeningBook.from_lines(["# commentaire", "", "C20\tPartie du pion roi\te4 e5"])
    assert small.lines == 1 and small.max_ply == 2


# --------------------------------------------------------------------------
# Coups du livre
# --------------------------------------------------------------------------
_SMALL = [
    "B20\tDéfense sicilienne\te4 c5",
    "B27\tDéfense sicilienne\te4 c5 Nf3",
    "C20\tPartie du pion roi\te4 e5",
    "C44\tPartie du cavalier du roi\te4 e5 Nf3 Nc6",
    "D06\tGambit dame\td4 d5 c4",
]


def test_weights_count_the_lines_through_each_move() -> None:
    small = book.OpeningBook.from_lines(_SMALL)
    assert small.candidates(GameState()) == {"e2e4": 4, "d2d4": 1}
    assert small.candidates(_play("e4")) == {"c7c5": 2, "e7e5": 2}
    assert small.candidates(_play("e4 e5 Nf3 Nc6")) == {}


def test_book_move_varies_and_follows_the_weights() -> None:
    small = book.OpeningBook.from_lines(_SMALL)
    rng = random.Random(0)
    counts = Counter(_uci(small.book_move(GameState(), rng)) for _ in range(500))
    assert set(counts) == {"e2e4", "d2d4"}
    assert 0.7 < counts["e2e4"] / 500 < 0.9  # poids 4 contre 1


def test_rare_moves_are_named_but_not_played() -> None:
    lines = [f"C20\tPartie {i}\te4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 {i}" for i in ["Bb3"]]
    lines += [f"C20\tLigne {i}\te4 e{5 if i % 2 else 6}" for i in range(60)]
    lines.append("A00\tOuverture Grob\tg4")
    small = book.OpeningBook.from_lines(lines)
    rng = random.Random(1)
    played = {_uci(small.book_move(GameState(), rng)) for _ in range(300)}
    assert played == {"e2e4"}
    assert small.identify(_play("g4")) == book.Opening("A00", "Ouverture Grob")


def test_book_move_outside_the_book_is_none() -> None:
    assert book.book_move(_play("a4 h5 a5 h4")) is None


def test_ai_varies_its_first_moves() -> None:
    rng = random.Random(2026)
    level = levels.LEVELS_BY_NAME["Expert"]
    firsts = Counter(_uci(levels.choose_move(GameState(), level, rng)) for _ in range(60))
    assert len(firsts) >= 3 and firsts.most_common(1)[0][1] < 50
    replies = {_uci(levels.choose_move(_play("e4"), level, rng)) for _ in range(40)}
    assert len(replies) >= 3


def test_level_leaves_the_book_after_its_plies() -> None:
    position = _play("e4 e5 Nf3 Nc6")  # 4 demi-coups : encore dans le livre
    assert book.book_move(position) is not None
    beginner = levels.LEVELS_BY_NAME["Débutant"]
    assert beginner.book_plies <= 4
    assert levels.book_choice(position, beginner) is None
    assert levels.book_choice(position, levels.LEVELS_BY_NAME["Expert"]) is not None


def test_game_ply_counts_from_the_fen_move_number() -> None:
    assert levels.game_ply(GameState()) == 0
    assert levels.game_ply(_play("e4 e5 Nf3")) == 3
    fen = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"
    assert levels.game_ply(load_fen(fen)) == 4
    assert levels.book_choice(load_fen(fen), levels.LEVELS_BY_NAME["Expert"]) is not None


# --------------------------------------------------------------------------
# Nom de l'ouverture
# --------------------------------------------------------------------------
def test_identify_names_common_openings() -> None:
    najdorf = book.identify(_play("e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6"))
    assert najdorf is not None and najdorf.eco == "B90" and "Najdorf" in najdorf.name
    assert book.identify(_play("e4 e5 Nf3 Nc6 Bb5")) == book.Opening("C60", "Partie espagnole")
    assert book.identify(GameState()) is None


def test_identify_keeps_the_last_named_position_after_leaving_the_book() -> None:
    game = _play("e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O h3 Bb7 a3 a5")
    opening = book.identify(game)
    assert opening is not None and "Zaïtsev" in opening.name
    assert opening.label.startswith("C92 · ")


def test_identify_recognizes_transpositions() -> None:
    # 1.Nf3 d5 2.d4 Nf6 3.c4 e6 4.Nc3 : gambit dame refusé par un autre ordre de coups.
    opening = book.identify(_play("Nf3 d5 d4 Nf6 c4 e6 Nc3"))
    assert opening is not None and opening.name.startswith("Gambit dame refusé")


# --------------------------------------------------------------------------
# UCI : option OwnBook
# --------------------------------------------------------------------------
def test_uci_own_book_option() -> None:
    out = io.StringIO()
    engine = uci.UciEngine(out)
    engine.handle("uci")
    assert "option name OwnBook type check default false" in out.getvalue()
    assert engine.own_book is False
    engine.handle("setoption name OwnBook value true")
    assert engine.own_book is True
    engine.handle("position startpos")
    engine.handle("go depth 1")
    last = out.getvalue().strip().splitlines()[-1]
    assert last.split()[1] in book.default_book().candidates(GameState())
    engine.handle("setoption name OwnBook value peut-être")
    assert engine.own_book is True and "true ou false" in out.getvalue()
