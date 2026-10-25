"""
Livre d'ouvertures (J8.3)
-------------------------
Lit ``assets/openings.tsv`` (code ECO, nom français, coups SAN depuis la position
initiale) et l'indexe **par position** (clé Zobrist du moteur) : une ouverture atteinte
par un autre ordre de coups est reconnue, et le livre s'applique aussi à une partie
importée.

- :func:`book_move` tire un coup du livre au hasard, pondéré par le nombre de lignes qui
  le jouent depuis la position : les suites les plus représentées sortent le plus
  souvent, les autres restent possibles (l'IA varie ses débuts). Les coups trop rares
  (moins de :data:`MIN_SHARE` des lignes de la position) ne sont pas joués : ces lignes
  servent seulement à nommer l'ouverture (1.g4, 1.a3…) ;
- :func:`identify` donne l'ouverture de la partie : la position nommée la plus récente
  de son historique.

Le livre est chargé une fois par processus (:func:`default_book`).
"""

import copy
import random
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from chessproject import paths
from chessproject.core import engine
from chessproject.core.notation import NotationError, parse_san, to_uci

# Part minimale des lignes de la position pour qu'un coup soit joué par le livre
MIN_SHARE: float = 0.02


class BookError(ValueError):
    """Ligne du livre invalide (format, ECO ou coup illégal), avec son numéro."""


@dataclass(frozen=True, slots=True)
class Opening:
    eco: str
    name: str

    @property
    def label(self) -> str:
        return f"{self.eco} · {self.name}"


@dataclass(slots=True)
class _Entry:
    opening: Opening | None = None  # nom de la position (fin d'une ligne du livre)
    # Position intermédiaire sans nom : dernier nom rencontré avant elle sur une ligne
    inherited: Opening | None = None
    moves: dict[str, int] = field(default_factory=dict)  # coup UCI -> nombre de lignes
    ply: int = 0  # demi-coups depuis la position initiale (première fois rencontrée)


def _valid_eco(eco: str) -> bool:
    return len(eco) == 3 and eco[0] in "ABCDE" and eco[1:].isdigit()


class OpeningBook:
    def __init__(self) -> None:
        self._entries: dict[int, _Entry] = {}
        self.lines = 0
        self.max_ply = 0

    @classmethod
    def from_lines(cls, lines: Iterable[str]) -> "OpeningBook":
        """Livre construit à partir des lignes du fichier TSV (``BookError`` si invalide)."""
        book = cls()
        paths: list[list[int]] = []
        for number, raw in enumerate(lines, start=1):
            text = raw.strip()
            if not text or text.startswith("#"):
                continue
            fields = raw.rstrip("\r\n").split("\t")
            if len(fields) != 3 or not all(f.strip() for f in fields):
                raise BookError(f"ligne {number} : trois champs attendus (ECO, nom, coups)")
            eco, name, sans = (f.strip() for f in fields)
            if not _valid_eco(eco):
                raise BookError(f"ligne {number} : code ECO invalide {eco!r}")
            paths.append(book._add_line(eco, name, sans.split(), number))
        # Seconde passe, une fois tous les noms connus : une position intermédiaire sans
        # nom reçoit le dernier nom de la ligne qui y passe (ex. 1.d4 d5 2.c4 e6 3.Nc3 Nf6
        # 4.Nf3 : « Gambit dame refusé », atteint aussi par 1.Nf3 d5 2.d4 Nf6 3.c4 e6 4.Nc3).
        for keys in paths:
            current: Opening | None = None
            for key in keys:
                entry = book._entries[key]
                if entry.opening is not None:
                    current = entry.opening
                elif entry.inherited is None:
                    entry.inherited = current
        return book

    def _add_line(self, eco: str, name: str, sans: list[str], number: int) -> list[int]:
        """Ajoute une ligne ; renvoie les clés des positions traversées (départ compris)."""
        game_state = engine.GameState()
        keys = [game_state.zobrist_key]
        for ply, san in enumerate(sans):
            entry = self._entries.setdefault(game_state.zobrist_key, _Entry(ply=ply))
            try:
                move = parse_san(game_state, san)
            except NotationError as exc:
                raise BookError(f"ligne {number} : coup {san!r} refusé ({exc})") from exc
            uci = to_uci(move)
            entry.moves[uci] = entry.moves.get(uci, 0) + 1
            game_state.make_move(move, validate=False)
            keys.append(game_state.zobrist_key)
        final = self._entries.setdefault(game_state.zobrist_key, _Entry(ply=len(sans)))
        final.opening = Opening(eco, name)
        self.lines += 1
        self.max_ply = max(self.max_ply, len(sans))
        return keys

    # -- consultation ---------------------------------------------------
    def candidates(self, game_state: engine.GameState) -> dict[str, int]:
        """Coups du livre (UCI -> poids) dans la position, vide hors du livre."""
        entry = self._entries.get(game_state.zobrist_key)
        return dict(entry.moves) if entry else {}

    def opening_at(self, game_state: engine.GameState) -> Opening | None:
        """Nom de la position (le sien, ou celui hérité de sa ligne), None hors du livre."""
        entry = self._entries.get(game_state.zobrist_key)
        if entry is None:
            return None
        return entry.opening or entry.inherited

    def book_move(
        self, game_state: engine.GameState, rng: random.Random | None = None
    ) -> engine.Move | None:
        """Coup du livre tiré au hasard (pondéré), ou None hors du livre."""
        weights = self.candidates(game_state)
        if not weights:
            return None
        legal = {to_uci(move): move for move in game_state.get_valid_moves()}
        # La clé Zobrist pourrait (très rarement) confondre deux positions : on ne garde
        # que les coups légaux ici.
        threshold = MIN_SHARE * sum(weights.values())
        choices = [
            (uci, weight)
            for uci, weight in sorted(weights.items())
            if uci in legal and weight >= threshold
        ]
        if not choices:
            return None
        rng = rng or random.Random()
        uci = rng.choices([c[0] for c in choices], weights=[c[1] for c in choices])[0]
        return legal[uci]

    def identify(self, game_state: engine.GameState) -> Opening | None:
        """Ouverture de la partie : position nommée la plus avancée de l'historique."""
        state = copy.deepcopy(game_state)
        while True:
            opening = self.opening_at(state)
            if opening is not None:
                return opening
            if not state.move_log:
                return None
            state.undo_move()


def book_path() -> Path:
    return paths.ASSETS_DIR / "openings.tsv"


@cache
def default_book() -> OpeningBook:
    """Livre livré avec le jeu, lu une seule fois par processus."""
    with book_path().open(encoding="utf-8") as handle:
        return OpeningBook.from_lines(handle)


def book_move(game_state: engine.GameState, rng: random.Random | None = None) -> engine.Move | None:
    return default_book().book_move(game_state, rng)


def identify(game_state: engine.GameState) -> Opening | None:
    return default_book().identify(game_state)
