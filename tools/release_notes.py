"""
Notes de version (J6.4)
----------------------
Extrait de ``CHANGELOG.md`` la section d'une version, pour la release GitHub :

    python tools/release_notes.py 1.0.0 > notes.md
    python tools/release_notes.py v1.0.0       # le préfixe « v » du tag est accepté

Sort en erreur si la version est absente du changelog : on ne publie pas une version
sans notes.
"""

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def section(text: str, version: str) -> str:
    """Contenu de la section ``## [version]`` (sans son titre), ou ValueError."""
    version = version.removeprefix("v")
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(rf"^## \[{re.escape(version)}\]", line):
            start = i + 1
        elif start is not None and (line.startswith("## [") or re.match(r"^\[[^\]]+\]: ", line)):
            return "\n".join(lines[start:i]).strip() + "\n"
    if start is None:
        raise ValueError(f"Version {version} absente du changelog")
    return "\n".join(lines[start:]).strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage : release_notes.py <version>", file=sys.stderr)
        return 2
    try:
        sys.stdout.write(section(CHANGELOG.read_text(encoding="utf-8"), args[0]))
    except ValueError as ex:
        print(ex, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
