"""
Suite tactique (J3.0) : vérification des solutions et mesure de l'IA par UCI
---------------------------------------------------------------------------
Format EPD (``chessproject/assets/tactics.epd``, lu par
:mod:`chessproject.core.puzzles`), une position par ligne ::

    <4 champs FEN> bm <coup SAN> [<coup SAN> ...]; [dm <N>;] id "<nom>";

``bm`` liste les coups acceptés (plusieurs seulement pour un mat, quand plusieurs coups
matent dans le même nombre de coups) ; ``dm N`` (*direct mate*, opcode EPD standard)
marque un mat en N coups. Les positions sans ``dm`` sont des gains de matériel.

Toutes les solutions sont **vérifiées par programme** sur notre moteur (``--verify``) :

- mat en N : solveur de mat forcé exhaustif (:func:`mating_moves`, 2N-1 demi-coups) :
  ``bm`` est exactement l'ensemble des coups qui matent en N au plus, et aucun mat en
  N-1 n'existe ;
- gain de matériel : minimax matériel (P=1, C=F=3, T=5, D=9) à 4 demi-coups suivis des
  captures (:func:`winning_moves`) : ``bm`` est l'**unique** coup qui gagne au moins
  la valeur d'un cavalier par rapport au matériel actuel.

Mesure ::

    python tools/tactics.py --depth 3
    python tools/tactics.py --movetime 1000 --engine "python -m chessproject.uci"
    python tools/tactics.py --verify          # revérifie les solutions de la suite
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from uci_client import EngineError, UciProcess, go_command, move_timeout

from chessproject import paths
from chessproject.core.engine import GameState, Move
from chessproject.core.notation import NotationError, parse_san, to_san, to_uci
from chessproject.core.puzzles import Puzzle as Tactic
from chessproject.core.puzzles import format_epd, parse_epd_line
from chessproject.core.puzzles import load_suite as _load_suite

DEFAULT_SUITE = paths.TACTICS_FILE
DEFAULT_ENGINE = "python -m chessproject.uci"


# --------------------------------------------------------------------------
# Format EPD : lecture et écriture dans chessproject.core.puzzles (J13.3)
# --------------------------------------------------------------------------
__all__ = ["Tactic", "format_epd", "load_suite", "parse_epd_line"]


def load_suite(path: Path = DEFAULT_SUITE) -> list[Tactic]:
    return _load_suite(path)


# --------------------------------------------------------------------------
# Solveur de mat forcé
# --------------------------------------------------------------------------
def _gives_check(gs: GameState, move: Move) -> bool:
    gs.make_move(move, validate=False)
    try:
        return gs.king_in_check()
    finally:
        gs.undo_move()


def _attacker_order(gs: GameState, moves: list[Move]) -> list[Move]:
    """Échecs d'abord, puis prises et promotions : trouve plus vite un mat qui existe."""
    return sorted(
        moves,
        key=lambda m: (_gives_check(gs, m), m.is_capture or m.is_pawn_promotion),
        reverse=True,
    )


def move_mates_within(gs: GameState, move: Move, n: int) -> bool:
    """Vrai si ``move`` force le mat en au plus ``n`` coups (``n`` ≥ 1) contre toute défense."""
    gs.make_move(move, validate=False)
    try:
        if n == 1:
            if not gs.king_in_check():
                return False
            replies = gs.get_valid_moves()
            return not replies and gs.checkmate
        replies = list(gs.get_valid_moves())
        if not replies:
            return gs.checkmate  # Pat ou nulle automatique : pas de mat
        for reply in replies:
            gs.make_move(reply, validate=False)
            try:
                if not has_mate_within(gs, n - 1):
                    return False
            finally:
                gs.undo_move()
        return True
    finally:
        gs.undo_move()


def has_mate_within(gs: GameState, n: int) -> bool:
    """Le camp au trait peut-il forcer le mat en au plus ``n`` coups ?"""
    if n < 1:
        return False
    moves = list(gs.get_valid_moves())
    if n == 1:
        return any(move_mates_within(gs, m, 1) for m in moves)
    return any(move_mates_within(gs, m, n) for m in _attacker_order(gs, moves))


def mating_moves(gs: GameState, n: int) -> list[Move]:
    """Tous les coups du camp au trait qui forcent le mat en au plus ``n`` coups."""
    return [m for m in list(gs.get_valid_moves()) if move_mates_within(gs, m, n)]


def shortest_mate(gs: GameState, max_n: int) -> tuple[int, list[Move]] | None:
    """(N, coups qui matent en N) pour le plus petit N ≤ ``max_n``, ou None."""
    for n in range(1, max_n + 1):
        moves = mating_moves(gs, n)
        if moves:
            return n, moves
    return None


