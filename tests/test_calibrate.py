"""Tests de l'échelle des niveaux ``tools/calibrate.py`` (J8.0)."""

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import calibrate
import match

from chessproject.ai import levels
from chessproject.core.fen import load_fen


def test_parse_rung_accepts_names_and_specs() -> None:
    rung = calibrate.parse_rung("Facile")
    assert rung.level is levels.LEVELS_BY_NAME["Facile"]
    assert rung.command.endswith("--level Facile")
    custom = calibrate.parse_rung("base=Moyen,nodes=3000")
    assert custom.level.max_nodes == 3000
    assert custom.label == "Moyen*"
    assert calibrate.parse_rung("name=M2,base=Moyen").label == "M2"
    assert custom.command.endswith("--level-spec base=Moyen,nodes=3000")
    with pytest.raises(ValueError):
        calibrate.parse_rung("Inconnu")


def test_book_openings_are_distinct_legal_positions() -> None:
    fens = calibrate.book_openings(50)
    assert len(fens) == len(set(fens)) == 50
    for fen in fens:
        load_fen(fen)
    with pytest.raises(ValueError):
        calibrate.book_openings(100_000)


def test_parse_anchor() -> None:
    assert calibrate.parse_anchor("4=1650:45", 5) == (4, 1650.0, 45.0)
    assert calibrate.parse_anchor("0=1000", 5) == (0, 1000.0, 0.0)
    for bad in ("1650", "5=1650", "-1=1000", "0=1000:-3"):
        with pytest.raises(ValueError):
            calibrate.parse_anchor(bad, 5)


def test_pair_result_matches_the_match_statistics() -> None:
    pair = calibrate.pair_result("A", "B", 50, 20, 30)
    assert pair.score == pytest.approx(0.6)
    assert pair.elo == pytest.approx(match.elo_difference(0.6))
    low, high = match.elo_interval(50, 20, 30)
    assert pair.elo_se == pytest.approx((high - low) / (2 * match.Z_95))


def test_pair_result_stays_finite_on_a_whitewash() -> None:
    pair = calibrate.pair_result("A", "B", 100, 0, 0)
    assert math.isfinite(pair.elo) and math.isfinite(pair.elo_se) and pair.elo > 0


def test_chain_ratings_adds_offsets_and_variances() -> None:
    labels = ["D", "F", "M"]
    pairs = [
        calibrate.PairResult("D", "F", 0, 0, 0, 0.7, 150.0, 30.0),
        calibrate.PairResult("F", "M", 0, 0, 0, 0.65, 100.0, 40.0),
    ]
    from_bottom = calibrate.chain_ratings(labels, pairs)
    assert [r.elo for r in from_bottom] == [0.0, 150.0, 250.0]
    assert [r.se for r in from_bottom] == pytest.approx([0.0, 30.0, 50.0])
    from_top = calibrate.chain_ratings(labels, pairs, anchor=(2, 1600.0, 20.0))
    assert [r.elo for r in from_top] == [1350.0, 1500.0, 1600.0]
    assert [r.se for r in from_top] == pytest.approx(
        [math.sqrt(20**2 + 50**2), math.sqrt(20**2 + 40**2), 20.0]
    )
    with pytest.raises(ValueError):
        calibrate.chain_ratings(labels, pairs[:1])


def test_short_ladder_cli(tmp_path: Path) -> None:
    """Intégration : deux échelons très bornés, 2 parties de 20 demi-coups au plus."""
    out = tmp_path / "echelle.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(TOOLS / "calibrate.py"),
            "base=Débutant,nodes=50,movetime=100",
            "base=Débutant,nodes=200,movetime=100",
            "--games",
            "2",
            "--max-plies",
            "20",
            "--json",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "| Échelon | Elo | IC 95 % |" in completed.stdout
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["pairs"]) == 1 and len(data["ratings"]) == 2
    pair = data["pairs"][0]
    assert pair["wins"] + pair["draws"] + pair["losses"] == 2
