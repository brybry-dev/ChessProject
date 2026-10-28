"""
Écran « Nouvelle partie » (J5.1)
-------------------------------
Un seul écran remplace les trois menus successifs (mode, niveau, cadence) : mode
de jeu, couleur, niveau de l'IA et cadence, modifiables avant de commencer. Les
choix sont mémorisés dans les préférences pour la partie suivante.
"""

import random
from dataclasses import dataclass, replace

import pygame as p

from chessproject import i18n
from chessproject.ai import levels
from chessproject.core import clock
from chessproject.i18n import tr
from chessproject.settings import Settings
from chessproject.ui import theme as th
from chessproject.ui import widgets as w
from chessproject.ui.theme import Theme

MODES = [("PvC", "Joueur vs IA"), ("PvP", "Joueur vs Joueur"), ("CvC", "IA vs IA")]
COLORS = [("w", "Blancs"), ("r", "Au hasard"), ("b", "Noirs")]
LEVEL_HINTS = {
    "Débutant": "pour débuter",
    "Facile": "imprécis",
    "Moyen": "solide",
    "Difficile": "précis",
    "Expert": "pleine force",
}


@dataclass(frozen=True)
class GameConfig:
    """Réglages d'une partie, tels que choisis dans l'écran « Nouvelle partie »."""

    mode: str
    human_white: bool
    human_black: bool
    level: str
    time_control: clock.TimeControl

    @property
    def flip_board(self) -> bool:
        """Contre l'IA avec les noirs : l'échiquier est vu du côté noir."""
        return self.mode == "PvC" and not self.human_white


def config_from(settings: Settings, rng: random.Random | None = None) -> GameConfig:
    """Partie décrite par les choix mémorisés (couleur « au hasard » tirée ici)."""
    mode = settings.mode
    if mode == "PvP":
        white, black = True, True
    elif mode == "CvC":
        white, black = False, False
    else:
        color = settings.color
        if color == "r":
            color = (rng or random.Random()).choice("wb")
        white, black = color == "w", color == "b"
    return GameConfig(mode, white, black, settings.level, settings.control)


def _strength_label(level: levels.Level) -> str:
    """Force du niveau (« ≈ 1450 Elo », J8.2), ou à défaut son temps de réflexion."""
    if level.elo is not None:
        return tr("≈ {elo} Elo", elo=level.elo)
    return tr("{seconds} s", seconds=i18n.decimal(level.movetime_ms / 1000, -1))


