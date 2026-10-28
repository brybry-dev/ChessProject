"""
Fenêtres superposées (J5.1)
---------------------------
Raccourcis, apparence, confirmation, fin de partie et choix de promotion. Une
fenêtre superposée reçoit les événements tant qu'elle est ouverte ; elle renvoie une
action (chaîne ou tuple) que le contrôleur exécute, ou ``"close"``. Les fenêtres
modales suspendent la pendule (``pauses_clock``).
"""

from collections.abc import Callable, Sequence

import pygame as p

from chessproject import i18n
from chessproject.ai import review
from chessproject.i18n import tr
from chessproject.settings import Settings
from chessproject.ui import theme as th
from chessproject.ui import widgets as w
from chessproject.ui.theme import Theme

SHORTCUTS: list[tuple[str, str]] = [
    ("Entrée", "Taper un coup (e4, Nf3, O-O)"),
    ("Z", "Annuler le dernier coup"),
    ("N", "Proposer / accepter la nulle"),
    ("A", "Abandonner"),
    ("R", "Rejouer avec les mêmes réglages"),
    ("S", "Sauvegarder la partie"),
    ("L", "Charger une sauvegarde"),
    ("E", "Exporter en PGN"),
    ("I", "Importer un PGN"),
    ("F", "Retourner l'échiquier"),
    ("C", "Apparence"),
    ("V", "Afficher la variante principale"),
    ("B", "Indice : meilleur coup en flèche"),
    ("G", "Bilan de la partie"),
    ("H", "Afficher les raccourcis"),
    ("← →", "Coup précédent / suivant"),
    ("Orig. Fin", "Début / position actuelle"),
    ("Échap", "Annuler la sélection, fermer"),
    ("Clic droit", "Flèche (glisser) ou marque"),
]


class Overlay:
    pauses_clock = True

    def __init__(self) -> None:
        self.buttons: list[w.Button] = []
        self.card = p.Rect(0, 0, 0, 0)

    def handle_event(self, e: p.event.Event):
        if e.type == p.KEYDOWN and e.key == p.K_ESCAPE:
            return "close"
        if e.type == p.MOUSEBUTTONDOWN and e.button == 1:
            button = w.hovered_button(self.buttons, e.pos)
            if button is not None:
                return button.action
            if not self.card.collidepoint(e.pos):
                return "close"
        return None

    def draw(self, surface: p.Surface, t: Theme, mouse: tuple[int, int], now_ms: int) -> None:
        raise NotImplementedError

    def _frame(self, surface: p.Surface, t: Theme, size: tuple[int, int]) -> p.Rect:
        """Voile sur la fenêtre et carte centrée de taille ``size``."""
        w.translucent(surface, t.scrim, surface.get_rect())
        self.card = p.Rect(0, 0, *size)
        self.card.center = surface.get_rect().center
        w.shadow(surface, self.card, 14, 28)
        w.rounded(surface, t.surface, self.card, 14)
        w.rounded(surface, t.border, self.card, 14, 1)
        return self.card

    def _title(self, surface, t: Theme, title: str, subtitle: str | None = None) -> int:
        y = self.card.y + 28
        w.text(surface, title, th.font(22, "semibold"), t.text, (self.card.x + 32, y))
        y += 34
        if subtitle:
            for line in w.wrap(subtitle, th.font(14), self.card.width - 64):
                w.text(surface, line, th.font(14), t.muted, (self.card.x + 32, y))
                y += 20
        return y + 12


def _close_button(card: p.Rect) -> w.Button:
    button = w.Button("close", icon="close", variant="ghost")
    button.rect = p.Rect(card.right - 56, card.y + 16, 44, 44)
    return button


