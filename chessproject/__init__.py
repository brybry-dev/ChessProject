"""ChessProject : jeu d'échecs Pygame avec une IA NegaMax."""

import os

__version__ = "1.0.0"

# Pas de bannière pygame dans la console (jeu, moteur UCI, exécutables).
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
