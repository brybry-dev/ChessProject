"""
Protocole UCI minimal (J3.0, préfigure J6.5)
--------------------------------------------
Permet de faire jouer le moteur par un programme tiers (``tools/match.py``,
``tools/tactics.py``, ``cutechess-cli``…). Lancement : ``python -m chessproject.uci`` ou
script console ``chessproject-uci``.

Commandes reconnues :

- ``uci`` → ``id name`` / ``id author`` / ``uciok`` ;
- ``isready`` → ``readyok`` ;
- ``ucinewgame`` → retour à la position initiale ;
- ``position startpos|fen <FEN> [moves m1 m2 ...]`` (FEN lue par ``core.fen.load_fen``,
  coups par ``core.notation.parse_uci``) ;
- ``go`` avec ``depth N``, ``movetime MS``, ``wtime/btime/winc/binc/movestogo``,
  ``infinite`` → ``bestmove <uci>`` (``bestmove 0000`` s'il n'existe aucun coup légal) ;
- ``stop``, ``quit``.

Toute entrée invalide est ignorée et signalée par une ligne ``info string ...`` : le
programme ne s'arrête jamais sur une erreur de l'interface. Chaque écriture est suivie
d'un ``flush`` (l'interface lit la sortie par un tube).

**Recherche synchrone** : il n'y a pas de fil d'exécution séparé. Une commande ``go``
calcule jusqu'au bout avant que la ligne suivante de stdin soit lue ; un ``stop`` envoyé
pendant la recherche n'est donc traité qu'après elle (il n'a alors plus d'effet). En mode
``go infinite``, la recherche se fait à la profondeur par défaut de l'IA et le
``bestmove`` est retenu jusqu'au ``stop`` (ou au ``go`` / ``quit`` suivant), comme le veut
le protocole. Une recherche réellement interruptible viendra avec J3.2.
"""

from __future__ import annotations

import contextlib
import sys
from typing import TextIO

from chessproject.ai import levels, search
from chessproject.ai.search import SearchLimits, SearchResult
from chessproject.core.engine import GameState, Move
from chessproject.core.fen import FenError, load_fen
from chessproject.core.notation import NotationError, parse_uci, to_uci

ENGINE_NAME = "ChessProject"
ENGINE_AUTHOR = "BryanBlinDorard"
# Valeur de l'option Level qui désactive les niveaux (limites de go appliquées telles quelles).
FULL_STRENGTH = "Max"

# Gestion du temps (cf. allocate_time_ms)
DEFAULT_MOVES_TO_GO: int = 30  # Nombre de coups restants supposé sans ``movestogo``
INCREMENT_SHARE: float = 0.8  # Part de l'incrément dépensée dès ce coup
MOVE_OVERHEAD_MS: int = 50  # Marge de sécurité (latence du tube, démarrage de la recherche)
MIN_TIME_MS: int = 1

_INT_GO_PARAMS = ("depth", "movetime", "wtime", "btime", "winc", "binc", "movestogo", "nodes")


def allocate_time_ms(remaining_ms: int, increment_ms: int = 0, movestogo: int | None = None) -> int:
    """Temps à consacrer au prochain coup, en millisecondes (fonction pure).

    ``remaining / (movestogo ou 30) + 0,8 × incrément``, borné à ``[1, remaining - 50]`` :
    on ne dépense jamais tout le temps restant, et toujours au moins 1 ms.
    """
    remaining_ms = max(0, remaining_ms)
    increment_ms = max(0, increment_ms)
    moves_left = movestogo if movestogo is not None and movestogo > 0 else DEFAULT_MOVES_TO_GO
    budget = remaining_ms / moves_left + INCREMENT_SHARE * increment_ms
    ceiling = max(MIN_TIME_MS, remaining_ms - MOVE_OVERHEAD_MS)
    return max(MIN_TIME_MS, min(int(budget), ceiling))


def _think(
    game_state: GameState,
    depth: int | None,
    movetime_ms: int | None,
    nodes: int | None = None,
    level: str | None = None,
) -> tuple[Move | None, SearchResult | None]:
    """Unique point d'entrée vers l'IA : coup choisi (None sans coup légal) et, hors
    niveau de difficulté, le résultat détaillé de la recherche.

    Avec ``level`` (option UCI ``Level``), l'IA joue à ce niveau (temps et bruit du
    niveau). Sinon, recherche limitée par ``depth`` / ``movetime_ms`` / ``nodes`` ; sans
    aucune limite, profondeur par défaut de l'IA.
    """
    if not game_state.get_valid_moves():
        return None, None
    if level is not None:
        return levels.choose_move(game_state, levels.LEVELS_BY_NAME[level]), None
    if depth is None and movetime_ms is None and nodes is None:
        depth = search.DEPTH
    result = search.think(
        game_state, SearchLimits(depth=depth, movetime_ms=movetime_ms, nodes=nodes)
    )
    return result.move, result


