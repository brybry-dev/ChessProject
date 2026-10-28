"""
Choix de fichier et de partie (J11.1)
------------------------------------
Fenêtres superposées pour choisir où sauvegarder, quelle sauvegarde charger, où
exporter un PGN, quel PGN importer, puis quelle partie d'un PGN qui en contient
plusieurs. Tout est dessiné par le jeu (pas de dialogue du système) : le même parcours
sur toutes les plateformes, testable sans écran.

Comme les autres fenêtres superposées, elles renvoient une action au contrôleur :
``("file", kind, chemin)`` pour un fichier choisi, ``("pgn_game", index)`` pour une
partie, ou ``"close"``.
"""

import contextlib
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pygame as p

from chessproject.core import pgn
from chessproject.ui import theme as th
from chessproject.ui import widgets as w
from chessproject.ui.overlays import Overlay, _close_button

ROW_HEIGHT = 36
# Caractères refusés dans un nom de fichier (Windows est le plus strict).
FORBIDDEN_CHARS = set('/\\:*?"<>|')
MAX_NAME_LENGTH = 80


@dataclass(frozen=True)
class Entry:
    path: Path
    is_dir: bool
    label: str
    detail: str = ""


def _modified(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def list_directory(directory: Path, extensions: Sequence[str]) -> list[Entry]:
    """Contenu de ``directory`` : dossier parent (« .. »), sous-dossiers par ordre
    alphabétique, puis fichiers portant une des ``extensions``, du plus récent au plus
    ancien. Fichiers cachés ignorés. Lève ``OSError`` si le dossier est illisible."""
    entries: list[Entry] = []
    if directory.parent != directory:
        entries.append(Entry(directory.parent, True, ".."))
    folders: list[Path] = []
    files: list[Path] = []
    for child in directory.iterdir():
        if child.name.startswith("."):
            continue
        try:
            if child.is_dir():
                folders.append(child)
            elif child.suffix.lower() in extensions:
                files.append(child)
        except OSError:
            continue
    entries += [Entry(f, True, f.name) for f in sorted(folders, key=lambda f: f.name.lower())]
    for f in sorted(files, key=_modified, reverse=True):
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(_modified(f)))
        entries.append(Entry(f, False, f.name, stamp))
    return entries


def clean_name(name: str) -> str:
    """Nom de fichier tapé, sans les caractères interdits ni espaces aux extrémités."""
    return "".join(c for c in name if c not in FORBIDDEN_CHARS and c.isprintable()).strip()


