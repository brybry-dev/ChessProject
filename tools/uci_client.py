"""
Client UCI pour les outils de mesure (``tools/match.py``, ``tools/tactics.py``)
----------------------------------------------------------------------------
Lance un moteur UCI (une commande shell) dans un sous-processus et dialogue avec lui
par ses tubes, avec des délais d'attente : une lecture se fait dans un fil dédié qui
alimente une file, ce qui permet d'attendre une réponse au plus ``timeout`` secondes.
"""

from __future__ import annotations

import contextlib
import os
import queue
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class EngineError(RuntimeError):
    """Le moteur ne répond pas, répond hors délai ou s'est arrêté."""


def engine_argv(command: str) -> list[str]:
    """Découpe la commande ; ``python``/``python3`` en tête devient l'interpréteur courant.

    Cela évite de lancer un autre Python que celui des outils (environnement virtuel).
    """
    argv = shlex.split(command)
    if argv and argv[0] in ("python", "python3"):
        argv[0] = sys.executable
    return argv


def engine_env_and_cwd(pythonpath: str | None) -> tuple[dict[str, str], str | None]:
    """Environnement et répertoire de travail d'un moteur.

    Avec ``pythonpath`` (ex. une révision extraite par ``git worktree add``), la variable
    PYTHONPATH du moteur est remplacée par cette valeur et le moteur est lancé depuis son
    premier répertoire : ``python -m`` place le répertoire courant en tête de ``sys.path``,
    devant PYTHONPATH, il faut donc que ce soit lui aussi la révision voulue.
    """
    env = dict(os.environ)
    if pythonpath is None:
        return env, None
    env["PYTHONPATH"] = pythonpath
    first = pythonpath.split(os.pathsep)[0]
    return env, first or None


class UciProcess:
    """Un moteur UCI en sous-processus."""

    def __init__(self, command: str, pythonpath: str | None = None, name: str = "") -> None:
        self.command = command
        self.name = name or command
        env, cwd = engine_env_and_cwd(pythonpath)
        self.proc = subprocess.Popen(
            engine_argv(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=env,
            cwd=cwd,
        )
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self._lines.put(line.rstrip("\r\n"))
        self._lines.put(None)  # Fin de flux : le moteur s'est arrêté

    def send(self, line: str) -> None:
        if self.proc.stdin is None or self.proc.poll() is not None:
            raise EngineError(f"{self.name} : moteur arrêté")
        try:
            self.proc.stdin.write(line + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise EngineError(f"{self.name} : écriture impossible ({exc})") from exc

    def read_until(self, prefix: str, timeout: float) -> str:
        """Lit jusqu'à une ligne commençant par ``prefix`` ; la renvoie. ``EngineError`` sinon."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EngineError(f"{self.name} : pas de « {prefix} » en {timeout:.1f} s")
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty:
                continue
            if line is None:
                raise EngineError(f"{self.name} : arrêt du moteur en attendant « {prefix} »")
            if line.startswith(prefix):
                return line

    def handshake(self, timeout: float = 30.0) -> None:
        self.send("uci")
        self.read_until("uciok", timeout)
        self.is_ready(timeout)

    def is_ready(self, timeout: float = 30.0) -> None:
        self.send("isready")
        self.read_until("readyok", timeout)

    def bestmove(self, position: str, go: str, timeout: float) -> tuple[str, float]:
        """Envoie ``position`` puis ``go`` ; renvoie (coup UCI, durée en secondes)."""
        self.send(position)
        start = time.monotonic()
        self.send(go)
        line = self.read_until("bestmove", timeout)
        elapsed = time.monotonic() - start
        parts = line.split()
        return (parts[1] if len(parts) > 1 else ""), elapsed

    def close(self) -> None:
        with contextlib.suppress(EngineError):
            self.send("quit")
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        for stream in (self.proc.stdin, self.proc.stdout):
            if stream is not None:
                with contextlib.suppress(OSError):
                    stream.close()

    def __enter__(self) -> UciProcess:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def go_command(depth: int | None, movetime_ms: int | None) -> str:
    """Commande ``go`` pour une limite de profondeur ou de temps (profondeur prioritaire)."""
    if depth is not None:
        return f"go depth {depth}"
    if movetime_ms is not None:
        return f"go movetime {movetime_ms}"
    return "go"


def move_timeout(depth: int | None, movetime_ms: int | None, override: float | None) -> float:
    """Délai de réponse accordé par coup (secondes) avant de déclarer le moteur fautif."""
    if override is not None:
        return override
    if depth is None and movetime_ms is not None:
        return 5.0 + 3.0 * movetime_ms / 1000
    return 120.0
