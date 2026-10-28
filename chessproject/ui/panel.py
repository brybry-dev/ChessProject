"""
En-tête et panneau latéral (J5.2 / J5.5)
---------------------------------------
L'en-tête porte les actions de partie (nouvelle partie, sauvegarde, PGN, apparence,
raccourcis). Le panneau latéral montre les deux joueurs (pendule, matériel pris),
l'historique SAN navigable, une ligne d'état et les actions de jeu.

Ces classes ne connaissent pas le contrôleur : elles dessinent un modèle
(:class:`PanelModel`) construit à chaque image et renvoient l'action cliquée.
"""

from dataclasses import dataclass, field

import pygame as p

from chessproject.i18n import tr
from chessproject.ui import theme as th
from chessproject.ui import widgets as w
from chessproject.ui.theme import Theme

TOOLTIP_DELAY_MS = 400


# --------------------------------------------------------------------------
# En-tête
# --------------------------------------------------------------------------
class Header:
    def __init__(self) -> None:
        self.buttons = [
            w.Button("new_game", "Nouvelle partie", icon="plus", variant="primary"),
            w.Button("save", icon="save", variant="ghost", tooltip="Sauvegarder (S)"),
            w.Button("load", icon="folder", variant="ghost", tooltip="Charger (L)"),
            w.Button("export", icon="download", variant="ghost", tooltip="Exporter en PGN (E)"),
            w.Button("import", icon="upload", variant="ghost", tooltip="Importer un PGN (I)"),
            w.Button("hint", icon="bulb", variant="ghost", tooltip="Indice (B)"),
            w.Button("flip", icon="flip", variant="ghost", tooltip="Retourner l'échiquier (F)"),
            w.Button("appearance", icon="contrast", variant="ghost", tooltip="Apparence (C)"),
            w.Button("shortcuts", icon="keyboard", variant="ghost", tooltip="Raccourcis (H)"),
        ]
        self._hover: w.Button | None = None
        self._hover_since = 0

    def layout(self, rect: p.Rect) -> None:
        x = rect.right - 16
        for button in reversed(self.buttons):
            if button.label:
                width = th.font(14, "semibold").size(tr(button.label))[0] + 50
                button.rect = p.Rect(0, 0, width, 38)
                x -= 12  # séparation avec les icônes
            else:
                button.rect = p.Rect(0, 0, 44, 44)
            button.rect.midright = (x, rect.centery)
            x = button.rect.left - 2

    def hit(self, pos: tuple[int, int]) -> str | None:
        button = w.hovered_button(self.buttons, pos)
        return str(button.action) if button else None

    def draw(
        self,
        surface: p.Surface,
        rect: p.Rect,
        t: Theme,
        logo: p.Surface,
        info: str,
        mouse: tuple[int, int],
        now_ms: int,
    ) -> None:
        self.layout(rect)
        p.draw.rect(surface, t.surface, rect)
        p.draw.line(surface, t.border, (rect.x, rect.bottom - 1), (rect.right, rect.bottom - 1))
        x = rect.x + 24
        surface.blit(logo, logo.get_rect(midleft=(x, rect.centery)))
        x += logo.get_width() + 10
        title = w.text(
            surface, "ChessProject", th.font(17, "semibold"), t.text, (x, rect.centery), "midleft"
        )
        limit = self.buttons[0].rect.left - title.right - 48
        if limit > 40:
            value = w.ellipsize(info, th.font(13), limit)
            w.text(
                surface, value, th.font(13), t.muted, (title.right + 24, rect.centery), "midleft"
            )
        w.draw_buttons(surface, t, self.buttons, mouse)
        self._draw_tooltip(surface, t, mouse, now_ms)

    def _draw_tooltip(self, surface: p.Surface, t: Theme, mouse, now_ms: int) -> None:
        hovered = w.hovered_button(self.buttons, mouse)
        if hovered is not self._hover:
            self._hover, self._hover_since = hovered, now_ms
        if hovered and hovered.tooltip and now_ms - self._hover_since >= TOOLTIP_DELAY_MS:
            w.tooltip(surface, t, hovered.tooltip, hovered.rect)