class UciEngine:
    """État de la session UCI : position courante et ``bestmove`` en attente (infinite)."""

    def __init__(self, out: TextIO) -> None:
        self.out = out
        self.game_state = GameState()
        self.pending_bestmove: str | None = None
        self.pending_info: str | None = None  # ligne info retenue avec le bestmove (infinite)
        # Niveau de difficulté (option UCI Level) ; None = pleine force, limites de go.
        self.level: str | None = None

    # -- sortie -----------------------------------------------------------
    def send(self, line: str) -> None:
        self.out.write(line + "\n")
        self.out.flush()

    def info(self, message: str) -> None:
        self.send(f"info string {message}")

    def _flush_pending(self) -> None:
        if self.pending_bestmove is not None:
            if self.pending_info is not None:
                self.send(self.pending_info)
            self.send(f"bestmove {self.pending_bestmove}")
            self.pending_bestmove = None
            self.pending_info = None

    # -- commandes --------------------------------------------------------
    def handle(self, line: str) -> bool:
        """Traite une ligne ; renvoie False sur ``quit``. Ne lève jamais d'exception."""
        tokens = line.split()
        if not tokens:
            return True
        command, args = tokens[0], tokens[1:]
        try:
            if command == "quit":
                self._flush_pending()
                return False
            if command == "uci":
                self.send(f"id name {ENGINE_NAME}")
                self.send(f"id author {ENGINE_AUTHOR}")
                names = " ".join(f"var {level.name}" for level in levels.LEVELS)
                self.send(
                    f"option name Level type combo default {FULL_STRENGTH} "
                    f"var {FULL_STRENGTH} {names}"
                )
                self.send("uciok")
            elif command == "isready":
                self.send("readyok")
            elif command == "ucinewgame":
                self._flush_pending()
                self.game_state = GameState()
            elif command == "position":
                self._flush_pending()
                self._position(args)
            elif command == "go":
                self._flush_pending()
                self._go(args)
            elif command == "stop":
                self._flush_pending()
            elif command == "setoption":
                self._setoption(args)
            elif command in ("debug", "register", "ponderhit"):
                pass  # Acceptées et sans effet
            else:
                self.info(f"commande inconnue ignorée : {line.strip()}")
        except Exception as exc:  # L'interface ne doit jamais voir un crash
            self.info(f"erreur interne ({type(exc).__name__}: {exc}) sur : {line.strip()}")
        return True

    def _position(self, args: list[str]) -> None:
        if not args:
            self.info("position : argument manquant (startpos ou fen)")
            return
        if "moves" in args:
            index = args.index("moves")
            setup, moves = args[:index], args[index + 1 :]
        else:
            setup, moves = args, []
        if setup[0] == "startpos" and len(setup) == 1:
            game_state = GameState()
        elif setup[0] == "fen" and len(setup) > 1:
            try:
                game_state = load_fen(" ".join(setup[1:]))
            except FenError as exc:
                self.info(f"FEN invalide, position inchangée : {exc}")
                return
        else:
            self.info(f"position : syntaxe invalide : {' '.join(args)}")
            return
        for text in moves:
            try:
                move = parse_uci(game_state, text)
            except NotationError as exc:
                self.info(f"coup refusé, position inchangée : {exc}")
                return
            game_state.make_move(move, validate=False)
        self.game_state = game_state

    def _setoption(self, args: list[str]) -> None:
        # setoption name <nom> [value <valeur>] ; seule l'option Level est reconnue.
        text = " ".join(args)
        if not text.startswith("name "):
            self.info(f"setoption mal formé : {text}")
            return
        name, _, value = text[len("name ") :].partition(" value ")
        if name.strip().lower() != "level":
            self.info(f"option inconnue ignorée : {name.strip()}")
            return
        value = value.strip()
        if value == FULL_STRENGTH:
            self.level = None
        elif value in levels.LEVELS_BY_NAME:
            self.level = value
        else:
            self.info(f"niveau inconnu : {value!r}")

    def _go(self, args: list[str]) -> None:
        params: dict[str, int] = {}
        infinite = False
        i = 0
        while i < len(args):
            key = args[i]
            if key in _INT_GO_PARAMS:
                if i + 1 >= len(args):
                    self.info(f"go : valeur manquante pour {key}")
                    break
                try:
                    params[key] = int(args[i + 1])
                except ValueError:
                    self.info(f"go : valeur entière attendue pour {key} : {args[i + 1]!r}")
                i += 2
                continue
            if key == "infinite":
                infinite = True
            elif key == "ponder":
                pass
            elif key == "searchmoves":
                self.info("go : searchmoves non pris en charge, ignoré")
                break
            else:
                self.info(f"go : paramètre inconnu ignoré : {key}")
            i += 1

        depth = params.get("depth")
        if depth is not None and depth < 1:
            self.info(f"go : profondeur {depth} invalide, ramenée à 1")
            depth = 1
        movetime = params.get("movetime")
        if movetime is None and not infinite:
            white = self.game_state.white_to_move
            remaining = params.get("wtime" if white else "btime")
            if remaining is not None:
                increment = params.get("winc" if white else "binc", 0)
                movetime = allocate_time_ms(remaining, increment, params.get("movestogo"))
        if infinite:
            depth, movetime = None, None

        move, result = _think(self.game_state, depth, movetime, params.get("nodes"), self.level)
        info: str | None = None
        if result is not None and result.move is not None:
            pv = " ".join(to_uci(m) for m in result.pv)
            if abs(result.score) >= search.MATE_THRESHOLD:
                plies = search.MATE - abs(result.score)
                mate = (plies + 1) // 2 if result.score > 0 else -((plies + 1) // 2)
                score = f"mate {mate}"
            else:
                score = f"cp {result.score}"
            info = (
                f"info depth {result.depth} score {score} nodes {result.nodes} "
                f"time {result.elapsed_ms} pv {pv}"
            )
        bestmove = to_uci(move) if move is not None else "0000"
        if infinite:
            self.pending_bestmove, self.pending_info = bestmove, info
        else:
            if info is not None:
                self.send(info)
            self.send(f"bestmove {bestmove}")


def run(stdin: TextIO, stdout: TextIO) -> None:
    """Boucle principale : lit ``stdin`` ligne par ligne jusqu'à ``quit`` ou EOF."""
    engine = UciEngine(stdout)
    for line in stdin:
        if not engine.handle(line):
            return
    engine._flush_pending()


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt, BrokenPipeError):
        run(sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
