"""Tests du protocole UCI minimal (J3.0) : dialogue réel par sous-processus et fonctions pures."""

import io
import subprocess
import sys
from unittest import mock

import pytest

from chessproject import uci
from chessproject.core.clock import allocate_think_time_ms
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
    assert lines[:2] == ["id name ChessProject", "id author BryanBlinDorard"]
    assert lines[2].startswith("option name Level type combo default Max")
    assert lines[3] == "option name OwnBook type check default false"
    assert lines[4] == "uciok"
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
    assert lines[1].startswith("info depth ")  # retenue avec le bestmove jusqu'à stop
    assert lines[2].startswith("bestmove ")


def test_infinite_flushed_on_eof() -> None:
    lines = _run_in_process(["position startpos", "go infinite"])
    assert len(_bestmoves(lines)) == 1


def test_illegal_move_keeps_previous_position() -> None:
    engine = uci.UciEngine(io.StringIO())
    engine.handle("position startpos moves e2e4")
    engine.handle("position startpos moves e2e4 e7e4")
    assert len(engine.game_state.move_log) == 1


def test_think_returns_the_search_result() -> None:
    move, result = uci._think(load_fen("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"), 1, None)
    assert move is not None and result is not None
    assert result.move == move and result.depth == 1
    assert uci._think(load_fen("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"), 2, None) == (None, None)


def test_movetime_is_a_real_time_limit() -> None:
    _, result = uci._think(GameState(), None, 200)
    assert result is not None and result.elapsed_ms < 1000


def test_level_option_selects_a_difficulty_level() -> None:
    out = io.StringIO()
    engine = uci.UciEngine(out)
    engine.handle("uci")
    assert "option name Level type combo" in out.getvalue()
    engine.handle("setoption name Level value Débutant")
    assert engine.level is not None and engine.level.name == "Débutant"
    engine.handle("go movetime 50")
    assert out.getvalue().strip().splitlines()[-1].startswith("bestmove ")
    engine.handle("setoption name Level value Max")
    assert engine.level is None
    engine.handle("setoption name Level value Inexistant")
    assert engine.level is None and "niveau inconnu" in out.getvalue()


def test_info_line_reports_mate() -> None:
    out = io.StringIO()
    engine = uci.UciEngine(out)
    engine.handle("position fen 6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1")
    engine.handle("go depth 2")
    lines = out.getvalue().splitlines()
    assert any(line.startswith("info depth") and "score mate 1" in line for line in lines)
    assert lines[-1] == "bestmove a1a8"


# --------------------------------------------------------------------------
# Gestion du temps
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("commands", "expected_args"),
    [
        # Après 1. d4, aux Noirs : 1 demi-coup joué, temps et incrément des Noirs.
        (
            ["position startpos moves d2d4", "go wtime 2000 btime 9000 winc 0 binc 10"],
            (9000, 10, 1, None),
        ),
        # FEN au 21e coup, Blancs au trait : 40 demi-coups, movestogo transmis.
        (
            ["position fen 4k3/8/8/8/8/8/8/4K2R w K - 0 21", "go wtime 60000 movestogo 10"],
            (60000, 0, 40, 10),
        ),
    ],
)
def test_go_uses_the_shared_time_allocation(
    commands: list[str], expected_args: tuple[int, int, int, int | None]
) -> None:
    # Un seul calcul du temps de réflexion, celui de la pendule du jeu (J10.3).
    calls: list[tuple[int, int, int, int | None]] = []

    def spy(remaining, increment, moves_played, max_ms=None, moves_to_go=None):
        calls.append((remaining, increment, moves_played, moves_to_go))
        return allocate_think_time_ms(remaining, increment, moves_played, max_ms, moves_to_go)

    out = io.StringIO()
    with mock.patch.object(uci, "allocate_think_time_ms", spy):
        uci.run(io.StringIO("\n".join([*commands, "quit"]) + "\n"), out)
    (best,) = _bestmoves(out.getvalue().splitlines())
    assert calls == [expected_args]
    assert best != "0000"


def test_level_command_line_option() -> None:
    out = io.StringIO()
    uci.run(io.StringIO("go movetime 50\nquit\n"), out, level="Débutant")
    assert out.getvalue().strip().splitlines()[-1].startswith("bestmove ")
    completed = subprocess.run(
        [sys.executable, "-m", "chessproject.uci", "--level", "Facile"],
        input="position startpos\ngo movetime 50\nquit\n",
        capture_output=True,
        text=True,
        timeout=TIMEOUT_S,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().splitlines()[-1].startswith("bestmove ")


def test_level_spec_command_line_option() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "chessproject.uci", "--level-spec", "base=Facile,nodes=500"],
        input="position startpos\ngo movetime 50\nquit\n",
        capture_output=True,
        text=True,
        timeout=TIMEOUT_S,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().splitlines()[-1].startswith("bestmove ")
    refused = subprocess.run(
        [sys.executable, "-m", "chessproject.uci", "--level-spec", "vitesse=3"],
        input="quit\n",
        capture_output=True,
        text=True,
        timeout=TIMEOUT_S,
        check=False,
    )
    assert refused.returncode == 2 and "clé inconnue" in refused.stderr
