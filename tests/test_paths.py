"""Tests des chemins de ressources et de données utilisateur (B42, B43).

Le jeu doit fonctionner quel que soit le dossier de lancement : les ressources
(images, sons) sont résolues depuis le code, les données (sauvegarde, journal)
dans un dossier propre à l'utilisateur.
"""

import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_from(cwd, code, data_dir):
    env = dict(
        os.environ,
        PYTHONPATH=REPO,
        SDL_VIDEODRIVER="dummy",
        SDL_AUDIODRIVER="dummy",
        CHESSPROJECT_DATA_DIR=data_dir,
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


class ResourcesTests(unittest.TestCase):
    def test_pieces_fonts_and_sounds_load_from_another_directory(self):
        code = (
            "from chessproject import paths; from chessproject.ui import app;"
            "import pygame; pygame.font.init();"
            "from chessproject.ui import theme;"
            "assert app.ResourceManager().get_image('wK', 64).get_size() == (64, 64);"
            "assert (paths.PIECES_DIR / 'bP.svg').is_file();"
            "theme.font(14, 'semibold'); theme.font(14, mono=True);"
            "assert all((paths.FONTS_DIR / n).is_file() for n in "
            "('IBMPlexSans-Regular.ttf', 'IBMPlexMono-SemiBold.ttf'));"
            "assert all((paths.SOUNDS_DIR / n).is_file() for n in "
            "('move1.wav', 'capture1.wav', 'gameover.wav'))"
        )
        with tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as data:
            result = _run_from(cwd, code, data)
        self.assertEqual(result.returncode, 0, result.stderr)


class UserDataTests(unittest.TestCase):
    def test_log_goes_to_the_user_data_directory_at_info_level(self):
        code = (
            "import logging; from chessproject.ui import app;"
            "app._configure_logging();"
            "logging.getLogger('chessproject.ui.app').debug('bruit');"
            "logging.getLogger('chessproject.ui.app').info('signal');"
            "logging.shutdown()"
        )
        with tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as data:
            result = _run_from(cwd, code, data)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(os.listdir(cwd), [], "rien ne doit être écrit dans le dossier courant")
            with open(os.path.join(data, "chess.log"), encoding="utf-8") as f:
                log = f.read()
        self.assertIn("signal", log)
        self.assertNotIn("bruit", log)

    def test_save_file_lives_in_the_user_data_directory(self):
        code = "from chessproject import paths; print(paths.save_file())"
        with tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as data:
            result = _run_from(cwd, code, data)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                os.path.realpath(result.stdout.strip()),
                os.path.realpath(os.path.join(data, "saved_game.json")),
            )

    def test_legacy_save_in_the_working_directory_is_still_found(self):
        code = "from chessproject import paths; print(paths.existing_save_file())"
        with tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as data:
            with open(os.path.join(cwd, "saved_game.json"), "w", encoding="utf-8") as f:
                f.write("{}")
            result = _run_from(cwd, code, data)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                os.path.realpath(result.stdout.strip()),
                os.path.realpath(os.path.join(cwd, "saved_game.json")),
            )


if __name__ == "__main__":
    unittest.main()