# --------------------------------------------------------------------------
# Panneau latéral
# --------------------------------------------------------------------------
@dataclass
class PlayerCard:
    name: str
    subtitle: str
    white: bool
    is_ai: bool
    clock: str | None  # None : pas de pendule affichée
    clock_state: str = "idle"  # idle, active, low, paused
    captured: list[str] = field(default_factory=list)  # pièces adverses prises
    advantage: int = 0  # avance matérielle (pions)
    thinking: bool = False
    highlighted: bool = False  # camp au trait


@dataclass
class MoveRow:
    number: int
    white: tuple[str, int] | None  # (SAN, demi-coup après ce coup)
    black: tuple[str, int] | None


@dataclass
class PanelModel:
    top: PlayerCard
    bottom: PlayerCard
    rows: list[MoveRow]
    current_ply: int  # position affichée (0 = position de départ)
    live_ply: int  # position réelle de la partie
    status: str
    status_kind: str = "info"  # info, accent, warning
    eval_text: str | None = None
    opening: str | None = None  # « ECO · nom » de l'ouverture (J8.3)
    # Analyse (J9.1) : (variante numérotée, « +0,4 · prof. 9 »), None si désactivée.
    analysis: tuple[str, str] | None = None
    can_undo: bool = True
    can_draw: bool = True
    can_resign: bool = True
    draw_label: str = "Nulle"
    # Coup tapé au clavier (J11.2) : (texte, erreur éventuelle), None si fermé.
    move_input: tuple[str, str | None] | None = None


ROW_HEIGHT = 34
OPENING_HEIGHT = 30
CARD_HEIGHT = 64
ACTIONS_HEIGHT = 44
GAP = 12


