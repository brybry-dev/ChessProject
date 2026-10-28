"""
Module chessproject.core.puzzles
--------------------------------
Problèmes « trouvez le meilleur coup » (J13.3) : lecture de la suite tactique au format
EPD et déroulement d'une série.

Format (``assets/tactics.epd``), une position par ligne ::

    <4 champs FEN> bm <coup SAN> [<coup SAN> ...]; [dm <N>;] id "<nom>";

``bm`` liste les coups acceptés, ``dm N`` (*direct mate*) marque un mat en N coups ;
sans ``dm``, la position est un gain de matériel. Les solutions sont vérifiées par
programme (``python tools/tactics.py --verify``) : pour un mat, ``bm`` est exactement
l'ensemble des coups qui matent en N et aucun mat plus court n'existe ; pour un gain,
``bm`` est l'unique coup qui gagne au moins la valeur d'un cavalier.

Série. Seules les positions à solution unique (un seul coup dans ``bm``) sont proposées.
Un problème est **réussi** quand ce coup est trouvé du premier essai, sans indice ni
solution ; un coup faux est repris (la pièce revient) et le joueur peut réessayer, mais
le problème ne compte plus. Le score de la série est le nombre de problèmes réussis sur
le nombre de problèmes terminés.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from chessproject.core.engine import GameState, Move
from chessproject.core.fen import load_fen
from chessproject.core.notation import parse_san, to_uci


# --------------------------------------------------------------------------
# Format EPD
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Puzzle:
    fen: str  # 4 champs
    best_moves: tuple[str, ...]  # SAN
    mate_in: int | None
    name: str

    def game_state(self) -> GameState:
        return load_fen(self.fen)

    def best_moves_uci(self) -> set[str]:
        gs = self.game_state()
        return {to_uci(parse_san(gs, san)) for san in self.best_moves}

    @property
    def white_to_move(self) -> bool:
        return self.fen.split()[1] == "w"


_OPERATION_RE = re.compile(r'\s*([A-Za-z][A-Za-z0-9_]*)\s+("[^"]*"|[^;]*);')


def parse_epd_line(line: str) -> Puzzle:
    """Lit une ligne EPD (``ValueError`` si elle est mal formée)."""
    fields = line.split(maxsplit=4)
    if len(fields) < 5:
        raise ValueError(f"Ligne EPD incomplète : {line!r}")
    fen = " ".join(fields[:4])
    operations: dict[str, str] = {}
    rest = fields[4]
    position = 0
    for match in _OPERATION_RE.finditer(rest):
        if rest[position : match.start()].strip():
            raise ValueError(f"Opération EPD illisible dans : {line!r}")
        operations[match.group(1)] = match.group(2).strip().strip('"')
        position = match.end()
    if rest[position:].strip():
        raise ValueError(f"Fin de ligne EPD illisible : {line!r}")
    if "bm" not in operations or "id" not in operations:
        raise ValueError(f"Opérations bm et id obligatoires : {line!r}")
    mate_in = int(operations["dm"]) if "dm" in operations else None
    return Puzzle(fen, tuple(operations["bm"].split()), mate_in, operations["id"])


def load_suite(path: Path) -> list[Puzzle]:
    puzzles = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            puzzles.append(parse_epd_line(line))
    return puzzles


def format_epd(puzzle: Puzzle) -> str:
    ops = f"bm {' '.join(puzzle.best_moves)};"
    if puzzle.mate_in is not None:
        ops += f" dm {puzzle.mate_in};"
    return f'{puzzle.fen} {ops} id "{puzzle.name}";'


def series(path: Path) -> list[Puzzle]:
    """Problèmes à solution unique, des plus courts aux plus longs : mats en 1, gains
    de matériel, puis mats en 2 et en 3 (ordre du fichier à difficulté égale)."""
    unique = [p for p in load_suite(path) if len(p.best_moves) == 1]

    def difficulty(puzzle: Puzzle) -> float:
        return 1.5 if puzzle.mate_in is None else puzzle.mate_in

    return sorted(unique, key=difficulty)


# --------------------------------------------------------------------------
# Déroulement d'une série
# --------------------------------------------------------------------------
@dataclass
class PuzzleRun:
    """Série de problèmes : problème courant, aides demandées et score."""

    puzzles: list[Puzzle]
    index: int = 0
    # Un résultat par problème terminé : True réussi, False raté (aide ou coup faux).
    results: list[bool] = field(default_factory=list)
    wrong_tries: int = 0
    hint_used: bool = False
    solution_shown: bool = False
    solved: bool = False

    def __post_init__(self) -> None:
        if not self.puzzles:
            raise ValueError("série vide")

    @property
    def current(self) -> Puzzle:
        return self.puzzles[self.index]

    @property
    def solution(self) -> str:
        return self.current.best_moves[0]

    @property
    def finished(self) -> bool:
        """Problème courant terminé : coup trouvé ou solution montrée."""
        return self.solved or self.solution_shown

    @property
    def is_last(self) -> bool:
        return self.index == len(self.puzzles) - 1

    @property
    def score(self) -> int:
        return sum(self.results)

    @property
    def done(self) -> int:
        return len(self.results)

    def position(self) -> GameState:
        return self.current.game_state()

    def solution_move(self, game_state: GameState) -> Move:
        return parse_san(game_state, self.solution)

    def answer(self, game_state: GameState, move: Move) -> bool:
        """Coup ``move`` proposé dans ``game_state`` (position du problème) : vrai s'il
        est la solution. Le premier coup juste termine le problème."""
        if self.solved:
            raise ValueError("problème déjà résolu")
        if move != self.solution_move(game_state):
            self.wrong_tries += 1
            return False
        self.solved = True
        self._finish()
        return True

    def hint(self) -> None:
        self.hint_used = True

    def show_solution(self) -> None:
        if not self.finished:
            self.solution_shown = True
            self._finish()

    def _finish(self) -> None:
        if len(self.results) == self.index:
            success = self.solved and not (
                self.wrong_tries or self.hint_used or self.solution_shown
            )
            self.results.append(success)

    def next(self) -> bool:
        """Passe au problème suivant (un problème sauté compte comme raté) ; faux après
        le dernier."""
        if not self.finished:
            self.solution_shown = True
            self._finish()
        if self.is_last:
            return False
        self.index += 1
        self.wrong_tries = 0
        self.hint_used = self.solution_shown = self.solved = False
        return True
