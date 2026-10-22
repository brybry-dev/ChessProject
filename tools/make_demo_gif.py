"""Génère le GIF de démonstration du README (``docs/images/demo.gif``) : la « partie de
l'Opéra » (Morphy, 1858) rejouée dans l'interface, avec animations, coups possibles,
flèche et carte de fin. Rendu sans écran, horloges simulées : le résultat est
reproductible.

    python -m pip install -e ".[build]"   # Pillow
    python tools/make_demo_gif.py
"""

import os
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as p
from PIL import Image

from chessproject.core import clock, notation
from chessproject.settings import Settings
from chessproject.ui import app

# Partie de l'Opéra, Paris 1858 : Morphy contre le duc de Brunswick et le comte Isouard.
MOVETEXT = (
    "1. e4 e5 2. Nf3 d6 3. d4 Bg4 4. dxe5 Bxf3 5. Qxf3 dxe5 6. Bc4 Nf6 7. Qb3 Qe7 "
    "8. Nc3 c6 9. Bg5 b5 10. Nxb5 cxb5 11. Bxb5+ Nbd7 12. O-O-O Rd8 13. Rxd7 Rxd7 "
    "14. Rd1 Qe6 15. Bxd7+ Nxd7 16. Qb8+ Nxb8 17. Rd8#"
)
MOVES = [token for token in MOVETEXT.split(" ") if not token.endswith(".")]
WINDOW = (1280, 800)
OUTPUT_SIZE = (800, 500)
ANIMATION_FRAMES = 4
FRAME_MS = 40
HOLD_MS = 650
TARGET = Path(__file__).resolve().parent.parent / "docs" / "images" / "demo.gif"


class Clock:
    def __init__(self) -> None:
        self.s = 1000.0

    def __call__(self) -> float:
        return self.s


def main() -> None:
    p.init()
    screen = p.display.set_mode(WINDOW)
    seconds = Clock()
    now_ms = [0]
    gc = app.GameController(
        screen,
        p.time.Clock(),
        app.UIManager(now=lambda: now_ms[0]),
        app.PieceSet(),
        "PvP",
        True,
        True,
        False,
        time_control=clock.BLITZ_5_0,
        clock_now=seconds,
        settings=Settings(show_eval=True),
        now_ms=lambda: now_ms[0],
    )
    frames: list[tuple[Image.Image, int]] = []

    def capture(duration: int) -> None:
        gc.draw()
        raw = p.image.tobytes(screen, "RGB")
        image = Image.frombytes("RGB", WINDOW, raw).resize(OUTPUT_SIZE, Image.Resampling.LANCZOS)
        frames.append((image, duration))

    capture(900)
    for index, san in enumerate(MOVES):
        move = notation.parse_san(gc.game_state, san)
        if san == "Nxb5":  # montre les coups possibles du cavalier
            gc.square_selected = (move.start_row, move.start_col)
            capture(900)
            gc.square_selected = ()
        if san == "Qb8+":  # flèche tracée au clic droit
            gc.arrows.add(((move.start_row, move.start_col), (move.end_row, move.end_col)))
            capture(900)
        seconds.s += 3 + index % 4
        gc._play(move, animate=True)
        gc.update()
        step = gc.renderer.animation.duration_ms // ANIMATION_FRAMES if gc.renderer.animation else 0
        for _ in range(ANIMATION_FRAMES if step else 0):
            now_ms[0] += step
            capture(FRAME_MS)
        now_ms[0] += 300
        gc.update()
        capture(HOLD_MS)
    for _ in range(3):  # carte de fin de partie
        now_ms[0] += 300
        gc.update()
    capture(3000)

    # Palette commune sans tramage : d'une image à l'autre, seules les zones qui changent
    # diffèrent, ce que le format GIF stocke de façon compacte.
    samples = [frames[0][0], frames[len(frames) // 2][0], frames[-1][0]]
    mosaic = Image.new("RGB", (OUTPUT_SIZE[0], OUTPUT_SIZE[1] * len(samples)))
    for i, sample in enumerate(samples):
        mosaic.paste(sample, (0, OUTPUT_SIZE[1] * i))
    palette = mosaic.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    images = [image.quantize(palette=palette, dither=Image.Dither.NONE) for image, _ in frames]
    first, *rest = images
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    first.save(
        TARGET,
        save_all=True,
        append_images=rest,
        duration=[duration for _, duration in frames],
        loop=0,
        optimize=True,
    )
    print(f"{len(frames)} images -> {TARGET} ({TARGET.stat().st_size // 1024} Ko)")


if __name__ == "__main__":
    main()
