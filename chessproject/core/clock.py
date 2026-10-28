"""
Module chessproject.core.clock
------------------------------
Cadence de jeu (J4.1) : contrôle de temps, pendule Fischer et perte au temps. Allocation
du temps de réflexion de l'IA (J4.2).

Module pur, sans pygame : le temps est fourni par une fonction injectable ``now`` (en
**secondes**, comme :func:`time.monotonic`), ce qui rend la pendule testable sans attendre.
Toutes les durées exposées sont en **millisecondes entières**.

Conventions :

- ``TimeControl.from_minutes(5, 3)`` : notation usuelle « minutes + secondes
  d'incrément » (5 min, 3 s par coup) ;
- ``TimeControl.from_pgn("300+2")`` / ``TimeControl.pgn_tag`` : en-tête PGN
  ``[TimeControl]``, **tout en secondes** (300 s, 2 s par coup), « - » pour une partie
  sans limite. Il n'y a volontairement pas d'analyseur « 5+3 » générique : la même
  chaîne serait ambiguë entre ces deux notations ;
- ``TimeControl.label`` : affichage « 5+3 » (minutes + secondes) ou « Sans limite ».
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from chessproject.core.engine import Color, GameResult, GameState, Termination

# Fonction d'horloge : un instant en secondes (référence arbitraire, croissante).
Now = Callable[[], float]

CLOCK_FORMAT_VERSION = 1


def _opponent(color: Color) -> Color:
    return Color.BLACK if color is Color.WHITE else Color.WHITE


def _format_seconds(ms: int) -> str:
    """Millisecondes en secondes pour le PGN : ``300``, ou ``0.5`` si non entier."""
    if ms % 1000 == 0:
        return str(ms // 1000)
    return f"{ms / 1000:.3f}".rstrip("0").rstrip(".")


def _parse_seconds(text: str, source: str) -> int:
    try:
        seconds = float(text)
    except ValueError:
        raise ValueError(f"TimeControl PGN invalide : {source!r}") from None
    if not seconds >= 0 or seconds == float("inf"):  # rejette aussi NaN
        raise ValueError(f"TimeControl PGN invalide : {source!r}")
    return round(seconds * 1000)


# --------------------------------------------------------------------------
# Contrôle de temps
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class TimeControl:
    """Cadence : temps initial et incrément Fischer, en millisecondes.

    ``initial_ms <= 0`` signifie « sans limite ». ``name`` sert à l'affichage et n'entre
    pas dans l'égalité : ``from_pgn("180+2") == BLITZ_3_2``.
    """

    initial_ms: int
    increment_ms: int = 0
    name: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if self.increment_ms < 0:
            raise ValueError(f"Incrément négatif : {self.increment_ms} ms")

    @property
    def is_unlimited(self) -> bool:
        return self.initial_ms <= 0

    @staticmethod
    def unlimited(name: str = "Sans limite") -> TimeControl:
        return TimeControl(0, 0, name)

    @staticmethod
    def from_minutes(
        minutes: float, increment_seconds: float = 0, name: str | None = None
    ) -> TimeControl:
        """Cadence « minutes + secondes d'incrément » : ``from_minutes(5, 3)`` = 5+3.
        ``minutes == 0`` donne une cadence sans limite (l'incrément est alors ignoré)."""
        if minutes < 0 or increment_seconds < 0:
            raise ValueError(f"Cadence invalide : {minutes}+{increment_seconds}")
        control = TimeControl(round(minutes * 60_000), round(increment_seconds * 1000))
        if control.is_unlimited:
            return TimeControl.unlimited(name or "Sans limite")
        return TimeControl(control.initial_ms, control.increment_ms, name or control.label)

    @staticmethod
    def from_pgn(text: str, name: str | None = None) -> TimeControl:
        """Analyse un en-tête PGN ``TimeControl`` : ``"300+2"``, ``"600"`` ou ``"-"``.

        Les valeurs sont en secondes (décimales acceptées). Les formes PGN à périodes
        (``40/9000``), sablier (``*60``) et inconnue (``?``) ne sont pas gérées :
        ``ValueError``.
        """
        stripped = text.strip()
        if stripped == "-":
            return TimeControl.unlimited(name or "Sans limite")
        base, sep, inc = stripped.partition("+")
        initial_ms = _parse_seconds(base, text)
        increment_ms = _parse_seconds(inc, text) if sep else 0
        if initial_ms <= 0:
            raise ValueError(f"TimeControl PGN invalide (temps nul) : {text!r}")
        control = TimeControl(initial_ms, increment_ms)
        return TimeControl(initial_ms, increment_ms, name or control.label)

    @property
    def pgn_tag(self) -> str:
        """Valeur de l'en-tête PGN ``[TimeControl]`` : ``"300+2"`` (secondes) ou ``"-"``."""
        if self.is_unlimited:
            return "-"
        base = _format_seconds(self.initial_ms)
        if self.increment_ms == 0:
            return base
        return f"{base}+{_format_seconds(self.increment_ms)}"

    @property
    def label(self) -> str:
        """Notation courte pour l'affichage : ``"5+3"`` (minutes + secondes)."""
        if self.is_unlimited:
            return "Sans limite"
        minutes = self.initial_ms / 60_000
        base = str(int(minutes)) if minutes.is_integer() else f"{minutes:g}"
        return f"{base}+{_format_seconds(self.increment_ms)}"


BULLET_1_0 = TimeControl.from_minutes(1, 0, "Bullet 1+0")
BLITZ_3_2 = TimeControl.from_minutes(3, 2, "Blitz 3+2")
BLITZ_5_0 = TimeControl.from_minutes(5, 0, "Blitz 5+0")
RAPID_10_5 = TimeControl.from_minutes(10, 5, "Rapide 10+5")
RAPID_15_10 = TimeControl.from_minutes(15, 10, "Rapide 15+10")
UNLIMITED = TimeControl.unlimited()

PRESETS: tuple[TimeControl, ...] = (
    BULLET_1_0,
    BLITZ_3_2,
    BLITZ_5_0,
    RAPID_10_5,
    RAPID_15_10,
    UNLIMITED,
)
DEFAULT: TimeControl = UNLIMITED


# --------------------------------------------------------------------------
# Pendule
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ClockSnapshot:
    """État de la pendule entre deux coups (pile de :meth:`ChessClock.undo_press`)."""

    white_ms: int
    black_ms: int
    turn: Color

    def to_dict(self) -> dict[str, Any]:
        return {"white_ms": self.white_ms, "black_ms": self.black_ms, "turn": self.turn.value}

    @staticmethod
    def from_dict(data: dict[str, Any]) -> ClockSnapshot:
        return ClockSnapshot(
            _int_field(data, "white_ms"), _int_field(data, "black_ms"), _color(data["turn"])
        )


def _int_field(data: dict[str, Any], key: str) -> int:
    value = data[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"Pendule : champ {key!r} entier attendu, {value!r} trouvé")
    return value


def _color(value: Any) -> Color:
    try:
        return Color(value)
    except ValueError:
        raise ValueError(f"Pendule : couleur invalide {value!r}") from None


class ChessClock:
    """Pendule d'échecs à incrément Fischer, pilotée par le contrôleur.

    Cycle de vie : ``start()`` lance la pendule du camp au trait ; à chaque coup joué,
    ``press()`` décompte le temps de ce camp, lui crédite l'incrément **après** le coup,
    puis donne la main à l'adversaire. ``pause()`` / ``resume()`` (ou ``with
    clock.paused():``) suspendent le décompte pendant les menus et animations (B44).
    ``flagged()``, appelé à chaque image, détecte la chute du drapeau : la pendule
    s'arrête alors, le temps du camp restant à 0.

    Annulation : chaque ``press()`` empile l'état d'avant le coup ; ``undo_press()``
    restaure les deux temps et le trait (et efface une chute du drapeau). Le temps écoulé
    depuis le dernier ``press()`` est abandonné. L'état pause/marche n'est pas modifié.

    Mode sans limite (``control.is_unlimited``) : rien n'est décompté, ``remaining_ms``
    renvoie None, ``flagged()`` renvoie toujours None et ``press()`` renvoie 0 ; le trait
    et la pile d'annulation restent tenus.
    """

    def __init__(self, control: TimeControl, now: Now = time.monotonic) -> None:
        self._control = control
        self._now = now
        initial = max(0, control.initial_ms)
        self._remaining: dict[Color, int] = {Color.WHITE: initial, Color.BLACK: initial}
        self._turn = Color.WHITE
        self._running = False
        self._paused = False
        self._flag: Color | None = None
        # Instant (secondes) depuis lequel le temps du camp au trait n'est pas décompté.
        self._since = now()
        self._history: list[ClockSnapshot] = []

    # ------------------------------------------------------------------ état
    @property
    def control(self) -> TimeControl:
        return self._control

    @property
    def is_unlimited(self) -> bool:
        return self._control.is_unlimited

    @property
    def turn(self) -> Color:
        """Camp dont la pendule tourne (ou tournera au prochain ``resume``)."""
        return self._turn

    @property
    def running(self) -> bool:
        """Vrai entre ``start()`` et la fin (drapeau ou ``stop()``), pause comprise."""
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def press_count(self) -> int:
        """Nombre de coups annulables par :meth:`undo_press`."""
        return len(self._history)

    def _ticking(self) -> bool:
        return self._running and not self._paused and not self.is_unlimited

    def _elapsed_ms(self) -> int:
        """Temps écoulé non encore décompté pour le camp au trait."""
        if not self._ticking():
            return 0
        return max(0, round((self._now() - self._since) * 1000))

    def _commit(self) -> int:
        """Reporte le temps écoulé sur le camp au trait ; renvoie ce temps (ms)."""
        elapsed = self._elapsed_ms()
        self._remaining[self._turn] -= elapsed
        self._since = self._now()
        return elapsed

    def remaining_ms(self, color: Color) -> int | None:
        """Temps restant de ``color`` à cet instant (calculé sans muter l'état), jamais
        négatif ; None en mode sans limite."""
        if self.is_unlimited:
            return None
        value = self._remaining[color]
        if color is self._turn:
            value -= self._elapsed_ms()
        return max(0, value)

    # -------------------------------------------------------------- commandes
    def start(self, white_to_move: bool = True) -> None:
        """Lance la pendule du camp au trait (``white_to_move``). L'état de pause est
        conservé : une pendule mise en pause avant ``start`` ne tourne qu'au ``resume``."""
        if self._running:
            raise RuntimeError("La pendule est déjà lancée")
        self._turn = Color.WHITE if white_to_move else Color.BLACK
        self._running = True
        self._flag = None
        self._since = self._now()

    def stop(self) -> None:
        """Arrête définitivement la pendule (fin de partie hors temps)."""
        self._commit()
        self._running = False

    def press(self) -> int:
        """Le camp au trait vient de jouer : décompte son temps, lui ajoute l'incrément
        (Fischer, après le coup) et passe la main. Renvoie le temps consommé (ms).

        Si le temps du camp était épuisé, le drapeau tombe : pas d'incrément ni de
        changement de trait, la pendule s'arrête (``flagged()`` renvoie ce camp) ; le
        coup reste empilé, pour que la pile suive celle des coups de la partie.
        Lève RuntimeError si la pendule n'est pas lancée.
        """
        if not self._running:
            raise RuntimeError("Pendule arrêtée : start() d'abord")
        snapshot = ClockSnapshot(
            self._remaining[Color.WHITE], self._remaining[Color.BLACK], self._turn
        )
        consumed = self._commit()
        self._history.append(snapshot)
        if not self.is_unlimited and self._remaining[self._turn] <= 0:
            self._fall()
            return consumed
        if not self.is_unlimited:
            self._remaining[self._turn] += self._control.increment_ms
        self._turn = _opponent(self._turn)
        return consumed

    def undo_press(self) -> bool:
        """Annule le dernier ``press()`` : temps des deux camps et trait d'avant ce coup.
        Relance une pendule arrêtée par le drapeau. Renvoie False si rien à annuler."""
        if not self._history:
            return False
        snapshot = self._history.pop()
        self._remaining[Color.WHITE] = snapshot.white_ms
        self._remaining[Color.BLACK] = snapshot.black_ms
        self._turn = snapshot.turn
        if self._flag is not None:
            self._flag = None
            self._running = True
        self._since = self._now()
        return True

    def pause(self) -> None:
        """Suspend le décompte (idempotent)."""
        if self._paused:
            return
        self._commit()
        self._paused = True

    def resume(self) -> None:
        """Reprend le décompte (idempotent)."""
        if not self._paused:
            return
        self._paused = False
        self._since = self._now()

    @contextmanager
    def paused(self) -> Iterator[None]:
        """``with clock.paused(): ...`` : pause le temps du bloc, puis rétablit l'état
        d'avant (une pendule déjà en pause le reste)."""
        was_paused = self._paused
        self.pause()
        try:
            yield
        finally:
            if not was_paused:
                self.resume()

    def flagged(self) -> Color | None:
        """Camp dont le drapeau est tombé, sinon None. À appeler à chaque image : à la
        chute, la pendule s'arrête et le temps de ce camp reste à 0."""
        if self._flag is None and self._ticking():
            remaining = self.remaining_ms(self._turn)
            if remaining is not None and remaining <= 0:
                self._commit()
                self._fall()
        return self._flag

    def _fall(self) -> None:
        self._remaining[self._turn] = 0
        self._flag = self._turn
        self._running = False

    # ------------------------------------------------------- sérialisation
    def to_dict(self) -> dict[str, Any]:
        """État sérialisable en JSON (sauvegarde v2). Les temps sont figés à l'instant de
        l'appel, sans muter la pendule."""
        white = self._remaining[Color.WHITE]
        black = self._remaining[Color.BLACK]
        if self._turn is Color.WHITE:
            white -= self._elapsed_ms()
        else:
            black -= self._elapsed_ms()
        return {
            "version": CLOCK_FORMAT_VERSION,
            "initial_ms": self._control.initial_ms,
            "increment_ms": self._control.increment_ms,
            "name": self._control.name,
            "white_ms": max(0, white),
            "black_ms": max(0, black),
            "turn": self._turn.value,
            "running": self._running,
            "paused": self._paused,
            "flagged": self._flag.value if self._flag else None,
            "history": [s.to_dict() for s in self._history],
        }

    @staticmethod
    def from_dict(data: dict[str, Any], now: Now = time.monotonic) -> ChessClock:
        """Reconstruit une pendule depuis :meth:`to_dict`. Une pendule qui tournait
        reprend son décompte à partir de l'instant du chargement. ValueError si les
        données sont invalides."""
        try:
            if data.get("version") != CLOCK_FORMAT_VERSION:
                raise ValueError(f"Pendule : version inconnue {data.get('version')!r}")
            name = data.get("name", "")
            if not isinstance(name, str):
                raise ValueError("Pendule : nom de cadence invalide")
            control = TimeControl(
                _int_field(data, "initial_ms"), _int_field(data, "increment_ms"), name
            )
            clock = ChessClock(control, now)
            clock._remaining[Color.WHITE] = _int_field(data, "white_ms")
            clock._remaining[Color.BLACK] = _int_field(data, "black_ms")
            clock._turn = _color(data["turn"])
            clock._running = bool(data["running"])
            clock._paused = bool(data["paused"])
            flag = data.get("flagged")
            clock._flag = None if flag is None else _color(flag)
            clock._history = [ClockSnapshot.from_dict(s) for s in data.get("history", [])]
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError(f"Pendule : données invalides ({exc!r})") from None
        return clock


# --------------------------------------------------------------------------
# Fin de partie au temps et affichage
# --------------------------------------------------------------------------
def timeout_result(game_state: GameState, flagged: Color) -> GameResult:
    """Résultat d'une chute du drapeau de ``flagged`` : défaite au temps, sauf si
    l'adversaire n'a pas de quoi mater (nulle, FIDE 6.9, cf.
    :meth:`GameState.has_mating_material`)."""
    opponent = _opponent(flagged)
    if not game_state.has_mating_material(opponent):
        return GameResult(Termination.TIMEOUT_VS_INSUFFICIENT_MATERIAL)
    return GameResult(Termination.TIME_FORFEIT, opponent)


def format_ms(ms: int | None) -> str:
    """Temps de pendule pour l'affichage (arrondi par défaut, jamais négatif) :
    ``"4:59"``, ``"0:09.7"`` sous 10 s (dixièmes), ``"1:02:03"`` dès une heure,
    ``"∞"`` pour None (sans limite)."""
    if ms is None:
        return "∞"
    ms = max(0, ms)
    if ms < 10_000:
        return f"0:{ms // 1000:02d}.{(ms % 1000) // 100}"
    total = ms // 1000
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


# --------------------------------------------------------------------------
# J4.2 : temps de réflexion de l'IA
# --------------------------------------------------------------------------
THINK_MIN_MS = 10
THINK_SAFETY_MS = 50
THINK_INCREMENT_SHARE = 0.75
THINK_MAX_FRACTION = 1 / 3


def allocate_think_time_ms(
    remaining_ms: int,
    increment_ms: int,
    moves_played: int,
    max_ms: int | None = None,
    moves_to_go: int | None = None,
) -> int:
    """Budget de réflexion de l'IA pour le prochain coup, en millisecondes (fonction pure).

    Seul calcul du temps de réflexion, pour la pendule du jeu comme pour le moteur UCI
    (J10.3). ``moves_played`` est le nombre de demi-coups déjà joués dans la partie (par
    exemple ``len(game_state.move_log)``). Formule :

    - ``remaining / max(20, 40 - moves_played // 2) + 0,75 × incrément`` : on prévoit
      40 coups restants en début de partie, puis jamais moins de 20 ;
    - avec ``moves_to_go`` (coups restants avant le prochain contrôle, ``movestogo`` en
      UCI), ``remaining / moves_to_go`` à la place ; le temps restant est alors rendu au
      contrôle, et le plafond du tiers ne s'applique pas ;
    - plafonné à 1/3 du temps restant et à ``remaining - 50 ms`` (marge de sécurité pour
      le coût du coup et de l'affichage) ;
    - au moins 10 ms ;
    - plafonné enfin par ``max_ms`` (temps du niveau de difficulté) s'il est donné.

    Le résultat est croissant (au sens large) en ``remaining_ms``, ``increment_ms`` et
    ``moves_played``.
    """
    remaining_ms = max(0, remaining_ms)
    increment_ms = max(0, increment_ms)
    if moves_to_go is not None and moves_to_go > 0:
        budget = remaining_ms / moves_to_go + THINK_INCREMENT_SHARE * increment_ms
    else:
        budget = remaining_ms / max(20, 40 - max(0, moves_played) // 2)
        budget = min(
            budget + THINK_INCREMENT_SHARE * increment_ms, remaining_ms * THINK_MAX_FRACTION
        )
    budget = min(budget, remaining_ms - THINK_SAFETY_MS)
    result = max(THINK_MIN_MS, int(budget))
    if max_ms is not None:
        result = min(result, max(THINK_MIN_MS, max_ms))
    return result
