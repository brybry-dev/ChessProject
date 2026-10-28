"""Livraison (J6) : version, notes de version, nom des archives, test de démarrage."""

import os
import queue
import sys
import tomllib
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as p

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import build_exe
import release_notes

import chessproject
from chessproject.ui import app


class VersionTests(unittest.TestCase):
    def test_package_pyproject_and_changelog_agree(self):
        with open(ROOT / "pyproject.toml", "rb") as f:
            pyproject = tomllib.load(f)["project"]["version"]
        self.assertEqual(chessproject.__version__, pyproject)
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        first = next(line for line in changelog.splitlines() if line.startswith("## ["))
        self.assertTrue(first.startswith(f"## [{pyproject}]"), first)

    def test_version_option(self):
        with self.assertRaises(SystemExit) as ctx, mock.patch("sys.stdout"):
            app.main(["--version"])
        self.assertEqual(ctx.exception.code, 0)


CHANGELOG = """# Changelog

## [2.0.0] - 2027-01-01

### Ajouté
- Une chose.

## [1.0.0] - 2026-10-22

### Corrigé
- Une autre.

[2.0.0]: https://example.org/v2
"""


class ReleaseNotesTests(unittest.TestCase):
    def test_extracts_one_section(self):
        self.assertEqual(release_notes.section(CHANGELOG, "2.0.0"), "### Ajouté\n- Une chose.\n")
        self.assertEqual(release_notes.section(CHANGELOG, "v1.0.0"), "### Corrigé\n- Une autre.\n")

    def test_unknown_version_is_an_error(self):
        with self.assertRaises(ValueError):
            release_notes.section(CHANGELOG, "3.0.0")

    def test_real_changelog_has_notes_for_the_current_version(self):
        notes = release_notes.section(
            (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), chessproject.__version__
        )
        self.assertIn("### ", notes)  # au moins une rubrique (Ajouté, Corrigé…)
        self.assertNotIn("## [", notes)


class ArchiveNameTests(unittest.TestCase):
    def test_names_and_paths_per_system(self):
        cases = [
            ("Windows", "AMD64", "ChessProject-1.0.0-windows-x64", "ChessProject.exe"),
            ("Linux", "x86_64", "ChessProject-1.0.0-linux-x64", "ChessProject"),
            ("Darwin", "arm64", "ChessProject-1.0.0-macos-arm64", "ChessProject"),
        ]
        for system, machine, name, exe in cases:
            with (
                self.subTest(system=system),
                mock.patch("platform.system", return_value=system),
                mock.patch("platform.machine", return_value=machine),
            ):
                self.assertEqual(build_exe.archive_name("1.0.0"), name)
                self.assertEqual(build_exe.executable().name, exe)
                if system == "Darwin":
                    self.assertIn("ChessProject.app", build_exe.executable().parts)


class _InlineProcess:
    def __init__(self, target, args=(), **kwargs):
        self._target, self._args, self._ran, self.exitcode = target, args, False, None

    def start(self):
        self._target(*self._args)
        self._ran, self.exitcode = True, 0

    def is_alive(self):
        return not self._ran

    def terminate(self):
        self._ran = True


class _Queue:
    def __init__(self):
        self._q: queue.Queue[object] = queue.Queue()

    def put(self, x):
        self._q.put(x)

    def get(self, block=True, timeout=None):
        return self._q.get_nowait()


class SmokeTestTests(unittest.TestCase):
    def test_smoke_test_plays_against_the_ai(self):
        p.init()
        screen = p.display.set_mode((1280, 800))
        with (
            mock.patch.object(app, "Process", _InlineProcess),
            mock.patch.object(app, "Queue", _Queue),
            mock.patch.object(app.settings_module, "save"),
        ):
            self.assertTrue(app.smoke_test(screen, app.PieceSet()))


if __name__ == "__main__":
    unittest.main()
