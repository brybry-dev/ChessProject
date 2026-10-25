"""Tests de la mini-ligue ``tools/match.py`` (J3.0) : statistiques, ouvertures, arbitrage."""

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import match
from uci_client import engine_argv, engine_env_and_cwd, go_command, move_timeout

from chessproject.core.fen import load_fen

try:
    import chess

    _CHESS_OK = True
except ImportError:  # pragma: no cover - dépendance de développement absente
    _CHESS_OK = False

ENGINE = "python -m chessproject.uci"


# --------------------------------------------------------------------------
# Statistiques
# --------------------------------------------------------------------------
def test_elo_difference_reference_values() -> None:
    assert match.elo_difference(0.5) == 0.0
    assert math.copysign(1.0, match.elo_difference(0.5)) == 1.0  # pas de -0.0
    assert match.elo_difference(0.75) == pytest.approx(190.85, abs=0.01)
    assert match.elo_difference(0.25) == pytest.approx(-190.85, abs=0.01)
    assert match.elo_difference(0.64) == pytest.approx(100.0, abs=0.5)
    assert match.elo_difference(1.0) == math.inf
    assert match.elo_difference(0.0) == -math.inf


def test_elo_difference_is_antisymmetric_and_increasing() -> None:
    scores = [i / 100 for i in range(1, 100)]
    elos = [match.elo_difference(s) for s in scores]
    assert elos == sorted(elos)
    for s in scores:
        assert match.elo_difference(1 - s) == pytest.approx(-match.elo_difference(s))


def test_score_and_stderr() -> None:
    assert match.match_score(10, 20, 10) == 0.5
    # Que des nulles : aucune variance.
    assert match.score_stderr(0, 40, 0) == 0.0
    # Moitié victoires, moitié défaites : σ = 0,5 par partie, σ/√N.
    assert match.score_stderr(50, 0, 50) == pytest.approx(0.05)
    with pytest.raises(ValueError):
        match.match_score(0, 0, 0)


def test_elo_interval() -> None:
    low, high = match.elo_interval(50, 0, 50)
    # s = 0,5 ± 1,96 × 0,05 → [0,402 ; 0,598] → environ ±69 Elo
    assert high == pytest.approx(match.elo_difference(0.5 + match.Z_95 * 0.05))
    assert high == pytest.approx(69.0, abs=0.5)
    assert low == pytest.approx(-high)
    assert low < 0 < high
    # Plus de parties : intervalle plus étroit.
    low2, high2 = match.elo_interval(500, 0, 500)
    assert high2 - low2 < high - low
    # Les nulles réduisent la variance (à score égal).
    low3, high3 = match.elo_interval(25, 50, 25)
    assert high3 - low3 < high - low
    # Score parfait : borne haute finie (score ramené dans ]0, 1[), point central infini.
    low4, high4 = match.elo_interval(10, 0, 0)
    assert math.isfinite(low4) and math.isfinite(high4)


def test_likelihood_of_superiority() -> None:
    assert match.likelihood_of_superiority(0, 0) == 0.5
    assert match.likelihood_of_superiority(10, 10) == 0.5
    assert match.likelihood_of_superiority(30, 20) == pytest.approx(0.9214, abs=1e-3)
    assert match.likelihood_of_superiority(20, 30) == pytest.approx(1 - 0.9214, abs=1e-3)


def test_summarize_counts() -> None:
    def record(i: int, score: float, termination: str) -> match.GameRecord:
        return match.GameRecord(i, 0, "", True, score, "*", termination, 10, 0.1)

    summary = match.summarize(
        [record(0, 1.0, "checkmate"), record(1, 0.5, "stalemate"), record(2, 0.0, "checkmate")],
        1.0,
    )
    assert (summary.wins, summary.draws, summary.losses) == (1, 1, 1)
    assert summary.score == 0.5
    assert summary.terminations == {"checkmate": 2, "stalemate": 1}


