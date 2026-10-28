"""
Audit des contrastes WCAG 2.2 (J11.4)
-------------------------------------
Calcule le rapport de contraste de chaque paire de couleurs que l'interface dessine
réellement (texte sur fond, état d'une commande, repère sur l'échiquier), dans les
deux thèmes et sur les quatre échiquiers, et le compare au seuil AA :

- **texte** (critère 1.4.3) : 4,5:1, ou 3:1 pour un grand texte (au moins 24 px, ou
  18,7 px en gras) ;
- **non textuel** (critère 1.4.11) : 3:1 pour ce qui est nécessaire pour comprendre
  l'interface ou s'en servir (icônes, état d'une option, repères de l'échiquier).

Les couleurs translucides sont d'abord composées sur leur fond, comme à l'écran. Les
formules sont celles de la norme (luminance relative sRGB, ``(L1 + 0,05) / (L2 + 0,05)``).

    python tools/contrast.py            # tableau complet, code 1 si un écart reste
    python tools/contrast.py --failures # écarts seulement

Exclus, comme le permet la norme : commandes désactivées, décor (ombres, voile des
fenêtres, séparateurs), annotations dessinées par le joueur (flèches, marques), et les
pièces elles-mêmes (images à deux tons, contour sombre sur tous les fonds).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from chessproject.ui import theme as th

RGB = tuple[int, int, int]
RGBA = tuple[int, int, int, int]

TEXT = "texte"
LARGE = "grand texte"
UI = "non textuel"
THRESHOLDS = {TEXT: 4.5, LARGE: 3.0, UI: 3.0}


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(color: RGB) -> float:
    """Luminance relative WCAG d'une couleur sRGB."""
    r, g, b = (_channel(v) for v in color[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: RGB, b: RGB) -> float:
    """Rapport de contraste WCAG entre deux couleurs (de 1 à 21)."""
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def over(color: RGB | RGBA, background: RGB) -> RGB:
    """Couleur ``color`` (éventuellement translucide) composée sur ``background``."""
    if len(color) == 3:
        return (color[0], color[1], color[2])
    alpha = color[3] / 255
    return (
        round(color[0] * alpha + background[0] * (1 - alpha)),
        round(color[1] * alpha + background[1] * (1 - alpha)),
        round(color[2] * alpha + background[2] * (1 - alpha)),
    )


@dataclass(frozen=True)
class Pair:
    where: str  # contexte : thème, échiquier
    what: str  # élément dessiné
    fg: RGB
    bg: RGB
    kind: str

    @property
    def ratio(self) -> float:
        return contrast(self.fg, self.bg)

    @property
    def threshold(self) -> float:
        return THRESHOLDS[self.kind]

    @property
    def ok(self) -> bool:
        return self.ratio >= self.threshold


def theme_pairs(t: th.Theme) -> list[Pair]:
    where = f"thème {t.name}"
    selected_row = over(t.current, t.surface2)  # ligne choisie d'une liste de fichiers
    current_move = over(t.current, t.surface)  # coup affiché dans l'historique
    hovered = over(t.hover, t.surface)
    choice_selected = th.mix(t.surface2, t.accent, 0.16)
    pairs = [
        Pair(where, "texte sur le fond de la fenêtre", t.text, t.bg, TEXT),
        Pair(where, "texte sur une carte", t.text, t.surface, TEXT),
        Pair(where, "texte sur une zone secondaire", t.text, t.surface2, TEXT),
        Pair(where, "texte secondaire sur le fond", t.muted, t.bg, TEXT),
        Pair(where, "texte secondaire sur une carte", t.muted, t.surface, TEXT),
        Pair(where, "texte secondaire sur une zone secondaire", t.muted, t.surface2, TEXT),
        Pair(where, "touche dans une pastille", t.muted, t.surface2, TEXT),
        Pair(where, "bouton principal", t.on_accent, t.accent, TEXT),
        Pair(where, "bouton survolé", t.text, hovered, TEXT),
        Pair(where, "option choisie (texte)", t.text, choice_selected, TEXT),
        Pair(where, "option choisie (cadre)", t.accent_ink, t.surface, UI),
        Pair(where, "option choisie (cadre, zone secondaire)", t.accent_ink, t.surface2, UI),
        Pair(where, "coup affiché dans l'historique", t.text, current_move, TEXT),
        Pair(where, "fichier choisi dans la liste", t.text, selected_row, TEXT),
        Pair(where, "pendule active", t.on_accent, t.accent, LARGE),
        Pair(where, "pendule à l'arrêt", t.muted, t.surface2, LARGE),
        Pair(where, "pendule sous 20 s", t.danger_text, t.danger_bg, LARGE),
        Pair(where, "camp au trait (cadre de la carte)", t.accent_ink, t.surface, UI),
        Pair(where, "icône d'un bouton discret", t.muted, t.surface, UI),
        Pair(where, "interrupteur activé (fond)", t.accent_ink, t.surface, UI),
        Pair(where, "interrupteur activé (curseur)", t.on_accent, t.accent_ink, UI),
        Pair(where, "interrupteur désactivé (curseur)", t.muted, t.surface2, UI),
        Pair(where, "champ de saisie (cadre)", t.accent_ink, t.surface, UI),
        Pair(where, "invite de la saisie du coup", t.accent_ink, t.surface2, UI),
        Pair(where, "niveau de l'IA (barres)", t.accent_ink, t.surface2, UI),
        Pair(where, "saisie refusée (cadre)", th.WARNING_DOT, t.surface, UI),
        Pair(where, "ligne d'état : pastille d'alerte", th.WARNING_DOT, t.surface, UI),
        Pair(where, "infobulle", t.text, t.surface2, TEXT),
    ]
    return pairs


def board_pairs(palette: th.BoardPalette) -> list[Pair]:
    where = f"échiquier {palette.name}"
    pairs: list[Pair] = []
    for square, name, ink in (
        (palette.light, "case claire", palette.coord_on_light),
        (palette.dark, "case foncée", palette.coord_on_dark),
    ):
        pairs += [
            Pair(where, f"coordonnée sur {name}", ink, square, TEXT),
            Pair(where, f"coup possible sur {name}", over(th.HINT, square), square, UI),
            Pair(where, f"roi en échec (liseré) sur {name}", th.CHECK_RING, square, UI),
        ]
    return pairs


def other_pairs() -> list[Pair]:
    pairs = [
        Pair("bilan", f"pastille « {kind} » (contour)", color, th.JUDGEMENT_RING, UI)
        for kind, color in th.JUDGEMENT_COLORS.items()
    ]
    return pairs + [
        Pair("barre d'évaluation", "avantage blanc / noir", th.EVAL_WHITE, th.EVAL_BLACK, UI),
        Pair(
            "promotion", "bouton annuler (×)", th.PROMOTION_CANCEL_TEXT, th.PROMOTION_CANCEL, TEXT
        ),
        Pair(
            "promotion",
            "bouton annuler survolé (×)",
            th.PROMOTION_CANCEL_TEXT,
            th.PROMOTION_CANCEL_HOVER,
            TEXT,
        ),
    ]


def audit() -> list[Pair]:
    """Toutes les paires de couleurs auditées."""
    pairs: list[Pair] = []
    for t in th.THEMES.values():
        pairs += theme_pairs(t)
    for palette in th.PALETTES.values():
        pairs += board_pairs(palette)
    return pairs + other_pairs()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--failures", action="store_true", help="n'affiche que les écarts")
    args = parser.parse_args(argv)
    pairs = audit()
    failures = [pair for pair in pairs if not pair.ok]
    shown = failures if args.failures else pairs
    width = max((len(pair.what) for pair in shown), default=10)
    for pair in shown:
        mark = "ok " if pair.ok else "ÉCART"
        print(
            f"{mark:5} {pair.ratio:5.2f} ≥ {pair.threshold:3.1f}  {pair.where:22} "
            f"{pair.what:{width}}  {pair.kind}"
        )
    print(f"\n{len(pairs)} paires, {len(failures)} écart(s) au niveau AA")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
