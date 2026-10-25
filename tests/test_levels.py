"""Tests des niveaux de difficulté (J3.7)."""

import random
import time
import unittest
from unittest import mock

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
                assert weaker.max_nodes is not None and stronger.max_nodes is not None
                self.assertLess(weaker.max_nodes, stronger.max_nodes)
                self.assertLessEqual(weaker.book_plies, stronger.book_plies)

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

    def test_movetime_cap_shortens_the_search(self):
        # Expert réfléchit 3 s ; plafonné à 50 ms par la cadence, il répond vite.
        gs = load_fen("r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3")
        start = time.monotonic()
        move = levels.choose_move(gs, levels.LEVELS_BY_NAME["Expert"], movetime_ms=50)
        self.assertIn(move, gs.get_valid_moves())
        self.assertLess(time.monotonic() - start, 1.0)

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


class NodeBudgetTests(unittest.TestCase):
    def test_node_budget_bounds_the_search(self):
        # Sans bruit, choose_move joue le coup d'une recherche bornée au même budget.
        gs = load_fen("r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3")
        level = levels.Level("Test", 60_000, search.MAX_PLY, 0, 0.0, 1, max_nodes=800)
        expected = search.think(gs, SearchLimits(movetime_ms=60_000, nodes=800)).move
        self.assertEqual(levels.choose_move(gs, level), expected)

    def test_node_budget_makes_the_choice_independent_of_the_clock(self):
        # Même budget, même graine : même coup, quelle que soit la vitesse de la machine.
        gs = engine.GameState()
        level = levels.Level("Test", 60_000, search.MAX_PLY, 60, 0.2, 3, max_nodes=600)
        moves = {levels.choose_move(gs, level, random.Random(5)) for _ in range(3)}
        self.assertEqual(len(moves), 1)

    def test_noise_reevaluation_stays_within_the_node_budget(self):
        # Régression (calibration J8.1) : sans profondeur maximale, une finale simple est
        # explorée très profond en peu de nœuds, et la réévaluation bruitée des coups à
        # cette profondeur n'était pas bornée (plus de 120 s pour un coup).
        gs = load_fen("8/8/4k3/8/8/4K3/4P3/8 w - - 0 1")
        level = levels.Level("Test", 60_000, search.MAX_PLY, 30, 0.0, 1, max_nodes=400)
        ticks = 0
        original = search.Searcher._tick

        def counting_tick(searcher):
            nonlocal ticks
            ticks += 1
            original(searcher)

        with mock.patch.object(search.Searcher, "_tick", counting_tick):
            move = levels.choose_move(gs, level, random.Random(0), use_book=False)
        self.assertIn(move, gs.get_valid_moves())
        self.assertLessEqual(ticks, 2 * 400 + 1)

    def test_noise_reevaluation_respects_the_time_cap(self):
        gs = load_fen("8/8/4k3/8/8/4K3/4P3/8 w - - 0 1")
        level = levels.Level("Test", 200, search.MAX_PLY, 30, 0.0, 1)
        start = time.monotonic()
        move = levels.choose_move(gs, level, random.Random(0), use_book=False)
        self.assertIn(move, gs.get_valid_moves())
        self.assertLess(time.monotonic() - start, 1.0)


class LevelSpecTests(unittest.TestCase):
    def test_base_level_without_overrides(self):
        self.assertEqual(levels.parse_level_spec("base=Facile"), levels.LEVELS_BY_NAME["Facile"])

    def test_overrides_replace_the_base_values(self):
        level = levels.parse_level_spec("base=Moyen, nodes=4000, noise=40, mistake=0.05")
        base = levels.LEVELS_BY_NAME["Moyen"]
        self.assertEqual(level.name, "Moyen*")
        self.assertEqual(
            (level.max_nodes, level.eval_noise_cp, level.mistake_probability),
            (4000, 40, 0.05),
        )
        self.assertEqual((level.movetime_ms, level.max_depth), (base.movetime_ms, base.max_depth))

    def test_name_and_nodes_zero(self):
        level = levels.parse_level_spec("name=Essai,nodes=0,depth=4")
        self.assertEqual((level.name, level.max_nodes, level.max_depth), ("Essai", None, 4))

    def test_invalid_specs_are_rejected(self):
        for spec in (
            "vitesse=3",
            "nodes",
            "nodes=",
            "base=Inconnu",
            "noise=-5",
            "mistake=1.5",
            "depth=0",
            "nodes=beaucoup",
        ):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                levels.parse_level_spec(spec)


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