class NewGameMenu:
    """Scène de configuration. ``handle_event`` renvoie ``("start", GameConfig)``,
    ``"load"``, ``"import"``, ``"cancel"``, ``("language", code)`` ou None."""

    def __init__(self, settings: Settings, can_cancel: bool, pieces) -> None:
        self.settings = settings
        self.can_cancel = can_cancel
        self.pieces = pieces
        self.buttons: list[w.Button] = []

    # -- état ------------------------------------------------------------
    def choose(self, field: str, value) -> None:
        self.settings = replace(self.settings, **{field: value})

    def config(self, rng: random.Random | None = None) -> GameConfig:
        return config_from(self.settings, rng)

    def summary(self) -> str:
        s = self.settings
        control = s.control
        if control.is_unlimited:
            cadence = tr("sans pendule")
        else:
            cadence = tr("cadence {control}", control=control.label)
        level = tr(s.level)
        if s.mode == "PvP":
            return tr("Deux joueurs sur le même écran, {cadence}.", cadence=cadence)
        if s.mode == "CvC":
            return tr(
                "L'IA {level} joue contre elle-même, {cadence}.", level=level, cadence=cadence
            )
        color = {"w": "les blancs", "b": "les noirs", "r": "une couleur tirée au sort"}[s.color]
        return tr(
            "Vous jouez " + color + " contre l'IA {level}, {cadence}.", level=level, cadence=cadence
        )

    # -- événements ------------------------------------------------------
    def handle_event(self, e: p.event.Event):
        if e.type == p.KEYDOWN:
            if e.key in (p.K_RETURN, p.K_KP_ENTER):
                return ("start", self.config())
            if e.key == p.K_ESCAPE and self.can_cancel:
                return "cancel"
            if e.key == p.K_l:
                return "load"
            if e.key == p.K_i:
                return "import"
            return None
        if e.type == p.MOUSEBUTTONDOWN and e.button == 1:
            button = w.hovered_button(self.buttons, e.pos)
            if button is None:
                return None
            action = button.action
            if isinstance(action, tuple) and action[0] == "choose":
                self.choose(action[1], action[2])
                return None
            if isinstance(action, tuple) and action[0] == "language":
                return action
            if action == "start":
                return ("start", self.config())
            return action
        return None

    # -- dessin ----------------------------------------------------------
    def draw(self, surface: p.Surface, t: Theme, mouse: tuple[int, int], now_ms: int) -> None:
        s = self.settings
        surface.fill(t.bg)
        width = min(940, surface.get_width() - 48)
        card = p.Rect(0, 0, width, 590)
        card.center = surface.get_rect().center
        card.y = max(16, card.y)
        w.shadow(surface, card, 16, 30)
        w.rounded(surface, t.surface, card, 16)
        w.rounded(surface, t.border, card, 16, 1)

        x, inner = card.x + 40, card.width - 80
        y = card.y + 34
        logo = self.pieces.get_image("wN", 44)
        surface.blit(logo, (x, y))
        w.text(surface, tr("Nouvelle partie"), th.font(24, "semibold"), t.text, (x + 58, y - 2))
        w.text(
            surface,
            tr("Tous les réglages sur un seul écran, modifiables avant de commencer."),
            th.font(14),
            t.muted,
            (x + 58, y + 30),
        )
        y += 76
        label = th.font(12, "semibold")
        buttons: list[w.Button] = []

        w.text(surface, tr("MODE"), label, t.muted, (x, y))
        y += 24
        third = (inner - 20) // 3
        for i, (value, text) in enumerate(MODES):
            b = w.Button(
                ("choose", "mode", value), text, variant="choice", selected=s.mode == value
            )
            b.rect = p.Rect(x + i * (third + 10), y, third, 52)
            buttons.append(b)
        y += 52 + 26

        decorations: list[tuple[str, object]] = []
        color_w = min(300, (inner - 28) * 2 // 5)
        level_x = x
        if s.mode == "PvC":
            w.text(surface, tr("VOUS JOUEZ"), label, t.muted, (x, y))
            cw = (color_w - 20) // 3
            for i, (value, text) in enumerate(COLORS):
                b = w.Button(
                    ("choose", "color", value), variant="choice", selected=s.color == value
                )
                b.rect = p.Rect(x + i * (cw + 10), y + 24, cw, 92)
                buttons.append(b)
                decorations.append(("color", (b.rect, value, text)))
            level_x = x + color_w + 28
        if s.mode != "PvP":
            level_w = x + inner - level_x
            w.text(surface, tr("NIVEAU DE L'IA"), label, t.muted, (level_x, y))
            lw = (level_w - 4 * 8) // 5
            for i, level in enumerate(levels.LEVELS):
                b = w.Button(
                    ("choose", "level", level.name),
                    variant="choice",
                    selected=s.level == level.name,
                )
                b.rect = p.Rect(level_x + i * (lw + 8), y + 24, lw, 92)
                buttons.append(b)
                decorations.append(("level", (b.rect, i, level)))
        else:
            box = p.Rect(x, y + 24, inner, 92)
            w.rounded(surface, t.surface2, box, 10)
            w.text(
                surface,
                tr("Deux joueurs se partagent l'écran : l'échiquier reste côté blancs."),
                th.font(14),
                t.muted,
                box.center,
                "center",
            )
        y += 24 + 92 + 26

        w.text(surface, tr("CADENCE"), label, t.muted, (x, y))
        y += 24
        sixth = (inner - 5 * 8) // 6
        current = s.control
        for i, control in enumerate(clock.PRESETS):
            b = w.Button(
                ("choose", "time_control", control.pgn_tag),
                variant="choice",
                selected=current == control,
            )
            b.rect = p.Rect(x + i * (sixth + 8), y, sixth, 64)
            buttons.append(b)
            decorations.append(("cadence", (b.rect, control)))
        y += 64 + 26

        p.draw.line(surface, t.border, (x, y), (x + inner, y))
        y += 22
        start = w.Button("start", "Commencer", variant="primary", hint="Entrée")
        start.rect = p.Rect(0, y, 170, 44)
        start.rect.right = x + inner
        imp = w.Button("import", "Importer un PGN")
        imp.rect = p.Rect(0, y, 160, 44)
        imp.rect.right = start.rect.left - 10
        load = w.Button("load", "Charger une partie")
        load.rect = p.Rect(0, y, 170, 44)
        load.rect.right = imp.rect.left - 10
        buttons += [load, imp, start]
        right = card.right - 24
        if self.can_cancel:
            back = w.Button("cancel", "Retour à la partie", variant="ghost")
            back.rect = p.Rect(card.x + 24, card.y + 20, 170, 40)
            back.rect.right = right
            buttons.append(back)
            right = back.rect.left - 8
        # Langue (J11.3) : chaque langue est nommée dans sa langue.
        for code in reversed(i18n.LANGUAGES):
            b = w.Button(
                ("language", code),
                i18n.LANGUAGE_NAMES[code],
                variant="choice",
                selected=s.language == code,
            )
            b.rect = p.Rect(0, card.y + 20, 96, 40)
            b.rect.right = right
            right = b.rect.left - 6
            buttons.append(b)
        summary_w = load.rect.left - x - 16
        f = th.font(14)
        lines = w.wrap(self.summary(), f, summary_w)[:2]
        for i, line in enumerate(lines):
            w.text(
                surface,
                line,
                f,
                t.muted,
                (x, start.rect.centery + round((i - (len(lines) - 1) / 2) * 20)),
                "midleft",
            )

        self.buttons = buttons
        w.draw_buttons(surface, t, buttons, mouse)
        for kind, data in decorations:
            self._decorate(surface, t, kind, data)

    def _decorate(self, surface, t: Theme, kind: str, data) -> None:
        if kind == "color":
            rect, value, text = data
            if value == "r":
                glyph = p.Rect(0, 0, 40, 40)
                glyph.center = (rect.centerx, rect.y + 34)
                w.rounded(surface, t.border, glyph, 20, 2)
                w.text(surface, "?", th.font(22, "semibold"), t.muted, glyph.center, "center")
            else:
                image = self.pieces.get_image(value + "K", 44)
                surface.blit(image, image.get_rect(center=(rect.centerx, rect.y + 34)))
            w.text(
                surface,
                tr(text),
                th.font(14, "medium"),
                t.text,
                (rect.centerx, rect.bottom - 12),
                "midbottom",
            )
        elif kind == "level":
            rect, index, level = data
            for k in range(5):
                bar = p.Rect(rect.x + 12 + k * 13, rect.y + 14, 10, 4)
                w.rounded(surface, t.accent_ink if k <= index else t.border, bar, 2)
            name_font = th.font(15 if rect.width > 96 else 13, "semibold")
            w.text(
                surface,
                w.ellipsize(tr(level.name), name_font, rect.width - 20),
                name_font,
                t.text,
                (rect.x + 12, rect.y + 26),
            )
            f = th.font(12)
            hint = tr(LEVEL_HINTS.get(level.name, ""))
            w.text(
                surface,
                w.ellipsize(hint, f, rect.width - 20),
                f,
                t.muted,
                (rect.x + 12, rect.y + 50),
            )
            w.text(
                surface,
                _strength_label(level),
                th.font(11, "medium", mono=True),
                t.muted,
                (rect.x + 12, rect.bottom - 10),
                "bottomleft",
            )
        elif kind == "cadence":
            rect, control = data
            value = "∞" if control.is_unlimited else control.label
            name = tr(control.name.split(" ")[0] if not control.is_unlimited else "Sans limite")
            w.text(
                surface,
                value,
                th.font(17, "semibold", mono=True),
                t.text,
                (rect.centerx, rect.centery - 9),
                "center",
            )
            w.text(surface, name, th.font(12), t.muted, (rect.centerx, rect.centery + 13), "center")
