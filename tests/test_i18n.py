"""Version anglaise (J11.3) : catalogue complet et écrans dessinés sans un mot de français.

Deux contrôles complémentaires :

- **statique** : chaque texte passé à ``tr`` / ``plural``, chaque libellé de bouton et
  chaque table affichée (raccourcis, options, niveaux, cadences, motifs de fin, noms
  d'ouvertures…) a sa traduction ;
- **au rendu** : en anglais, chaque écran et chaque fenêtre est dessiné dans plusieurs
  états, et tous les textes effectivement rendus (``Font.render``) sont relevés ; aucun
  ne doit contenir de français.
"""

import ast
import os
import queue
import re
import string
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as p

try:
    p.init()
    p.display.set_mode((1280, 800))
    _PYGAME_OK = True
except Exception:  # pragma: no cover - environnement sans SDL
    _PYGAME_OK = False

from chessproject import i18n, paths
from chessproject import settings as settings_module
from chessproject.ai import levels, review
from chessproject.core import clock, engine, notation
from chessproject.core.fen import load_fen
from chessproject.i18n import EN, tr
from chessproject.settings import Settings
from chessproject.ui import app, files, new_game, overlays, theme
from chessproject.ui.board_view import PieceSet

PIECES: PieceSet = PieceSet() if _PYGAME_OK else None  # type: ignore[assignment]
UI_DIR = Path(app.__file__).parent

# Mots et lettres qui trahissent un texte resté en français.
FRENCH = re.compile(
    r"[éèêàçùœ]|\b(de|du|des|la|le|les|une?|à|aux?|pour|partie|coups?|blancs|noirs|joueur"
    r"|niveau|sans|avec|vous|sur|réfléchit|nulle|échec|annuler|fermer|charger)\b",
    re.IGNORECASE,
)
# Textes légitimes malgré tout : le nom de la langue française dans le sélecteur.
NOT_FRENCH = {"Français"}


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