class _ScrollList:
    """Liste défilante de lignes cliquables (sélection, molette, clavier)."""

    def __init__(self) -> None:
        self.rect = p.Rect(0, 0, 0, 0)
        self.scroll = 0
        self.selected: int | None = None

    def visible_rows(self) -> int:
        return max(1, self.rect.height // ROW_HEIGHT)

    def index_at(self, pos: tuple[int, int], count: int) -> int | None:
        if not self.rect.collidepoint(pos):
            return None
        index = (pos[1] - self.rect.y) // ROW_HEIGHT + self.scroll
        return index if 0 <= index < count else None

    def move(self, step: int, count: int) -> None:
        if count == 0:
            return
        current = self.selected if self.selected is not None else (-1 if step > 0 else count)
        self.selected = max(0, min(count - 1, current + step))
        self.ensure_visible()

    def ensure_visible(self) -> None:
        if self.selected is None:
            return
        rows = self.visible_rows()
        if self.selected < self.scroll:
            self.scroll = self.selected
        elif self.selected >= self.scroll + rows:
            self.scroll = self.selected - rows + 1

    def scroll_by(self, dy: int, count: int) -> None:
        self.scroll = max(0, min(max(0, count - self.visible_rows()), self.scroll - dy))

    def draw(self, surface, t, rows: Sequence[tuple[str | None, str, str]], mouse) -> None:
        """Dessine ``rows`` : (icône, libellé, détail à droite)."""
        w.rounded(surface, t.surface2, self.rect, 8)
        previous = surface.get_clip()
        surface.set_clip(self.rect)
        self.scroll = max(0, min(self.scroll, max(0, len(rows) - self.visible_rows())))
        f = th.font(14)
        detail_font = th.font(12, "medium", mono=True)
        for i in range(self.scroll, min(len(rows), self.scroll + self.visible_rows() + 1)):
            icon, label, detail = rows[i]
            row = p.Rect(
                self.rect.x + 4,
                self.rect.y + (i - self.scroll) * ROW_HEIGHT + 2,
                self.rect.width - 8,
                ROW_HEIGHT - 4,
            )
            if i == self.selected:
                w.translucent(surface, t.current, row, 6)
            elif row.collidepoint(mouse) and self.rect.collidepoint(mouse):
                w.translucent(surface, t.hover, row, 6)
            x = row.x + 10
            if icon:
                glyph = w.icon(icon, 18, t.muted)
                surface.blit(glyph, glyph.get_rect(midleft=(x, row.centery)))
                x += 28
            detail_w = detail_font.size(detail)[0] if detail else 0
            if detail:
                w.text(
                    surface, detail, detail_font, t.muted, (row.right - 10, row.centery), "midright"
                )
            w.text(
                surface,
                w.ellipsize(label, f, row.right - x - detail_w - 24),
                f,
                t.text,
                (x, row.centery),
                "midleft",
            )
        surface.set_clip(previous)


# --------------------------------------------------------------------------
class FileDialog(Overlay):
    """Choix d'un fichier à ouvrir (``mode="open"``) ou d'un nom de fichier à écrire
    (``mode="save"``). ``kind`` est rendu tel quel dans l'action ``("file", kind, chemin)``.

    Clavier : flèches pour parcourir, Entrée pour ouvrir un dossier ou valider, Échap
    pour fermer ; en enregistrement, les caractères tapés vont dans le nom du fichier.
    Souris : un clic ouvre un dossier ou choisit un fichier, un second clic le valide.
    ``allow_delete`` : Suppr (deux fois) supprime le fichier choisi.
    """

    def __init__(
        self,
        kind: str,
        mode: str,
        title: str,
        directory: Path,
        extension: str,
        places: Sequence[tuple[str, Path]] = (),
        default_name: str = "",
        confirm_label: str = "",
        allow_delete: bool = False,
    ) -> None:
        super().__init__()
        self.kind, self.mode, self.title = kind, mode, title
        self.extension = extension
        self.places = list(places)
        self.name = default_name
        self.confirm_label = confirm_label or ("Enregistrer" if mode == "save" else "Ouvrir")
        self.allow_delete = allow_delete
        self.list = _ScrollList()
        self.entries: list[Entry] = []
        self.message: tuple[str, str] | None = None  # (texte, info | warning)
        # Confirmation en attente : ("overwrite" | "delete", chemin).
        self.pending: tuple[str, Path] | None = None
        self.directory = directory
        self.open_directory(directory)

    # -- état ------------------------------------------------------------
    def open_directory(self, directory: Path) -> None:
        try:
            entries = list_directory(directory, (self.extension,))
        except OSError:
            self.message = ("Dossier illisible", "warning")
            return
        self.directory, self.entries = directory, entries
        self.list.scroll = 0
        self.pending = None
        self.message = None
        files = [i for i, e in enumerate(entries) if not e.is_dir]
        # À l'ouverture, le fichier le plus récent est présélectionné ; à
        # l'enregistrement, rien (Entrée enregistre sous le nom tapé).
        self.list.selected = files[0] if files and self.mode == "open" else None
        self.list.ensure_visible()

    @property
    def selected_entry(self) -> Entry | None:
        index = self.list.selected
        return self.entries[index] if index is not None else None

    def target(self) -> Path | None:
        """Fichier qui serait écrit ou ouvert par Entrée, ou None."""
        if self.mode == "save":
            name = clean_name(self.name)
            if not name:
                return None
            if not name.lower().endswith(self.extension):
                name += self.extension
            return self.directory / name
        entry = self.selected_entry
        return entry.path if entry is not None and not entry.is_dir else None

    def _select(self, index: int | None) -> None:
        self.list.selected = index
        self.pending = None
        self.message = None
        entry = self.selected_entry
        if entry is not None and not entry.is_dir and self.mode == "save":
            self.name = entry.path.stem

    def _confirm(self):
        entry = self.selected_entry
        if entry is not None and entry.is_dir:
            self.open_directory(entry.path)
            return None
        target = self.target()
        if target is None:
            self.message = (
                "Tapez un nom de fichier" if self.mode == "save" else "Choisissez un fichier",
                "warning",
            )
            return None
        if self.mode == "save" and target.exists() and self.pending != ("overwrite", target):
            self.pending = ("overwrite", target)
            self.message = (f"« {target.name} » existe déjà : Entrée pour le remplacer", "warning")
            return None
        return ("file", self.kind, target)

    def _delete(self) -> None:
        entry = self.selected_entry
        if not self.allow_delete or entry is None or entry.is_dir:
            return
        if self.pending != ("delete", entry.path):
            self.pending = ("delete", entry.path)
            self.message = (f"Supprimer « {entry.label} » ? Suppr pour confirmer", "warning")
            return
        try:
            entry.path.unlink()
        except OSError:
            self.message = ("Suppression impossible", "warning")
            return
        index = self.list.selected or 0
        self.open_directory(self.directory)
        self.message = (f"« {entry.label} » supprimé", "info")
        files = [i for i, e in enumerate(self.entries) if not e.is_dir]
        if files:
            self.list.selected = min(files, key=lambda i: abs(i - index))

    # -- événements ------------------------------------------------------
    def handle_event(self, e):
        count = len(self.entries)
        if e.type == p.TEXTINPUT and self.mode == "save":
            typed = "".join(c for c in e.text if c not in FORBIDDEN_CHARS and c.isprintable())
            self.name = (self.name + typed)[:MAX_NAME_LENGTH]
            self.list.selected = None
            self.pending = None
            return None
        if e.type == p.KEYDOWN:
            if e.key in (p.K_RETURN, p.K_KP_ENTER):
                return self._confirm()
            if e.key in (p.K_UP, p.K_DOWN):
                self.list.move(-1 if e.key == p.K_UP else 1, count)
                self._select(self.list.selected)
                return None
            if e.key == p.K_BACKSPACE:
                if self.mode == "save":
                    self.name = self.name[:-1]
                    self.pending = None
                elif self.directory.parent != self.directory:
                    self.open_directory(self.directory.parent)
                return None
            if e.key == p.K_DELETE:
                self._delete()
                return None
        if e.type == p.MOUSEWHEEL:
            self.list.scroll_by(e.y, count)
            return None
        if e.type == p.MOUSEBUTTONDOWN and e.button == 1:
            index = self.list.index_at(e.pos, count)
            if index is not None:
                entry = self.entries[index]
                if entry.is_dir:
                    self.open_directory(entry.path)
                    return None
                if index == self.list.selected:
                    return self._confirm()
                self._select(index)
                return None
            button = w.hovered_button(self.buttons, e.pos)
            if button is not None:
                action = button.action
                if action == "confirm":
                    return self._confirm()
                if action == "delete":
                    self._delete()
                    return None
                if isinstance(action, tuple) and action[0] == "place":
                    self.open_directory(action[1])
                    return None
        return super().handle_event(e)

    # -- dessin ----------------------------------------------------------
    def draw(self, surface, t, mouse, now_ms):
        width = min(760, surface.get_width() - 48)
        height = min(600, surface.get_height() - 48)
        card = self._frame(surface, t, (width, height))
        x, inner = card.x + 32, card.width - 64
        y = card.y + 28
        w.text(surface, self.title, th.font(22, "semibold"), t.text, (x, y))
        y += 34
        path_font = th.font(13, mono=True)
        w.text(
            surface,
            _ellipsize_left(str(self.directory), path_font, inner),
            path_font,
            t.muted,
            (x, y),
        )
        y += 28
        buttons: list[w.Button] = []
        if self.places:
            gap = 8
            place_w = (inner - gap * (len(self.places) - 1)) // len(self.places)
            for i, (label, folder) in enumerate(self.places):
                b = w.Button(
                    ("place", folder),
                    label,
                    variant="choice",
                    selected=_same_path(folder, self.directory),
                )
                b.rect = p.Rect(x + i * (place_w + gap), y, place_w, 38)
                buttons.append(b)
            y += 38 + 14

        bottom = card.bottom - 24 - 44
        field_h = 0
        if self.mode == "save":
            field_h = 24 + 44 + 16
        message_h = 28
        self.list.rect = p.Rect(x, y, inner, bottom - 16 - message_h - field_h - y)
        rows = [("folder" if e.is_dir else "file", e.label, e.detail) for e in self.entries]
        self.list.draw(surface, t, rows, mouse)
        if not any(not e.is_dir for e in self.entries):
            w.text(
                surface,
                f"Aucun fichier {self.extension} dans ce dossier",
                th.font(13),
                t.muted,
                (self.list.rect.centerx, self.list.rect.bottom - 24),
                "center",
            )
        y = self.list.rect.bottom + 16
        if self.mode == "save":
            w.text(surface, "NOM DU FICHIER", th.font(12, "semibold"), t.muted, (x, y))
            box = p.Rect(x, y + 24, inner, 44)
            w.rounded(surface, t.surface2, box, 8)
            w.rounded(surface, t.accent, box, 8, 2)
            f = th.font(15, mono=True)
            suffix = "" if self.name.lower().endswith(self.extension) else self.extension
            suffix_w = f.size(suffix)[0]
            shown = _ellipsize_left(self.name, f, box.width - 32 - suffix_w)
            r = w.text(surface, shown, f, t.text, (box.x + 14, box.centery), "midleft")
            if now_ms // 500 % 2 == 0:
                p.draw.line(
                    surface, t.text, (r.right + 1, box.y + 11), (r.right + 1, box.bottom - 11), 2
                )
            w.text(surface, suffix, f, t.muted, (r.right + 4, box.centery), "midleft")
            y += field_h
        if self.message is not None:
            text, kind = self.message
            color = th.WARNING_DOT if kind == "warning" else t.accent
            p.draw.circle(surface, color, (x + 4, y + 10), 4)
            w.text(
                surface,
                w.ellipsize(text, th.font(13), inner - 16),
                th.font(13),
                t.text,
                (x + 16, y + 10),
                "midleft",
            )

        confirm = w.Button("confirm", self.confirm_label, variant="primary", hint="Entrée")
        confirm.enabled = self.target() is not None or (
            self.selected_entry is not None and self.selected_entry.is_dir
        )
        confirm.rect = p.Rect(0, 0, 190, 44)
        confirm.rect.bottomright = (card.right - 32, card.bottom - 24)
        cancel = w.Button("close", "Annuler")
        cancel.rect = p.Rect(0, 0, 120, 44)
        cancel.rect.bottomright = (confirm.rect.left - 10, confirm.rect.bottom)
        buttons += [confirm, cancel, _close_button(card)]
        entry = self.selected_entry
        if self.allow_delete and entry is not None and not entry.is_dir:
            delete = w.Button("delete", "Supprimer", variant="ghost", hint="Suppr")
            delete.rect = p.Rect(x, confirm.rect.y, 150, 44)
            buttons.append(delete)
        self.buttons = buttons
        w.draw_buttons(surface, t, buttons, mouse)


def _same_path(a: Path, b: Path) -> bool:
    with contextlib.suppress(OSError):
        return a.resolve() == b.resolve()
    return a == b


def _ellipsize_left(value: str, font: p.font.Font, max_width: int) -> str:
    """Tronque le début de ``value`` (« …fin ») : la fin d'un chemin est la plus utile."""
    if font.size(value)[0] <= max_width:
        return value
    while value and font.size("…" + value)[0] > max_width:
        value = value[1:]
    return "…" + value


# --------------------------------------------------------------------------
def game_label(index: int, game: pgn.PgnGame) -> tuple[str, str]:
    """(« 3. Blancs – Noirs · 1-0 », « Tournoi · 1858.??.?? · 33 coups ») d'une partie."""
    h = game.headers
    white, black = h.get("White", "?"), h.get("Black", "?")
    title = f"{index + 1}. {white} – {black} · {game.result}"
    moves = (len(game.moves) + 1) // 2
    # En-têtes inconnus (« ? », « ????.??.?? ») omis.
    details = [v for v in (h.get("Event", ""), h.get("Date", "")) if v.strip("?.")]
    details.append(f"{moves} coup{'s' if moves > 1 else ''}")
    return title, " · ".join(details)


class GamePickerOverlay(Overlay):
    """Choix d'une partie dans un PGN qui en contient plusieurs (J11.1)."""

    def __init__(self, filename: str, games: Sequence[pgn.PgnGame]) -> None:
        super().__init__()
        self.filename = filename
        self.labels = [game_label(i, g) for i, g in enumerate(games)]
        self.list = _ScrollList()
        self.list.selected = 0

    def handle_event(self, e):
        count = len(self.labels)
        if e.type == p.KEYDOWN:
            if e.key in (p.K_RETURN, p.K_KP_ENTER) and self.list.selected is not None:
                return ("pgn_game", self.list.selected)
            if e.key == p.K_UP:
                self.list.move(-1, count)
                return None
            if e.key == p.K_DOWN:
                self.list.move(1, count)
                return None
            if e.key in (p.K_HOME, p.K_END):
                self.list.selected = 0 if e.key == p.K_HOME else count - 1
                self.list.ensure_visible()
                return None
        if e.type == p.MOUSEWHEEL:
            self.list.scroll_by(e.y, count)
            return None
        if e.type == p.MOUSEBUTTONDOWN and e.button == 1:
            index = self.list.index_at(e.pos, count)
            if index is not None:
                if index == self.list.selected:
                    return ("pgn_game", index)
                self.list.selected = index
                return None
            button = w.hovered_button(self.buttons, e.pos)
            if button is not None and button.action == "confirm":
                return ("pgn_game", self.list.selected)
        return super().handle_event(e)

    def draw(self, surface, t, mouse, now_ms):
        width = min(760, surface.get_width() - 48)
        height = min(600, surface.get_height() - 48)
        card = self._frame(surface, t, (width, height))
        count = len(self.labels)
        y = self._title(
            surface,
            t,
            "Choisir une partie",
            f"{self.filename} contient {count} parties.",
        )
        x, inner = card.x + 32, card.width - 64
        self.list.rect = p.Rect(x, y, inner, card.bottom - 24 - 44 - 16 - y)
        self.list.draw(surface, t, [(None, a, b) for a, b in self.labels], mouse)
        confirm = w.Button("confirm", "Importer", variant="primary", hint="Entrée")
        confirm.rect = p.Rect(0, 0, 170, 44)
        confirm.rect.bottomright = (card.right - 32, card.bottom - 24)
        cancel = w.Button("close", "Annuler")
        cancel.rect = p.Rect(0, 0, 120, 44)
        cancel.rect.bottomright = (confirm.rect.left - 10, confirm.rect.bottom)
        self.buttons = [confirm, cancel, _close_button(card)]
        w.draw_buttons(surface, t, self.buttons, mouse)
