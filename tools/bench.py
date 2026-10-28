"""
Mesure de vitesse du moteur (J10.1)
-----------------------------------
Recherche à profondeur fixe sur quelques positions de référence ; affiche, pour chaque
position, le nombre de nœuds, le temps et les nœuds par seconde, puis le total.

Le **nombre de nœuds** est déterministe : une optimisation qui ne change pas l'algorithme
doit le laisser identique (c'est la signature de la recherche), seule la vitesse bouge.
Une technique de recherche (J10.2) le change, et se juge alors en mini-ligue.

    python tools/bench.py                # profondeur 4, sans élagage (arbre des niveaux)
    python tools/bench.py --features pvs,null_move,lmr
    python tools/bench.py --depth 5
    python tools/bench.py --profile      # profil cProfile des 25 fonctions les plus chères
"""

from __future__ import annotations

import argparse
import cProfile
import pstats
import time
from dataclasses import dataclass

from chessproject.ai.search import NO_FEATURES, Searcher, SearchFeatures, SearchLimits
from chessproject.core.fen import load_fen

# Ouverture, milieu de partie ouvert (Kiwipete), milieu fermé, finale de tours, finale
# de pions : des positions variées pour ne pas optimiser un seul cas.
POSITIONS: tuple[tuple[str, str], ...] = (
    ("départ", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"),
    ("kiwipete", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"),
    ("italienne", "r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 7"),
    ("finale-tours", "8/5pk1/6p1/R7/5P2/6PK/r7/8 w - - 0 40"),
    ("finale-pions", "8/2k5/3p4/p2P1p2/P4P2/8/6K1/8 w - - 0 50"),
)


@dataclass(frozen=True)
class BenchLine:
    name: str
    nodes: int
    seconds: float

    @property
    def nps(self) -> float:
        return self.nodes / self.seconds if self.seconds > 0 else 0.0


def run(depth: int, features: SearchFeatures = NO_FEATURES) -> list[BenchLine]:
    """Une recherche à ``depth`` par position, chacune avec une table de transposition
    neuve (les mesures ne dépendent pas de l'ordre des positions)."""
    lines = []
    for name, fen in POSITIONS:
        game_state = load_fen(fen)
        start = time.perf_counter()
        result = Searcher(features=features).think(game_state, SearchLimits(depth=depth))
        lines.append(BenchLine(name, result.nodes, time.perf_counter() - start))
    return lines


def report(lines: list[BenchLine]) -> str:
    rows = [f"{'position':<14}{'nœuds':>10}{'temps (s)':>11}{'nœuds/s':>10}"]
    for line in lines:
        rows.append(f"{line.name:<14}{line.nodes:>10}{line.seconds:>11.2f}{line.nps:>10.0f}")
    total = BenchLine("total", sum(x.nodes for x in lines), sum(x.seconds for x in lines))
    rows.append(f"{total.name:<14}{total.nodes:>10}{total.seconds:>11.2f}{total.nps:>10.0f}")
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--depth", type=int, default=4)
    parser.add_argument("--profile", action="store_true", help="profil cProfile")
    parser.add_argument(
        "--features", type=SearchFeatures.parse, default=NO_FEATURES, help="ex. pvs,lmr ; all"
    )
    args = parser.parse_args(argv)
    if args.profile:
        profiler = cProfile.Profile()
        profiler.enable()
        lines = run(args.depth, args.features)
        profiler.disable()
        pstats.Stats(profiler).sort_stats("tottime").print_stats(25)
    else:
        lines = run(args.depth, args.features)
    print(report(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