# --------------------------------------------------------------------------
# Ouvertures et planification
# --------------------------------------------------------------------------
def test_default_openings_are_legal_and_distinct() -> None:
    fens = match.load_openings(match.DEFAULT_OPENINGS)
    assert len(fens) >= 24
    assert len(set(fens)) == len(fens)
    for fen in fens:
        gs = load_fen(fen)
        assert gs.get_valid_moves(), fen
        assert not gs.result().is_over
        if _CHESS_OK:
            board = chess.Board(fen)
            assert board.is_valid(), fen
            assert not board.is_game_over()
            assert board.fen() == fen  # même écriture que python-chess


def test_load_openings_rejects_invalid_fen(tmp_path: Path) -> None:
    path = tmp_path / "bad.txt"
    path.write_text("# commentaire\n\n8/8/8/8/8/8/8/8 w - - 0 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="bad.txt:3"):
        match.load_openings(path)


def test_schedule_plays_each_opening_twice_with_colors_swapped() -> None:
    plan = match.schedule(3, 6, seed=None)
    assert plan == [(0, True), (0, False), (1, True), (1, False), (2, True), (2, False)]
    shuffled = match.schedule(24, 48, seed=1)
    assert sorted(o for o, _ in shuffled) == sorted(list(range(24)) * 2)
    assert shuffled == match.schedule(24, 48, seed=1)
    assert match.schedule(2, 5, None)[4] == (0, True)  # au-delà : on recommence


def test_uci_client_helpers() -> None:
    assert engine_argv("python -m chessproject.uci")[0] == sys.executable
    assert engine_argv("stockfish")[0] == "stockfish"
    env, cwd = engine_env_and_cwd("/tmp/ref")
    assert env["PYTHONPATH"] == "/tmp/ref" and cwd == "/tmp/ref"
    assert engine_env_and_cwd(None)[1] is None
    assert go_command(3, 100) == "go depth 3"
    assert go_command(None, 100) == "go movetime 100"
    assert move_timeout(None, 1000, None) == 8.0
    assert move_timeout(2, None, 1.5) == 1.5


# --------------------------------------------------------------------------
# Arbitrage
# --------------------------------------------------------------------------
_FAKE_ENGINE = (
    "import sys\n"
    "for line in sys.stdin:\n"
    "    cmd = line.split()[0] if line.split() else ''\n"
    "    if cmd == 'uci': print('uciok', flush=True)\n"
    "    elif cmd == 'isready': print('readyok', flush=True)\n"
    "    elif cmd == 'go': print('bestmove {move}', flush=True)\n"
    "    elif cmd == 'quit': break\n"
)


def _fake_engine(tmp_path: Path, move: str) -> str:
    script = tmp_path / f"fake_{move}.py"
    script.write_text(_FAKE_ENGINE.format(move=move), encoding="utf-8")
    return f'python "{script}"'


def _config(**kwargs: object) -> match.MatchConfig:
    values: dict[str, object] = {"depth": 1, "movetime_ms": None, "max_plies": 40}
    values["timeout_s"] = 30.0
    values.update(kwargs)
    return match.MatchConfig(**values)  # type: ignore[arg-type]


def test_illegal_move_loses(tmp_path: Path) -> None:
    good = match.EngineSpec("bon", ENGINE)
    bad = match.EngineSpec("fautif", _fake_engine(tmp_path, "a1a1"))
    fen = match.load_openings(match.DEFAULT_OPENINGS)[0]  # Les Blancs ont le trait
    record = match.play_game(0, 0, fen, False, good, bad, _config())
    assert record.termination == "illegal_move"
    assert record.score_a == 1.0 and record.pgn_result == "0-1"
    assert record.fault is not None and "fautif" in record.fault


def test_silent_engine_loses_on_timeout(tmp_path: Path) -> None:
    good = match.EngineSpec("bon", ENGINE)
    script = tmp_path / "mute.py"
    script.write_text(
        _FAKE_ENGINE.replace("print('bestmove {move}', flush=True)", "pass"), encoding="utf-8"
    )
    mute = match.EngineSpec("muet", f'python "{script}"')
    fen = match.load_openings(match.DEFAULT_OPENINGS)[0]
    record = match.play_game(0, 0, fen, True, good, mute, _config(timeout_s=1.0))
    assert record.termination == "engine_failure"
    assert record.score_a == 1.0 and record.plies == 1


def test_missing_engine_loses() -> None:
    good = match.EngineSpec("bon", ENGINE)
    missing = match.EngineSpec("absent", "moteur-qui-n-existe-pas-1234")
    fen = match.load_openings(match.DEFAULT_OPENINGS)[0]
    record = match.play_game(0, 0, fen, True, good, missing, _config())
    assert record.termination == "engine_failure"
    assert record.score_a == 1.0


def test_parse_options() -> None:
    assert match.parse_options(None) == {}
    assert match.parse_options(["UCI_LimitStrength=true", " UCI_Elo = 1500 "]) == {
        "UCI_LimitStrength": "true",
        "UCI_Elo": "1500",
    }
    for bad in ("UCI_Elo", "=1500"):
        with pytest.raises(ValueError):
            match.parse_options([bad])


def test_engine_options_are_sent_before_the_game(tmp_path: Path) -> None:
    log = tmp_path / "received.txt"
    script = tmp_path / "logger.py"
    script.write_text(
        _FAKE_ENGINE.format(move="0000").replace(
            "for line in sys.stdin:\n",
            f"log = open({str(log)!r}, 'w', encoding='utf-8')\n"
            "for line in sys.stdin:\n    log.write(line); log.flush()\n",
        ),
        encoding="utf-8",
    )
    good = match.EngineSpec("bon", ENGINE)
    spec = match.EngineSpec("journal", f'python "{script}"', options={"UCI_Elo": "1500"})
    fen = match.load_openings(match.DEFAULT_OPENINGS)[0]
    match.play_game(0, 0, fen, False, good, spec, _config())
    lines = log.read_text(encoding="utf-8").splitlines()
    assert "setoption name UCI_Elo value 1500" in lines
    assert lines.index("setoption name UCI_Elo value 1500") < lines.index("ucinewgame")


def test_checkmate_detected_by_arbiter() -> None:
    # Mat en 1 pour les Blancs (Ta8#) : la partie s'arrête au premier coup.
    fen = "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"
    spec = match.EngineSpec("moteur", ENGINE)
    record = match.play_game(0, 0, fen, True, spec, spec, _config(depth=2))
    assert record.termination == "checkmate"
    assert record.moves == ["a1a8"]
    assert record.score_a == 1.0 and record.pgn_result == "1-0"


def test_short_match_cli(tmp_path: Path) -> None:
    """Intégration : 2 parties à profondeur 1, limitées à 40 demi-coups (≈ 1 s)."""
    out = tmp_path / "res.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(TOOLS / "match.py"),
            "--engine-a",
            ENGINE,
            "--engine-b",
            ENGINE,
            "--games",
            "2",
            "--depth",
            "1",
            "--max-plies",
            "40",
            "--json",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "V/N/D pour A" in completed.stdout
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["summary"]["games"] == 2
    assert [g["a_is_white"] for g in data["games"]] == [True, False]
    for game in data["games"]:
        assert game["fault"] is None
        assert game["plies"] <= 40


@pytest.mark.slow
def test_self_play_is_balanced() -> None:
    """Moteur contre lui-même, 8 parties à profondeur 2 : aucune faute, score non extrême."""
    spec_a = match.EngineSpec("A", ENGINE)
    spec_b = match.EngineSpec("B", ENGINE)
    openings = match.load_openings(match.DEFAULT_OPENINGS)
    records, summary = match.run_match(
        spec_a, spec_b, openings, 8, _config(depth=2, max_plies=200), concurrency=4, log=False
    )
    print(f"\nAutojeu : V/N/D {summary.wins}/{summary.draws}/{summary.losses}")
    assert summary.games == 8
    assert not summary.faults
    # Même moteur, ouvertures jouées des deux côtés et recherche déterministe :
    # chaque paire est symétrique ou presque.
    assert 0.2 <= summary.score <= 0.8
    assert len(records) == 8