# --------------------------------------------------------------------------
class ShortcutsOverlay(Overlay):
    def handle_event(self, e):
        if e.type == p.KEYDOWN and e.key in (p.K_h, p.K_RETURN):
            return "close"
        return super().handle_event(e)

    def draw(self, surface, t, mouse, now_ms):
        rows = (len(SHORTCUTS) + 1) // 2
        width = min(820, surface.get_width() - 48)
        self._frame(surface, t, (width, 158 + rows * 40))
        y0 = self._title(surface, t, tr("Raccourcis clavier"))
        col_w = (self.card.width - 64 - 24) // 2
        kbd_font = th.font(13, "medium", mono=True)
        for i, (keys, label) in enumerate(SHORTCUTS):
            keys, label = tr(keys), tr(label)
            x = self.card.x + 32 + (i // rows) * (col_w + 24)
            y = y0 + (i % rows) * 40
            chip_w = max(36, kbd_font.size(keys)[0] + 16)
            chip = p.Rect(x, y, chip_w, 28)
            w.rounded(surface, t.surface2, chip, 6)
            w.rounded(surface, t.border, chip, 6, 1)
            w.text(surface, keys, kbd_font, t.text, chip.center, "center")
            f = th.font(14)
            w.text(
                surface,
                w.ellipsize(label, f, col_w - chip_w - 14),
                f,
                t.text,
                (chip.right + 14, chip.centery),
                "midleft",
            )
        close = w.Button("close", "Fermer", variant="primary")
        close.rect = p.Rect(0, 0, 120, 44)
        close.rect.bottomright = (self.card.right - 32, self.card.bottom - 24)
        self.buttons = [close, _close_button(self.card)]
        w.draw_buttons(surface, t, self.buttons, mouse)


# --------------------------------------------------------------------------
TOGGLES: list[tuple[str, str]] = [
    ("show_eval", "Barre d'évaluation"),
    ("show_analysis", "Variante principale (analyse)"),
    ("hints_vs_ai", "Indices contre l'IA"),
    ("show_coordinates", "Coordonnées sur l'échiquier"),
    ("show_legal_moves", "Coups possibles de la pièce choisie"),
    ("sound", "Sons"),
]


class AppearanceOverlay(Overlay):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings

    def handle_event(self, e):
        if e.type == p.KEYDOWN and e.key in (p.K_c, p.K_RETURN):
            return "close"
        return super().handle_event(e)

    def draw(self, surface, t, mouse, now_ms):
        s = self.settings
        self._frame(surface, t, (560, 620))
        y = self._title(surface, t, tr("Apparence"))
        x = self.card.x + 32
        inner = self.card.width - 64
        label_font = th.font(12, "semibold")
        buttons: list[w.Button] = []

        half = (inner - 10) // 2
        w.text(surface, tr("THÈME"), label_font, t.muted, (x, y))
        w.text(surface, tr("LANGUE"), label_font, t.muted, (x + half + 10, y))
        y += 24
        quarter = (half - 10) // 2
        for i, (value, label) in enumerate((("sombre", "Sombre"), ("clair", "Clair"))):
            b = w.Button(
                ("setting", "theme", value), label, variant="choice", selected=s.theme == value
            )
            b.rect = p.Rect(x + i * (quarter + 10), y, quarter, 48)
            buttons.append(b)
        # Chaque langue est nommée dans sa langue (J11.3).
        for i, code in enumerate(i18n.LANGUAGES):
            b = w.Button(
                ("setting", "language", code),
                i18n.LANGUAGE_NAMES[code],
                variant="choice",
                selected=s.language == code,
            )
            b.rect = p.Rect(x + half + 10 + i * (quarter + 10), y, quarter, 48)
            buttons.append(b)
        y += 48 + 24

        w.text(surface, tr("ÉCHIQUIER"), label_font, t.muted, (x, y))
        y += 24
        quarter = (inner - 30) // 4
        swatches = []
        for i, palette in enumerate(th.PALETTES.values()):
            b = w.Button(
                ("setting", "board", palette.name),
                variant="choice",
                selected=s.board == palette.name,
            )
            b.rect = p.Rect(x + i * (quarter + 10), y, quarter, 92)
            buttons.append(b)
            swatches.append((b.rect, palette))
        y += 92 + 24

        w.text(surface, tr("AFFICHAGE"), label_font, t.muted, (x, y))
        y += 20
        toggles = []
        for name, label in TOGGLES:
            b = w.Button(("setting", name, not getattr(s, name)), variant="ghost")
            b.rect = p.Rect(x - 8, y, inner + 16, 40)
            buttons.append(b)
            toggles.append((b.rect, tr(label), bool(getattr(s, name))))
            y += 40

        close = _close_button(self.card)
        buttons.append(close)
        self.buttons = buttons
        w.draw_buttons(surface, t, buttons, mouse)
        for rect, palette in swatches:
            board = p.Rect(0, 0, 44, 44)
            board.midtop = (rect.centerx, rect.y + 12)
            for r in range(2):
                for c in range(2):
                    color = palette.light if (r + c) % 2 == 0 else palette.dark
                    p.draw.rect(surface, color, (board.x + c * 22, board.y + r * 22, 22, 22))
            w.text(
                surface,
                tr(palette.name),
                th.font(13, "medium"),
                t.text,
                (rect.centerx, rect.bottom - 12),
                "midbottom",
            )
        for rect, label, on in toggles:
            w.text(surface, label, th.font(14), t.text, (rect.x + 8, rect.centery), "midleft")
            switch = p.Rect(0, 0, 40, 22)
            switch.midright = (rect.right - 8, rect.centery)
            w.rounded(surface, t.accent_ink if on else t.surface2, switch, 11)
            if not on:
                w.rounded(surface, t.border, switch, 11, 1)
            knob_x = switch.right - 11 if on else switch.x + 11
            p.draw.circle(surface, t.on_accent if on else t.muted, (knob_x, switch.centery), 7)


# --------------------------------------------------------------------------
class ConfirmOverlay(Overlay):
    def __init__(self, title: str, message: str, confirm_label: str, action) -> None:
        super().__init__()
        self.title, self.message = title, message
        self.confirm_label, self.action = confirm_label, action

    def handle_event(self, e):
        if e.type == p.KEYDOWN and e.key in (p.K_RETURN, p.K_KP_ENTER):
            return self.action
        return super().handle_event(e)

    def draw(self, surface, t, mouse, now_ms):
        self._frame(surface, t, (460, 210))
        self._title(surface, t, self.title, self.message)
        confirm = w.Button(self.action, self.confirm_label, variant="primary", hint="Entrée")
        confirm.rect = p.Rect(0, 0, 190, 44)
        confirm.rect.bottomright = (self.card.right - 32, self.card.bottom - 24)
        cancel = w.Button("close", "Annuler")
        cancel.rect = p.Rect(0, 0, 120, 44)
        cancel.rect.bottomright = (confirm.rect.left - 10, confirm.rect.bottom)
        self.buttons = [confirm, cancel]
        w.draw_buttons(surface, t, self.buttons, mouse)


# --------------------------------------------------------------------------
class EndGameOverlay(Overlay):
    """Carte de fin de partie : vainqueur, motif et suites possibles."""

    pauses_clock = False

    def __init__(
        self, title: str, subtitle: str, piece: str | None, pieces, description: str = ""
    ) -> None:
        super().__init__()
        self.title, self.subtitle, self.piece, self.pieces = title, subtitle, piece, pieces
        self.description = description  # motif de fin seul (``GameResult.description``)

    def handle_event(self, e):
        if e.type == p.KEYDOWN and e.key == p.K_ESCAPE:
            return "review"
        if e.type == p.KEYDOWN and e.key in (p.K_RETURN, p.K_KP_ENTER):
            return "rematch"
        action = super().handle_event(e)
        return "review" if action == "close" else action

    def draw(self, surface, t, mouse, now_ms):
        width = 380
        lines = w.wrap(self.subtitle, th.font(14), width - 48)
        # Hauteur suivant le texte : pièce, titre, motif sur une ou plusieurs lignes, boutons.
        height = 28 + 66 + 34 + 20 * len(lines) + 18 + 3 * 44 + 2 * 8 + 24
        card = self._frame(surface, t, (width, height))
        y = card.y + 28
        if self.piece:
            image = self.pieces.get_image(self.piece, 56)
            surface.blit(image, image.get_rect(midtop=(card.centerx, y)))
        y += 66
        w.text(surface, self.title, th.font(22, "semibold"), t.text, (card.centerx, y), "midtop")
        y += 34
        for line in lines:
            w.text(surface, line, th.font(14), t.muted, (card.centerx, y), "midtop")
            y += 20
        inner = card.width - 48
        rematch = w.Button("rematch", "Rejouer", variant="primary", hint="Entrée")
        rematch.rect = p.Rect(card.x + 24, card.bottom - 24 - 44 - 8 - 44 - 8 - 44, inner, 44)
        half = (inner - 8) // 2
        review = w.Button("review", "Revoir la partie")
        review.rect = p.Rect(card.x + 24, rematch.rect.bottom + 8, half, 44)
        export = w.Button("export", "Exporter PGN")
        export.rect = p.Rect(review.rect.right + 8, review.rect.y, half, 44)
        bilan = w.Button("game_review", "Bilan", hint="G")
        bilan.rect = p.Rect(card.x + 24, review.rect.bottom + 8, half, 44)
        new = w.Button("new_game", "Nouvelle partie", variant="ghost")
        new.rect = p.Rect(bilan.rect.right + 8, bilan.rect.y, half, 44)
        self.buttons = [rematch, review, export, bilan, new]
        w.draw_buttons(surface, t, self.buttons, mouse)


# --------------------------------------------------------------------------
class ReviewOverlay(Overlay):
    """Bilan de la partie (J9.3) : courbe d'évaluation (un clic montre la position) et,
    pour chaque camp, imprécisions, erreurs, gaffes et perte moyenne par coup."""

    def __init__(self, reviewer: review.Reviewer, eval_text: Callable[[int], str]) -> None:
        super().__init__()
        self.reviewer = reviewer
        self.eval_text = eval_text
        self.chart = p.Rect(0, 0, 0, 0)

    def ply_at(self, x: int) -> int:
        """Demi-coup le plus proche de l'abscisse ``x`` de la courbe."""
        last = max(1, self.reviewer.total - 1)
        share = (x - self.chart.x) / max(1, self.chart.width)
        return max(0, min(last, round(share * last)))

    def _point(self, ply: int, cp: int) -> tuple[int, int]:
        last = max(1, self.reviewer.total - 1)
        x = self.chart.x + round(self.chart.width * ply / last)
        y = self.chart.bottom - round(self.chart.height * review.expected_score(cp))
        return x, y

    def handle_event(self, e):
        if e.type == p.KEYDOWN and e.key in (p.K_g, p.K_RETURN):
            return "close"
        if e.type == p.MOUSEBUTTONDOWN and e.button == 1 and self.chart.collidepoint(e.pos):
            return ("review_goto", self.ply_at(e.pos[0]))
        return super().handle_event(e)

    def draw(self, surface, t, mouse, now_ms):
        width = min(720, surface.get_width() - 48)
        card = self._frame(surface, t, (width, 572))
        reviewer = self.reviewer
        result = reviewer.result()
        evaluated = len(reviewer.evals)
        if result is None:
            subtitle = tr(
                "Analyse des positions… {done} / {total}", done=evaluated, total=reviewer.total
            )
        else:
            subtitle = tr(
                "Survolez la courbe pour lire l'évaluation, cliquez pour voir la position."
            )
        y = self._title(surface, t, tr("Bilan de la partie"), subtitle)
        self.chart = p.Rect(card.x + 32, y + 26, card.width - 64, 180)
        self._draw_chart(surface, t, mouse, result)
        self._draw_summary(surface, t, self.chart.bottom + 28, result)
        close = w.Button("close", "Fermer", variant="primary")
        close.rect = p.Rect(0, 0, 120, 44)
        close.rect.bottomright = (card.right - 32, card.bottom - 24)
        self.buttons = [close, _close_button(card)]
        w.draw_buttons(surface, t, self.buttons, mouse)

    def _draw_chart(self, surface, t, mouse, result) -> None:
        chart = self.chart
        w.rounded(surface, th.EVAL_BLACK, chart, 6)
        evals = self.reviewer.evals
        if evals:
            points = [self._point(ply, cp) for ply, cp in enumerate(evals)]
            if len(points) == 1:
                points.append((chart.right, points[0][1]))
            area = [(points[0][0], chart.bottom), *points, (points[-1][0], chart.bottom)]
            p.draw.polygon(surface, th.EVAL_WHITE, area)
        p.draw.line(surface, t.accent, (chart.x, chart.centery), (chart.right - 1, chart.centery))
        w.rounded(surface, t.border, chart, 6, 1)
        if result is not None:
            for move in result.moves:
                if move.judgement:
                    color = th.JUDGEMENT_COLORS[move.judgement]
                    center = self._point(move.ply, result.evals[move.ply])
                    p.draw.circle(surface, th.JUDGEMENT_RING, center, 7)
                    p.draw.circle(surface, color, center, 5)
        if chart.collidepoint(mouse) and evals:
            ply = min(self.ply_at(mouse[0]), len(evals) - 1)
            x, y = self._point(ply, evals[ply])
            p.draw.line(surface, t.accent_ink, (x, chart.y), (x, chart.bottom - 1))
            p.draw.circle(surface, t.accent_ink, (x, y), 4)
            label = tr("Position de départ")
            if result is not None and ply > 0:
                move = result.moves[ply - 1]
                label = move.label + move.symbol
            elif ply > 0:
                label = tr("Demi-coup {n}", n=ply)
            text = f"{label} · {self.eval_text(evals[ply])}"
            w.text(
                surface, text, th.font(13, "medium"), t.text, (chart.x, chart.y - 8), "bottomleft"
            )

    def _draw_summary(self, surface, t, y: int, result) -> None:
        if result is None:
            return
        x = self.chart.x
        col = (self.chart.width - 200) // 2
        head = th.font(12, "semibold")
        w.text(surface, tr("BLANCS"), head, t.muted, (x + 200 + col // 2, y), "midtop")
        w.text(surface, tr("NOIRS"), head, t.muted, (x + 200 + col + col // 2, y), "midtop")
        y += 26
        rows: list[tuple[str, str | None, str, str]] = [
            (
                f"{tr(review.LABELS[kind])} {review.SYMBOLS[kind]}",
                kind,
                str(result.white.count(kind)),
                str(result.black.count(kind)),
            )
            for kind in (review.INACCURACY, review.MISTAKE, review.BLUNDER)
        ]
        rows.append(
            (tr("Perte moyenne (cp)"), None, str(result.white.acpl), str(result.black.acpl))
        )
        f = th.font(14)
        value_font = th.font(14, "semibold", mono=True)
        for label, kind, white, black in rows:
            if kind is not None:
                p.draw.circle(surface, th.JUDGEMENT_RING, (x + 5, y + 10), 7)
                p.draw.circle(surface, th.JUDGEMENT_COLORS[kind], (x + 5, y + 10), 5)
            w.text(surface, label, f, t.text, (x + 18, y + 10), "midleft")
            w.text(surface, white, value_font, t.text, (x + 200 + col // 2, y + 10), "center")
            w.text(surface, black, value_font, t.text, (x + 200 + col + col // 2, y + 10), "center")
            y += 30


# --------------------------------------------------------------------------
PROMOTION_KEYS = {
    p.K_q: "Q",
    p.K_d: "Q",  # dame
    p.K_r: "R",
    p.K_t: "R",  # tour
    p.K_b: "B",
    p.K_f: "B",  # fou
    p.K_n: "N",
    p.K_c: "N",  # cavalier
}


class PromotionPopup:
    """Choix de la pièce de promotion, ouvert sur la case d'arrivée : dame, tour, fou,
    cavalier, vers le centre de l'échiquier. Échap ou clic ailleurs : annulation."""

    pieces_order: Sequence[str] = ("Q", "R", "B", "N")

    def __init__(self, square_rect: p.Rect, downward: bool, color: str, pieces) -> None:
        self.color, self.pieces = color, pieces
        size = square_rect.width
        self.buttons: list[w.Button] = []
        for i, piece in enumerate(self.pieces_order):
            b = w.Button(piece, piece, variant="ghost")
            offset = i * size if downward else -i * size
            b.rect = p.Rect(square_rect.x, square_rect.y + offset, size, size)
            self.buttons.append(b)
        cancel_h = max(24, size // 3)
        last = self.buttons[-1].rect
        cancel_y = last.bottom if downward else last.y - cancel_h
        self.cancel = p.Rect(square_rect.x, cancel_y, size, cancel_h)
        self.rect = self.cancel.unionall([b.rect for b in self.buttons])

    def choice_for(self, e: p.event.Event) -> str | None:
        """Pièce choisie, ``"cancel"`` ou None (événement sans effet)."""
        if e.type == p.KEYDOWN:
            if e.key == p.K_ESCAPE:
                return "cancel"
            return PROMOTION_KEYS.get(e.key)
        if e.type == p.MOUSEBUTTONDOWN:
            for b in self.buttons:
                if b.rect.collidepoint(e.pos):
                    return b.label
            return "cancel"
        return None

    def draw(self, surface: p.Surface, t: Theme, mouse: tuple[int, int]) -> None:
        w.shadow(surface, self.rect, 8, 20)
        p.draw.rect(surface, th.PROMOTION_BG, self.rect, border_radius=8)
        for b in self.buttons:
            if b.rect.collidepoint(mouse):
                p.draw.rect(surface, th.PROMOTION_HOVER, b.rect, border_radius=6)
            image = self.pieces.get_image(self.color + b.label, int(b.rect.width * 0.86))
            surface.blit(image, image.get_rect(center=b.rect.center))
        hovered = self.cancel.collidepoint(mouse)
        p.draw.rect(
            surface,
            th.PROMOTION_CANCEL if not hovered else th.PROMOTION_CANCEL_HOVER,
            self.cancel,
            border_bottom_left_radius=8,
            border_bottom_right_radius=8,
        )
        w.text(
            surface,
            "×",
            th.font(18, "semibold"),
            th.PROMOTION_CANCEL_TEXT,
            self.cancel.center,
            "center",
        )
