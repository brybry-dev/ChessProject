# Rapport d'analyse — ChessProject

Jeu d'échecs Python / Pygame avec IA NegaMax. Projet personnel et **vitrine technique** :
priorité à la rigueur, à la maintenabilité, aux tests et à la robustesse.

**Cadre validé (2026-10-22)**
- IA visée : un **bon adversaire pour un humain** (pas de moteur de compétition).
- Fonctionnalités attendues : import/export **PGN**, **cadence** (temps + incrément),
  **niveaux de difficulté** clairs, **packaging** propre en fin de parcours.
- Interface : refonte visuelle « pro » prévue plus tard (phase dédiée).
- Méthode : phase par phase, avec validation entre chaque phase.

| Phase | Contenu | État |
|---|---|---|
| 1. Vérification | Tests, outils statiques, contrôle des correctifs B1–B25 | ✅ ce document, §1 |
| 2. Bilan | Avancement global, points forts | ⏳ |
| 3. Audit | Dette, bugs cachés, typage, cas limites (suite de B26–B40) | ⏳ |
| 4. Feuille de route | Plan court / moyen terme, tâches incrémentales | ⏳ |

Le rapport du 2026-09-06 (étapes 0 à 2, bugs B1–B25) est conservé tel quel en
**Annexe A**, en fin de document.

---

## 1. Phase 1 — Vérification de l'état réel (2026-10-22)

Environnement : Python 3.13, pygame 2.6.1, numpy 2.5.3, pytest 8, ruff 0.16.9,
mypy 2.3.1. SDL en mode `dummy` (sans écran).

### 1.1 Suite de tests

| Commande | Résultat |
|---|---|
| `pytest -q` | **35 réussis, 1 ignoré** (perft lent), 20 sous-tests réussis, ~7 s |
| `RUN_SLOW_PERFT=1 pytest test_perft.py` | **7 réussis, 25 sous-tests réussis** (~150 s) : perft profond toujours exact |

Le chiffre annoncé (« 35 tests verts ») est exact. Deux avertissements :
- `DeprecationWarning` de `fork()` dans un processus multi-thread (`test_ai_performance`).
  C'est le signe avant-coureur de **B32** : Python 3.14 change la méthode de démarrage
  par défaut sous Linux.
- `pkg_resources` déprécié, côté pygame (sans action de notre part).

Ce que les tests **ne couvrent pas**, et qui cache les bugs de §1.4 :
- aucune partie jouée en orientation retournée (`flip_board=True`) ;
- aucun test tactique de l'IA (mat en 1 ou 2, éviter le pat quand on gagne) ;
- aucun test du choix de sous-promotion **passant par l'UI** (popup puis `makeMove`) ;
- aucun test de `R` / `L` quand l'IA a le trait ;
- `test_ai_performance` repose sur le temps réel (5 s) : fragile sur une CI lente, et le
  processus n'est pas tué en cas de dépassement.

### 1.2 Outils statiques

Le dépôt n'a **aucune configuration** ruff ou mypy (pas de `pyproject.toml`) et **aucune CI**.
Les résultats dépendent donc de la version installée.

| Outil | Résultat | Lecture |
|---|---|---|
| `ruff check .` (règles par défaut 0.16) | 156 constats, 115 corrigibles automatiquement | Surtout de la modernisation (`List` → `list`, `Optional` → `X \| None`) |
| `ruff check --select F,B` | **4 constats** : 3 imports inutilisés (`F401`), 1 `B023` (lambda dans une boucle, `ChessMain.py:628`) | Le `B023` est inoffensif ici (lambda appelée tout de suite), mais c'est à nettoyer |
| `ruff check --select E501` | 124 lignes > 88 caractères | Pas de longueur de ligne fixée |
| `ruff format --check` | 10 fichiers sur 12 à reformater | Pas de formateur adopté |
| `mypy .` | **9 erreurs** dans 3 fichiers | Voir ci-dessous |
| `mypy --strict .` | 239 erreurs | `ChessMain.py` n'est pas annoté |

Les erreurs mypy (mode normal) révèlent de vrais défauts de modélisation :
- `enpassant_possible: Tuple[int, int] = ()` (`ChessEngine.py:135,236`) et
  `possiblePin = ()` (`:691`) : la valeur « absente » est un tuple vide au lieu
  d'`Optional[...]`. C'est masqué par des `# type: ignore`.
- `ChessAI.py:28-48` : la table de transposition est typée `Dict[int, ...]` mais indexée par
  une `str`. Signe que la clé de position n'a jamais été fixée (voir B32).
- `ChessAI.py:98,120` : l'évaluation mélange `int` et `float`, puis tronque le résultat (voir B30).
- `fen_utils.py:44` : réutilisation d'une variable `row` avec deux types différents.

### 1.3 Contrôle des correctifs annoncés (B1–B25)