class CatalogTests(unittest.TestCase):
    def test_every_translation_keeps_the_same_fields(self):
        for french, english in EN.items():
            with self.subTest(french=french):
                self.assertEqual(_fields(french), _fields(english))

    def test_every_literal_passed_to_tr_is_translated(self):
        missing = []
        for path in [*UI_DIR.glob("*.py"), Path(i18n.__file__)]:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                    continue
                if node.func.id not in ("tr", "plural"):
                    continue
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if arg.value not in EN:
                            missing.append(f"{path.name}:{node.lineno} {arg.value!r}")
        self.assertEqual(missing, [])

    def test_every_button_label_hint_and_tooltip_is_translated(self):
        exempt = {"ChessProject", *i18n.LANGUAGE_NAMES.values()}
        missing = []
        for path in UI_DIR.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name != "Button":
                    continue
                texts = [a for a in node.args[1:2]]
                texts += [k.value for k in node.keywords if k.arg in ("label", "hint", "tooltip")]
                for arg in texts:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        value = arg.value
                        if len(value) > 1 and value not in EN and value not in exempt:
                            missing.append(f"{path.name}:{node.lineno} {value!r}")
        self.assertEqual(missing, [])

    def test_displayed_tables_are_translated(self):
        tables = {
            "raccourcis": [t for pair in overlays.SHORTCUTS for t in pair if len(t) > 1],
            "options": [label for _, label in overlays.TOGGLES],
            "modes": [label for _, label in new_game.MODES],
            "couleurs": [label for _, label in new_game.COLORS],
            "niveaux": [level.name for level in levels.LEVELS],
            "forces": list(new_game.LEVEL_HINTS.values()),
            "échiquiers": list(theme.PALETTES),
            "bilan": list(review.LABELS.values()),
            "dossiers": [label for label, _ in paths.places()],
            "cadences": [c.name.split(" ")[0] for c in clock.PRESETS if not c.is_unlimited],
        }
        for table, texts in tables.items():
            for text in texts:
                if any(c.isalpha() for c in text):  # « ← → » n'a rien à traduire
                    with self.subTest(table=table, text=text):
                        self.assertTrue(text in EN, text)

    def test_every_game_result_is_translated(self):
        results = [engine.GameResult()]
        for termination in engine.Termination:
            for winner in (None, engine.Color.WHITE, engine.Color.BLACK):
                result = engine.GameResult(termination, winner)
                try:
                    result.description  # noqa: B018 - motif impossible pour ce vainqueur
                except KeyError:
                    continue
                results.append(result)
        for result in results:
            with self.subTest(description=result.description):
                self.assertTrue(result.description in EN, result.description)

    def test_every_opening_name_has_an_english_name(self):
        i18n.set_language("en")
        self.addCleanup(i18n.set_language, "fr")
        source = paths.ASSETS_DIR / "openings.tsv"
        names = {
            line.split("\t")[1].strip()
            for line in source.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
        self.assertGreater(len(names), 200)
        missing = sorted(n for n in names if i18n.opening_name(n) == n)
        self.assertEqual(missing, [])
        self.assertEqual(
            i18n.opening_name("Défense sicilienne : variante Najdorf"),
            "Sicilian Defense: Najdorf Variation",
        )


class HelperTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("fr")

    def test_french_by_default_and_english_on_demand(self):
        self.assertEqual(tr("Nouvelle partie"), "Nouvelle partie")
        i18n.set_language("en")
        self.assertEqual(tr("Nouvelle partie"), "New game")
        self.assertEqual(tr("Indice : {san}", san="Nf3"), "Hint: Nf3")
        self.assertEqual(tr("Z"), "Z", "texte hors catalogue rendu tel quel")
        i18n.set_language("xx")
        self.assertEqual(i18n.language(), "fr", "langue inconnue : français")

    def test_one_french_word_with_two_meanings(self):
        self.assertEqual(tr("Annuler|coup"), "Annuler")
        i18n.set_language("en")
        self.assertEqual(tr("Annuler|coup"), "Undo")
        self.assertEqual(tr("Annuler"), "Cancel")

    def test_plural_and_decimals_follow_the_language(self):
        self.assertEqual(i18n.plural(1, "{n} coup", "{n} coups"), "1 coup")
        self.assertEqual(i18n.plural(0, "{n} coup", "{n} coups"), "0 coup")
        self.assertEqual(app.eval_text(43), "+0,4")
        i18n.set_language("en")
        self.assertEqual(i18n.plural(0, "{n} coup", "{n} coups"), "0 moves")
        self.assertEqual(i18n.plural(1, "{n} coup", "{n} coups"), "1 move")
        self.assertEqual(app.eval_text(43), "+0.4")
        self.assertEqual(app.eval_text(-120), "−1.2")
        self.assertEqual(app.control_name(clock.RAPID_10_5), "Rapid 10+5")
        self.assertEqual(app.control_name(clock.UNLIMITED), "Unlimited")

    def test_system_language_on_first_launch(self):
        for value, expected in (("fr_FR.UTF-8", "fr"), ("en_GB.UTF-8", "en"), ("de_DE", "en")):
            env = {"LC_ALL": value, "LC_MESSAGES": "", "LANG": "", "LANGUAGE": ""}
            with mock.patch.dict(os.environ, env):
                self.assertEqual(i18n.system_language(), expected)

    def test_language_is_a_setting(self):
        self.assertEqual(settings_module.from_dict({"language": "en"}).language, "en")
        self.assertEqual(settings_module.from_dict({"language": "xx"}).language, "fr")


class _RecordingFont:
    """Police qui relève chaque texte rendu (délègue tout le reste)."""

    def __init__(self, font, seen):
        self._font, self._seen = font, seen

    def render(self, text, *args, **kwargs):
        self._seen.append(text)
        return self._font.render(text, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._font, name)


class _InlineProcess:
    """Faux multiprocessing.Process : exécute la cible immédiatement."""

    def __init__(self, target, args=(), **kwargs):
        self._target, self._args = target, args
        self.exitcode = None

    def start(self):
        self._target(*self._args)
        self.exitcode = 0

    def is_alive(self):
        return False

    def terminate(self):
        pass


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class EnglishScreensTests(unittest.TestCase):
    """Chaque écran, dessiné en anglais, ne rend aucun texte français."""

    def setUp(self):
        i18n.set_language("en")
        self.addCleanup(i18n.set_language, "fr")
        self.data = tempfile.TemporaryDirectory()
        self.addCleanup(self.data.cleanup)
        patcher = mock.patch.dict(os.environ, {"CHESSPROJECT_DATA_DIR": self.data.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.seen: list[str] = []
        real_font = theme.font
        font_patch = mock.patch.object(
            theme, "font", side_effect=lambda *a, **k: _RecordingFont(real_font(*a, **k), self.seen)
        )
        font_patch.start()
        self.addCleanup(font_patch.stop)
        self.screen = p.display.get_surface()

    def _controller(self, mode="PvC", white=True, black=False, **kwargs):
        gc = app.GameController(
            self.screen,
            p.time.Clock(),
            app.UIManager(),
            PIECES,
            mode,
            white,
            black,
            False,
            settings=Settings(language="en"),
            **kwargs,
        )
        gc.reviewer = review.Reviewer(process=_InlineProcess, make_queue=queue.Queue, nodes=500)
        return gc

    def _draw(self, gc):
        gc.update()
        for name in ("sombre", "clair"):
            gc.settings = Settings(theme=name, language="en", show_analysis=False)
            gc.draw()

    def _play(self, gc, *sans):
        for san in sans:
            gc.game_state.make_move(notation.parse_san(gc.game_state, san))
        gc.move_made = True

    def assert_no_french(self):
        french = sorted({t for t in self.seen if FRENCH.search(t) and t not in NOT_FRENCH})
        self.assertEqual(french, [], "textes restés en français")
        self.assertTrue(self.seen, "aucun texte relevé")

    def test_new_game_screen(self):
        for mode in ("PvC", "PvP", "CvC", "Puzzle"):
            for color in ("w", "r", "b"):
                menu = new_game.NewGameMenu(
                    Settings(mode=mode, color=color, language="en", time_control="600+5"),
                    can_cancel=True,
                    pieces=PIECES,
                )
                menu.draw(self.screen, theme.theme("sombre"), (0, 0), 0)
                self.seen.append(menu.summary())
        self.assertIn("You play White against the Medium AI, 10+5 time control.", self.seen)
        self.assert_no_french()

    def test_game_screen_in_every_state(self):
        gc = self._controller(time_control=clock.BLITZ_3_2, level="Débutant")
        self._draw(gc)  # « Your move »
        self._play(gc, "e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4", "Nf6", "Nc3", "a6")
        self._draw(gc)  # ouverture nommée, historique
        self.assertIn("B90 · Sicilian Defense: Najdorf Variation", self.seen)
        gc._navigate("prev")
        self._draw(gc)  # revue
        gc._navigate("last")
        gc._open_move_input()
        gc.move_input, gc.move_input_error = "Qh5", "Illegal move: Qh5"
        self._draw(gc)
        gc._close_move_input()
        gc.move_input = ""
        self._draw(gc)  # aide de la saisie
        gc._close_move_input()
        gc.ai_thinking = True
        self._draw(gc)  # « The AI is thinking » + carte « thinking »
        gc.ai_thinking = False
        for state in (
            "Aucun coup à analyser",
            "L'IA refuse la nulle : elle estime sa position meilleure",
        ):
            gc._notify(tr(state))
            self._draw(gc)
        pvp = self._controller("PvP", True, True)
        self._play(pvp, "f3", "e5")
        pvp.draw_offer = (engine.Color.BLACK, 1)
        self._draw(pvp)  # proposition de nulle
        self._play(pvp, "g4")
        self._draw(pvp)
        cvc = self._controller("CvC", False, False)
        cvc.ai_thinking = True
        cvc.draw()
        self.assert_no_french()

    def test_puzzle_screens(self):
        """J13.3 : consigne, coup faux, indice, solution, problème résolu, fin de série."""
        gc = self._controller("PvP", True, True)
        gc.start_puzzles()
        self._draw(gc)
        self.assertIn("White to play and mate in 1", self.seen)
        run = gc.puzzles
        solution = run.solution_move(gc.game_state)
        wrong = next(m for m in gc.valid_moves if m != solution)
        gc._play(wrong, False)
        self._draw(gc)
        gc._hint()
        self._draw(gc)
        gc._play(solution, False)
        self._draw(gc)
        gc._puzzle_next()
        gc._puzzle_solution()
        gc.notice = None
        self._draw(gc)
        while run.next():
            pass
        gc._load_puzzle(run)
        gc._play(run.solution_move(gc.game_state), False)
        self._draw(gc)
        gc._puzzle_next()
        self._draw(gc)
        self.assertIn("0 puzzles solved out of 39.", self.seen)  # tous sautés
        self.assert_no_french()

    def test_overlays(self):
        gc = self._controller()
        self._play(gc, "e4", "e5")
        gc.update()
        for opener in (
            lambda: gc._open(app.ShortcutsOverlay()),
            lambda: gc._open(app.AppearanceOverlay(gc.settings)),
            gc._ask_restart,
            gc._ask_resign,
            gc._save,
            gc._export_pgn,
            gc._import_pgn,
        ):
            opener()
            gc.draw()
            gc.overlay = None
        gc._save_to(paths.saves_dir() / "game.json")
        gc._load()
        gc.draw()
        gc.handle_event(p.event.Event(p.KEYDOWN, {"key": p.K_DELETE}))
        gc.draw()  # confirmation de suppression
        gc.overlay = None
        gc._save()
        gc.overlay.name = "game"
        gc.handle_event(p.event.Event(p.KEYDOWN, {"key": p.K_RETURN}))
        gc.draw()  # confirmation de remplacement
        gc.overlay = None
        empty = Path(self.data.name) / "empty"
        empty.mkdir()
        dialog = files.FileDialog("import", "open", tr("Importer un PGN"), empty, ".pgn")
        gc._open(dialog)
        gc.handle_event(p.event.Event(p.KEYDOWN, {"key": p.K_RETURN}))
        gc.draw()  # « Choose a file », dossier vide
        gc.overlay = None
        source = Path(self.data.name) / "club.pgn"
        source.write_text(
            '[White "A"]\n[Black "B"]\n[Event "Club"]\n\n1. e4 *\n\n'
            '[White "C"]\n[Black "D"]\n\n1. d4 d5 *\n',
            encoding="utf-8",
        )
        gc._import_from(source)
        gc.draw()
        self.assertIn("club.pgn contains 2 games.", self.seen)
        gc.overlay = None
        self.assert_no_french()

    def test_end_of_game_review_and_promotion(self):
        gc = self._controller("PvC", True, False)
        self._play(gc, "f3", "e5", "g4", "Qh4#")
        gc.update()
        gc.draw()  # carte de fin : « Defeat »
        self.assertIn("Black wins by checkmate · 0-1 · 2 moves", self.seen)
        gc.overlay = None
        gc._open_review()
        gc.draw()  # bilan en cours
        gc.update()
        gc.draw()  # bilan terminé
        gc.overlay = None
        draw = self._controller("PvP", True, True)
        draw._new_game(load_fen("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"))
        draw.update()
        draw.draw()  # pat
        promo = self._controller("PvP", True, True)
        promo._new_game(load_fen("7k/P7/8/8/8/8/8/K7 w - - 0 1"))
        promo._try_move((1, 0), (0, 0), animate=False)
        promo.draw()
        self.assert_no_french()

    def test_exported_pgn_is_in_english(self):
        gc = self._controller()
        self._play(gc, "e4", "c5")
        target = Path(self.data.name) / "game.pgn"
        gc._export_to(target)
        text = target.read_text(encoding="utf-8")
        self.assertIn('[Event "ChessProject game"]', text)
        self.assertIn('[White "Human"]', text)
        self.assertIn('[Black "ChessProject (Medium)"]', text)
        self.assertIn('[Opening "Sicilian Defense"]', text)


@unittest.skipUnless(_PYGAME_OK, "SDL indisponible")
class LanguageChoiceTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(i18n.set_language, "fr")
        self.saved: list[Settings] = []
        patcher = mock.patch.object(app.settings_module, "save", side_effect=self.saved.append)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = app.App(p.display.get_surface(), Settings(language="fr"), PIECES)

    def _click(self, pos):
        self.app.handle_event(p.event.Event(p.MOUSEBUTTONDOWN, {"pos": pos, "button": 1}))

    def test_choice_on_the_new_game_screen(self):
        self.app.step()
        menu = self.app.scene
        assert isinstance(menu, new_game.NewGameMenu)
        english = next(b for b in menu.buttons if b.action == ("language", "en"))
        self._click(english.rect.center)
        self.assertEqual(i18n.language(), "en")
        self.assertEqual(self.saved[-1].language, "en", "choix mémorisé")
        self.app.step()
        self.app.handle_event(p.event.Event(p.KEYDOWN, {"key": p.K_RETURN}))
        game = self.app.scene
        assert isinstance(game, app.GameController)
        self.assertEqual(game.settings.language, "en")

    def test_choice_in_the_appearance_window(self):
        self.app.handle_event(p.event.Event(p.KEYDOWN, {"key": p.K_RETURN}))
        game = self.app.scene
        assert isinstance(game, app.GameController)
        game.handle_event(p.event.Event(p.KEYDOWN, {"key": p.K_c}))
        game.draw()
        overlay = game.overlay
        assert overlay is not None
        english = next(b for b in overlay.buttons if b.action == ("setting", "language", "en"))
        game.handle_event(
            p.event.Event(p.MOUSEBUTTONDOWN, {"pos": english.rect.center, "button": 1})
        )
        self.assertEqual(i18n.language(), "en")
        self.assertEqual(self.saved[-1].language, "en")
        self.assertEqual(game._info_text(), "Player vs AI · Medium level · Blitz 5+0")


if __name__ == "__main__":
    unittest.main()
