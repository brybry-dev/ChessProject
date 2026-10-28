# Changelog

Toutes les évolutions notables du projet. Format inspiré de
[Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versionnage
[sémantique](https://semver.org/lang/fr/). Le détail des tâches et des mesures est dans
[RAPPORT_ANALYSE.md](RAPPORT_ANALYSE.md).

## [1.1.1] - 2026-10-28

### Corrigé

- **Windows** : pièces, icônes et pastilles des coups possibles n'apparaissaient pas.
  Le lissage des images utilise maintenant le même filtre sur tous les systèmes, et les
  tests vérifient que ces images ont des pixels visibles, pas seulement leur taille.
- **Windows** : quand la bibliothèque d'images rend les pièces vectorielles (SVG)
  entièrement transparentes, comme sur la CI Windows, les pièces PNG sont utilisées à
  la place, avec un seul avertissement dans le journal.

## [1.1.0] - 2026-10-25

Un adversaire calibré : niveaux resserrés et mesurés en Elo, livre d'ouvertures.

### Ajouté

- **Elo de chaque niveau** affiché dans l'écran « Nouvelle partie » (de ≈ 1250 pour
  Débutant à ≈ 1950 pour Expert), mesuré contre Stockfish 19 bridé.
- **Livre d'ouvertures** de 342 lignes (codes ECO, noms français) : l'IA varie ses débuts,
  plus ou moins longtemps selon le niveau.
- **Nom de l'ouverture** au-dessus de l'historique des coups, et en-têtes PGN `ECO` et
  `Opening` à l'export.
- Moteur UCI : option `OwnBook`, niveau sur mesure `--level-spec`.
- Outils : échelle des niveaux avec Elo chaîné (`tools/calibrate.py`), options UCI par
  moteur dans la mini-ligue (`--option-a` / `--option-b`).

### Modifié

- **Niveaux recalibrés** : chaque niveau bat le précédent avec 60 à 80 % des points
  (contre 90 à 99 % en 1.0). Leur force repose sur un budget de nœuds, identique sur
  toutes les machines ; le temps de réflexion n'est plus qu'un plafond.

### Corrigé

- La réévaluation bruitée des coups d'un niveau sans profondeur maximale pouvait durer
  plus de deux minutes dans une finale simple ; elle est maintenant bornée.

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

[1.1.1]: https://github.com/brybry-dev/ChessProject/releases/tag/v1.1.1
[1.1.0]: https://github.com/brybry-dev/ChessProject/releases/tag/v1.1.0
[1.0.0]: https://github.com/brybry-dev/ChessProject/releases/tag/v1.0.0
[0.1.0]: https://github.com/brybry-dev/ChessProject/commits/master
