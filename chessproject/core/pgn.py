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

**Import** — :func:`parse_pgn` lit un texte contenant une ou plusieurs parties.
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
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from chessproject.core.engine import GameResult, GameState, Termination
from chessproject.core.fen import FenError, fullmove_number, load_fen, to_fen
from chessproject.core.notation import NotationError, parse_san, san_history, to_san


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
    Termination.SEVENTY_FIVE_MOVES: "normal",
    Termination.FIVEFOLD_REPETITION: "normal",
    Termination.RESIGNATION: "normal",
    Termination.DRAW_AGREEMENT: "normal",
    Termination.TIME_FORFEIT: "time forfeit",
    Termination.TIMEOUT_VS_INSUFFICIENT_MATERIAL: "time forfeit",
}

RESULTS: tuple[str, ...] = ("1-0", "0-1", "1/2-1/2", "*")
MAX_LINE_LENGTH = 80
DEFAULT_MAX_BYTES = 5_000_000
DEFAULT_MAX_GAMES = 10_000
#: Nombre maximal de demi-coups de la ligne principale d'une partie.
DEFAULT_MAX_MOVES = 2_000

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
        """Position de départ (validée par ``load_fen`` si ``start_fen`` est fournie), en
        règles FIDE strictes : une partie réelle peut continuer après une triple
        répétition ou 50 coups non réclamés (cf. GameState.automatic_draws)."""
        try:
            state = GameState() if self.start_fen is None else load_fen(self.start_fen)
        except FenError as exc:
            raise PgnError(f"FEN de départ invalide : {exc}") from exc
        state.automatic_draws = False
        return state

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


# --------------------------------------------------------------------------
# Import (J4.4) : analyse lexicale
# --------------------------------------------------------------------------
# Jetons produits par _tokenize (genre ``kind``) :
#   "tag"            : en-tête, ``value`` = nom, ``tag_value`` = valeur déséchappée ;
#   "open" / "close" : parenthèses de variante ;
#   "word"           : coup, numéro de coup, résultat ou suffixe d'annotation.
# Commentaires, NAG et lignes d'échappement ne produisent aucun jeton.
_DELIMITERS = frozenset(' \t\r\n\f\v{}()[];"$%')
_MOVE_NUMBER_RE = re.compile(r"^\d+\.*")
_ANNOTATION_ONLY_RE = re.compile(r"^[!?]+$")


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str
    line: int
    tag_value: str = ""


def _tokenize(text: str) -> Iterator[_Token]:
    pos = 0
    line = 1
    length = len(text)
    at_line_start = True
    while pos < length:
        ch = text[pos]
        if ch == "\n":
            line += 1
            pos += 1
            at_line_start = True
            continue
        if ch in " \t\r\f\v﻿":
            pos += 1
            continue
        if ch == "%" and at_line_start:
            # Ligne d'échappement (§6) : ignorée jusqu'à la fin de la ligne.
            end = text.find("\n", pos)
            pos = length if end < 0 else end
            continue
        at_line_start = False
        if ch == ";":
            end = text.find("\n", pos)
            pos = length if end < 0 else end
        elif ch == "{":
            end = text.find("}", pos + 1)
            if end < 0:
                raise PgnError(f"Ligne {line} : commentaire « {{ » jamais refermé")
            line += text.count("\n", pos, end)
            pos = end + 1
        elif ch == "}":
            raise PgnError(f"Ligne {line} : « }} » sans « {{ » correspondant")
        elif ch == "(":
            yield _Token("open", ch, line)
            pos += 1
        elif ch == ")":
            yield _Token("close", ch, line)
            pos += 1
        elif ch == "[":
            pos, tag = _read_tag(text, pos, line)
            yield tag
        elif ch == "$":
            end = pos + 1
            while end < length and text[end].isdigit():
                end += 1
            if end == pos + 1:
                raise PgnError(f"Ligne {line} : NAG « $ » sans numéro")
            pos = end
        elif ch == '"' or ch == "]" or ch == "%":
            raise PgnError(f"Ligne {line} : caractère inattendu {ch!r}")
        else:
            end = pos
            while end < length and text[end] not in _DELIMITERS:
                end += 1
            yield _Token("word", text[pos:end], line)
            pos = end


_TAG_START_RE = re.compile(r'\[[ \t]*([A-Za-z0-9_]+)[ \t]*"')
_TAG_END_RE = re.compile(r"[ \t]*\]")


