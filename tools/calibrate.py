"""
Échelle des niveaux de difficulté (J8.0)
---------------------------------------
Fait jouer chaque niveau contre son voisin immédiat (``tools/match.py``) et chaîne les
écarts pour situer tous les niveaux sur une même échelle Elo ::

    python tools/calibrate.py --games 100 --concurrency 6
    python tools/calibrate.py Débutant "base=Débutant,nodes=300" Facile --games 40
    python tools/calibrate.py --anchor 4=1650:45 --json echelle.json

Chaque échelon est un nom de niveau (``chessproject.ai.levels``) ou une description pour
``--level-spec`` (``base=Moyen,nodes=4000,noise=40``). Sans échelon, les cinq niveaux.

Chaînage : l'écart entre deux voisins est ``Elo(s)`` (cf. ``match.elo_difference``), son
écart type est estimé par la demi-largeur de l'intervalle à 95 % divisée par 1,96. L'Elo
d'un échelon est la somme des écarts depuis l'échelon de référence (``--anchor
INDICE=ELO[:ÉCART_TYPE]``, défaut : le premier échelon à 0) ; les variances s'ajoutent,
les matchs étant indépendants.
"""

from __future__ import annotations

import argparse
import json
import math
import shlex
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import match

from chessproject.ai import levels

ENGINE = "python -m chessproject.uci"
# Écart retenu quand un match est gagné ou perdu à 100 % (Elo infini) : borne prudente.
_SATURATED_ELO = 800.0


@dataclass
class Rung:
    label: str
    level: levels.Level

    @property
    def command(self) -> str:
        if self.label in levels.LEVELS_BY_NAME:
            return f"{ENGINE} --level {shlex.quote(self.label)}"
        return f"{ENGINE} --level-spec {shlex.quote(self.label)}"


@dataclass
class PairResult:
    weaker: str
    stronger: str
    wins: int  # du point de vue du plus fort
    draws: int
    losses: int
    score: float
    elo: float
    elo_se: float


@dataclass
class Rating:
    label: str
    elo: float
    se: float  # écart type ; IC 95 % = elo ± 1,96 se


def parse_rung(text: str) -> Rung:
    """Échelon : nom de niveau, ou description ``--level-spec`` (``ValueError`` sinon)."""
    if text in levels.LEVELS_BY_NAME:
        return Rung(text, levels.LEVELS_BY_NAME[text])
    return Rung(text, levels.parse_level_spec(text))


def parse_anchor(text: str, rungs: int) -> tuple[int, float, float]:
    """``INDICE=ELO[:ÉCART_TYPE]`` (indice à partir de 0) ; ``ValueError`` si invalide."""
    index_text, sep, value = text.partition("=")
    if not sep:
        raise ValueError(f"ancre mal formée (INDICE=ELO[:ÉCART_TYPE]) : {text!r}")
    elo_text, _, se_text = value.partition(":")
    index, elo, se = int(index_text), float(elo_text), float(se_text or 0)
    if not 0 <= index < rungs or se < 0:
        raise ValueError(f"ancre hors limites : {text!r}")
    return index, elo, se


def pair_result(weaker: str, stronger: str, wins: int, draws: int, losses: int) -> PairResult:
    """Écart Elo du plus fort (``wins`` = ses victoires) et son écart type."""
    score = match.match_score(wins, draws, losses)
    elo = match.elo_difference(score)
    low, high = match.elo_interval(wins, draws, losses)
    if not math.isfinite(elo):
        elo = math.copysign(_SATURATED_ELO, elo)
    low = max(low, elo - _SATURATED_ELO) if math.isfinite(low) else elo - _SATURATED_ELO
    high = min(high, elo + _SATURATED_ELO) if math.isfinite(high) else elo + _SATURATED_ELO
    se = (high - low) / (2 * match.Z_95)
    return PairResult(weaker, stronger, wins, draws, losses, score, elo, se)


