"""Audit des contrastes WCAG 2.2 niveau AA (J11.4) : formules de la norme, puis aucune
paire de couleurs de l'interface sous son seuil, dans les deux thèmes et sur les
quatre échiquiers (cf. ``tools/contrast.py``)."""

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import contrast

from chessproject.ui import theme as th


def test_formulas_match_the_standard() -> None:
    assert contrast.contrast((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0)
    assert contrast.contrast((255, 255, 255), (255, 255, 255)) == pytest.approx(1.0)
    # Valeurs de référence (WebAIM) : #777777 sur blanc 4,48:1, #767676 4,54:1.
    assert contrast.contrast((0x77, 0x77, 0x77), (255, 255, 255)) == pytest.approx(4.48, abs=0.01)
    assert contrast.contrast((0x76, 0x76, 0x76), (255, 255, 255)) == pytest.approx(4.54, abs=0.01)
    assert contrast.over((0, 0, 0, 128), (255, 255, 255)) == (127, 127, 127)
    assert contrast.over((10, 20, 30), (255, 255, 255)) == (10, 20, 30)


def test_every_theme_and_board_is_audited() -> None:
    places = {pair.where for pair in contrast.audit()}
    for t in th.THEMES.values():
        assert f"thème {t.name}" in places
    for palette in th.PALETTES.values():
        assert f"échiquier {palette.name}" in places


def test_no_pair_is_below_the_aa_threshold() -> None:
    failures = [
        f"{p.where} · {p.what} : {p.ratio:.2f} < {p.threshold}"
        for p in contrast.audit()
        if not p.ok
    ]
    assert failures == []


def test_command_line_reports_success() -> None:
    assert contrast.main(["--failures"]) == 0
