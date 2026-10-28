# Changelog

Toutes les évolutions notables du projet. Format inspiré de
[Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versionnage
[sémantique](https://semver.org/lang/fr/). Le détail des tâches et des mesures est dans
[RAPPORT_ANALYSE.md](RAPPORT_ANALYSE.md).

## [1.4.0] - 2026-10-28

Confort : fichiers, clavier, anglais, contrastes.

### Ajouté

- **Plusieurs sauvegardes** : `S` demande un nom (la date et l'heure par défaut), `L`
  ouvre la liste des sauvegardes, la plus récente choisie ; `Suppr` en supprime une. La
  sauvegarde unique des versions précédentes est reprise dans la liste.
- **PGN dans le dossier de son choix** : `E` et `I` ouvrent un choix de fichier
  (dossiers du jeu, personnel, Documents, Téléchargements) ; le dernier dossier utilisé
  est retenu. Un PGN de plusieurs parties affiche la liste des parties (joueurs,
  résultat, tournoi, date, nombre de coups) pour en choisir une.
- **Jouer au clavier** : `Entrée` (ou `Espace`), taper le coup, puis `Entrée`. Saisie
  tolérante (`e4`, `nf3`, `Ne5` pour `Nxe5`, `0-0`, `e2e4`, initiales françaises `Cf3`,
  `Dh5`…) ; un coup illégal, ambigu (avec les coups possibles) ou illisible est signalé.
- **Version anglaise** : toute l'interface, y compris les motifs de fin, les niveaux,
  les cadences et les 268 noms d'ouvertures. Langue au choix sur l'écran « Nouvelle
  partie » et dans Apparence ; au premier lancement, celle du système.
- `tools/contrast.py` : audit des contrastes WCAG 2.2 de toutes les couleurs de
  l'interface.

### Modifié

- **Contrastes au niveau WCAG AA** dans les deux thèmes et sur les quatre échiquiers :
  coordonnées de l'échiquier plus foncées, points des coups possibles plus marqués,
  liseré autour du halo d'échec et des pastilles du bilan, accent plus foncé pour les
  cadres et interrupteurs du thème clair.

## [1.3.0] - 2026-10-28

Moteur plus rapide.

### Modifié

- **Moteur environ 1,8 fois plus rapide** (19 000 positions par seconde au lieu de
  10 000 sur la machine de mesure), sans changer ses coups : les niveaux gardent leur
  force et leur Elo, et réfléchissent environ deux fois moins longtemps (Expert ≈ 2 s).
- **Analyse, indice et moteur UCI plus forts** : la recherche à pleine force élague
  les coups peu prometteurs (PVS, coup nul, réduction des coups tardifs) et voit plus
  loin dans le même temps, environ +24 Elo mesurés à 400 ms par coup. Les niveaux de
  difficulté et le bilan de partie n'utilisent pas cet élagage.
- Moteur UCI : le temps de réflexion par coup (`go wtime/btime`) est calculé comme
  pour la pendule du jeu : un peu moins de temps en début de partie, jamais plus du
  tiers du temps restant.

### Ajouté

- `tools/bench.py` : mesure de la vitesse du moteur (positions par seconde) et profil ;
  option `--features` du moteur UCI pour comparer les techniques de recherche.

## [1.2.0] - 2026-10-28

Mode analyse : variante principale, indice et bilan de la partie.

### Ajouté

- **Variante principale** (touche `V`, ou option dans « Apparence ») : le moteur analyse
  en arrière-plan la position affichée, y compris pendant la revue de la partie. La
  meilleure suite s'affiche au-dessus de l'historique avec son évaluation et sa
  profondeur, et se met à jour pendant la réflexion. La barre d'évaluation reprend
  alors ce score. Désactivée par défaut.
- **Indice** (ampoule dans l'en-tête, touche `B`) : le meilleur coup s'affiche en
  flèche. Option « Indices contre l'IA » pour le désactiver dans les parties contre
  l'IA.
- **Bilan de la partie** (bouton « Bilan » en fin de partie, touche `G`) : courbe
  d'évaluation cliquable pour revoir une position, imprécisions `?!`, erreurs `?` et
  gaffes `??` de chaque camp, perte moyenne par coup. Les symboles s'ajoutent aussi aux
  coups de l'historique. Les seuils, fixés sur des parties de référence, sont
  expliqués dans le rapport d'analyse.

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