def _read_tag(text: str, pos: int, line: int) -> tuple[int, _Token]:
    """Lit ``[Nom "valeur"]`` à partir de ``pos`` (sur le ``[``), sur une seule ligne.

    ``\\"`` et ``\\\\`` sont déséchappés. Tolérance : un ``"`` non échappé qui n'est pas
    suivi de ``]`` alors qu'un autre ``"`` suit sur la ligne est pris littéralement
    (certains logiciels, dont python-chess 1.11, n'échappent pas les guillemets).
    """
    match = _TAG_START_RE.match(text, pos)
    if match is None:
        raise PgnError(f'Ligne {line} : en-tête mal formé (attendu [Nom "valeur"])')
    name = match.group(1)
    index = match.end()
    line_end = text.find("\n", index)
    if line_end < 0:
        line_end = len(text)
    chars: list[str] = []
    while True:
        if index >= line_end:
            raise PgnError(f"Ligne {line} : valeur de l'en-tête {name} non terminée")
        ch = text[index]
        if ch == "\\" and index + 1 < line_end and text[index + 1] in '\\"':
            chars.append(text[index + 1])
            index += 2
            continue
        if ch == '"':
            close = _TAG_END_RE.match(text, index + 1)
            if close is not None:
                return close.end(), _Token("tag", name, line, "".join(chars))
            if text.find('"', index + 1, line_end) < 0:
                raise PgnError(f"Ligne {line} : « ] » manquant après l'en-tête {name}")
        chars.append(ch)
        index += 1


# --------------------------------------------------------------------------
# Import : construction des parties
# --------------------------------------------------------------------------
class _GameBuilder:
    """Partie en cours de lecture : en-têtes, puis coups validés un à un."""

    def __init__(self, number: int, max_moves: int) -> None:
        self.number = number
        self.max_moves = max_moves
        self.raw_headers: dict[str, str] = {}
        self.moves: list[str] = []
        self.result: str | None = None
        self.state: GameState | None = None
        self.start_fen: str | None = None
        self.depth = 0  # profondeur de variante courante

    def error(self, message: str) -> PgnError:
        white = self.raw_headers.get("White", "?")
        black = self.raw_headers.get("Black", "?")
        return PgnError(f"Partie n° {self.number} ({white} – {black}) : {message}")

    @property
    def started(self) -> bool:
        return self.state is not None or self.result is not None

    def add_tag(self, name: str, value: str) -> None:
        self.raw_headers[name] = value

    def _start(self) -> GameState:
        if self.state is not None:
            return self.state
        variant = self.raw_headers.get("Variant", "Standard").strip().lower()
        if variant not in ("standard", "chess", ""):
            raise self.error(f"variante non prise en charge : {self.raw_headers['Variant']!r}")
        fen = self.raw_headers.get("FEN")
        setup = self.raw_headers.get("SetUp")
        if setup == "1" and fen is None:
            raise self.error('[SetUp "1"] sans en-tête [FEN]')
        if fen is not None:
            try:
                self.state = load_fen(fen.strip())
            except FenError as exc:
                raise self.error(f"en-tête [FEN] invalide : {exc}") from exc
            normalized = to_fen(self.state)
            self.start_fen = None if normalized == STANDARD_START_FEN else normalized
        else:
            self.state = GameState()
        # Parties réelles : nulles par répétition / 50 coups à réclamer (FIDE stricte).
        self.state.automatic_draws = False
        return self.state

    def add_move(self, word: str, line: int) -> None:
        state = self._start()
        label = _move_label(state)
        if len(self.moves) >= self.max_moves:
            raise self.error(
                f"plus de {self.max_moves} demi-coups : coup {label} {word!r} (ligne {line}) refusé"
            )
        result = state.result()
        if result.is_over:
            raise self.error(
                f"coup {label} {word!r} (ligne {line}) joué après la fin de la partie "
                f"({result.description})"
            )
        try:
            move = parse_san(state, word)
            san = to_san(state, move)
        except NotationError as exc:
            raise self.error(f"coup {label} {word!r} (ligne {line}) refusé : {exc}") from exc
        state.make_move(move, validate=False)
        self.moves.append(san)

    def build(self) -> PgnGame:
        self._start()
        result = self.result
        if result is None:
            header_result = self.raw_headers.get("Result", "*").strip()
            result = header_result if header_result in RESULTS else "*"
        headers: dict[str, str] = {}
        for name in SEVEN_TAG_ROSTER:
            headers[name] = self.raw_headers.get(name, _ROSTER_DEFAULTS[name])
        headers["Result"] = result
        for name, value in self.raw_headers.items():
            headers.setdefault(name, value)
        return PgnGame(headers=headers, start_fen=self.start_fen, moves=self.moves, result=result)


