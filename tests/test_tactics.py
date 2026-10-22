"""Suite tactique (J3.0) : légalité des positions, solutions vérifiées, mesure de l'IA."""

import sys
import time
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import tactics

from chessproject.core.fen import load_fen
from chessproject.core.notation import parse_san, to_san

try:
    import chess

    _CHESS_OK = True
except ImportError:  # pragma: no cover - dépendance de développement absente
    _CHESS_OK = False

needs_chess = pytest.mark.skipif(not _CHESS_OK, reason="python-chess absent")

SUITE = tactics.load_suite()
MATES = [t for t in SUITE if t.mate_in is not None]
GAINS = [t for t in SUITE if t.mate_in is None]
MATES_IN_ONE = [t for t in MATES if t.mate_in == 1]
LONGER_MATES = [t for t in MATES if (t.mate_in or 0) > 1]


def _ids(items: list[tactics.Tactic]) -> list[str]:
    return [t.name for t in items]


# --------------------------------------------------------------------------
# Format et contenu
# --------------------------------------------------------------------------
def test_suite_size_and_composition() -> None:
    assert len(SUITE) >= 30
    assert len(MATES) >= 15
    assert {t.mate_in for t in MATES} == {1, 2, 3}
    assert len(GAINS) >= 10
    assert len({t.name for t in SUITE}) == len(SUITE)
    assert len({t.fen for t in SUITE}) == len(SUITE)
    for t in MATES:
        assert t.name.startswith(f"mate{t.mate_in}.")
    for t in GAINS:
        assert t.name.startswith("gain.") and len(t.best_moves) == 1


def test_epd_round_trip() -> None:
    for line in tactics.DEFAULT_SUITE.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            assert tactics.format_epd(tactics.parse_epd_line(line)) == line


def test_epd_parsing() -> None:
    t = tactics.parse_epd_line('k7/8/2K5/8/8/8/8/7R w - - bm Kc7 Kb6; dm 2; id "x y";')
    assert t.fen == "k7/8/2K5/8/8/8/8/7R w - -"
    assert t.best_moves == ("Kc7", "Kb6") and t.mate_in == 2 and t.name == "x y"
    for bad in (
        "k7/8/2K5/8/8/8/8/7R w - -",
        'k7/8/2K5/8/8/8/8/7R w - - id "sans bm";',
        "k7/8/2K5/8/8/8/8/7R w - - bm Kc7",
        'k7/8/2K5/8/8/8/8/7R w - - bm Kc7; ??? id "x";',
    ):
        with pytest.raises(ValueError):
            tactics.parse_epd_line(bad)


@pytest.mark.parametrize("tactic", SUITE, ids=_ids(SUITE))
def test_position_is_legal(tactic: tactics.Tactic) -> None:
    gs = load_fen(tactic.fen)
    assert gs.get_valid_moves()
    assert not gs.result().is_over
    if _CHESS_OK:
        board = chess.Board(tactic.fen + " 0 1")
        assert board.is_valid(), board.status()
        assert not board.is_game_over()


@pytest.mark.parametrize("tactic", SUITE, ids=_ids(SUITE))
def test_best_moves_are_legal_and_canonical(tactic: tactics.Tactic) -> None:
    gs = load_fen(tactic.fen)
    for san in tactic.best_moves:
        move = parse_san(gs, san)
        assert to_san(gs, move) == san  # SAN canonique, suffixe compris
        if _CHESS_OK:
            board = chess.Board(tactic.fen + " 0 1")
            assert board.san(board.parse_san(san)) == san


# --------------------------------------------------------------------------
# Solveur de mat et minimax matériel
# --------------------------------------------------------------------------
@pytest.mark.parametrize("tactic", MATES, ids=_ids(MATES))
def test_solver_confirms_mate(tactic: tactics.Tactic) -> None:
    """Chaque bm mate en dm coups et aucun mat plus court n'existe (≈ 1 s au plus)."""
    assert tactics.verify_tactic(tactic, full=False) == []


@needs_chess
@pytest.mark.parametrize("tactic", MATES_IN_ONE, ids=_ids(MATES_IN_ONE))
def test_mate_in_one_confirmed_by_python_chess(tactic: tactics.Tactic) -> None:
    board = chess.Board(tactic.fen + " 0 1")
    mates = {board.san(m) for m in board.legal_moves if _is_mate_after(board, m)}
    assert mates == set(tactic.best_moves)


