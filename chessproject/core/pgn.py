"""
PGN (Portable Game Notation)
----------------------------
Export (J4.3) et import (J4.4) de parties au format PGN, sans dépendance externe ni
pygame.

**Export** — :func:`export_pgn` produit :

- le *Seven Tag Roster* dans l'ordre imposé (Event, Site, Date, Round, White, Black,
  Result), avec des valeurs par défaut (« ? », date « ????.??.?? ») ;
- ``[SetUp "1"]`` et ``[FEN "..."]`` si la partie ne part pas de la position initiale
  (position différente ou numéro de coup de départ différent de 1) ;
- ``[Termination "..."]`` quand la partie est finie (cf. :data:`TERMINATION_TAGS`) ;
- les autres en-têtes fournis (``TimeControl``…), dans l'ordre donné ;
- les coups en SAN, numérotés depuis le numéro de coup de départ (« 12... Nf6 » si les
  Noirs commencent), terminés par le résultat, en lignes d'au plus 80 caractères coupées
  entre deux jetons (un jeton n'est jamais coupé).

**Import** (J4.4, commit suivant) — :func:`parse_pgn` lit un texte contenant une ou plusieurs parties.
Commentaires ``{...}`` et ``;`` (jusqu'à la fin de la ligne), lignes d'échappement ``%``,
variantes ``(...)`` (imbriquées), NAG ``$n``, suffixes ``!``/``?`` et numéros de coup
sont ignorés ; seule la ligne principale est conservée. Chaque coup est **validé** par
le moteur au fil de la lecture.

Sécurité (rapport §3.3) : le texte vient de l'extérieur, rien n'y est supposé correct.

- Les en-têtes ``[SetUp]`` / ``[FEN]`` ne sont jamais crus sur parole : la FEN est
  validée par :func:`chessproject.core.fen.load_fen` (une :class:`FenError` devient une
  :class:`PgnError`), et tous les coups sont rejoués et vérifiés par le moteur.
- Limites : taille du fichier (:func:`read_pgn_file`, 5 Mo par défaut), nombre de
  parties (10 000) et de demi-coups par partie (2 000) ; au-delà, :class:`PgnError`.
- L'analyse est itérative (pas de récursion sur les variantes imbriquées) et linéaire
  en la taille du texte.

Toutes les erreurs de contenu lèvent :class:`PgnError` (sous-classe de ``ValueError``)
avec un message en français indiquant le numéro de la partie et le coup fautif.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from chessproject.core.engine import GameResult, GameState, Termination
from chessproject.core.fen import FenError, load_fen
from chessproject.core.notation import NotationError, parse_san, san_history
from chessproject.serialization import fullmove_number, to_fen


class PgnError(ValueError):
    """PGN illisible, trop volumineux, ou décrivant une partie illégale."""


STANDARD_START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

#: Les sept en-têtes obligatoires, dans l'ordre du standard PGN (§8.1.1).
SEVEN_TAG_ROSTER: tuple[str, ...] = ("Event", "Site", "Date", "Round", "White", "Black", "Result")
_ROSTER_DEFAULTS: dict[str, str] = {
    "Event": "?",
    "Site": "?",
    "Date": "????.??.??",
    "Round": "?",
    "White": "?",
    "Black": "?",
    "Result": "*",
}

#: Correspondance motif de fin du moteur → valeur de l'en-tête ``[Termination]``
#: (valeurs du standard PGN §9.8.1). Les fins prévues par les règles (mat, pat, nulles
#: automatiques) ainsi que l'abandon et la nulle par accord sont des fins « normal » ;
#: les fins au temps, y compris la nulle au temps contre un matériel insuffisant, sont
#: « time forfeit ». Une partie en cours n'a pas d'en-tête Termination.
TERMINATION_TAGS: dict[Termination, str] = {
    Termination.CHECKMATE: "normal",
    Termination.STALEMATE: "normal",
    Termination.FIFTY_MOVES: "normal",
    Termination.THREEFOLD_REPETITION: "normal",
    Termination.INSUFFICIENT_MATERIAL: "normal",
    Termination.RESIGNATION: "normal",
    Termination.DRAW_AGREEMENT: "normal",
    Termination.TIME_FORFEIT: "time forfeit",
    Termination.TIMEOUT_VS_INSUFFICIENT_MATERIAL: "time forfeit",
}

RESULTS: tuple[str, ...] = ("1-0", "0-1", "1/2-1/2", "*")
MAX_LINE_LENGTH = 80

_TAG_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
_DATE_RE = re.compile(r"^[0-9?]{4}\.[0-9?]{2}\.[0-9?]{2}$")


# --------------------------------------------------------------------------
# Modèle
# --------------------------------------------------------------------------
@dataclass
class PgnGame:
    """Une partie lue dans un PGN (ligne principale seulement).

    ``headers`` commence par les sept en-têtes obligatoires (complétés par défaut s'ils
    manquent), suivis des autres dans l'ordre du fichier. ``start_fen`` vaut None pour la
    position initiale. ``moves`` contient la SAN canonique (celle de
    :func:`chessproject.core.notation.to_san`) des coups, déjà validés.
    """

    headers: dict[str, str] = field(default_factory=dict)
    start_fen: str | None = None
    moves: list[str] = field(default_factory=list)
    result: str = "*"

    def start_state(self) -> GameState:
        """Position de départ (validée par ``load_fen`` si ``start_fen`` est fournie)."""
        if self.start_fen is None:
            return GameState()
        try:
            return load_fen(self.start_fen)
        except FenError as exc:
            raise PgnError(f"FEN de départ invalide : {exc}") from exc

    def replay(self) -> GameState:
        """Rejoue les coups depuis la position de départ et renvoie la position finale.

        Lève :class:`PgnError` si un coup est illisible ou illégal.
        """
        game_state = self.start_state()
        for san in self.moves:
            try:
                move = parse_san(game_state, san)
            except NotationError as exc:
                raise PgnError(f"Coup {_move_label(game_state)} {san!r} injouable : {exc}") from exc
            game_state.make_move(move, validate=False)
        return game_state


def _move_label(game_state: GameState) -> str:
    """« 12. » ou « 12... » pour le prochain coup à jouer dans ``game_state``."""
    number = fullmove_number(game_state)
    return f"{number}." if game_state.white_to_move else f"{number}..."


# --------------------------------------------------------------------------
# Export (J4.3)
# --------------------------------------------------------------------------
def _escape(value: str) -> str:
    """Valeur d'en-tête : ``\\`` et ``"`` échappés, retours à la ligne remplacés."""
    value = " ".join(value.splitlines())
    return value.replace("\\", "\\\\").replace('"', '\\"')