# --------------------------------------------------------------------------
# Minimax matériel (gains de matériel)
# --------------------------------------------------------------------------
MATERIAL: dict[str, int] = {"p": 100, "N": 300, "B": 300, "R": 500, "Q": 900, "K": 0}
KNIGHT_VALUE: int = MATERIAL["N"]
MATERIAL_DEPTH: int = 4  # Demi-coups pleins, coup examiné compris, puis captures
_MATE_SCORE: int = 1_000_000
_INF: int = 10 * _MATE_SCORE
_MAX_QUIESCENCE: int = 12


def material_balance(gs: GameState) -> int:
    """Matériel du camp au trait moins celui de l'adversaire (centipions)."""
    total = 0
    for row in gs.board:
        for piece in row:
            if piece != "--":
                total += MATERIAL[piece[1]] if piece[0] == "w" else -MATERIAL[piece[1]]
    return total if gs.white_to_move else -total


def _mvv_lva(move: Move) -> int:
    victim = MATERIAL[move.piece_captured[1]] if move.is_capture else 0
    promo = MATERIAL[move.promotion_piece] if move.promotion_piece else 0
    return 10 * (victim + promo) - MATERIAL[move.piece_moved[1]]


def _quiescence(gs: GameState, alpha: int, beta: int, ply: int, qdepth: int) -> int:
    moves = gs.get_valid_moves()
    if not moves:
        return -_MATE_SCORE + ply if gs.checkmate else 0
    in_check = gs.in_check
    best = -_INF
    if not in_check:
        best = material_balance(gs)
        if best >= beta or qdepth >= _MAX_QUIESCENCE:
            return best
        alpha = max(alpha, best)
        candidates = [m for m in moves if m.is_capture or m.is_pawn_promotion]
    else:
        candidates = list(moves)  # En échec : toutes les parades (pas de « stand pat »)
    for move in sorted(candidates, key=_mvv_lva, reverse=True):
        gs.make_move(move, validate=False)
        score = -_quiescence(gs, -beta, -alpha, ply + 1, qdepth + 1)
        gs.undo_move()
        if score > best:
            best = score
        if score > alpha:
            alpha = score
        if alpha >= beta:
            break
    return best


def _material_search(gs: GameState, depth: int, alpha: int, beta: int, ply: int) -> int:
    """Alpha-bêta « fail-soft » sur le seul matériel, du point de vue du camp au trait."""
    moves = gs.get_valid_moves()
    if not moves:
        return -_MATE_SCORE + ply if gs.checkmate else 0
    if depth <= 0:
        return _quiescence(gs, alpha, beta, ply, 0)
    best = -_INF
    for move in sorted(moves, key=_mvv_lva, reverse=True):
        gs.make_move(move, validate=False)
        score = -_material_search(gs, depth - 1, -beta, -alpha, ply + 1)
        gs.undo_move()
        if score > best:
            best = score
        if score > alpha:
            alpha = score
        if alpha >= beta:
            break
    return best


def material_gain(gs: GameState, move: Move, depth: int = MATERIAL_DEPTH) -> int:
    """Gain de matériel exact de ``move`` (centipions, mat = très grand)."""
    baseline = material_balance(gs)
    gs.make_move(move, validate=False)
    try:
        score = -_material_search(gs, depth - 1, -_INF, _INF, 1)
    finally:
        gs.undo_move()
    return score - baseline


def winning_moves(
    gs: GameState, threshold: int = KNIGHT_VALUE, depth: int = MATERIAL_DEPTH
) -> list[Move]:
    """Coups qui gagnent au moins ``threshold`` (test à fenêtre nulle, plus rapide)."""
    target = material_balance(gs) + threshold
    winners = []
    for move in list(gs.get_valid_moves()):
        gs.make_move(move, validate=False)
        try:
            score = -_material_search(gs, depth - 1, -target, -target + 1, 1)
        finally:
            gs.undo_move()
        if score >= target:
            winners.append(move)
    return winners