def parse_pgn(
    text: str,
    max_games: int = DEFAULT_MAX_GAMES,
    max_moves: int = DEFAULT_MAX_MOVES,
) -> list[PgnGame]:
    """Lit toutes les parties du texte PGN ``text`` (ligne principale de chacune).

    Lève :class:`PgnError` pour un texte mal formé, un coup illégal ou ambigu, une FEN
    invalide, plus de ``max_games`` parties ou plus de ``max_moves`` demi-coups dans une
    partie. Une partie sans jeton de résultat se termine au premier en-tête suivant ou à
    la fin du texte ; son résultat est alors celui de l'en-tête Result (« * » à défaut).
    """
    games: list[PgnGame] = []
    builder = _GameBuilder(1, max_moves)
    has_content = False

    def finish() -> None:
        nonlocal builder, has_content
        if builder.depth:
            raise builder.error("variante « ( » jamais refermée")
        games.append(builder.build())
        builder = _GameBuilder(len(games) + 1, max_moves)
        has_content = False

    for token in _tokenize(text):
        if token.kind == "tag":
            if builder.depth:
                raise builder.error(
                    f"en-tête [{token.value}] dans une variante (ligne {token.line})"
                )
            if builder.started:
                finish()  # partie précédente sans jeton de résultat
            if len(games) >= max_games:
                raise PgnError(f"Plus de {max_games} parties dans le fichier")
            builder.add_tag(token.value, token.tag_value)
            has_content = True
            continue
        if len(games) >= max_games:
            raise PgnError(f"Plus de {max_games} parties dans le fichier")
        has_content = True
        if token.kind == "open":
            builder.depth += 1
            continue
        if token.kind == "close":
            if builder.depth == 0:
                raise builder.error(f"« ) » sans « ( » correspondant (ligne {token.line})")
            builder.depth -= 1
            continue
        word = token.value
        if builder.depth:
            continue  # coups, numéros et résultats des variantes : ignorés
        if word in RESULTS:
            builder.result = word
            finish()
            continue
        rest = _MOVE_NUMBER_RE.sub("", word) if word[0].isdigit() and "." in word else word
        if not rest or rest.isdigit() or set(rest) == {"."} or _ANNOTATION_ONLY_RE.match(rest):
            continue  # numéro de coup (« 12. », « 12... », « 12 »), suffixe isolé
        if rest == "--" or rest.upper() in ("Z0", "0000", "NULL"):
            raise builder.error(f"coup nul {rest!r} non pris en charge (ligne {token.line})")
        builder.add_move(rest, token.line)
    if has_content:
        finish()
    return games


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")  # encodage du standard PGN


def read_pgn_file(
    path: str | os.PathLike[str],
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_games: int = DEFAULT_MAX_GAMES,
    max_moves: int = DEFAULT_MAX_MOVES,
) -> list[PgnGame]:
    """Lit un fichier PGN (UTF-8, ou Latin-1 à défaut) d'au plus ``max_bytes`` octets.

    Lève :class:`PgnError` si le fichier est trop gros ou invalide (cf.
    :func:`parse_pgn`), ``OSError`` s'il est illisible.
    """
    with open(path, "rb") as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise PgnError(f"Fichier PGN trop volumineux (plus de {max_bytes} octets) : {path}")
    return parse_pgn(_decode(data), max_games=max_games, max_moves=max_moves)


def load_pgn_game(text_or_path: str | os.PathLike[str], index: int = 0) -> GameState:
    """Position finale de la partie n° ``index`` (à partir de 0) d'un texte ou fichier PGN.

    Un ``os.PathLike``, ou une chaîne d'une ligne qui désigne un fichier existant, est lu
    comme un fichier (:func:`read_pgn_file`) ; toute autre chaîne est un texte PGN.
    """
    if isinstance(text_or_path, os.PathLike) or (
        "\n" not in text_or_path and "[" not in text_or_path and os.path.isfile(text_or_path)
    ):
        games = read_pgn_file(text_or_path)
    else:
        games = parse_pgn(text_or_path)
    if not 0 <= index < len(games):
        raise PgnError(f"Partie n° {index + 1} introuvable : le PGN en contient {len(games)}")
    return games[index].replay()


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_GAMES",
    "DEFAULT_MAX_MOVES",
    "PgnError",
    "PgnGame",
    "SEVEN_TAG_ROSTER",
    "STANDARD_START_FEN",
    "TERMINATION_TAGS",
    "export_pgn",
    "load_pgn_game",
    "movetext_tokens",
    "parse_pgn",
    "read_pgn_file",
    "start_position",
    "wrap_tokens",
]