class SidePanel:
    def __init__(self) -> None:
        self.scroll = 0
        self.max_scroll = 0
        self._list_rect = p.Rect(0, 0, 0, 0)
        self._cells: list[tuple[p.Rect, int]] = []
        self._last_ply: int | None = None
        self.nav = [
            w.Button(("nav", "first"), icon="first", variant="ghost", tooltip="Début (Origine)"),
            w.Button(("nav", "prev"), icon="prev", variant="ghost", tooltip="Coup précédent (←)"),
            w.Button(("nav", "next"), icon="next", variant="ghost", tooltip="Coup suivant (→)"),
            w.Button(("nav", "last"), icon="last", variant="ghost", tooltip="Position actuelle"),
        ]
        self.actions = [
            w.Button("undo", "Annuler|coup", icon="undo", hint="Z"),
            w.Button("draw", "Nulle", icon="equal", hint="N"),
            w.Button("resign", "Abandonner", icon="flag", hint="A"),
        ]
        self._hover: w.Button | None = None
        self._hover_since = 0

    # -- interaction -----------------------------------------------------
    def hit(self, pos: tuple[int, int]):
        for button in (*self.nav, *self.actions):
            if button.hit(pos):
                return button.action
        if self._list_rect.collidepoint(pos):
            for rect, ply in self._cells:
                if rect.collidepoint(pos):
                    return ("goto", ply)
        return None

    def scroll_by(self, pos: tuple[int, int], dy: int) -> bool:
        if not self._list_rect.collidepoint(pos):
            return False
        self.scroll = max(0, min(self.max_scroll, self.scroll - dy * ROW_HEIGHT))
        return True

    # -- dessin ----------------------------------------------------------
    def draw(self, surface, rect: p.Rect, model: PanelModel, t: Theme, pieces, mouse, now_ms):
        top = p.Rect(rect.x, rect.y, rect.width, CARD_HEIGHT)
        actions = p.Rect(rect.x, rect.bottom - ACTIONS_HEIGHT, rect.width, ACTIONS_HEIGHT)
        bottom = p.Rect(rect.x, actions.y - GAP - CARD_HEIGHT, rect.width, CARD_HEIGHT)
        moves = p.Rect(rect.x, top.bottom + GAP, rect.width, bottom.y - GAP - top.bottom - GAP)
        self._draw_card(surface, top, model.top, t, pieces, now_ms)
        self._draw_moves(surface, moves, model, t, mouse)
        self._draw_card(surface, bottom, model.bottom, t, pieces, now_ms)
        self._draw_actions(surface, actions, model, t, mouse)
        hovered = w.hovered_button(self.nav, mouse)
        if hovered is not self._hover:
            self._hover, self._hover_since = hovered, now_ms
        if hovered and hovered.tooltip and now_ms - self._hover_since >= TOOLTIP_DELAY_MS:
            w.tooltip(surface, t, hovered.tooltip, hovered.rect)

    def _draw_card(self, surface, rect, card: PlayerCard, t: Theme, pieces, now_ms) -> None:
        w.rounded(surface, t.surface, rect, 10)
        w.rounded(surface, t.accent_ink if card.highlighted else t.border, rect, 10, 1)
        avatar = p.Rect(rect.x + 14, rect.centery - 20, 40, 40)
        tile = th.WHITE_PIECE_TILE if card.white else th.BLACK_PIECE_TILE
        w.rounded(surface, tile, avatar, 8)
        fg = th.BLACK_PIECE_TILE if card.white else th.WHITE_PIECE_TILE
        glyph = w.icon("cpu" if card.is_ai else "user", 22, fg, 1.8)
        surface.blit(glyph, glyph.get_rect(center=avatar.center))

        clock_rect = p.Rect(0, 0, 0, 0)
        if card.clock is not None:
            f = th.font(26 if rect.width >= 360 else 22, "semibold", mono=True)
            width = max(f.size(card.clock)[0] + 28, 108)
            clock_rect = p.Rect(0, 0, width, 44)
            clock_rect.midright = (rect.right - 12, rect.centery)
            bg, fg_clock = t.surface2, t.muted
            if card.clock_state == "active":
                bg, fg_clock = t.accent, t.on_accent
            elif card.clock_state == "low":
                bg, fg_clock = t.danger_bg, t.danger_text
            w.rounded(surface, bg, clock_rect, 8)
            if card.clock_state == "paused":
                p.draw.rect(surface, t.muted, clock_rect, 1, border_radius=8)
            w.text(
                surface,
                card.clock,
                f,
                fg_clock,
                (clock_rect.right - 14, clock_rect.centery),
                "midright",
            )

        x = avatar.right + 12
        limit = (clock_rect.left if clock_rect.width else rect.right) - x - 10
        name_font = th.font(15, "semibold")
        name = card.name
        if card.thinking:
            name = tr("{name} · réfléchit", name=name) + "." * (now_ms // 400 % 4)
        w.text(
            surface,
            w.ellipsize(name, name_font, limit),
            name_font,
            t.text,
            (x, rect.centery - 2),
            "bottomleft",
        )
        sub_font = th.font(13)
        sub = w.text(surface, card.subtitle, sub_font, t.muted, (x, rect.centery + 2))
        cx = sub.right + 8
        for piece in card.captured:
            if cx + 18 > x + limit:
                break
            image = pieces.get_image(piece, 20)
            surface.blit(image, (cx, sub.centery - 10))
            cx += 11
        if card.advantage > 0:
            w.text(
                surface, f"+{card.advantage}", sub_font, t.text, (cx + 12, sub.centery), "midleft"
            )

    def _draw_moves(self, surface, rect, model: PanelModel, t: Theme, mouse) -> None:
        w.rounded(surface, t.surface, rect, 10)
        w.rounded(surface, t.border, rect, 10, 1)
        head = p.Rect(rect.x, rect.y, rect.width, 48)
        w.text(
            surface,
            tr("Coups"),
            th.font(14, "semibold"),
            t.text,
            (head.x + 16, head.centery),
            "midleft",
        )
        x = head.right - 8
        for button in reversed(self.nav):
            button.rect = p.Rect(0, 0, 40, 34)
            button.rect.midright = (x, head.centery)
            x = button.rect.left - 2
        reviewing = model.current_ply != model.live_ply
        self.nav[0].enabled = self.nav[1].enabled = model.current_ply > 0
        self.nav[2].enabled = self.nav[3].enabled = reviewing
        w.draw_buttons(surface, t, self.nav, mouse)
        if model.eval_text:
            w.text(
                surface,
                model.eval_text,
                th.font(13, "medium", mono=True),
                t.muted,
                (head.x + 72, head.centery),
                "midleft",
            )
        p.draw.line(surface, t.border, (rect.x, head.bottom), (rect.right - 1, head.bottom))
        top = head.bottom
        if model.opening:
            band = p.Rect(rect.x, head.bottom, rect.width, OPENING_HEIGHT)
            f = th.font(12, "medium")
            w.text(
                surface,
                w.ellipsize(model.opening, f, band.width - 32),
                f,
                t.muted,
                (band.x + 16, band.centery),
                "midleft",
            )
            p.draw.line(surface, t.border, (rect.x, band.bottom), (rect.right - 1, band.bottom))
            top = band.bottom
        if model.analysis:
            line, info = model.analysis
            band = p.Rect(rect.x, top, rect.width, OPENING_HEIGHT)
            info_font = th.font(12, "medium", mono=True)
            info_w = info_font.size(info)[0] if info else 0
            if info:
                w.text(
                    surface, info, info_font, t.muted, (band.right - 16, band.centery), "midright"
                )
            f = th.font(12, "medium", mono=True)
            w.text(
                surface,
                w.ellipsize(line, f, band.width - 32 - info_w - (12 if info else 0)),
                f,
                t.text,
                (band.x + 16, band.centery),
                "midleft",
            )
            p.draw.line(surface, t.border, (rect.x, band.bottom), (rect.right - 1, band.bottom))
            top = band.bottom

        foot = p.Rect(rect.x, rect.bottom - 42, rect.width, 42)
        p.draw.line(surface, t.border, (rect.x, foot.y), (rect.right - 1, foot.y))
        if model.move_input is not None:
            self._draw_move_input(surface, foot, model.move_input, t)
        else:
            dot = {"accent": t.accent_ink, "warning": th.WARNING_DOT}.get(
                model.status_kind, t.muted
            )
            p.draw.circle(surface, dot, (foot.x + 20, foot.centery), 4)
            f = th.font(13)
            w.text(
                surface,
                w.ellipsize(model.status, f, foot.width - 48),
                f,
                t.text if model.status_kind != "info" else t.muted,
                (foot.x + 32, foot.centery),
                "midleft",
            )

        self._list_rect = p.Rect(rect.x + 8, top + 6, rect.width - 16, foot.y - top - 12)
        self._draw_rows(surface, model, t, mouse)

    def _draw_move_input(self, surface, foot: p.Rect, value, t: Theme) -> None:
        """Ligne d'état remplacée par le coup en cours de frappe (J11.2)."""
        text, error = value
        box = foot.inflate(-12, -10)
        w.rounded(surface, t.surface2, box, 6)
        w.rounded(surface, th.WARNING_DOT if error else t.accent_ink, box, 6, 1)
        mono = th.font(14, "semibold", mono=True)
        prompt = w.text(surface, "›", mono, t.accent_ink, (box.x + 10, box.centery), "midleft")
        typed = w.text(surface, text, mono, t.text, (prompt.right + 8, box.centery), "midleft")
        p.draw.line(
            surface, t.text, (typed.right + 2, box.y + 7), (typed.right + 2, box.bottom - 7), 2
        )
        f = th.font(12)
        note = error or tr("Entrée : jouer · Échap : annuler")
        w.text(
            surface,
            w.ellipsize(note, f, box.right - typed.right - 28),
            f,
            t.text if error else t.muted,
            (box.right - 10, box.centery),
            "midright",
        )

    def _draw_rows(self, surface, model: PanelModel, t: Theme, mouse) -> None:
        area = self._list_rect
        content = len(model.rows) * ROW_HEIGHT
        self.max_scroll = max(0, content - area.height)
        if model.current_ply != self._last_ply:
            self._ensure_visible(model)
            self._last_ply = model.current_ply
        self.scroll = min(self.scroll, self.max_scroll)
        self._cells = []
        previous_clip = surface.get_clip()
        surface.set_clip(area)
        mono = th.font(15, "medium", mono=True)
        bold = th.font(15, "semibold", mono=True)
        col_w = (area.width - 48) // 2
        for i, row in enumerate(model.rows):
            y = area.y + i * ROW_HEIGHT - self.scroll
            if y + ROW_HEIGHT < area.y or y > area.bottom:
                continue
            w.text(
                surface,
                f"{row.number}.",
                mono,
                t.muted,
                (area.x + 8, y + ROW_HEIGHT // 2),
                "midleft",
            )
            for j, cell in enumerate((row.white, row.black)):
                if cell is None:
                    if j == 0 and row.black is not None:
                        w.text(
                            surface,
                            "…",
                            mono,
                            t.muted,
                            (area.x + 52, y + ROW_HEIGHT // 2),
                            "midleft",
                        )
                    continue
                san, ply = cell
                cell_rect = p.Rect(area.x + 44 + j * (col_w + 4), y + 1, col_w, ROW_HEIGHT - 2)
                current = ply == model.current_ply
                if current:
                    w.translucent(surface, t.current, cell_rect, 6)
                elif cell_rect.collidepoint(mouse) and area.collidepoint(mouse):
                    w.translucent(surface, t.hover, cell_rect, 6)
                future = ply > model.current_ply
                color = t.muted if future else t.text
                w.text(
                    surface,
                    san,
                    bold if current else mono,
                    color,
                    (cell_rect.x + 10, cell_rect.centery),
                    "midleft",
                )
                self._cells.append((cell_rect.clip(area), ply))
        surface.set_clip(previous_clip)
        if not model.rows:
            w.text(
                surface,
                tr("Aucun coup joué"),
                th.font(13),
                t.muted,
                (area.centerx, area.y + 24),
                "center",
            )

    def _ensure_visible(self, model: PanelModel) -> None:
        index = next(
            (
                i
                for i, row in enumerate(model.rows)
                if any(c is not None and c[1] == model.current_ply for c in (row.white, row.black))
            ),
            None,
        )
        if index is None:
            if model.current_ply == 0:
                self.scroll = 0
            return
        top = index * ROW_HEIGHT
        if top < self.scroll:
            self.scroll = top
        elif top + ROW_HEIGHT > self.scroll + self._list_rect.height:
            self.scroll = top + ROW_HEIGHT - self._list_rect.height
        self.scroll = max(0, min(self.scroll, self.max_scroll))

    def _draw_actions(self, surface, rect, model: PanelModel, t: Theme, mouse) -> None:
        width = (rect.width - 2 * 8) // 3
        enabled = (model.can_undo, model.can_draw, model.can_resign)
        for i, button in enumerate(self.actions):
            button.rect = p.Rect(rect.x + i * (width + 8), rect.y, width, rect.height)
            button.enabled = enabled[i]
        self.actions[1].label = model.draw_label
        compact = width < 130
        for button in self.actions:
            hint = button.hint
            if compact:
                button.hint = None
            button.draw(surface, t, hovered=button.hit(mouse))
            button.hint = hint