def chain_ratings(
    labels: Sequence[str],
    pairs: Sequence[PairResult],
    anchor: tuple[int, float, float] = (0, 0.0, 0.0),
) -> list[Rating]:
    """Elo de chaque échelon à partir des écarts entre voisins (``pairs[i]`` : i contre i+1)."""
    if len(pairs) != len(labels) - 1:
        raise ValueError("il faut un match par paire de voisins")
    index, anchor_elo, anchor_se = anchor
    ratings: list[Rating] = []
    for i, label in enumerate(labels):
        lo, hi = sorted((i, index))
        span = pairs[lo:hi]
        offset = sum(p.elo for p in span)
        variance = anchor_se**2 + sum(p.elo_se**2 for p in span)
        elo = anchor_elo + offset if i > index else anchor_elo - offset
        ratings.append(Rating(label, elo, math.sqrt(variance)))
    return ratings


def format_table(pairs: Sequence[PairResult], ratings: Sequence[Rating]) -> str:
    lines = ["| Match | V / N / D | Score | Écart Elo [IC 95 %] |", "|---|---|---|---|"]
    for p in pairs:
        half = match.Z_95 * p.elo_se
        lines.append(
            f"| {p.stronger} – {p.weaker} | {p.wins} / {p.draws} / {p.losses} | "
            f"{100 * p.score:.1f} % | {p.elo:+.0f} [{p.elo - half:+.0f}, {p.elo + half:+.0f}] |"
        )
    lines += ["", "| Échelon | Elo | IC 95 % |", "|---|---|---|"]
    for r in ratings:
        lines.append(f"| {r.label} | {r.elo:.0f} | ± {match.Z_95 * r.se:.0f} |")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("rungs", nargs="*", help="échelons, du plus faible au plus fort")
    parser.add_argument("--games", type=int, default=100, help="parties par paire (100)")
    parser.add_argument("--concurrency", type=int, default=1, help="parties en parallèle")
    parser.add_argument("--seed", type=int, help="mélange l'ordre des ouvertures")
    parser.add_argument("--openings", type=Path, default=match.DEFAULT_OPENINGS)
    parser.add_argument("--max-plies", type=int, default=300)
    parser.add_argument("--anchor", help="INDICE=ELO[:ÉCART_TYPE] (défaut : 0=0)")
    parser.add_argument("--json", metavar="FICHIER", help="résultats machine")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rungs = [parse_rung(text) for text in args.rungs or [lv.name for lv in levels.LEVELS]]
        if len(rungs) < 2:
            raise ValueError("il faut au moins deux échelons")
        anchor = parse_anchor(args.anchor, len(rungs)) if args.anchor else (0, 0.0, 0.0)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    openings = match.load_openings(args.openings)
    # Les niveaux ignorent les limites de « go » ; la profondeur 1 ne sert qu'à la commande,
    # et le délai de réponse de ce mode (120 s) couvre le plafond de temps de tout niveau.
    config = match.MatchConfig(1, None, args.max_plies, None)
    pairs: list[PairResult] = []
    for weaker, stronger in zip(rungs, rungs[1:], strict=False):
        print(f"== {stronger.label} contre {weaker.label}", file=sys.stderr, flush=True)
        _, summary = match.run_match(
            match.EngineSpec(stronger.label, stronger.command),
            match.EngineSpec(weaker.label, weaker.command),
            openings,
            args.games,
            config,
            args.concurrency,
            args.seed,
        )
        if summary.faults:
            print("\n".join(summary.faults), file=sys.stderr)
        pairs.append(
            pair_result(weaker.label, stronger.label, summary.wins, summary.draws, summary.losses)
        )
    ratings = chain_ratings([r.label for r in rungs], pairs, anchor)
    print(format_table(pairs, ratings), flush=True)
    if args.json:
        payload = {
            "games_per_pair": args.games,
            "rungs": [{"label": r.label, "level": asdict(r.level)} for r in rungs],
            "pairs": [asdict(p) for p in pairs],
            "ratings": [asdict(r) for r in ratings],
        }
        Path(args.json).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
