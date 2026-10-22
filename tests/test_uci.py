"""Tests du protocole UCI minimal (J3.0) : dialogue réel par sous-processus et fonctions pures."""

import io
import subprocess
import sys

import pytest

from chessproject import uci
from chessproject.core.engine import GameState
from chessproject.core.fen import load_fen
from chessproject.core.notation import parse_uci

TIMEOUT_S = 60


def _dialogue(commands: list[str]) -> list[str]:
    """Lance ``python -m chessproject.uci``, envoie les commandes, renvoie les lignes lues."""
    completed = subprocess.run(
        [sys.executable, "-m", "chessproject.uci"],
        input="\n".join(commands) + "\n",
        capture_output=True,
        text=True,
        timeout=TIMEOUT_S,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    return completed.stdout.splitlines()


def _bestmoves(lines: list[str]) -> list[str]:
    return [line.split()[1] for line in lines if line.startswith("bestmove ")]


def _run_in_process(commands: list[str]) -> list[str]:
    out = io.StringIO()
    uci.run(io.StringIO("\n".join(commands) + "\n"), out)
    return out.getvalue().splitlines()


# --------------------------------------------------------------------------
# Dialogue par sous-processus
# --------------------------------------------------------------------------
def test_full_dialogue() -> None:
    lines = _dialogue(
        ["uci", "isready", "ucinewgame", "position startpos moves e2e4 e7e5", "go depth 2", "quit"]
    )
    assert lines[:3] == ["id name ChessProject", "id author BryanBlinDorard", "uciok"]
    assert "readyok" in lines
    (best,) = _bestmoves(lines)
    gs = GameState()
    for text in ("e2e4", "e7e5"):
        gs.make_move(parse_uci(gs, text))
    parse_uci(gs, best)  # lève NotationError si le coup est illégal


def test_mate_in_one_from_fen() -> None:
    fen = "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"  # Ta8#
    lines = _dialogue(["uci", f"position fen {fen}", "go depth 2", "quit"])
    assert _bestmoves(lines) == ["a1a8"]


def test_invalid_input_does_not_crash() -> None:
    lines = _dialogue(
        [
            "",
            "bonjour",
            "position",
            "position fen pas/une/fen w - - 0 1",
            "position startpos moves e2e5",
            "position startpos moves",
            "go depth abc",
            "go depth",
            "go depth 0",
            "go movetime 50",
            "stop",
            "isready",
            "quit",
        ]
    )
    infos = [line for line in lines if line.startswith("info string")]
    assert len(infos) >= 6
    assert "readyok" in lines
    # Deux go valides (depth abc ignoré → profondeur par défaut ; depth 0 → 1)
    # et le go "depth" sans valeur : chacun répond par un bestmove légal.
    best = _bestmoves(lines)
    assert len(best) == 4
    for text in best:
        parse_uci(GameState(), text)


def test_no_legal_move_returns_null_move() -> None:
    fen = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"  # Pat : aucun coup légal
    assert _dialogue([f"position fen {fen}", "go depth 2", "quit"]) == ["bestmove 0000"]


def test_go_with_clock_and_movestogo() -> None:
    lines = _dialogue(
        ["position startpos moves d2d4", "go wtime 2000 btime 300 winc 0 binc 10", "quit"]
    )
    (best,) = _bestmoves(lines)
    gs = GameState()
    gs.make_move(parse_uci(gs, "d2d4"))
    parse_uci(gs, best)


# --------------------------------------------------------------------------
# Même boucle, en processus (rapide)
# --------------------------------------------------------------------------
def test_infinite_waits_for_stop() -> None:
    lines = _run_in_process(["position startpos", "go infinite", "isready", "stop"])
    assert lines[0] == "readyok"
    assert lines[1].startswith("bestmove ")


def test_infinite_flushed_on_eof() -> None:
    lines = _run_in_process(["position startpos", "go infinite"])
    assert len(_bestmoves(lines)) == 1


def test_illegal_move_keeps_previous_position() -> None:
    engine = uci.UciEngine(io.StringIO())
    engine.handle("position startpos moves e2e4")
    engine.handle("position startpos moves e2e4 e7e4")
    assert len(engine.game_state.move_log) == 1


def test_think_restores_depth() -> None:
    saved = uci.search.DEPTH
    move = uci._think(load_fen("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"), 1, None)
    assert move is not None and move.get_chess_notation() is not None
    assert saved == uci.search.DEPTH
    assert uci._think(load_fen("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"), 2, None) is None


# --------------------------------------------------------------------------
# Gestion du temps
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("remaining", "increment", "movestogo", "expected"),
    [
        (60_000, 0, None, 2000),  # 60 s / 30
        (60_000, 1000, None, 2800),  # + 0,8 × incrément
        (60_000, 0, 10, 6000),  # movestogo explicite
        (10_000, 0, 1, 9950),  # dernier coup avant le contrôle : tout sauf la marge
        (100, 5000, None, 50),  # jamais plus que le temps restant moins la marge
        (0, 0, None, 1),  # au moins 1 ms
        (-500, 0, 0, 1),  # entrées aberrantes tolérées
    ],
)
def test_allocate_time_ms(
    remaining: int, increment: int, movestogo: int | None, expected: int
) -> None:
    assert uci.allocate_time_ms(remaining, increment, movestogo) == expected


def test_allocate_time_is_monotonic() -> None:
    values = [uci.allocate_time_ms(t, 100) for t in range(0, 300_000, 1000)]
    assert values == sorted(values)


def test_depth_for_movetime() -> None:
    depths = [uci.depth_for_movetime(ms) for ms in (1, 39, 40, 249, 250, 2499, 2500, 10**6)]
    assert depths == [1, 1, 2, 2, 3, 3, 4, 4]