Légende : ✅ conforme au code · ⚠️ corrigé, mais avec un défaut résiduel · ⏳ ouvert
(non annoncé comme corrigé).

| Bug | Statut | Vérification dans le code |
|---|---|---|
| B1 ordre broches/échecs | ✅ | `checkForPinsAndChecks()` est appelé avant la génération (`ChessEngine.py:334`) |
| B2 pat | ✅ | `ChessEngine.py:375-378` |
| B3 matériel insuffisant | ✅ | R/R, R+F/R, R+C/R, fous de même couleur (`:169-198`) |
| B4 pion qui contrôle une case vide | ✅ | `squareUnderAttack` fait une détection directe (`:392-436`) |
| B5 bornes du roque | ⚠️ | Les indices sont bornés, mais rien ne vérifie que **le roi est sur sa case et la tour présente**. En mode retourné, c'est la **dame** qui roque (B26) |
| B6 table de transposition sans bornes | ⏳ | Toujours présent (`ChessAI.py:28,48`) |
| B7 clé de position complète | ⚠️ | Contenu complet, mais la clé est un `hash()` aléatoire d'un processus à l'autre (B32). La case en passant est comptée même sans prise possible |
| B8 promotion dans `Move` | ⚠️ | Moteur conforme. **Le chemin UI perd la pièce choisie** (B29) |
| B9 `__hash__` | ✅ | `ChessEngine.py:772` |
| B10 annulation en PvP | ✅ | `ChessMain.py:683-695` |
| B11 mobilité à chaque feuille | ⏳ | `ChessAI.py:127` |
| B12 jouer/annuler chaque coup pour l'ordonnancement | ⏳ | `ChessAI.py:62-64` |
| B13 texte de fin | ✅ | `ChessMain.py:309-317` |
| B14 `R` qui conserve l'orientation | ⚠️ | Cohérent, mais cela **pérennise la permutation roi/dame**, qui est elle-même un bug critique (B26) |
| B15 défilement | ✅ | `max_scroll` borné (`:144-161`) |
| B16 chronomètre | ✅ | `reset_timer()` (`:77-83`) |
| B17 pickle → JSON | ✅ | JSON versionné, coups rejoués. Les données de promotion sont toutefois faussées en amont (B29) |
| B18 tour promue capturée | ✅ | `:296-305` |
| B19 notation | ⏳ | `return "error"` mort, notation non SAN (`O-O` écrit avec des zéros, pas de `+`, `#` ni désambiguïsation) |
| B20 / B21 effets de bord à l'import | ✅ | `_load_sounds()` / `_configure_logging()`. Reste l'import groupé `import sys, os, logging` |
| B22 `flip_board` global | ⚠️ | Le global a disparu, mais `Renderer` ne retourne que les **rangées** (effet miroir). D'où le bricolage roi/dame (B26) |
| B23 FPS | ✅ | 30 |
| B24 alias des droits de roque | ✅ | Copie défensive (`:274-276`) |
| B25 prise en passant du pion qui donne échec | ✅ | `:355-357` |

**Bilan** : 15 correctifs ✅, 5 ⚠️ (B5, B7, B8, B14, B22) et 4 bugs encore ouverts
(B6, B11, B12, B19), qui étaient bien annoncés comme tels. Le générateur de coups est fiable
**en orientation normale**. Les points ⚠️ mènent tous à des bugs nouveaux (§1.4).

### 1.4 Nouveaux bugs découverts pendant la vérification

Chaque bug ci-dessous a été **reproduit par un script** (fichier hors dépôt). Sa reproduction
deviendra un test de non-régression au moment de la correction.

#### 🔴 Critiques

**B26. Mode retourné : position illégale et roi « perdu » par le moteur.**
`GameState(flip_board=True)` permute roi et dame (`ChessEngine.py:116-120`) pour compenser
un `Renderer` qui ne fait qu'un miroir vertical (`display_row`, colonnes intactes). Or
`white_king_location` reste `(7, 4)`, case qui contient désormais la **dame**. Reproduit :
- un roi attaqué par une tour sur sa colonne donne `in_check == False` (échecs non détectés,
  donc coups illégaux acceptés) ;
- une fois f1 et g1 dégagés, le moteur propose `0-0` **joué par la dame** ;
- la notation, la FEN et la sauvegarde décrivent la position permutée (cases fausses, roi en d1).
Ce mode est activé dès qu'un humain joue les Noirs contre l'IA.
→ Corriger dans la **vue** : rotation à 180° (rangées **et** colonnes) dans `Renderer` et
`square_from_pixel`, libellés a–h et 1–8 en conséquence. Retirer `flip_board` du moteur.
Passer la sauvegarde en version 2 (les fichiers v1 avec `flip_board=true` contiennent une
position permutée : les refuser ou les migrer).

