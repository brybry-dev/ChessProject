"""Mode problèmes (J13.3) : série, solutions uniques vérifiées, parcours sans écran.

- la série : positions à solution unique de la suite tactique, de la plus courte à la
  plus longue ; score (réussi du premier coup sans aide) ;
- chaque solution est **unique** (solveur exhaustif de ``tools/tactics.py``) et
  **trouvée par le moteur du jeu** (recherche complète, sans élagage, à la profondeur
  du mat annoncé : le mat est trouvé exactement à cette distance) ;
- un parcours complet de la série sans écran (pilote SDL « dummy »), au clavier et à
  la souris : coup faux repris, indice, solution, coup juste, problème suivant, fin de
  série et nouvelle série.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as p

try:
    p.init()
    p.display.set_mode((1280, 800))
    _PYGAME_OK = True
except Exception:  # pragma: no cover - environnement sans SDL
    _PYGAME_OK = False

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import tactics

from chessproject import paths
from chessproject.ai import search
from chessproject.core import notation, puzzles
from chessproject.core.engine import GameState
from chessproject.settings import Settings
from chessproject.ui import app, overlays
from chessproject.ui.board_view import PieceSet
from chessproject.ui.new_game import PUZZLE, NewGameMenu, config_from

SERIES = puzzles.series(paths.TACTICS_FILE)
PIECES: PieceSet = PieceSet() if _PYGAME_OK else None  # type: ignore[assignment]


def _ids(items: list[puzzles.Puzzle]) -> list[str]:
    return [puzzle.name for puzzle in items]


def _event(kind, **data):
    return p.event.Event(kind, data)


# --------------------------------------------------------------------------
# La série
# --------------------------------------------------------------------------
def test_series_holds_every_single_solution_position() -> None:
    suite = tactics.load_suite()
    assert len(SERIES) >= 35
    assert {pz.name for pz in SERIES} == {t.name for t in suite if len(t.best_moves) == 1}
    assert all(len(pz.best_moves) == 1 for pz in SERIES)
    # Des plus courts aux plus longs : mats en 1, gains de matériel, mats en 2 puis en 3.
    kinds = [pz.mate_in or 1.5 for pz in SERIES]
    assert kinds == sorted(kinds)
    assert kinds[0] == 1 and kinds[-1] == 3


def test_side_to_move_and_position() -> None:
    black = next(pz for pz in SERIES if pz.name == "mate1.back-rank-black")
    assert not black.white_to_move
    assert not black.game_state().white_to_move
    assert SERIES[0].white_to_move


SOLVER_SLOW = [pz for pz in SERIES if pz.mate_in == 3]
SOLVER_FAST = [pz for pz in SERIES if pz.mate_in != 3]


def _assert_unique_and_found_by_the_engine(puzzle: puzzles.Puzzle) -> None:
    # Solution unique : bm = tous les coups qui matent en dm (et pas de mat plus court),
    # ou l'unique coup qui gagne au moins un cavalier.
    assert tactics.verify_tactic(puzzle, full=True) == []
    # Le moteur du jeu, sans élagage, trouve ce coup ; pour un mat, exactement à la
    # distance annoncée (2 × dm - 1 demi-coups).
    gs = puzzle.game_state()
    depth = 2 * puzzle.mate_in - 1 if puzzle.mate_in else 4
    found = search.Searcher(features=search.NO_FEATURES).think(gs, search.SearchLimits(depth=depth))
    assert found.move is not None
    assert notation.to_san(gs, found.move) == puzzle.best_moves[0]
    if puzzle.mate_in:
        assert search.MATE - found.score == depth


@pytest.mark.parametrize("puzzle", SOLVER_FAST, ids=_ids(SOLVER_FAST))
def test_solution_is_unique_and_found_by_the_engine(puzzle: puzzles.Puzzle) -> None:
    _assert_unique_and_found_by_the_engine(puzzle)


@pytest.mark.slow
@pytest.mark.parametrize("puzzle", SOLVER_SLOW, ids=_ids(SOLVER_SLOW))
def test_mate_in_three_is_unique_and_found_by_the_engine(puzzle: puzzles.Puzzle) -> None:
    _assert_unique_and_found_by_the_engine(puzzle)


# --------------------------------------------------------------------------
# Déroulement et score
# --------------------------------------------------------------------------
class RunTests(unittest.TestCase):
    def setUp(self):
        self.series = puzzles.PuzzleRun(SERIES[:4])

    def _move(self, san):
        gs = self.series.position()
        return gs, notation.parse_san(gs, san)

    def _wrong_move(self):
        gs = self.series.position()
        solution = self.series.solution_move(gs)
        return gs, next(m for m in gs.get_valid_moves() if m != solution)

    def test_found_at_the_first_try_counts(self):
        self.assertTrue(self.series.answer(*self._move(self.series.solution)))
        self.assertTrue(self.series.solved and self.series.finished)
        self.assertEqual((self.series.score, self.series.done), (1, 1))
        with self.assertRaises(ValueError):
            self.series.answer(*self._move(self.series.solution))

    def test_a_wrong_try_hint_or_solution_does_not_count(self):
        self.assertFalse(self.series.answer(*self._wrong_move()))
        self.assertFalse(self.series.finished)
        self.assertTrue(self.series.answer(*self._move(self.series.solution)))
        self.assertTrue(self.series.next())
        self.series.hint()
        self.assertTrue(self.series.answer(*self._move(self.series.solution)))
        self.assertTrue(self.series.next())
        self.series.show_solution()
        self.assertTrue(self.series.finished and not self.series.solved)
        self.assertTrue(self.series.answer(*self._move(self.series.solution)))  # jouable ensuite
        self.assertEqual((self.series.score, self.series.done), (0, 3))

    def test_skipped_puzzles_are_failed_and_the_series_ends(self):
        self.assertTrue(self.series.next())
        self.assertEqual(self.series.results, [False])
        self.assertEqual(self.series.index, 1)
        self.assertFalse(self.series.hint_used or self.series.solution_shown or self.series.solved)
        self.series.answer(*self._move(self.series.solution))
        self.assertTrue(self.series.next())
        self.assertTrue(self.series.next())
        self.assertTrue(self.series.is_last)
        self.assertFalse(self.series.next())
        self.assertEqual(self.series.results, [False, True, False, False])
        with self.assertRaises(ValueError):
            puzzles.PuzzleRun([])


def test_epd_round_trip_and_errors() -> None:
    line = 'k7/8/2K5/8/8/8/8/7R w - - bm Kc7 Kb6; dm 2; id "x y";'
    assert puzzles.format_epd(puzzles.parse_epd_line(line)) == line
    with pytest.raises(ValueError):
        puzzles.parse_epd_line('k7/8/2K5/8/8/8/8/7R w - - id "sans bm";')


# --------------------------------------------------------------------------
# Parcours sans écran
# --------------------------------------------------------------------------
@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class PuzzleModeTests(unittest.TestCase):
    def setUp(self):
        self.screen = p.display.get_surface()
        # Dossier de données temporaire : les préférences du joueur ne sont pas touchées.
        data = tempfile.TemporaryDirectory()
        self.addCleanup(data.cleanup)
        self.enterContext(mock.patch.dict(os.environ, {"CHESSPROJECT_DATA_DIR": data.name}))
        self.app = app.App(self.screen, Settings(mode=PUZZLE), PIECES)
        self.app.step()
        self.app.handle_event(_event(p.KEYDOWN, key=p.K_RETURN))  # Commencer
        scene = self.app.scene
        assert isinstance(scene, app.GameController)
        self.gc = scene

    def _key(self, key, **data):
        self.app.handle_event(_event(p.KEYDOWN, key=key, **data))
        self.app.step()

    def _type(self, text):
        self._key(p.K_RETURN)
        for char in text:
            self.app.handle_event(_event(p.TEXTINPUT, text=char))
        self._key(p.K_RETURN)

    def _click(self, rect):
        self.app.handle_event(_event(p.MOUSEBUTTONDOWN, pos=rect.center, button=1))
        self.app.handle_event(_event(p.MOUSEBUTTONUP, pos=rect.center, button=1))
        self.app.step()

    def _panel_button(self, action):
        return next(b for b in self.gc.panel.puzzle_actions if b.action == action)

    def _square(self, square):
        return self.gc.renderer.square_rect(*square)

    def test_menu_offers_puzzles(self):
        menu = NewGameMenu(Settings(mode=PUZZLE), can_cancel=False, pieces=PIECES)
        menu.draw(self.screen, app.th.theme("sombre"), (0, 0), 0)
        self.assertIn(str(len(SERIES)), menu.summary())
        config = config_from(Settings(mode=PUZZLE))
        self.assertTrue(config.human_white and config.human_black)
        self.assertTrue(config.time_control.is_unlimited)
        cadences = [
            b
            for b in menu.buttons
            if isinstance(b.action, tuple) and b.action[:2] == ("choose", "time_control")
        ]
        self.assertEqual(cadences, [])  # sans pendule

    def test_first_puzzle_wrong_move_hint_then_solution(self):
        gc = self.gc
        run = gc.puzzles
        assert run is not None
        self.assertEqual(gc.game_state.board, SERIES[0].game_state().board)
        self.assertEqual(gc.mode, "PvP")
        self.assertTrue(gc.chess_clock.is_unlimited)
        self.assertEqual(gc._status(), ("Les blancs jouent et matent en 1 coup", "info"))
        self.assertIn("Problèmes · 1 / ", gc._info_text())
        # L'évaluation trahirait la solution : cachée jusqu'à la fin du problème.
        self.assertIsNone(gc._panel_model(gc.game_state).eval_text)
        # Coup faux, à la souris : la pièce revient, rien n'est joué.
        solution = run.solution_move(gc.game_state)
        wrong = next(m for m in gc.valid_moves if m != solution)
        self._click(self._square((wrong.start_row, wrong.start_col)))
        self._click(self._square((wrong.end_row, wrong.end_col)))
        self.assertEqual(gc.game_state.move_log, [])
        self.assertEqual(gc._status()[1], "warning")
        self.assertEqual(run.wrong_tries, 1)
        # Indice : la pièce à jouer est marquée.
        self._click(self._panel_button("hint").rect)
        self.assertEqual(gc.marks, {(solution.start_row, solution.start_col)})
        # Coup juste, à la souris : joué, problème résolu, pas de carte de fin de partie.
        self._click(self._square((solution.start_row, solution.start_col)))
        self._click(self._square((solution.end_row, solution.end_col)))
        self.assertEqual(gc.game_state.move_log, [solution])
        self.assertTrue(run.solved)
        self.assertTrue(gc.game_over)  # mat
        self.assertIsNone(gc.overlay)
        self.assertEqual(gc._status(), ("Bien joué ! N : problème suivant", "accent"))
        self.assertIsNotNone(gc._panel_model(gc.game_state).eval_text)
        self.assertFalse(self._panel_button("hint").enabled)
        self.assertEqual((run.score, run.done), (0, 1))  # avec un essai faux et l'indice
        # Problème suivant au bouton du panneau.
        self._click(self._panel_button("puzzle_next").rect)
        self.assertEqual(run.index, 1)
        self.assertEqual(gc.game_state.board, SERIES[1].game_state().board)
        self.assertEqual(gc.renderer.flip_board, not SERIES[1].white_to_move)

    def test_solution_is_shown_then_playable(self):
        gc = self.gc
        run = gc.puzzles
        assert run is not None
        self._key(p.K_o)
        move = run.solution_move(gc.game_state)
        self.assertIn(((move.start_row, move.start_col), (move.end_row, move.end_col)), gc.arrows)
        self.assertTrue(gc._status()[0].startswith("Solution : " + run.solution))
        self._type(run.solution)
        self.assertEqual(gc.game_state.move_log, [move])
        self.assertEqual(run.results, [False])

    def test_game_keys_do_nothing_and_leaving_the_series(self):
        gc = self.gc
        for key in (p.K_z, p.K_a, p.K_r):
            self._key(key)
        self.assertIsNone(gc.overlay)
        self.assertIsNotNone(gc.puzzles)
        # Une nouvelle partie quitte le mode problèmes.
        new_game = next(b for b in gc.header.buttons if b.action == "new_game")
        self._click(new_game.rect)
        menu = self.app.scene
        assert isinstance(menu, NewGameMenu)
        self.assertEqual(menu.settings.mode, PUZZLE)  # choix mémorisé
        self._click(next(b for b in menu.buttons if b.action == ("choose", "mode", "PvP")).rect)
        self._key(p.K_RETURN)
        self.assertIs(self.app.scene, gc)
        self.assertIsNone(gc.puzzles)
        self.assertEqual(gc.game_state.board, GameState().board)

    def test_whole_series_without_a_screen(self):
        """Toute la série au clavier : la solution tapée, puis N ; un problème sur trois
        avec un coup faux d'abord (il ne compte pas) ; fin de série, puis nouvelle série."""
        gc = self.gc
        run = gc.puzzles
        assert run is not None
        missed = 0
        for index, puzzle in enumerate(SERIES):
            with self.subTest(puzzle=puzzle.name):
                self.assertEqual(run.current, puzzle)
                self.assertEqual(gc.game_state.board, puzzle.game_state().board)
                if index % 3 == 0:
                    solution = run.solution_move(gc.game_state)
                    wrong = next(m for m in gc.valid_moves if m != solution)
                    self._type(notation.to_san(gc.game_state, wrong))
                    self.assertEqual(gc.game_state.move_log, [])
                    missed += 1
                self._type(puzzle.best_moves[0])
                self.assertTrue(run.solved)
                self.assertEqual(notation.san_history(gc.game_state), list(puzzle.best_moves))
                self.assertIsNone(gc.overlay)
                gc.draw()
                self._key(p.K_n)
        end = gc.overlay
        assert isinstance(end, overlays.ConfirmOverlay)
        self.assertEqual(end.title, "Série terminée")
        self.assertIn(f"{len(SERIES) - missed} problèmes réussis sur {len(SERIES)}", end.message)
        self.assertEqual((run.score, run.done), (len(SERIES) - missed, len(SERIES)))
        self._key(p.K_RETURN)  # Recommencer
        self.assertIsNone(gc.overlay)
        again = gc.puzzles
        assert again is not None and again is not run
        self.assertEqual((again.index, again.done), (0, 0))
        self.assertEqual(gc.game_state.board, SERIES[0].game_state().board)
