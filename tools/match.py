"""
Mini-ligue entre deux moteurs UCI (J3.0)
---------------------------------------
Mesure l'écart de force entre deux moteurs, typiquement deux révisions de notre IA ::

    python tools/match.py --engine-a "python -m chessproject.uci" \\
        --engine-b "python -m chessproject.uci" --games 40 --movetime 200
    python tools/match.py ... --depth 3 --concurrency 4 --json resultats.json

Comparer à une autre révision : ``git worktree add ../ref <commit>`` puis
``--pythonpath-b ../ref`` (le moteur B est alors lancé depuis ``../ref`` avec
``PYTHONPATH=../ref``, cf. ``uci_client.engine_env_and_cwd``).

Déroulement : chaque position de ``--openings`` (une FEN par ligne, par défaut
``tools/openings.txt``) est jouée deux fois, couleurs inversées, ce qui neutralise le
biais de l'ouverture. Chaque partie lance ses deux moteurs (une partie qui plante n'en
contamine pas une autre). L'**arbitre est notre moteur** (``core.engine.GameState`` et
``result()``) : il valide chaque coup ; un coup illégal, un ``bestmove`` absent ou hors
délai, ou un moteur arrêté fait perdre le fautif (motif journalisé). Mat, pat et nulles
automatiques (50 coups, triple répétition, matériel insuffisant) sont détectés par le
moteur ; au-delà de ``--max-plies`` demi-coups, la partie est déclarée nulle par
adjudication.

Statistiques (point de vue de A, *N* parties, *V/N/D* victoires/nulles/défaites) :

- score ``s = (V + N/2) / N`` ;
- différence Elo du modèle logistique : ``Elo(s) = -400 · log10(1/s - 1)`` ;
- intervalle de confiance à 95 % : variance *empirique* d'une partie
  ``σ² = [V(1-s)² + N(½-s)² + D(0-s)²] / N`` (elle tient compte des nulles, plus
  fidèle que la loi binomiale), écart type de la moyenne ``σ/√N``, bornes
  ``Elo(s ± 1,96 σ/√N)`` (bornes de score ramenées dans ]0, 1[) ;
- LOS (*likelihood of superiority*, probabilité que A soit plus fort que B), approximation
  normale usuelle sur les parties décisives : ``LOS = ½ [1 + erf((V-D) / √(2(V+D)))]``.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

from uci_client import EngineError, UciProcess, go_command, move_timeout

from chessproject.core.engine import Color
from chessproject.core.fen import load_fen
from chessproject.core.notation import NotationError, parse_uci

DEFAULT_OPENINGS = Path(__file__).resolve().parent / "openings.txt"
Z_95 = 1.959963984540054  # Quantile 97,5 % de la loi normale
_SCORE_EPSILON = 1e-6  # Les bornes de score sont ramenées dans [ε, 1-ε] (Elo fini)


# --------------------------------------------------------------------------
# Statistiques (fonctions pures)
# --------------------------------------------------------------------------
def elo_difference(score: float) -> float:
    """Écart Elo correspondant à un score moyen dans ]0, 1[ (±inf aux bornes)."""
    if score <= 0.0:
        return -math.inf
    if score >= 1.0:
        return math.inf
    return -400.0 * math.log10(1.0 / score - 1.0) + 0.0  # + 0.0 : pas de « -0.0 »


def match_score(wins: int, draws: int, losses: int) -> float:
    games = wins + draws + losses
    if games == 0:
        raise ValueError("Aucune partie")
    return (wins + 0.5 * draws) / games


def score_stderr(wins: int, draws: int, losses: int) -> float:
    """Écart type du score moyen, à partir de la variance empirique des résultats."""
    games = wins + draws + losses
    s = match_score(wins, draws, losses)
    variance = (wins * (1 - s) ** 2 + draws * (0.5 - s) ** 2 + losses * s**2) / games
    return math.sqrt(variance / games)


def elo_interval(wins: int, draws: int, losses: int, z: float = Z_95) -> tuple[float, float]:
    """Intervalle de confiance (bas, haut) de l'écart Elo, à ``z`` écarts types."""
    s = match_score(wins, draws, losses)
    margin = z * score_stderr(wins, draws, losses)
    low = min(max(s - margin, _SCORE_EPSILON), 1 - _SCORE_EPSILON)
    high = min(max(s + margin, _SCORE_EPSILON), 1 - _SCORE_EPSILON)
    return elo_difference(low), elo_difference(high)


def likelihood_of_superiority(wins: int, losses: int) -> float:
    """LOS : probabilité que A soit plus fort que B (0,5 sans partie décisive)."""
    if wins + losses == 0:
        return 0.5
    return 0.5 * (1.0 + math.erf((wins - losses) / math.sqrt(2.0 * (wins + losses))))


# --------------------------------------------------------------------------
# Parties
# --------------------------------------------------------------------------
@dataclass
class EngineSpec:
    name: str
    command: str
    pythonpath: str | None = None


@dataclass
class GameRecord:
    index: int
    opening_index: int
    fen: str
    a_is_white: bool
    score_a: float  # 1, 0,5 ou 0, du point de vue de A
    pgn_result: str  # 1-0, 0-1, 1/2-1/2
    termination: str
    plies: int
    duration_s: float
    moves: list[str] = field(default_factory=list)
    fault: str | None = None


@dataclass
class MatchConfig:
    depth: int | None
    movetime_ms: int | None
    max_plies: int
    timeout_s: float | None


def load_openings(path: Path) -> list[str]:
    """FEN du fichier (lignes vides et commentaires « # » ignorés), validées par load_fen."""
    fens = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            load_fen(line)
        except ValueError as exc:
            raise ValueError(f"{path}:{number} : FEN invalide ({exc})") from exc
        fens.append(line)
    if not fens:
        raise ValueError(f"{path} : aucune position")
    return fens


def schedule(n_openings: int, games: int, seed: int | None) -> list[tuple[int, bool]]:
    """(indice d'ouverture, A a les Blancs) pour chaque partie : chaque ouverture deux fois."""
    order = list(range(n_openings))
    if seed is not None:
        random.Random(seed).shuffle(order)
    return [(order[(g // 2) % n_openings], g % 2 == 0) for g in range(games)]


def _score_for_a(white_score: float, a_is_white: bool) -> float:
    return white_score if a_is_white else 1.0 - white_score


def _pgn(white_score: float) -> str:
    return {1.0: "1-0", 0.0: "0-1"}.get(white_score, "1/2-1/2")


def play_game(
    index: int,
    opening_index: int,
    fen: str,
    a_is_white: bool,
    engine_a: EngineSpec,
    engine_b: EngineSpec,
    config: MatchConfig,
) -> GameRecord:
    """Joue une partie arbitrée par notre moteur et renvoie son compte rendu."""
    start = time.monotonic()
    white_spec, black_spec = (engine_a, engine_b) if a_is_white else (engine_b, engine_a)
    go = go_command(config.depth, config.movetime_ms)
    timeout = move_timeout(config.depth, config.movetime_ms, config.timeout_s)
    game_state = load_fen(fen)
    moves: list[str] = []
    engines: dict[bool, UciProcess] = {}

    def finish(white_score: float, termination: str, fault: str | None = None) -> GameRecord:
        return GameRecord(
            index=index,
            opening_index=opening_index,
            fen=fen,
            a_is_white=a_is_white,
            score_a=_score_for_a(white_score, a_is_white),
            pgn_result=_pgn(white_score),
            termination=termination,
            plies=len(moves),
            duration_s=round(time.monotonic() - start, 3),
            moves=moves,
            fault=fault,
        )

    try:
        for is_white, spec in ((True, white_spec), (False, black_spec)):
            try:
                engine = UciProcess(spec.command, spec.pythonpath, name=spec.name)
                engines[is_white] = engine
                engine.handshake()
                engine.send("ucinewgame")
                engine.is_ready()
            except (EngineError, OSError) as exc:
                return finish(0.0 if is_white else 1.0, "engine_failure", f"{spec.name}: {exc}")

        while True:
            result = game_state.result()
            if result.is_over:
                assert result.termination is not None
                if result.winner is Color.WHITE:
                    return finish(1.0, result.termination.value)
                if result.winner is Color.BLACK:
                    return finish(0.0, result.termination.value)
                return finish(0.5, result.termination.value)
            if len(moves) >= config.max_plies:
                return finish(0.5, "adjudication_max_plies")

            white = game_state.white_to_move
            spec = white_spec if white else black_spec
            loss = 0.0 if white else 1.0
            position = f"position fen {fen}" + (" moves " + " ".join(moves) if moves else "")
            try:
                text, _ = engines[white].bestmove(position, go, timeout)
            except EngineError as exc:
                return finish(loss, "engine_failure", f"{spec.name}: {exc}")
            try:
                move = parse_uci(game_state, text)
            except NotationError:
                return finish(loss, "illegal_move", f"{spec.name}: coup illégal {text!r}")
            moves.append(text)
            game_state.make_move(move, validate=False)
    finally:
        for engine in engines.values():
            engine.close()


@dataclass
class MatchSummary:
    games: int
    wins: int
    draws: int
    losses: int
    score: float
    elo: float
    elo_low: float
    elo_high: float
    los: float
    duration_s: float
    terminations: dict[str, int]
    faults: list[str]


def summarize(records: Sequence[GameRecord], duration_s: float) -> MatchSummary:
    wins = sum(1 for r in records if r.score_a == 1.0)
    draws = sum(1 for r in records if r.score_a == 0.5)
    losses = sum(1 for r in records if r.score_a == 0.0)
    low, high = elo_interval(wins, draws, losses)
    terminations: dict[str, int] = {}
    for record in records:
        terminations[record.termination] = terminations.get(record.termination, 0) + 1
    score = match_score(wins, draws, losses)
    return MatchSummary(
        games=len(records),
        wins=wins,
        draws=draws,
        losses=losses,
        score=score,
        elo=elo_difference(score),
        elo_low=low,
        elo_high=high,
        los=likelihood_of_superiority(wins, losses),
        duration_s=round(duration_s, 2),
        terminations=dict(sorted(terminations.items())),
        faults=[f"partie {r.index + 1} : {r.fault}" for r in records if r.fault],
    )


def run_match(
    engine_a: EngineSpec,
    engine_b: EngineSpec,
    openings: list[str],
    games: int,
    config: MatchConfig,
    concurrency: int = 1,
    seed: int | None = None,
    log: bool = True,
) -> tuple[list[GameRecord], MatchSummary]:
    plan = schedule(len(openings), games, seed)
    start = time.monotonic()
    records: list[GameRecord] = []
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [
            pool.submit(play_game, g, o, openings[o], a_white, engine_a, engine_b, config)
            for g, (o, a_white) in enumerate(plan)
        ]
        for future in as_completed(futures):
            record = future.result()
            with lock:
                records.append(record)
                if log:
                    _log_game(record, len(records), games, engine_a.name, engine_b.name)
    records.sort(key=lambda r: r.index)
    return records, summarize(records, time.monotonic() - start)


# --------------------------------------------------------------------------
# Affichage et ligne de commande
# --------------------------------------------------------------------------
def _fmt_elo(value: float) -> str:
    return f"{value:+.1f}" if math.isfinite(value) else ("+inf" if value > 0 else "-inf")


def _log_game(record: GameRecord, done: int, total: int, name_a: str, name_b: str) -> None:
    white, black = (name_a, name_b) if record.a_is_white else (name_b, name_a)
    line = (
        f"[{done}/{total}] partie {record.index + 1} (ouverture {record.opening_index + 1}) "
        f"{white} - {black} : {record.pgn_result} ({record.termination}, "
        f"{record.plies} demi-coups, {record.duration_s:.1f} s)"
    )
    if record.fault:
        line += f" FAUTE : {record.fault}"
    print(line, file=sys.stderr, flush=True)


def format_summary(summary: MatchSummary, name_a: str, name_b: str) -> str:
    lines = [
        f"{name_a} contre {name_b} : {summary.games} parties en {summary.duration_s:.1f} s",
        f"V/N/D pour A : {summary.wins}/{summary.draws}/{summary.losses}"
        f"  score {100 * summary.score:.1f} %",
        f"Elo(A - B) : {_fmt_elo(summary.elo)}  IC 95 % [{_fmt_elo(summary.elo_low)}, "
        f"{_fmt_elo(summary.elo_high)}]",
        f"LOS : {100 * summary.los:.1f} %",
        "Fins : " + ", ".join(f"{k} {v}" for k, v in summary.terminations.items()),
    ]
    if summary.faults:
        lines.append("Fautes :")
        lines.extend(f"  {fault}" for fault in summary.faults)
    return "\n".join(lines)


def _json_safe(value: float) -> float | str:
    return value if math.isfinite(value) else ("inf" if value > 0 else "-inf")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mini-ligue entre deux moteurs UCI.")
    parser.add_argument("--engine-a", required=True, help="Commande du moteur A (UCI)")
    parser.add_argument("--engine-b", required=True, help="Commande du moteur B (UCI)")
    parser.add_argument("--name-a", default="A")
    parser.add_argument("--name-b", default="B")
    parser.add_argument("--pythonpath-a", help="PYTHONPATH propre au moteur A")
    parser.add_argument("--pythonpath-b", help="PYTHONPATH propre au moteur B")
    parser.add_argument("--games", type=int, default=40, help="Nombre de parties (défaut 40)")
    limit = parser.add_mutually_exclusive_group()
    limit.add_argument("--depth", type=int, help="Profondeur fixe par coup")
    limit.add_argument("--movetime", type=int, help="Temps par coup (ms)")
    parser.add_argument("--openings", type=Path, default=DEFAULT_OPENINGS)
    parser.add_argument("--max-plies", type=int, default=300, help="Au-delà : nulle (300)")
    parser.add_argument("--concurrency", type=int, default=1, help="Parties en parallèle")
    parser.add_argument("--seed", type=int, help="Mélange l'ordre des ouvertures")
    parser.add_argument("--timeout", type=float, help="Délai max de réponse par coup (s)")
    parser.add_argument(
        "--json", metavar="FICHIER", help="Résultats machine (« - » : sortie standard)"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.games < 1:
        print("--games doit être >= 1", file=sys.stderr)
        return 2
    depth, movetime = args.depth, args.movetime
    if depth is None and movetime is None:
        depth = 3
    engine_a = EngineSpec(args.name_a, args.engine_a, args.pythonpath_a)
    engine_b = EngineSpec(args.name_b, args.engine_b, args.pythonpath_b)
    config = MatchConfig(depth, movetime, args.max_plies, args.timeout)
    openings = load_openings(args.openings)
    records, summary = run_match(
        engine_a, engine_b, openings, args.games, config, args.concurrency, args.seed
    )
    text = format_summary(summary, args.name_a, args.name_b)
    print(text, file=sys.stderr if args.json == "-" else sys.stdout, flush=True)
    if args.json:
        payload = {
            "engine_a": asdict(engine_a),
            "engine_b": asdict(engine_b),
            "config": asdict(config),
            "seed": args.seed,
            "summary": {
                key: _json_safe(value) if isinstance(value, float) else value
                for key, value in asdict(summary).items()
            },
            "games": [asdict(record) for record in records],
        }
        data = json.dumps(payload, indent=2, ensure_ascii=False)
        if args.json == "-":
            print(data, flush=True)
        else:
            Path(args.json).write_text(data + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