**B27. L'IA prend le pat (et toute nulle) pour une victoire.**
`negamax` renvoie `max_score = -CHECKMATE` quand un nœud interne n'a aucun coup, sans
distinguer mat, pat, 50 coups, répétition ou matériel (`ChessAI.py:34-49`). Reproduit avec
R+D contre R (`7k/8/6K1/8/8/8/8/5Q2 w`) : à profondeur 1, l'IA mate (`Qf8#`) ; à
profondeur 2 (et au-delà), elle joue **`Qf7`, pat**, et l'évalue à +1000.
Les scores de mat ne dépendent pas non plus de la distance : aucune préférence pour le
mat le plus court, et risque de tourner en rond au lieu de conclure.
→ Au nœud sans coup : `-MATE + ply` si échec, `0` sinon. Bornes de recherche `±INF`
strictement supérieures au score de mat.

**B28. Blocage définitif après `R` ou `L` quand l'IA a le trait.**
`_new_game` met `move_undone = True` (`ChessMain.py:601`). Ce drapeau n'est remis à `False`
que dans la branche `move_made` de `run()`, qui n'est jamais atteinte ensuite. Reproduit :
en PvC avec l'humain aux Noirs, après `R` l'IA ne joue plus, et l'humain ne peut pas jouer
non plus (ce n'est pas son trait). En IA contre IA, `R` fige la partie. Seul `Z` débloque,
par effet de bord.
→ Remplacer les drapeaux `move_made` / `move_undone` / `animate` par un état explicite du
contrôleur (machine à états), avec un test pour chaque transition.

#### 🟠 Importants

**B29. La sous-promotion choisie dans l'UI est perdue dans l'historique et la sauvegarde.**
`_try_move` retient la **première** variante légale (promotion en dame). Le popup passe
ensuite le choix par `promotion_callback`, qui écrit la pièce sur le plateau sans mettre à
jour `move.promotion_piece`. Reproduit : promotion en cavalier, plateau `wN`, historique
`a8=Q`, et la partie **rechargée** contient une **dame**.
→ Choisir dans `valid_moves` le `Move` dont `promotion_piece` correspond au choix, puis
supprimer `promotion_callback` du moteur.

**B30. Évaluation tronquée et biaisée.**
`scoreBoard` travaille en unités de pion (`Q=9`) et renvoie `int(total)` : tous les bonus
positionnels (0,1 à 0,7) sont **arrondis à zéro** selon les cas. Par ailleurs, la
« pénalité de répétition » (`-10 × occurrences`) n'est pas signée selon le camp et vaut
toujours au moins 1, puisque la position courante est déjà comptée. Reproduit : la
position initiale est évaluée à **-8**. Conséquence : les Blancs préfèrent une nulle (0) à
une position égale, et les Noirs la fuient.
→ Évaluer en **centipions entiers** (`Q=900`, tables × 100). Retirer la répétition de
l'évaluation : la détection de nulle dans la recherche suffit.

**B31. La racine peut ne renvoyer aucun coup.**
Quand tous les coups mènent au mat, `score > max_score` n'est jamais vrai (`-1000 > -1000`),
donc `best_move = None`. Reproduit sur `k7/8/1K6/8/8/8/8/7R b`. L'UI joue alors un coup **au
hasard** (`ChessMain.py:729-730`). Même effet lors d'un accès à la table de transposition
à la racine (B6).
→ Initialiser `best_move` avec le premier coup, et ne jamais court-circuiter la racine par
la table de transposition.

**B32. Clé de position non déterministe entre processus.**
`get_board_hash_str()` utilise `hash()`, aléatoire d'un processus à l'autre. Reproduit :
avec `PYTHONHASHSEED=1` et `=2`, la position initiale donne deux clés différentes. Avec
`spawn` (Windows, macOS) ou `forkserver` (défaut Linux à partir de Python 3.14), les clés de
`position_history` calculées dans l'UI ne correspondent plus à celles de l'IA : la
détection de répétition est faussée dans la recherche. Cela touche aussi toute sauvegarde
qui contiendrait ces clés.
→ Hachage de **Zobrist** à graine fixe, mis à jour à chaque coup (sert aussi à la table de
transposition et aux performances, étape 3).

**B33. L'UI peut se figer si le processus de l'IA échoue.**
Si le processus enfant lève une exception, il meurt sans rien écrire dans la file, et
`return_queue.get()` (`ChessMain.py:728`) **bloque indéfiniment** la boucle Pygame. Aucune
limite de temps non plus.
→ `get(timeout=...)`, vérification de `exitcode`, solution de repli journalisée. À terme :
une limite de temps passée à l'IA (niveaux de difficulté et cadence).

#### 🟡 Mineurs, dette et cas limites

- **B34.** Logique de jeu dans le rendu : `game_over` est mis à jour dans `draw()`
  (`ChessMain.py:748-754`). Toutes les nulles s'affichent « Impasse » sans motif (pat,
  50 coups, répétition, matériel), car le moteur les range toutes sous `stalemate`.
  Plusieurs choix de règles ne sont pas documentés : la triple répétition et les 50 coups
  sont des nulles **automatiques** (FIDE : à réclamer ; automatiques à 5 répétitions et
  75 coups), et la nulle prime sur un mat donné au 100ᵉ demi-coup (FIDE : le mat prime).
  → Introduire un `GameResult` / une énumération `DrawReason` côté moteur.
