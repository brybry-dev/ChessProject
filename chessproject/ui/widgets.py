"""
Briques de dessin de l'interface (J5.2)
---------------------------------------
Texte, rectangles arrondis et translucides, ombres, icônes vectorielles et boutons.
Les icônes sont décrites sur une grille de 24 × 24, tracées en sur-échantillonnage
×4 puis réduites (lissage) : nettes à toutes les tailles, sans fichier image.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import pygame as p

from chessproject.ui import theme as th
from chessproject.ui.theme import RGB, RGBA, Theme

Point = tuple[float, float]


def smoothscale(surface: p.Surface, size: tuple[int, int]) -> p.Surface:
    """``pygame.transform.smoothscale`` avec le filtre C portable.

    Les filtres MMX / SSE choisis par défaut ne sont pas les mêmes selon le système
    (assembleur GCC sous Linux, version MinGW sous Windows) ; sous Windows, rien de ce
    qui passait par eux ne s'affichait (pièces, icônes, pastilles, en v1.1.0). Le
    filtre « GENERIC » donne le même résultat partout.
    """
    if p.transform.get_smoothscale_backend() != "GENERIC":
        p.transform.set_smoothscale_backend("GENERIC")
    return p.transform.smoothscale(surface, size)


# --------------------------------------------------------------------------
# Texte et formes
# --------------------------------------------------------------------------
def text(
    surface: p.Surface,
    value: str,
    font: p.font.Font,
    color: RGB,
    pos: tuple[int, int],
    anchor: str = "topleft",
) -> p.Rect:
    """Écrit ``value`` ancré en ``pos`` (topleft, center, midleft, midright…)."""
    rendered = font.render(value, True, color)
    rect = rendered.get_rect(**{anchor: pos})
    surface.blit(rendered, rect)
    return rect


def ellipsize(value: str, font: p.font.Font, max_width: int) -> str:
    """Tronque ``value`` (avec « … ») pour tenir dans ``max_width`` pixels."""
    if font.size(value)[0] <= max_width:
        return value
    while value and font.size(value + "…")[0] > max_width:
        value = value[:-1]
    return value + "…"


def wrap(value: str, font: p.font.Font, max_width: int) -> list[str]:
    """Coupe ``value`` en lignes de ``max_width`` pixels au plus (aux espaces)."""
    lines: list[str] = []
    current = ""
    for word in value.split():
        candidate = f"{current} {word}".strip()
        if font.size(candidate)[0] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def rounded(surface: p.Surface, color: RGB, rect: p.Rect, radius: int = 8, width: int = 0) -> None:
    p.draw.rect(surface, color, rect, width=width, border_radius=radius)


def translucent(surface: p.Surface, color: RGBA, rect: p.Rect, radius: int = 0) -> None:
    """Rectangle translucide (``color`` avec opacité) dessiné par-dessus ``surface``."""
    rect = p.Rect(rect)
    if rect.width <= 0 or rect.height <= 0:
        return
    layer = p.Surface(rect.size, p.SRCALPHA)
    p.draw.rect(layer, color, layer.get_rect(), border_radius=radius)
    surface.blit(layer, rect.topleft)


@lru_cache(maxsize=32)
def _shadow_layer(size: tuple[int, int], radius: int, depth: int) -> p.Surface:
    """Halo d'ombre (mis en cache) pour un rectangle de taille ``size``."""
    steps = 6
    pad = depth
    layer = p.Surface((size[0] + 2 * pad, size[1] + 2 * pad + depth // 3), p.SRCALPHA)
    for i in range(steps, 0, -1):
        spread = depth * i // steps
        halo = p.Rect(pad, pad, *size).inflate(spread, spread).move(0, depth // 3)
        part = p.Surface(halo.size, p.SRCALPHA)
        p.draw.rect(
            part, (*th.SHADOW, 70 // steps), part.get_rect(), border_radius=radius + spread // 2
        )
        layer.blit(part, halo.topleft)
    return layer


def shadow(surface: p.Surface, rect: p.Rect, radius: int = 12, depth: int = 18) -> None:
    """Ombre portée douce sous ``rect`` (superposition de halos translucides)."""
    rect = p.Rect(rect)
    surface.blit(_shadow_layer(rect.size, radius, depth), (rect.x - depth, rect.y - depth))


@lru_cache(maxsize=64)
def _disc(color: RGBA, radius: int, width: int) -> p.Surface:
    """Disque (``width`` = 0) ou anneau lissé, sur-échantillonné et mis en cache."""
    size = radius * 2 + 2
    big = p.Surface((size * 4, size * 4), p.SRCALPHA)
    p.draw.circle(big, color, (size * 2, size * 2), radius * 4, width * 4)
    return smoothscale(big, (size, size))


def circle(surface: p.Surface, color: RGBA, center: tuple[int, int], radius: int) -> None:
    """Disque lissé et translucide."""
    disc = _disc(color, radius, 0)
    surface.blit(disc, disc.get_rect(center=center))


def ring(surface: p.Surface, color: RGBA, center: tuple[int, int], radius: int, width: int) -> None:
    """Anneau lissé et translucide."""
    disc = _disc(color, radius, width)
    surface.blit(disc, disc.get_rect(center=center))


# --------------------------------------------------------------------------
# Icônes
# --------------------------------------------------------------------------
def _arc(cx: float, cy: float, r: float, start: float, end: float, steps: int = 12) -> list[Point]:
    """Points d'un arc de cercle (angles en degrés, sens trigonométrique écran)."""
    return [
        (
            cx + r * math.cos(math.radians(start + (end - start) * i / steps)),
            cy + r * math.sin(math.radians(start + (end - start) * i / steps)),
        )
        for i in range(steps + 1)
    ]


# Chaque icône : liste de tracés ("line" = ligne brisée ouverte, "loop" = fermée,
# "fill" = polygone plein, "circle" = (cx, cy, r), "dot" = disque plein).
Stroke = tuple[str, Any]
ICONS: dict[str, list[Stroke]] = {
    "plus": [("line", [(12, 5), (12, 19)]), ("line", [(5, 12), (19, 12)])],
    "save": [
        ("loop", [(5, 4), (16, 4), (19, 7), (19, 20), (5, 20)]),
        ("line", [(8, 4), (8, 9), (15, 9), (15, 4)]),
        ("line", [(8, 20), (8, 14), (16, 14), (16, 20)]),
    ],
    "folder": [("loop", [(3, 6), (9, 6), (11, 8), (21, 8), (21, 19), (3, 19)])],
    "file": [
        ("loop", [(6, 3), (14, 3), (19, 8), (19, 21), (6, 21)]),
        ("line", [(14, 3), (14, 8), (19, 8)]),
    ],
    "download": [
        ("line", [(12, 4), (12, 15)]),
        ("line", [(7, 10), (12, 15), (17, 10)]),
        ("line", [(5, 20), (19, 20)]),
    ],
    "upload": [
        ("line", [(12, 15), (12, 4)]),
        ("line", [(7, 9), (12, 4), (17, 9)]),
        ("line", [(5, 20), (19, 20)]),
    ],
    "contrast": [("circle", (12, 12, 8)), ("fill", _arc(12, 12, 8, 90, 270))],
    "keyboard": [
        ("loop", [(3, 6), (21, 6), (21, 18), (3, 18)]),
        ("line", [(7, 10), (8, 10)]),
        ("line", [(11, 10), (13, 10)]),
        ("line", [(16, 10), (17, 10)]),
        ("line", [(8, 14), (16, 14)]),
    ],
    "undo": [
        ("line", [(9, 14), (4, 9), (9, 4)]),
        ("line", [(4, 9), (15, 9), *_arc(15, 14, 5, -90, 90)[1:], (12, 19)]),
    ],
    "equal": [("line", [(6, 9), (18, 9)]), ("line", [(6, 15), (18, 15)])],
    "flag": [("line", [(5, 21), (5, 4)]), ("loop", [(5, 4), (16, 4), (14, 8), (16, 12), (5, 12)])],
    "first": [("line", [(6, 5), (6, 19)]), ("line", [(18, 5), (10, 12), (18, 19)])],
    "prev": [("line", [(15, 5), (8, 12), (15, 19)])],
    "next": [("line", [(9, 5), (16, 12), (9, 19)])],
    "last": [("line", [(6, 5), (14, 12), (6, 19)]), ("line", [(18, 5), (18, 19)])],
    "flip": [
        ("line", [(7, 20), (7, 4)]),
        ("line", [(4, 7), (7, 4), (10, 7)]),
        ("line", [(17, 4), (17, 20)]),
        ("line", [(14, 17), (17, 20), (20, 17)]),
    ],
    "cpu": [
        ("loop", [(6, 6), (18, 6), (18, 18), (6, 18)]),
        ("line", [(9, 2), (9, 6)]),
        ("line", [(15, 2), (15, 6)]),
        ("line", [(9, 18), (9, 22)]),
        ("line", [(15, 18), (15, 22)]),
        ("line", [(2, 9), (6, 9)]),
        ("line", [(2, 15), (6, 15)]),
        ("line", [(18, 9), (22, 9)]),
        ("line", [(18, 15), (22, 15)]),
    ],
    "user": [("circle", (12, 8, 4)), ("line", _arc(12, 21, 8, 180, 360))],
    "close": [("line", [(6, 6), (18, 18)]), ("line", [(18, 6), (6, 18)])],
    "info": [("circle", (12, 12, 9)), ("line", [(12, 11), (12, 16)]), ("dot", (12, 8, 1.2))],
    "check": [("line", [(5, 12), (10, 17), (19, 7)])],
    "bulb": [
        ("line", [(9, 15), *_arc(12, 9, 6, 130, 410), (15, 15)]),
        ("line", [(9, 15), (9, 17), (15, 17), (15, 15)]),
        ("line", [(10, 21), (14, 21)]),
    ],
}


@lru_cache(maxsize=256)
def icon(name: str, size: int, color: RGB, stroke: float = 2.0) -> p.Surface:
    """Icône ``name`` de ``size`` pixels, tracée en ``color`` (mise en cache)."""
    scale = 4 * size / 24
    big = p.Surface((size * 4, size * 4), p.SRCALPHA)
    width = max(1, round(stroke * scale))
    rgba = (*color, 255)

    def pt(point: Point) -> tuple[int, int]:
        return round(point[0] * scale), round(point[1] * scale)

    for kind, data in ICONS[name]:
        if kind in ("line", "loop"):
            points = [pt(q) for q in data]
            p.draw.lines(big, rgba, kind == "loop", points, width)
            for q in points:  # jonctions arrondies
                p.draw.circle(big, rgba, q, width // 2)
        elif kind == "fill":
            p.draw.polygon(big, rgba, [pt(q) for q in data])
        elif kind in ("circle", "dot"):
            cx, cy, r = data
            p.draw.circle(big, rgba, pt((cx, cy)), round(r * scale), 0 if kind == "dot" else width)
    return smoothscale(big, (size, size))


# --------------------------------------------------------------------------
# Boutons
# --------------------------------------------------------------------------
@dataclass
class Button:
    """Bouton d'interface : rectangle cliquable avec libellé, icône et raccourci.

    ``variant`` : ``primary`` (accent), ``secondary`` (cadre), ``ghost`` (discret),
    ``choice`` (option sélectionnable, ``selected``). ``action`` identifie le bouton
    pour son propriétaire (chaîne ou valeur quelconque).
    """

    action: object
    label: str = ""
    icon: str | None = None
    hint: str | None = None  # touche affichée dans une pastille
    tooltip: str | None = None
    variant: str = "secondary"
    selected: bool = False
    enabled: bool = True
    rect: p.Rect = field(default_factory=lambda: p.Rect(0, 0, 0, 0))

    @property
    def text(self) -> str:
        return self.label

    def hit(self, pos: tuple[int, int]) -> bool:
        return self.enabled and bool(self.rect.collidepoint(pos))

    def draw(
        self,
        surface: p.Surface,
        t: Theme,
        hovered: bool = False,
        font: p.font.Font | None = None,
    ) -> None:
        rect = self.rect
        fg = t.text if self.enabled else t.muted
        if self.variant == "primary":
            color = t.accent if self.enabled else t.surface2
            if hovered and self.enabled:
                color = _lighten(color, 18)
            rounded(surface, color, rect, 8)
            fg = t.on_accent if self.enabled else t.muted
        elif self.variant == "choice":
            if self.selected:
                rounded(surface, _mix(t.surface2, t.accent, 0.16), rect, 10)
                rounded(surface, t.accent, rect, 10, 2)
            else:
                rounded(surface, t.surface2, rect, 10)
                rounded(surface, _lighten(t.border, 18) if hovered else t.border, rect, 10, 1)
        elif self.variant == "ghost":
            if hovered and self.enabled:
                translucent(surface, t.hover, rect, 8)
            fg = t.text if hovered and self.enabled else t.muted
        else:
            rounded(surface, t.surface, rect, 8)
            if hovered and self.enabled:
                translucent(surface, t.hover, rect, 8)
            rounded(surface, t.border, rect, 8, 1)

        font = font or th.font(14, "medium" if self.variant != "primary" else "semibold")
        parts: list[tuple[str, p.Surface]] = []
        if self.icon:
            parts.append(("icon", icon(self.icon, 18 if self.label else 20, fg)))
        if self.label:
            parts.append(("label", font.render(self.label, True, fg)))
        if self.hint and self.enabled:
            kbd_font = th.font(11, "medium", mono=True)
            kbd = kbd_font.render(self.hint, True, t.muted)
            chip = p.Surface((kbd.get_width() + 10, kbd.get_height() + 4), p.SRCALPHA)
            p.draw.rect(chip, (*t.surface2, 255), chip.get_rect(), border_radius=4)
            chip.blit(kbd, (5, 2))
            parts.append(("hint", chip))
        gap = 8
        total = sum(s.get_width() for _, s in parts) + gap * (len(parts) - 1)
        x = rect.centerx - total // 2
        for _, s in parts:
            surface.blit(s, (x, rect.centery - s.get_height() // 2))
            x += s.get_width() + gap


def _lighten(color: RGB, amount: int) -> RGB:
    return (min(255, color[0] + amount), min(255, color[1] + amount), min(255, color[2] + amount))


def _mix(a: RGB, b: RGB, t: float) -> RGB:
    return (
        round(a[0] + (b[0] - a[0]) * t),
        round(a[1] + (b[1] - a[1]) * t),
        round(a[2] + (b[2] - a[2]) * t),
    )


def hovered_button(buttons: Sequence[Button], pos: tuple[int, int]) -> Button | None:
    return next((b for b in buttons if b.hit(pos)), None)


def draw_buttons(
    surface: p.Surface,
    t: Theme,
    buttons: Sequence[Button],
    mouse: tuple[int, int],
    font_for: Callable[[Button], p.font.Font | None] = lambda b: None,
) -> None:
    for b in buttons:
        b.draw(surface, t, hovered=b.hit(mouse), font=font_for(b))


def tooltip(surface: p.Surface, t: Theme, value: str, anchor: p.Rect) -> None:
    """Infobulle sous ``anchor`` (gardée dans la fenêtre)."""
    f = th.font(12, "medium")
    label = f.render(value, True, t.text)
    box = p.Rect(0, 0, label.get_width() + 16, label.get_height() + 10)
    box.midtop = (anchor.centerx, anchor.bottom + 6)
    box.clamp_ip(surface.get_rect())
    rounded(surface, t.surface2, box, 6)
    rounded(surface, t.border, box, 6, 1)
    surface.blit(label, (box.x + 8, box.y + 5))