# --------------------------------------------------------------------------
# Vérification d'une position de la suite
# --------------------------------------------------------------------------
def verify_tactic(tactic: Tactic, full: bool = True) -> list[str]:
    """Liste des problèmes (vide si la solution est confirmée).

    Mat : chaque ``bm`` mate en ``dm`` coups et aucun mat plus court n'existe ; avec
    ``full``, ``bm`` contient en outre *tous* les coups qui matent en ``dm``.
    Matériel : ``bm`` est l'unique coup gagnant au moins un cavalier (``full`` ignoré).
    """
    gs = tactic.game_state()
    try:
        best = [parse_san(gs, san) for san in tactic.best_moves]
    except NotationError as exc:
        return [f"bm illisible : {exc}"]
    problems = []
    if tactic.mate_in is not None:
        n = tactic.mate_in
        for move in best:
            if not move_mates_within(gs, move, n):
                problems.append(f"{to_san(gs, move)} ne mate pas en {n}")
        if n > 1 and has_mate_within(gs, n - 1):
            problems.append(f"il existe un mat en {n - 1} ou moins")
        if full:
            expected = {to_uci(m) for m in mating_moves(gs, n)}
            if expected != {to_uci(m) for m in best}:
                problems.append(f"coups qui matent en {n} : {sorted(expected)}")
    else:
        winners = {to_uci(m) for m in winning_moves(gs)}
        if winners != {to_uci(m) for m in best}:
            problems.append(f"coups gagnant ≥ un cavalier : {sorted(winners) or 'aucun'}")
    return problems


# --------------------------------------------------------------------------
# Mesure d'un moteur par UCI
# --------------------------------------------------------------------------
@dataclass
class TacticResult:
    tactic: Tactic
    played: str  # UCI
    solved: bool
    seconds: float


def run_suite(
    tactics: Sequence[Tactic],
    engine_command: str = DEFAULT_ENGINE,
    depth: int | None = None,
    movetime_ms: int | None = None,
    timeout_s: float | None = None,
    pythonpath: str | None = None,
) -> list[TacticResult]:
    go = go_command(depth, movetime_ms)
    timeout = move_timeout(depth, movetime_ms, timeout_s)
    results = []
    with UciProcess(engine_command, pythonpath, name="moteur") as engine:
        engine.handshake()
        for tactic in tactics:
            engine.send("ucinewgame")
            engine.is_ready()
            try:
                played, seconds = engine.bestmove(f"position fen {tactic.fen} 0 1", go, timeout)
            except EngineError as exc:
                print(f"{tactic.name} : {exc}", file=sys.stderr)
                played, seconds = "", timeout
            results.append(TacticResult(tactic, played, played in tactic.best_moves_uci(), seconds))
    return results


def format_results(results: Sequence[TacticResult]) -> str:
    lines = []
    for r in results:
        mark = "OK " if r.solved else "-- "
        kind = f"mat en {r.tactic.mate_in}" if r.tactic.mate_in else "matériel"
        expected = " ".join(r.tactic.best_moves)
        lines.append(
            f"{mark}{r.tactic.name:<28} {kind:<9} attendu {expected:<16} "
            f"joué {r.played or '(rien)':<6} {r.seconds:6.2f} s"
        )
    solved = sum(r.solved for r in results)
    total_time = sum(r.seconds for r in results)
    by_kind: dict[str, list[bool]] = {}
    for r in results:
        key = f"mats en {r.tactic.mate_in}" if r.tactic.mate_in else "gains de matériel"
        by_kind.setdefault(key, []).append(r.solved)
    detail = ", ".join(f"{k} {sum(v)}/{len(v)}" for k, v in sorted(by_kind.items()))
    lines.append(f"{solved}/{len(results)} résolues ({detail}) en {total_time:.1f} s")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Suite tactique : mesure ou vérification.")
    limit = parser.add_mutually_exclusive_group()
    limit.add_argument("--depth", type=int, help="Profondeur fixe par position")
    limit.add_argument("--movetime", type=int, help="Temps par position (ms)")
    parser.add_argument("--engine", default=DEFAULT_ENGINE, help="Commande du moteur UCI")
    parser.add_argument("--pythonpath", help="PYTHONPATH propre au moteur")
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--timeout", type=float, help="Délai max par position (s)")
    parser.add_argument(
        "--verify", action="store_true", help="Revérifier les solutions (sans moteur)"
    )
    args = parser.parse_args(argv)
    tactics = load_suite(args.suite)

    if args.verify:
        failures = 0
        for tactic in tactics:
            start = time.monotonic()
            problems = verify_tactic(tactic)
            status = "OK" if not problems else "ÉCHEC : " + " ; ".join(problems)
            print(f"{tactic.name:<28} {time.monotonic() - start:6.2f} s  {status}", flush=True)
            failures += bool(problems)
        print(f"{len(tactics) - failures}/{len(tactics)} solutions confirmées")
        return 1 if failures else 0

    depth = args.depth
    if depth is None and args.movetime is None:
        depth = 3
    start = time.monotonic()
    results = run_suite(tactics, args.engine, depth, args.movetime, args.timeout, args.pythonpath)
    print(format_results(results))
    print(f"Durée totale (lancement compris) : {time.monotonic() - start:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
