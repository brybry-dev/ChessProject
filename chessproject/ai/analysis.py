"""
Module chessproject.ai.analysis
-------------------------------
Mode analyse (J9.1) : la variante principale de la position, calculée dans un processus
séparé et envoyée à chaque profondeur achevée, pour être affichée pendant la réflexion.

Le processus (:func:`run`) dépose dans une file une :class:`AnalysisLine` par profondeur,
puis ``None`` quand il a fini. :class:`Analyzer` le pilote depuis l'interface : une
analyse à la fois, relancée quand la position affichée change.
"""

import contextlib
import queue
from dataclasses import dataclass
from multiprocessing import Process, Queue
from typing import Any

from chessproject.ai import search
from chessproject.core import engine, notation
from chessproject.core.fen import fullmove_number

# Une analyse s'arrête d'elle-même : pas de processus qui tourne sans fin en arrière-plan.
ANALYSIS_MOVETIME_MS = 15_000
ANALYSIS_LIMITS = search.SearchLimits(depth=search.MAX_PLY, movetime_ms=ANALYSIS_MOVETIME_MS)


@dataclass(frozen=True, slots=True)
class AnalysisLine:
    depth: int
    score: int  # du point de vue des Blancs, en centipions (ou score de mat)
    pv: tuple[str, ...]  # variante principale en SAN, depuis la position analysée
    fullmove: int  # numéro du premier coup de la variante
    white_to_move: bool


def format_pv(line: AnalysisLine) -> str:
    """Variante numérotée : ``"12... Nf6 13. Nc3"``."""
    return " ".join(notation.format_move_lines(list(line.pv), line.fullmove, line.white_to_move))


def run(
    game_state: engine.GameState,
    out_queue: Any,
    limits: search.SearchLimits = ANALYSIS_LIMITS,
) -> None:
    """Point d'entrée du processus d'analyse : une ligne par profondeur, puis ``None``."""
    sign = 1 if game_state.white_to_move else -1
    fullmove = fullmove_number(game_state)

    def report(result: search.SearchResult) -> None:
        out_queue.put(
            AnalysisLine(
                depth=result.depth,
                score=sign * result.score,
                pv=tuple(notation.move_list_to_san(game_state, result.pv)),
                fullmove=fullmove,
                white_to_move=game_state.white_to_move,
            )
        )

    try:
        search.think(game_state, limits, on_iteration=report)
    finally:
        out_queue.put(None)


class Analyzer:
    """Une analyse en arrière-plan, identifiée par une clé (la position affichée)."""

    def __init__(
        self,
        process: Any = Process,
        make_queue: Any = Queue,
        limits: search.SearchLimits = ANALYSIS_LIMITS,
    ) -> None:
        self._process_factory = process
        self._make_queue = make_queue
        self.limits = limits
        self.key: object = None
        self.line: AnalysisLine | None = None
        self._process: Any = None
        self._queue: Any = None
        self._done = True

    @property
    def running(self) -> bool:
        return self._process is not None and not self._done and self._process.is_alive()

    def start(self, game_state: engine.GameState, key: object) -> None:
        """Analyse ``game_state`` ; sans effet si cette clé est déjà analysée."""
        if key == self.key:
            return
        self.stop()
        self.key = key
        self._queue = self._make_queue()
        self._done = False
        # daemon : le processus est tué avec l'application au lieu d'être attendu.
        self._process = self._process_factory(
            target=run, args=(game_state, self._queue, self.limits), daemon=True
        )
        self._process.start()

    def poll(self) -> AnalysisLine | None:
        """Dernière ligne reçue de l'analyse en cours (None tant qu'il n'y en a pas)."""
        if self._queue is None:
            return self.line
        while True:
            try:
                item = self._queue.get_nowait()
            except (queue.Empty, OSError, ValueError):
                break
            if item is None:
                self._done = True
                break
            self.line = item
        return self.line

    def stop(self) -> None:
        if self._process is not None and not self._done:
            with contextlib.suppress(Exception):
                self._process.terminate()
        self._process = self._queue = None
        self.key = None
        self.line = None
        self._done = True
