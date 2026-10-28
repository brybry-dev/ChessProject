"""Couverture en CI (J12.1) : regroupement par paquet, badge, seuil bloquant sur core
(cf. ``tools/coverage_report.py``)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import coverage_report


def _report(**files: tuple[int, int]) -> dict:
    return {
        "files": {
            name.replace("__", "/") + ".py": {
                "summary": {"num_statements": statements, "covered_lines": covered}
            }
            for name, (statements, covered) in files.items()
        }
    }


REPORT = _report(
    chessproject__core__engine=(600, 580),
    chessproject__core__fen=(100, 100),
    chessproject__ui__app=(300, 240),
    chessproject__uci=(100, 50),
    tests__test_chess=(50, 50),  # hors du paquet : ignoré
)


class CoverageReportTests(unittest.TestCase):
    def test_statements_are_summed_per_package(self):
        packages = coverage_report.by_package(REPORT)
        self.assertEqual(list(packages), ["(racine)", "core", "ui"])
        self.assertEqual(packages["core"], coverage_report.Coverage(700, 680))
        self.assertAlmostEqual(packages["core"].percent, 97.14, places=2)
        self.assertEqual(coverage_report.total(packages), coverage_report.Coverage(1100, 970))

    def test_badge_follows_the_total(self):
        self.assertEqual(
            coverage_report.badge(94.4),
            {"schemaVersion": 1, "label": "couverture", "message": "94 %", "color": "green"},
        )
        self.assertEqual(coverage_report.badge(60)["color"], "red")
        self.assertEqual(coverage_report.badge(100)["color"], "brightgreen")

    def test_command_line_writes_the_badge_and_the_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            report = folder / "coverage.json"
            report.write_text(json.dumps(REPORT), encoding="utf-8")
            badge, summary = folder / "badge.json", folder / "summary.md"
            code = coverage_report.main(
                [str(report), "--badge", str(badge), "--summary", str(summary)]
            )
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(badge.read_text("utf-8"))["message"], "88 %")
            self.assertIn("| `core` | 700 | 680 | 97.1 % |", summary.read_text("utf-8"))

    def test_core_below_the_threshold_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "coverage.json"
            report.write_text(json.dumps(REPORT), encoding="utf-8")
            self.assertEqual(coverage_report.main([str(report), "--core-min", "98"]), 1)
            report.write_text(json.dumps(_report(chessproject__uci=(10, 10))), "utf-8")
            self.assertEqual(coverage_report.main([str(report)]), 1)  # core absent


if __name__ == "__main__":
    unittest.main()