def start_position(game_state: GameState) -> GameState:
    """Copie de ``game_state`` ramenée à sa position de départ (annulations successives)."""
    start = copy.deepcopy(game_state)
    for _ in range(len(start.move_log)):
        start.undo_move()
    return start


def wrap_tokens(tokens: list[str], width: int = MAX_LINE_LENGTH) -> list[str]:
    """Regroupe des jetons en lignes d'au plus ``width`` caractères, sans couper un jeton
    (un jeton plus long que ``width`` occupe seul sa ligne)."""
    lines: list[str] = []
    current = ""
    for token in tokens:
        if not current:
            current = token
        elif len(current) + 1 + len(token) <= width:
            current += " " + token
        else:
            lines.append(current)
            current = token
    if current:
        lines.append(current)
    return lines


def movetext_tokens(sans: list[str], start_fullmove: int, white_starts: bool) -> list[str]:
    """Jetons du texte des coups : ``["1.", "e4", "e5", "2.", ...]`` ou
    ``["12...", "Nf6", "13.", ...]`` si les Noirs commencent."""
    tokens: list[str] = []
    number = start_fullmove
    white = white_starts
    for index, san in enumerate(sans):
        if white:
            tokens.append(f"{number}.")
        elif index == 0:
            tokens.append(f"{number}...")
        tokens.append(san)
        if not white:
            number += 1
        white = not white
    return tokens


def export_pgn(
    game_state: GameState,
    result: GameResult | None = None,
    headers: dict[str, str] | None = None,
) -> str:
    """Texte PGN complet de la partie ``game_state`` (laissée intacte).

    ``result`` : résultat à écrire (par défaut ``game_state.result()``, « * » si la partie
    continue) ; il fixe l'en-tête Result et le jeton final, qui ne peuvent pas être
    imposés par ``headers``. ``headers`` : en-têtes supplémentaires ou remplaçant les
    valeurs par défaut du Seven Tag Roster (Event, White, Date « AAAA.MM.JJ »,
    TimeControl…). ``SetUp`` / ``FEN`` sont toujours calculés depuis la partie ;
    ``Termination`` est déduit du résultat (cf. :data:`TERMINATION_TAGS`) sauf s'il est
    fourni. Lève ``ValueError`` pour un nom d'en-tête invalide ou une date mal formée.
    """
    if result is None:
        result = game_state.result()
    given = dict(headers or {})
    for name in given:
        if not _TAG_NAME_RE.match(name):
            raise ValueError(f"Nom d'en-tête PGN invalide : {name!r}")
    date = given.get("Date")
    if date is not None and not _DATE_RE.match(date):
        raise ValueError(f"Date PGN invalide : {date!r} (format AAAA.MM.JJ, « ? » permis)")

    start = start_position(game_state)
    start_fen = to_fen(start)
    sans = san_history(game_state)

    tags: dict[str, str] = {}
    for name in SEVEN_TAG_ROSTER:
        tags[name] = given.get(name, _ROSTER_DEFAULTS[name])
    tags["Result"] = result.pgn
    if start_fen != STANDARD_START_FEN:
        tags["SetUp"] = "1"
        tags["FEN"] = start_fen
    computed = {"Result", "SetUp", "FEN"}
    for name, value in given.items():
        if name not in tags and name not in computed and name != "Termination":
            tags[name] = value
    if "Termination" in given:
        tags["Termination"] = given["Termination"]
    elif result.termination is not None:
        tags["Termination"] = TERMINATION_TAGS[result.termination]

    lines = [f'[{name} "{_escape(value)}"]' for name, value in tags.items()]
    tokens = movetext_tokens(sans, start.start_fullmove, start.white_to_move)
    tokens.append(result.pgn)
    return "\n".join([*lines, "", *wrap_tokens(tokens)]) + "\n"


__all__ = [
    "PgnError",
    "PgnGame",
    "SEVEN_TAG_ROSTER",
    "STANDARD_START_FEN",
    "TERMINATION_TAGS",
    "export_pgn",
    "movetext_tokens",
    "start_position",
    "wrap_tokens",
]
