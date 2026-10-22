# Changelog

Toutes les évolutions notables du projet. Format inspiré de
[Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versionnage
[sémantique](https://semver.org/lang/fr/). Le détail des tâches et des mesures est dans
[RAPPORT_ANALYSE.md](RAPPORT_ANALYSE.md).

## [1.0.0] - 2026-10-22

Première version publiée : règles complètes et vérifiées, IA à cinq niveaux, pendule,
PGN, interface refondue, exécutables pour Windows, macOS et Linux.

### Ajouté

- **Exécutables autonomes** pour Windows, macOS et Linux, construits par la CI à chaque
  tag de version et vérifiés par un test de démarrage (partie automatique contre l'IA).
- **Interface** : écran « Nouvelle partie » unique (mode, couleur, niveau, cadence),
  thèmes sombre et clair, 4 échiquiers, pièces vectorielles, fenêtre redimensionnable,
  glisser-déposer, coups possibles, flèches et marques au clic droit, historique SAN
  navigable, matériel pris, barre d'évaluation, carte de fin de partie, préférences
  mémorisées, notifications.
- **Pendule** : Bullet, Blitz, Rapide ou sans limite, incrément Fischer, perte au temps ;
  l'IA gère son temps.
- **Fins de partie** : abandon, proposition de nulle (l'IA accepte selon son évaluation),
  perte au temps, nulles FIDE à 5 répétitions et 75 coups.
- **PGN** : export et import, vérifiés contre python-chess.
- **IA** : NegaMax alpha-bêta, approfondissement itératif borné en temps, table de
  transposition (Zobrist), quiescence, évaluation par phase de jeu, cinq niveaux de
  Débutant à Expert.
- **Moteur UCI** (`chessproject-uci`), mini-ligue avec Elo (`tools/match.py`), suite
  tactique.
- Notation SAN et UCI, FEN validée, sauvegarde JSON versionnée (v3) à écriture
  atomique.
- Outillage : `pyproject.toml`, ruff, mypy (strict sur le moteur), CI sur 3 systèmes,
  perft profond chaque nuit, tests différentiels contre python-chess.

### Corrigé

- Plateau retourné quand on joue les Noirs (B26), pat préféré au mat (B27), IA bloquée
  après `R` / `L` (B28), sous-promotion perdue (B29), évaluation (B30), interface figée
  au crash de l'IA (B33), temps des menus décompté (B44), ressources liées au dossier de
  lancement (B42), pion cloué vers son roi (B46), et la liste complète B26–B46 du rapport.

### Modifié

- Lancement par `chessproject` ou `python -m chessproject` (`ChessMain.py` supprimé).
- Paquet `chessproject/{core,ai,ui}` ; licence MIT.

## [0.1.0] - 2024

Version initiale : jeu Pygame avec IA NegaMax, trois modes de jeu.

[1.0.0]: https://github.com/brybry-dev/ChessProject/releases/tag/v1.0.0
[0.1.0]: https://github.com/brybry-dev/ChessProject/commits/master