def _is_mate_after(board: "chess.Board", move: "chess.Move") -> bool:
    board.push(move)
    try:
        return board.is_checkmate()
    finally:
        board.pop()


def test_solver_basics() -> None:
    gs = load_fen("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - -")
    assert tactics.has_mate_within(gs, 1)
    assert [to_san(gs, m) for m in tactics.mating_moves(gs, 1)] == ["Ra8#"]
    # Mat en 2 sans mat en 1 ; le solveur rend la position intacte.
    gs = load_fen("k7/8/2K5/8/8/8/8/7R w - -")
    before = [row[:] for row in gs.board]
    assert not tactics.has_mate_within(gs, 1)
    assert tactics.shortest_mate(gs, 3) is not None
    assert gs.board == before and gs.white_to_move and not gs.move_log
    # Un pat n'est pas un mat, à aucune profondeur.
    gs = load_fen("k7/8/2K5/8/8/8/8/1Q6 w - -")
    stalemate = parse_san(gs, "Qb6")
    assert not tactics.move_mates_within(gs, stalemate, 1)
    assert not tactics.move_mates_within(gs, stalemate, 2)
    assert tactics.move_mates_within(gs, parse_san(gs, "Qb7"), 1)  # protégée par le roi
    # Roi seul contre roi : aucun mat possible.
    assert not tactics.has_mate_within(load_fen("8/8/8/4k3/8/8/8/4K3 w - -"), 3)


def test_material_search_basics() -> None:
    gs = load_fen("2q3k1/5ppp/8/3N4/8/8/5PPP/6K1 w - -")
    assert tactics.material_balance(gs) == 300 - 900
    fork = parse_san(gs, "Ne7+")
    assert tactics.material_gain(gs, fork) == 900
    assert [to_san(gs, m) for m in tactics.winning_moves(gs)] == ["Ne7+"]
    # Prise défendue : pas de gain.
    gs = load_fen("4k3/8/3p4/4p3/8/8/8/4RK2 w - -")
    assert tactics.winning_moves(gs) == []


# --------------------------------------------------------------------------
# Vérification complète et mesure de l'IA (lents)
# --------------------------------------------------------------------------
@pytest.mark.slow
@pytest.mark.parametrize("tactic", SUITE, ids=_ids(SUITE))
def test_full_verification(tactic: tactics.Tactic) -> None:
    """Mats : bm = tous les coups qui matent en dm. Gains : bm unique gagnant ≥ un cavalier."""
    assert tactics.verify_tactic(tactic, full=True) == []


def _chess_mates_within(board: "chess.Board", n: int) -> bool:
    """Solveur de mat indépendant, sur python-chess (contrôle croisé du nôtre)."""
    for move in list(board.legal_moves):
        board.push(move)
        try:
            if board.is_checkmate():
                return True
            if n > 1 and not board.is_game_over(claim_draw=False) and board.legal_moves:
                if all(_reply_loses(board, reply, n - 1) for reply in list(board.legal_moves)):
                    return True
        finally:
            board.pop()
    return False


def _reply_loses(board: "chess.Board", reply: "chess.Move", n: int) -> bool:
    board.push(reply)
    try:
        return _chess_mates_within(board, n)
    finally:
        board.pop()


@pytest.mark.slow
@needs_chess
@pytest.mark.parametrize("tactic", LONGER_MATES, ids=_ids(LONGER_MATES))
def test_mates_cross_checked_with_python_chess(tactic: tactics.Tactic) -> None:
    board = chess.Board(tactic.fen + " 0 1")
    assert tactic.mate_in is not None
    assert not _chess_mates_within(board, tactic.mate_in - 1)
    for san in tactic.best_moves:
        board.push_san(san)
        try:
            assert all(
                _reply_loses(board, reply, tactic.mate_in - 1) for reply in list(board.legal_moves)
            )
        finally:
            board.pop()


@pytest.mark.slow
def test_current_ai_score() -> None:
    """Score de l'IA actuelle à profondeur 3, par UCI : affiché, sans seuil (seuil en J3.5)."""
    start = time.monotonic()
    results = tactics.run_suite(SUITE, depth=3)
    print("\n" + tactics.format_results(results))
    print(f"(durée {time.monotonic() - start:.1f} s)")
    assert len(results) == len(SUITE)
    assert all(r.played for r in results)  # Le moteur a toujours répondu
