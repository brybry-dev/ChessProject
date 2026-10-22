"""Point d'entrée : ``python -m chessproject`` (et exécutables PyInstaller)."""

import multiprocessing

from chessproject.ui.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