- **B35.** Notation (prolonge B19, prérequis du PGN) : `0-0` au lieu de `O-O`. `__str__`
  d'une prise-promotion donne `exd8` sans `=Q`, et `getChessNotation` ajoute ` e.p.`. Il n'y
  a ni `+`, ni `#`, ni désambiguïsation.
- **B36.** FEN : `load_fen` ignore les compteurs de demi-coups et de coups, et ne valide
  rien (nombre de rois, droits de roque sans roi ni tour en place, pion sur la première
  rangée). `to_fen` déduit le numéro de coup de `len(move_log)`, ce qui est faux si la
  partie part d'une FEN où les Noirs ont le trait.
- **B37.** Chargement (`L`) : l'orientation est restaurée, mais **pas** le mode ni la couleur
  de l'humain. Le fichier `saved_game.json` du dossier courant est écrasé par `S` sans
  confirmation.
- **B38.** Performances UI : `p.font.SysFont(...)` est recréé **à chaque image**
  (`Button.draw`, `draw_timer`, `draw_board`, `draw_loading_indicator`). La fenêtre est
  `RESIZABLE` alors que la mise en page est fixe. `position_history_log` fait un
  `deepcopy` par coup (coût quadratique, déjà prévu à l'étape 3).
- **B39.** `negamax` trie en place la liste reçue (`valid_moves.sort`), qui est le cache
  `_valid_moves` du moteur. C'est un effet de bord silencieux, et un piège pour la suite.
- **B40.** Popup de promotion sans annulation (clic hors du popup ignoré, plateau bloqué).
  Code mort : `ChessAI.get_board_hash`, le `return "error"` de la notation. Constantes en
  double (`CHECKMATE`, `DIMENSION` dans 3 fichiers). Le singleton `ResourceManager` ignore
  un `sq_size` passé après sa création.

### 1.5 Synthèse de la phase 1

- La **base de règles est solide** en orientation normale : perft exact, 35 tests, 15
  correctifs confirmés.
- Elle n'est **pas fiable en orientation retournée** (B26) : c'est le chantier le plus
  urgent, car il fausse les règles pour tout joueur des Noirs contre l'IA.
- L'**IA a trois défauts de correction**, et pas seulement de performance : elle prend le
  pat pour une victoire (B27), son évaluation est tronquée et biaisée (B30), et elle peut
  ne renvoyer aucun coup (B31). Ce sont des priorités avant toute optimisation.
- Le **contrôleur** a un blocage reproductible (B28) et un gel possible (B33).
- **Outillage** : sans `pyproject.toml` ni CI, les résultats de ruff et mypy changent avec
  la version installée. À poser en premier (filet de sécurité de la feuille de route).

Prochaine étape, après validation : **Phase 2 — Bilan** (avancement et points forts),
puis **Phase 3 — Audit** détaillé.

---

# Annexe A — Rapport du 2026-09-06 (historique des étapes 0 à 2)

## Rapport initial

Analyse du 2026-09-06. Projet : jeu d'échecs Python / Pygame, IA NegaMax.
Basé sur la structure de la série "Chess Engine in Python" (Eddie Sharick), largement retravaillé.

---

## ✅ État : Étapes 0 et 1 réalisées (2026-09-06)

**Étape 0 — filet de sécurité**
- `requirements.txt` figé, `requirements-dev.txt` ajouté (pytest, ruff, mypy).
- `fen_utils.py` : chargeur FEN + `perft` (utilitaires de test).
- `test_perft.py` : perft sur 6 positions de référence (position initiale, Kiwipete,
  positions 3 à 6). Toutes exactes jusqu'à perft(3) en test rapide, **jusqu'à
  ~4 millions de nœuds** (perft(4)/perft(5)) en test lent (`RUN_SLOW_PERFT=1`).
- `test_rules_regression.py` : 15 tests verrouillant les bugs corrigés.
- `TESTS.md` : mode d'emploi. **27 tests, tous verts.**

**Étape 1 — règles justes.** Corrigés : B1, B2, B3, B4, B5, B7, B8, B9, B18.
La campagne perft a révélé et corrigé **3 bugs supplémentaires** non repérés à la
lecture :
- **B24** — `undoMove` faisait aliaser `current_castling_rights` sur une entrée du
  log, que le `updateCastleRights` suivant corrompait en place → droits de roque
  qui « bavaient » d'une position à l'autre après annulation. Copie défensive ajoutée.
- **B25** — quand un pion venait mettre le roi en échec par une poussée double, la
  prise en passant de ce pion (case d'arrivée ≠ case du pion) était rejetée par le
  filtre de sortie d'échec. Exception ajoutée.
- **B18** confirmé — une tour issue d'une promotion, capturée en a1/h1/a8/h8,
  supprimait à tort un droit de roque (rangée non testée).

Le générateur de coups est désormais **conforme** (perft exact partout).

## ✅ État : Étape 2 (partielle) réalisée (2026-09-06)

Nettoyage UI — corrigés :
- **B10** — `Z` ne fait plus un double `undoMove` qu'en mode contre l'IA, et
  seulement si le dernier coup était celui de l'IA (test `human_now`). En PvP/CvC,
  un seul undo.
- **B13** — `drawEndGameText` centre désormais sur le plateau (décalage
  `LEFT_PANEL_WIDTH`) et non sous le panneau gauche.
- **B14** — `R` recrée `GameState(flip_board=flip_board)` (orientation conservée)
  et remet les pendules à zéro.
- **B15** — le défilement de l'historique est borné en haut : `UIManager` calcule
  `max_scroll` à partir de la hauteur réelle du contenu et `handle_scroll` clampe
  dans `[0, max_scroll]`.
- **B16** — `UIManager.reset_timer()` resynchronise `last_time` au (re)démarrage de
  la partie, après les menus : le temps passé dans les menus n'est plus imputé aux
  Blancs. Appelé aussi sur `R` et sur chargement.
- **B20 / B21** — `p.mixer.init()` + chargement des sons et `logging.basicConfig`
  sortis du niveau module vers `_load_sounds()` / `_configure_logging()`, appelés
  depuis `main()`. Importer `ChessMain` (tests) n'ouvre plus l'audio ni ne crée
  `chess_debug.log`.
- **B23** — `MAX_FPS` passé de 15 à 30.

## ✅ État : Étape 2 terminée (2026-09-06)

Les trois refactors restants de l'étape 2 sont faits :
- **B22** — la variable globale `flip_board` et le `ui_manager` global disparaissent.
  Tout le dessin passe par une classe `Renderer` (plateau, pièces, surbrillances,
  animation, texte de fin) qui porte l'orientation en attribut. Conversions
  pixel→case centralisées dans `Renderer.square_from_pixel`.
- **Découpage de `main()`** — la boucle de 200 lignes devient une classe
  `GameController` (`handle_event` / `update_ai` / `draw` / `run`). `main()` se
  limite à l'initialisation (pygame, sons, logging), au menu et au lancement du
  contrôleur.
- **B17** — la sauvegarde `pickle` est remplacée par `serialization.py` : JSON
  versionné contenant la FEN de départ + la liste des coups. Le chargement
  rejoue les coups par le moteur, l'état est donc toujours conforme aux règles
  courantes (et plus aucun risque d'exécution de code via `pickle`). Couvert par
  `test_serialization.py` (8 tests). `saved_game.json` remplace `saved_game.pkl`.

Détail : le son est désormais aussi joué sur les promotions ; `R` / `L` remettent
les pendules à zéro et lèvent l'état de fin de partie.

Suite de tests : **35 tests, tous verts.**

Restent ouverts : bugs IA (B6, B11, B12) → étapes 3 et 4.

---

## 1. Vue d'ensemble

| Fichier | Rôle | État |
|---|---|---|
| `ChessEngine.py` | Règles, plateau, génération/validation des coups, évaluation nulle | Fonctionnel, quelques bugs de règles |
| `ChessAI.py` | NegaMax + alpha‑bêta + table de transposition + ordonnancement | Fonctionnel mais faible et lent conceptuellement |
| `ChessMain.py` | Pygame : entrées, rendu, menus, sons, sauvegarde, animation, chrono | Fonctionnel, dette UI |
| `test_chess.py` | 6 tests unittest | Passent tous (`python -m unittest test_chess`) |

Points forts : broches (pins) et échecs gérés proprement, roque / en passant / promotion présents, règle des 50 coups + matériel insuffisant + répétition, séparation moteur/IA/UI, IA en `multiprocessing` (UI non bloquée), menus, personnalisation, sons, sauvegarde pickle.

`requirements.txt` liste `numpy` mais il n'était pas installé dans l'environnement ; à figer (`numpy==2.x`).

---

## 2. Bugs (par priorité)

### 🔴 Critiques — fausses règles

**B1. `getValidMoves` utilise des broches périmées.**
`ChessEngine.py:301-302` appelle `getAllPossibleMoves()` **avant** `checkForPinsAndChecks()`. La génération des coups filtre donc les pièces clouées avec les broches de la position **précédente** (et du mauvais camp). Reproduit : une pièce clouée se voit proposer des coups illégaux au premier calcul de la position (et c'est ce calcul qui est mis en cache et utilisé en jeu réel).
→ Corriger : calculer `in_check, pins, checks` d'abord, puis générer les coups.

**B2. Le pat (stalemate) n'est pas détecté.**
`ChessEngine.py:328-341` : `stalemate` n'est mis à `True` que par les règles de nulle (50 coups / matériel / répétition). Le cas « aucun coup légal et roi pas en échec » ne met jamais `stalemate = True`. Reproduit : position de pat classique → `moves=[]`, `stalemate=False`, `checkmate=False`, partie bloquée sans fin de partie.
→ Ajouter : `elif not moves and not self.in_check: self.stalemate = True`.

**B3. `insufficient_material` trop laxiste.**
`ChessEngine.py:162-174` : renvoie `True` dès qu'il y a ≤ 1 pièce hors roi. Donc **Roi + Dame vs Roi** ou **Roi + Tour vs Roi** sont déclarés nulle → impossible de mater avec une dame. C'est aussi ce qui masquait B2 dans certains tests.
→ Ne renvoyer `True` que pour : R vs R ; R+(B ou N) vs R ; R+B vs R+B de même couleur de case. Compter les pièces par type/couleur.

**B4. Cases attaquées par les pions ignorées si la case est vide.**
`getPawnMoves` (`:405-413`) n'ajoute une capture diagonale que si une pièce ennemie est présente. Or `squareUnderAttack` (`:351-362`) s'appuie sur `getAllPossibleMoves`. Conséquence : `getCastleMoves`/`getKingside/QueensideCastleMoves` (`:541-563`) peuvent autoriser un roque qui traverse une case **contrôlée par un pion** (case vide). Les déplacements de roi ne sont pas touchés (ils passent par `checkForPinsAndChecks`, correct).
→ Fournir une vraie fonction « case attaquée » (attaques des pions incluses, cases vides comprises), ou générer les coups de pion diagonaux vers cases vides marqués « attaque seulement ».

**B5. `getKingsideCastleMoves` / `getQueensideCastleMoves` : `IndexError` possible.**
`:555-563` accèdent à `board[row][col±2]` / `col-3` sans borne. En jeu normal les droits de roque protègent, mais toute position chargée / éditée avec le roi hors de sa case et des droits à `True` fait planter le moteur (`IndexError: list index out of range`, reproduit).
→ Vérifier que le roi est bien sur `(7,4)`/`(0,4)` et borner les indices, ou fiabiliser `updateCastleRights`.

### 🟠 Importants

**B6. Table de transposition sans borne (exact/lower/upper).**
`ChessAI.py:27-48` stocke `max_score` comme valeur **exacte** même quand la boucle a été coupée par `alpha >= beta` (c'est alors une borne inférieure). Des scores tronqués sont ensuite relus comme exacts → l'IA peut jouer un coup objectivement mauvais. De plus un hit TT à la racine renvoie `(score, None)` → `best_move = None`.
→ Stocker un flag `EXACT / LOWERBOUND / UPPERBOUND` + la profondeur, et ne couper sur un hit que si la borne est compatible avec `[alpha, beta]`. Toujours stocker le meilleur coup pour le réutiliser en tête d'ordonnancement.

**B7. Hash de position incomplet (répétition + TT).**
`get_board_hash_str` (`:157-160`) et `get_board_hash` (`ChessAI.py:141-146`) ne hachent que `board + white_to_move`. Ni les droits de roque, ni la case d'en passant. Deux positions réellement différentes (au sens FIDE de la triple répétition) sont comptées identiques → nulles réclamées à tort, et collisions dans la TT.
→ Inclure droits de roque + en passant dans la clé. Idéalement : hachage de Zobrist incrémental.
Détail : `str(hash(...))` n'apporte rien, garder l'`int`.

**B8. `moveID` n'encode pas la pièce de promotion.**
`Move.__eq__` (`:646,655-656`) : promotion en Dame et en Cavalier ont le même `moveID` → considérées égales. L'UI force toujours Dame côté moteur pour le popup (`ChessMain.py:583-585` passe `btn.text` mais `makeMove` revalide via `move not in getValidMoves()` avec un `Move` sans info de promotion — ça marche par chance). L'IA ne considère jamais la sous‑promotion.
→ Ajouter `promotion_piece` au `Move`, l'inclure dans `__eq__`/`__hash__`, générer les 4 promotions dans `getPawnMoves`.

**B9. `Move` définit `__eq__` sans `__hash__`.**
Les objets `Move` deviennent non hachables (impossible de faire `set(moves)`). Pas utilisé aujourd'hui mais piège pour l'optimisation de l'ordonnancement / killer moves.

**B10. Undo double inconditionnel.**
`ChessMain.py:645-651` : la touche `Z` fait deux `undoMove()` pour « sauter » le coup de l'IA. En mode **Joueur vs Joueur** cela annule aussi le coup adverse légitime. En début de partie (1 coup joué) le 2ᵉ undo est ignoré, OK, mais le comportement PvP est faux.
→ N'annuler deux fois qu'en mode contre l'IA, et seulement si le dernier coup est celui de l'IA.

**B11. `scoreBoard` appelle `getValidMoves()` à chaque feuille.**
`ChessAI.py:127` : la mobilité recalcule toute la génération légale (pins/checks compris) pour **chaque nœud feuille** du NegaMax. Très coûteux, et la mobilité n'est mesurée que pour le camp au trait (pas différentielle).
→ Mobilité différentielle approchée via `getAllPossibleMoves`, ou la retirer, ou ne l'évaluer qu'en cache.

**B12. `moveOrderingHeuristic` fait make/undo par coup.**
`ChessAI.py:62-64` applique puis annule chaque coup juste pour hacher la position et détecter une répétition, à chaque tri, à chaque profondeur. Coût ~×2 sur toute la recherche pour un signal marginal.
→ Ordonner via MVV‑LVA (valeur capturée − valeur capturante), promotions, puis coup de la TT ; garder la détection de répétition uniquement à la racine.

### 🟡 Mineurs / UI

- **B13.** `drawEndGameText` (`ChessMain.py:319-326`) centre sur `BOARD_WIDTH` sans ajouter `LEFT_PANEL_WIDTH` → texte de fin décalé sous le panneau gauche.
- **B14.** Touche `R` : `ChessEngine.GameState()` recréé sans `flip_board` (`:659`) → en jouant les Noirs, plateau toujours retourné mais roi/dame non permutés. Incohérent.
- **B15.** `handle_scroll` (`:143-146`) n'a pas de borne supérieure → on défile l'historique dans le vide.
- **B16.** Chronomètre : `last_time` initialisé à la création de `UIManager`, avant les menus → tout le temps passé dans les menus est imputé aux Blancs au premier tick.
- **B17.** `load_game` par `pickle` : rechargement d'un objet complet sans contrôle de version/schéma ; `pickle` est aussi un risque de sécurité si le fichier vient d'ailleurs. Préférer une sérialisation FEN + liste de coups.
- **B18.** `updateCastleRights` (`:263-274`) teste `move.end_col in (0,7)` pour une tour capturée sans vérifier `end_row` (rangée 0 ou 7).
- **B19.** `getChessNotation` a un `return "error"` mort après un `if/else` exhaustif ; pas d'annotation d'échec (`+`) ni de mat (`#`), pas de désambiguïsation (`Nbd2`).
- **B20.** `p.mixer.init()` et chargement des sons au niveau module → import de `ChessMain` par les tests initialise l'audio (effets de bord). À déplacer dans `main()`.
- **B21.** `ChessMain.py:6` `import sys, os, pickle, logging` groupés ; `logging.basicConfig` au niveau module écrit toujours `chess_debug.log` dans le cwd.
- **B22.** Le `flip_board` est une variable **globale** mutée un peu partout (`Animation`, `draw_board`, `draw_pieces`, `main`) → source de bugs d'orientation. À passer en paramètre / attribut d'un objet vue.
- **B23.** `MAX_FPS = 15` rend l'UI peu réactive (saisie souris, hover boutons). 30–60 conseillé.

---

## 3. Optimisations

### Correction / robustesse
1. Réordonner B1, ajouter B2, resserrer B3 : c'est le socle « règles justes ».
2. Clé de position complète (B7) → répétition FIDE correcte + TT fiable.
3. Suite de tests « perft » : compter les nœuds à profondeur 1‑4 depuis la position initiale et 4‑5 positions de référence (Kiwipete, etc.) et comparer aux valeurs connues. C'est le seul moyen fiable de valider la génération de coups.

### Performance moteur (gain ×5 à ×50 possible)
4. **Ne pas tout régénérer** : `getKingMoves` appelle `checkForPinsAndChecks` jusqu'à 8 fois ; `getCastleMoves` appelle `squareUnderAttack` (donc `getAllPossibleMoves`) 2 fois de plus. Calculer les cases attaquées **une seule fois** par position (bitboard ou tableau 8×8 `attacked[r][c]`).
5. **`makeMove`/`undoMove` sans `copy.deepcopy`** : `position_history_log` fait un `deepcopy` du dict à chaque coup (`:187`). Utiliser un hash unique + pile de hash, ou un compteur incrémental.
6. `makeMove(validate=True)` par défaut appelle `getValidMoves()` : coûteux quand on sait déjà que le coup vient de la liste valide. L'UI devrait passer `validate=False` pour un coup déjà vérifié.
7. **Représentation du plateau** : `List[List[str]]` avec des chaînes `"wp"` → beaucoup d'allocations et de comparaisons de chaînes. Passer à des entiers (ou bitboards) : gros gain sur l'évaluation et la génération.
8. IA : **quiescence search** (ne s'arrêter que sur position calme) pour supprimer l'effet d'horizon ; **iterative deepening piloté par le temps** (le process a 5 s mais l'IA rend en 0,2 s — profondeur ~3 gâchée) ; **move ordering** MVV‑LVA + killer + history + coup de la TT ; **null‑move pruning**.
9. `scoreBoard` : précalculer les tables `piece_position_scores` en dict d'accès O(1) sans `numpy` (l'indexation numpy scalaire est lente), ou vectoriser toute l'évaluation en une passe numpy.
10. `transposition_table` non borné → fuite mémoire sur longue partie. Ajouter une taille max / remplacement.

### Architecture / qualité
11. Extraire une classe `View`/`Renderer` (fin de `flip_board` global, de `ui_manager` global).
12. `ChessMain.main()` est une fonction de 200 lignes : séparer boucle d'événements, mise à jour, rendu.
13. Constantes dupliquées : `CHECKMATE`, `DIMENSION`, `Color` définis dans 3 fichiers. Un seul module `constants.py`.
14. Typage : `mypy --strict` passerait presque ; corriger les `# type: ignore` sur `enpassant_possible` (utiliser `Optional[Tuple[int,int]]`).
15. `logging` configurable (niveau, fichier) ; retirer les logs bruyants de la boucle.
16. `requirements.txt` : figer les versions ; ajouter `requirements-dev.txt` (pytest, mypy, ruff).
17. CI GitHub Actions : `unittest` + `perft` + `ruff` + `mypy` à chaque push.

---

## 4. Plan pour la suite

### Étape 0 — Filet de sécurité (0,5 j) — ✅ FAIT
- [x] Ajouter `pytest`, `ruff`, `mypy` en dev ; figer `requirements.txt`.
- [x] Écrire les tests **perft** (position initiale + Kiwipete + 4 autres).
- [x] Tests de non‑régression : mat du berger, pat classique, K+Q vs K matable, triple répétition réelle, roque à travers case attaquée par un pion, sous‑promotions, prise en passant exposant le roi.

### Étape 1 — Règles justes (1–2 j) — ✅ FAIT
- [x] B1 (ordre pins/checks), B2 (pat), B3 (matériel insuffisant), B4 (attaque de pion sur case vide), B5 (bornes roque).
- [x] B7 : clé de position = plateau + trait + droits de roque + en passant.
- [x] B8 : `Move.promotion_piece` + `__hash__` + génération des 4 promotions.
- [x] B18 / B24 / B25 (trouvés via perft).
- [x] Perft exact à profondeur 4–5 sur les 6 positions de référence.

### Étape 2 — Nettoyage UI (1–2 j) — ✅ FAIT
- [x] B10 (undo PvP), B13 (texte de fin), B14 (reset + flip), B15/B16 (scroll, chrono).
- [x] Sortir `mixer.init` + sons + `logging.basicConfig` dans `main()`.
- [x] `MAX_FPS` monté à 30.
- [x] Supprimer `flip_board` global → classe `Renderer`.
- [x] Découper `main()` → classe `GameController`.
- [x] Remplacer la sauvegarde `pickle` par FEN + liste de coups (`serialization.py`).

### Étape 3 — Moteur performant (2–4 j)
- [ ] Table `attacked[r][c]` calculée une fois par position ; supprimer les appels répétés à `squareUnderAttack`.
- [ ] Supprimer `copy.deepcopy` de l'historique (pile de hash).
- [ ] Bench avant/après (nœuds/s depuis Kiwipete).

### Étape 4 — IA forte (3–5 j)
- [ ] TT avec bornes (B6) + coup de la TT en tête d'ordonnancement.
- [ ] Move ordering MVV‑LVA + killers + history (retirer make/undo de B12).
- [ ] Quiescence search.
- [ ] Iterative deepening piloté par une **limite de temps** (ex. 2 s) au lieu de `DEPTH` fixe.
- [ ] Évaluation : phase de partie (ouverture/milieu/finale), structure de pions, roi en sécurité réelle, paires de fous.
- [ ] Optionnel : null‑move pruning, aspiration windows.
- [ ] Cible : mat en 2/3 résolu de façon fiable, profondeur effective 5–7 en milieu de partie sous 2 s.

### Étape 5 — Confort (optionnel)
- [ ] Niveaux de difficulté (profondeur/temps/bruit d'évaluation).
- [ ] Import/export FEN et PGN.
- [ ] Horloge d'échecs réelle (blitz/rapide) avec drapeau.
- [ ] Annotation d'échec `+` / mat `#` / désambiguïsation dans la notation.
- [ ] Support UCI → jouer contre Stockfish ou brancher un vrai moteur.
- [ ] Passage éventuel à `python-chess` pour les règles (garder l'IA maison).

### Effort total estimé
Corrections règles + UI : ~1 semaine. Moteur + IA : ~1,5–2 semaines de plus.
Priorité absolue : **Étape 0 puis Étape 1** (une partie avec de fausses règles est plus grave qu'une IA faible).
