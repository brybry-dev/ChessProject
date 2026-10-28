"""
Couverture des tests (J12.1)
----------------------------
Lit le rapport JSON de coverage.py (``pytest --cov --cov-report=json``) et en tire :

- un tableau Markdown par paquet (``core``, ``ai``, ``ui``…), ajouté au résumé de la
  tâche CI (``--summary "$GITHUB_STEP_SUMMARY"``) ;
- le fichier du badge du README, au format « endpoint » de shields.io (``--badge``) ;
- un seuil bloquant sur le moteur de règles : code 1 si ``chessproject/core`` est sous
  ``--core-min`` pour cent.

    python -m pytest --cov --cov-report=json
    python tools/coverage_report.py coverage.json --badge coverage-badge.json --core-min 90

La couverture comptée est celle des instructions (lignes exécutables).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

PACKAGE = "chessproject"
# Couleur du badge selon le pourcentage total (paliers habituels de shields.io).
COLORS = ((95, "brightgreen"), (90, "green"), (80, "yellowgreen"), (70, "yellow"), (0, "red"))


@dataclass(frozen=True)
class Coverage:
    statements: int
    covered: int

    @property
    def percent(self) -> float:
        return 100.0 * self.covered / self.statements if self.statements else 100.0

    def __add__(self, other: Coverage) -> Coverage:
        return Coverage(self.statements + other.statements, self.covered + other.covered)


def by_package(report: dict) -> dict[str, Coverage]:
    """Couverture de chaque sous-paquet (« core », « ai »…) ; les modules à la racine du
    paquet (``uci.py``, ``settings.py``…) sont regroupés sous « (racine) »."""
    packages: dict[str, Coverage] = {}
    for name, data in report["files"].items():
        parts = Path(name).as_posix().split("/")
        if PACKAGE not in parts:
            continue
        inner = parts[parts.index(PACKAGE) + 1 :]
        package = inner[0] if len(inner) > 1 else "(racine)"
        summary = data["summary"]
        part = Coverage(summary["num_statements"], summary["covered_lines"])
        packages[package] = packages.get(package, Coverage(0, 0)) + part
    return dict(sorted(packages.items()))


def total(packages: dict[str, Coverage]) -> Coverage:
    result = Coverage(0, 0)
    for part in packages.values():
        result += part
    return result


def badge(percent: float) -> dict:
    color = next(name for floor, name in COLORS if percent >= floor)
    return {
        "schemaVersion": 1,
        "label": "couverture",
        "message": f"{percent:.0f} %",
        "color": color,
    }


def markdown(packages: dict[str, Coverage], core_min: float) -> str:
    lines = [
        "### Couverture des tests",
        "",
        "| Paquet | Instructions | Couvertes | Couverture |",
        "|---|---:|---:|---:|",
    ]
    for name, part in packages.items():
        lines.append(f"| `{name}` | {part.statements} | {part.covered} | {part.percent:.1f} % |")
    whole = total(packages)
    lines.append(
        f"| **Total** | {whole.statements} | {whole.covered} | **{whole.percent:.1f} %** |"
    )
    lines += ["", f"Seuil bloquant : `core` ≥ {core_min:g} %."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("report", type=Path, help="rapport JSON de coverage.py")
    parser.add_argument("--badge", type=Path, help="fichier du badge shields.io à écrire")
    parser.add_argument("--summary", type=Path, help="fichier Markdown complété (résumé CI)")
    parser.add_argument("--core-min", type=float, default=90.0, help="seuil de core (%%)")
    args = parser.parse_args(argv)

    packages = by_package(json.loads(args.report.read_text(encoding="utf-8")))
    text = markdown(packages, args.core_min)
    print(text)
    if args.summary is not None:
        with args.summary.open("a", encoding="utf-8") as summary:
            summary.write(text)
    if args.badge is not None:
        args.badge.write_text(json.dumps(badge(total(packages).percent)) + "\n", "utf-8")
    core = packages.get("core")
    if core is None or core.percent < args.core_min:
        found = "absent" if core is None else f"{core.percent:.1f} %"
        print(f"Couverture de core sous le seuil de {args.core_min:g} % : {found}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
