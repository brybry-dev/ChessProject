"""
Exécutable autonome (J6.2)
-------------------------
Construit ChessProject avec PyInstaller pour le système courant, puis, avec
``--smoke-test``, lance l'exécutable obtenu en mode test de démarrage (partie
automatique contre l'IA, sans fenêtre) et produit l'archive à publier.

    python -m pip install -e ".[build]"
    python tools/build_exe.py --smoke-test

Résultat : ``dist/ChessProject-<version>-<système>-<architecture>.zip``.
Le dossier est en mode « onedir » (démarrage rapide, pas d'extraction temporaire) ;
sous macOS, c'est un paquet ``ChessProject.app``.
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from chessproject import __version__  # noqa: E402

APP_NAME = "ChessProject"
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def system_name() -> str:
    return {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(
        platform.system(), platform.system().lower()
    )


def archive_name(version: str = __version__) -> str:
    machine = platform.machine().lower().replace("amd64", "x64").replace("x86_64", "x64")
    return f"{APP_NAME}-{version}-{system_name()}-{machine}"


def executable() -> Path:
    """Chemin de l'exécutable construit."""
    if system_name() == "macos":
        return DIST / f"{APP_NAME}.app" / "Contents" / "MacOS" / APP_NAME
    suffix = ".exe" if system_name() == "windows" else ""
    return DIST / APP_NAME / f"{APP_NAME}{suffix}"


def build() -> None:
    import PyInstaller.__main__

    assets = ROOT / "chessproject" / "assets"
    PyInstaller.__main__.run(
        [
            str(ROOT / "chessproject" / "__main__.py"),
            "--name",
            APP_NAME,
            "--noconfirm",
            "--clean",
            "--onedir",
            "--windowed",
            "--icon",
            str(assets / "icon.png"),
            "--add-data",
            f"{assets}{os.pathsep}chessproject/assets",
            "--osx-bundle-identifier",
            "io.github.brybry-dev.chessproject",
            "--distpath",
            str(DIST),
            "--workpath",
            str(BUILD),
            "--specpath",
            str(BUILD),
        ]
    )


def smoke_test() -> None:
    """Lance l'exécutable en mode test de démarrage ; lève une erreur s'il échoue."""
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    result = subprocess.run(
        [str(executable()), "--smoke-test"], env=env, timeout=180, capture_output=True, text=True
    )
    print(result.stdout, result.stderr, sep="\n")
    if result.returncode != 0:
        raise SystemExit(f"Test de démarrage de l'exécutable en échec (code {result.returncode})")
    print("Test de démarrage de l'exécutable : ok")


def archive() -> Path:
    source = DIST / (f"{APP_NAME}.app" if system_name() == "macos" else APP_NAME)
    base = DIST / archive_name()
    # Sous macOS, l'archive garde le paquet .app à sa racine.
    path = shutil.make_archive(str(base), "zip", root_dir=source.parent, base_dir=source.name)
    print(f"Archive : {path}")
    return Path(path)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--smoke-test", action="store_true", help="tester l'exécutable construit")
    parser.add_argument("--no-build", action="store_true", help="réutiliser dist/ existant")
    args = parser.parse_args(argv)
    if not args.no_build:
        build()
    if args.smoke_test:
        smoke_test()
    archive()


if __name__ == "__main__":
    main()
