"""Tests différentiels du moteur contre python-chess (J2.1).

Des parties aléatoires (graine fixe) sont jouées en parallèle par notre moteur et
par python-chess. À chaque demi-coup, on compare l'ensemble des coups légaux et
le statut de la position (mat, pat, nulles automatiques). C'est le filet de
sécurité des refactors du moteur (J2.3, J2.4, J3.1) : le perft compte des nœuds,
ce test compare des coups et des fins de partie, position par position.

python-chess n'est qu'une dépendance de développement ; sans lui, ces tests
sont ignorés.
"""

import random
import unittest
from unittest import mock

import pytest

import ChessEngine
from fen_utils import load_fen

try:
    import chess

    _CHESS_OK = True
except ImportError:  # pragma: no cover - dépendance de développement absente
    _CHESS_OK = False

FILES = "abcdefgh"

START_FENS = [
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    # Kiwipete : roques, clouages, promotions, en passant
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    # Position 3 du Chess Programming Wiki : en passant avec échec à la découverte
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
    # Position 4 : promotions et roques, Blancs en difficulté
    "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
    # Finale de pions : promotions et sous-promotions fréquentes
    "8/PPP4k/8/8/8/8/4Kppp/8 w - - 0 1",
]


def _square(row: int, col: int) -> str:
    return f"{FILES[col]}{8 - row}"


def _uci(move) -> str:
    promo = (move.promotion_piece or "").lower() if move.is_pawn_promotion else ""
    return _square(move.start_row, move.start_col) + _square(move.end_row, move.end_col) + promo


def _our_draw_reason(gs) -> str | None:
    """Motif de nulle automatique retenu par notre moteur (cf. get_valid_moves)."""
    if gs.fifty_move_counter >= 100:
        return "fifty"
    if gs.insufficient_material():
        return "material"
    if gs.position_history.get(gs.get_board_hash_str(), 0) >= 3:
        return "repetition"
    return None


class _MismatchError(AssertionError):
    pass


def _play_random_game(fen: str, seed: int, max_plies: int) -> int:
    """Joue une partie aléatoire et compare chaque position. Renvoie le nombre de positions."""
    rng = random.Random(seed)
    ours = load_fen(fen)
    ref = chess.Board(fen)
    history: list[str] = []
    for ply in range(max_plies + 1):
        context = f"FEN de départ {fen!r}, graine {seed}, coups {' '.join(history)}"
        moves = ours.get_valid_moves()
        reason = _our_draw_reason(ours)

        if reason is not None:
            # Nulle automatique chez nous : python-chess doit la reconnaître.
            expected = {
                "fifty": ref.halfmove_clock >= 100,
                "material": ref.is_insufficient_material(),
                "repetition": ref.is_repetition(3),
            }[reason]
            if not expected:
                raise _MismatchError(
                    f"nulle « {reason} » non reconnue par python-chess ; {context}"
                )
            return ply + 1

        ours_uci = {_uci(m) for m in moves}
        ref_uci = {m.uci() for m in ref.legal_moves}
        if ours_uci != ref_uci:
            raise _MismatchError(
                f"coups légaux différents : en trop {sorted(ours_uci - ref_uci)}, "
                f"manquants {sorted(ref_uci - ours_uci)} ; FEN {ref.fen()} ; {context}"
            )
        if ours.in_check != ref.is_check():
            raise _MismatchError(
                f"échec : nous {ours.in_check}, référence {ref.is_check()}; {context}"
            )
        if not moves:
            if ours.checkmate != ref.is_checkmate() or ours.stalemate != ref.is_stalemate():
                raise _MismatchError(f"fin de partie divergente ; FEN {ref.fen()} ; {context}")
            return ply + 1
        if ply == max_plies:
            return ply + 1

        move = rng.choice(sorted(moves, key=_uci))
        history.append(_uci(move))
        ours.make_move(move, validate=False)
        ref.push(chess.Move.from_uci(_uci(move)))
    return max_plies + 1


def _run(test: unittest.TestCase, games_per_fen: int, max_plies: int) -> None:
    positions = 0
    for fen_index, fen in enumerate(START_FENS):
        for game in range(games_per_fen):
            seed = 1000 * fen_index + game
            with test.subTest(fen=fen, seed=seed):
                positions += _play_random_game(fen, seed, max_plies)
    test.assertGreater(positions, games_per_fen * len(START_FENS))


@unittest.skipUnless(_CHESS_OK, "python-chess non installé")
class DifferentialTests(unittest.TestCase):
    def test_random_games_match_python_chess(self):
        _run(self, games_per_fen=10, max_plies=120)

    @pytest.mark.slow
    def test_many_random_games_match_python_chess(self):
        # 1 000 parties au total, jusqu'à 300 demi-coups : finales, 50 coups, répétitions.
        _run(self, games_per_fen=200, max_plies=300)


@unittest.skipUnless(_CHESS_OK, "python-chess non installé")
class DifferentialHarnessTests(unittest.TestCase):
    """Le banc lui-même doit détecter une divergence."""

    def test_a_missing_legal_move_is_reported(self):
        # Moteur saboté (plus de roques) : Kiwipete autorise le roque d'emblée.
        no_castling = mock.patch.object(ChessEngine.GameState, "get_castle_moves", lambda *a: None)
        with no_castling, self.assertRaises(_MismatchError):
            _play_random_game(START_FENS[1], seed=0, max_plies=1)


if __name__ == "__main__":
    unittest.main()
