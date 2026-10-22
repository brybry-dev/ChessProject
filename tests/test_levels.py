"""Tests des niveaux de difficulté (J3.7)."""

import random
import unittest

from chessproject.ai import levels, search
from chessproject.ai.search import SearchLimits
from chessproject.core import engine
from chessproject.core.fen import load_fen


class LevelDefinitionTests(unittest.TestCase):
    def test_levels_get_strictly_stronger(self):
        for weaker, stronger in zip(levels.LEVELS, levels.LEVELS[1:], strict=False):
            with self.subTest(weaker=weaker.name, stronger=stronger.name):
                self.assertLess(weaker.movetime_ms, stronger.movetime_ms)
                self.assertLessEqual(weaker.max_depth, stronger.max_depth)
                self.assertGreaterEqual(weaker.eval_noise_cp, stronger.eval_noise_cp)
                self.assertGreaterEqual(weaker.mistake_probability, stronger.mistake_probability)

    def test_five_named_levels_and_a_default(self):
        self.assertEqual(
            [level.name for level in levels.LEVELS],
            ["Débutant", "Facile", "Moyen", "Difficile", "Expert"],
        )
        self.assertIn(levels.DEFAULT_LEVEL, levels.LEVELS)


class ChooseMoveTests(unittest.TestCase):
    def test_every_level_returns_a_legal_move(self):
        gs = engine.GameState()
        for level in levels.LEVELS[:3]:
            with self.subTest(level=level.name):
                move = levels.choose_move(gs, level, random.Random(1))
                self.assertIn(move, gs.get_valid_moves())

    def test_noisy_level_works_when_the_search_uses_up_its_time(self):
        # Régression (CI Windows) : la réévaluation des coups après think() levait
        # SearchLimitError, la limite de temps de think() étant déjà dépassée.
        level = levels.Level("Pressé", 1, 5, 50, 0.0, 1)
        gs = engine.GameState()
        self.assertIn(levels.choose_move(gs, level, random.Random(0)), gs.get_valid_moves())

    def test_choice_is_reproducible_with_a_seed(self):
        gs = engine.GameState()
        level = levels.LEVELS_BY_NAME["Débutant"]
        first = levels.choose_move(gs, level, random.Random(7))
        second = levels.choose_move(gs, level, random.Random(7))
        self.assertEqual(first, second)

    def test_no_legal_move_gives_none(self):
        gs = load_fen("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")  # pat
        self.assertIsNone(levels.choose_move(gs, levels.LEVELS[0], random.Random(0)))

    def test_noise_free_level_plays_the_search_move(self):
        gs = load_fen("r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3")
        level = levels.Level("Test", 10_000, 2, 0, 0.0, 1)
        expected = search.think(gs, SearchLimits(depth=2)).move
        self.assertEqual(levels.choose_move(gs, level), expected)

    def test_even_the_weakest_level_takes_a_free_mate_in_one(self):
        # Le bruit ne touche pas les scores de mat : Qh7# (ou tout mat) est toujours joué.
        gs = load_fen("6k1/5ppp/8/8/8/8/5PPP/3Q2K1 w - - 0 1")
        rng = random.Random(3)
        for _ in range(5):
            move = levels.choose_move(gs, levels.LEVELS_BY_NAME["Facile"], rng)
            assert move is not None
            gs.make_move(move, validate=False)
            mated = gs.result().termination is engine.Termination.CHECKMATE
            gs.undo_move()
            if not mated:
                # Une « erreur » est possible, mais jamais un coup qui laisse mater.
                gs.make_move(move, validate=False)
                for reply in gs.get_valid_moves():
                    gs.make_move(reply, validate=False)
                    self.assertNotEqual(gs.result().termination, engine.Termination.CHECKMATE)
                    gs.undo_move()
                gs.undo_move()


class FindBestMoveWithLevelTests(unittest.TestCase):
    def test_level_name_is_used(self):
        class Box:
            def put(self, value):
                self.value = value

        box = Box()
        gs = engine.GameState()
        search.find_best_move(gs, gs.get_valid_moves(), box, level_name="Débutant")
        self.assertIn(box.value, gs.get_valid_moves())


if __name__ == "__main__":
    unittest.main()
