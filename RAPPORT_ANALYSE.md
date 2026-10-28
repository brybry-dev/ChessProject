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
| 2. Bilan | Avancement global, points forts | ✅ §2 |
| 3. Audit | Dette, bugs cachés, typage, cas limites (B26–B45) | ✅ §3 |
| 4. Feuille de route | Plan court / moyen terme, tâches incrémentales | ✅ §4 |

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

Prochaine étape : Phase 2 — Bilan (§2).

## 2. Phase 2 — Bilan et état des lieux (2026-10-22)

### 2.1 Avancement global

Historique : 28 commits, du 2024-12-28 au 2026-10-22. Environ 2 000 lignes de code
applicatif et 470 lignes de tests (36 tests, plus des sous-tests).

Le projet est un **jeu jouable de bout en bout** : menus, trois modes de jeu, IA, sons,
sauvegarde. Les fondations (règles, tests, sérialisation) ont reçu une vraie remise à
niveau en septembre 2026. En revanche, **l'IA et le contrôleur n'ont pas encore été
traités**, et aucune des quatre fonctionnalités attendues n'est commencée.

Maturité par domaine (0 = absent, 5 = niveau vitrine) :

| Domaine | Note | État résumé |
|---|:---:|---|
| Règles du jeu | 4 | Conformes au perft. Pénalisées par B26 (mode retourné) et par l'absence de motif de nulle (B34) |
| Tests | 3 | Bon socle (perft, régressions, sérialisation). Rien sur l'IA, l'UI en mode retourné, ni la promotion via l'UI |
| IA | 1,5 | NegaMax alpha-bêta en processus séparé. Défauts de correction (B27, B30, B31) avant même la question de la force |
| Contrôleur / UI | 2,5 | `GameController` + `Renderer` extraits. États implicites par drapeaux (B28), logique dans le rendu, aspect « prototype » |
| Persistance | 3,5 | JSON versionné, coups rejoués par le moteur. Données de promotion faussées en amont (B29), pas de PGN |
| Outillage / qualité | 1,5 | Dépendances figées, mais ni `pyproject.toml`, ni configuration ruff/mypy, ni CI, ni README |
| Documentation | 2,5 | Rapport d'analyse et `TESTS.md` détaillés. **Pas de README** (installation, captures, architecture) : manque majeur pour un portfolio |
| Packaging | 0 | Script lancé depuis la racine. Ressources en chemins relatifs au dossier courant |

### 2.2 Couverture fonctionnelle

| Fonctionnalité | État |
|---|---|
| Coups légaux, roque, en passant, promotions (4 pièces) | ✅ (⚠️ en mode retourné : B26) |
| Mat, pat, 50 coups, triple répétition, matériel insuffisant | ✅ détection (⚠️ affichage unique « Impasse », règles automatiques non documentées : B34) |
| Modes Joueur contre Joueur, Joueur contre IA (choix de couleur), IA contre IA | ✅ (⚠️ blocage `R`/`L` : B28) |
| Annulation (`Z`), réinitialisation (`R`) | ✅ |
| Sauvegarde / chargement JSON (`S` / `L`) | ✅ (⚠️ B29, B37) |
| Historique des coups avec défilement | ✅ (notation non SAN : B19, B35) |
| Thèmes de plateau (3), sons, animation des coups, surbrillances | ✅ |
| Chronomètre | ⚠️ compte le temps écoulé, sans cadence |
| Import/export **FEN** | ⚠️ utilitaire de test uniquement (`fen_utils.py`), sans entrée dans l'UI |
| Import/export **PGN** | ❌ (prérequis : la notation SAN) |
| **Cadence** (temps + incrément, perte au temps) | ❌ |
| **Niveaux de difficulté** | ❌ (profondeur fixe `DEPTH = 3`) |
| **Packaging** (exécutable, ressources embarquées) | ❌ |
| Abandon, proposition de nulle, plateau redimensionnable | ❌ |

### 2.3 Forces de l'architecture et choix pertinents

Ce qui est bien fait, et qu'il faut **préserver** pendant la suite :

1. **Un perft comme juge de paix.** Six positions de référence (dont Kiwipete), en version
   rapide et en version profonde (environ 4 M de nœuds). C'est la pratique standard des
   moteurs d'échecs, et elle a déjà prouvé son utilité : trois bugs (B18, B24, B25)
   invisibles à la lecture ont été trouvés ainsi. Tout refactor du moteur (Zobrist, entiers)
   pourra se faire sans crainte.
2. **Des tests de non-régression nommés d'après les règles** (`test_cannot_castle_through_square_attacked_by_pawn`, etc.) :
   ils se lisent comme une spécification.
3. **Une génération légale fondée sur les broches et les échecs**, et non sur « jouer, puis
   tester l'échec, puis annuler » : algorithme correct et plus rapide, avec un cas limite
   délicat (l'en passant qui découvre une attaque sur la rangée) traité explicitement.
4. **Une sérialisation qui rejoue les coups** au lieu de restaurer un objet : le format est
   lisible, versionné, sûr (plus de pickle) et toujours conforme aux règles courantes. Le
   rejet des versions inconnues prépare les migrations, ce qui sera utile pour B26.
5. **L'IA dans un processus séparé** : l'UI reste réactive pendant la réflexion, et
   `terminate()` permet d'interrompre l'IA (annulation, réinitialisation).
6. **Un découpage moteur / IA / UI respecté** : `ChessEngine` n'importe ni Pygame ni l'IA. Le
   moteur est donc testable seul. C'est la base d'une future architecture en couches.
7. **Des refactors récents dans le bon sens** : `Renderer` (l'orientation devient un
   attribut), `GameController` (boucle découpée en `handle_event` / `update_ai` / `draw`),
   plus d'effets de bord à l'import. `test_game_controller.py` montre même un procédé
   d'injection (faux `Process` / `Queue`), réutilisable pour tester l'UI sans écran.
8. **Une hygiène du dépôt** correcte : dépendances figées, outils de développement séparés,
   `.gitignore` qui exclut sauvegardes et journaux, commits en français et descriptifs.

### 2.4 Faiblesses structurelles (détaillées en phase 3)

Ce sont des constats d'ensemble, au-delà des bugs ponctuels :

- **Représentation par chaînes** (`"wp"`, `"--"`, des tuples vides pour « absent ») : peu
  typée, lente, et source des erreurs mypy.
- **`GameState` porte trop de responsabilités** : règles, historique, détection des nulles
  et caches mutables (`pins` vidé pendant la génération, `_valid_moves` trié par l'IA).
- **Pas de modèle de résultat de partie** (`checkmate` / `stalemate` en booléens) : bloque
  l'affichage du motif, le PGN (`[Result]`) et la cadence (perte au temps).
- **Contrôleur piloté par des drapeaux** (`move_made`, `move_undone`, `animate`,
  `ai_thinking`) au lieu d'un état explicite : origine directe de B28.
- **Deux tests verrouillent un comportement fautif** :
  `test_roundtrip_preserves_flip_board` consacre la permutation roi/dame (B26), et
  `test_roundtrip_preserves_promotion_choice` contourne le chemin UI fautif (B29). Ils
  devront être réécrits avec la correction.

### 2.5 Synthèse de la phase 2

Le projet a des **fondations de règles de niveau professionnel** (perft, tests,
sérialisation sûre). C'est l'atout principal de la vitrine. L'écart avec l'objectif se
situe sur trois fronts :
**(1)** correction de l'IA et du contrôleur ;
**(2)** outillage de vitrine (CI, `pyproject.toml`, README) ;
**(3)** les quatre fonctionnalités attendues, qui reposent toutes sur un socle commun à
construire : un modèle de résultat, la notation SAN, et une IA bornée en temps.

Prochaine étape : Phase 3 — Audit détaillé (§3).

## 3. Phase 3 — Audit détaillé (2026-10-22)

Cette phase complète les bugs B26–B40 (§1.4) par une lecture module par module.
Elle ajoute cinq constats nouveaux (B41–B45), tous **reproduits ou vérifiés dans le code**.

### 3.1 Nouveaux constats

**B41 🟠. Position de départ non validée (FEN ou sauvegarde).**
`load_fen`, et donc `load_game` via `start_fen`, accepte n'importe quel contenu.
Reproduit :
- `4k3/p7/8/8/8/8/P7/4K3 w K` : le moteur propose `0-0` **sans tour en h1**. Le roi
  arrive en g1 et aucune tour n'apparaît.
- Une position **sans roi** est acceptée sans erreur : le moteur garde la case par défaut
  `(7, 4)` et calcule des échecs sur une case vide.

Le fichier de sauvegarde, modifiable à la main, est donc une porte d'entrée vers des états
incohérents.
→ Validation dans `load_fen` : un roi par camp, droits de roque cohérents avec le roi et
la tour en place, pas de pion sur les rangées 1 ou 8, camp qui n'a pas le trait non en
échec, case en passant plausible. Lever une `FenError` explicite.

**B42 🟠. Ressources et fichiers relatifs au dossier courant.**
`images/`, `sounds/`, `saved_game.json` et `chess_debug.log` sont résolus depuis le dossier
où le jeu est lancé (`ChessMain.py:37,525`, `serialization.py:23`). Lancé depuis un autre
dossier, le jeu plante (`FileNotFoundError` sur la première image). Cela **bloque le
packaging**.
→ Ressources via `Path(__file__).parent` ou `importlib.resources`. Données utilisateur
(sauvegardes, journal) dans un dossier par utilisateur (`platformdirs`).

**B43 🟡. Journalisation.**
Le niveau est `DEBUG`, dans un fichier sans rotation, et chaque coup est journalisé.
Les appels passent par le logger racine en f-string (12 occurrences `LOG015`, plus le
formatage fait même quand le message n'est pas émis).
→ `logger = logging.getLogger(__name__)` par module, arguments `%s`, niveau `INFO` par
défaut, `RotatingFileHandler`.

**B44 🟠. Le temps passé dans les menus en jeu est imputé au joueur au trait.**
Les menus `C` (couleurs) et `H` (raccourcis) ont leur propre boucle bloquante. Au retour,
`update_timer` ajoute tout le temps écoulé depuis le dernier tick au joueur au trait
(`ChessMain.py:85-94`). C'est B16 qui revient par une autre voie. Même effet, plus petit,
pendant `animate_move`. Par ailleurs, `Z`, `R` et `L` ne restaurent pas les pendules.
Ce n'est pas grave avec un chronomètre informatif, mais c'est **bloquant pour la cadence** :
perdre au temps à cause d'un menu n'est pas acceptable.
→ Horloge pilotée par le contrôleur (`pause` / `resume`) et alimentée par un temps
injectable, ce qui la rend testable sans attendre.

**B45 🟡. Boucles bloquantes et sortie du programme.**
`animate_move` et les quatre menus tournent dans leur propre boucle. Pendant l'animation,
aucun événement n'est traité : la fermeture de fenêtre est ignorée. Les menus appellent
`sys.exit()` sans `p.quit()`. Le processus de l'IA n'est pas `daemon` : à la fermeture
pendant sa réflexion, l'interpréteur **attend la fin de la recherche** avant de quitter.
→ Une seule boucle avec des « scènes » (menu, partie, popup) et une animation avancée
d'un pas par image. `daemon=True`, plus `terminate()` à la fermeture.

### 3.2 Audit par module

#### `ChessEngine.py` (811 lignes) — règles

| Sujet | Constat | Cible |
|---|---|---|
| Représentation | Cases en `str` (`"wp"`, `"--"`). Absence codée par `()` (en passant, broche), d'où les `# type: ignore` | `Piece` (énumération ou entier), `Square = tuple[int, int]`, `Optional[Square]` |
| Responsabilités | `GameState` mélange plateau, génération, historique, détection des nulles et caches (≈ 20 attributs mutables) | Séparer `Board` / position, `MoveGenerator`, `GameRecord` (historique et nulles), `GameResult` |
| État caché | `self.pins` est **vidé** pendant la génération (`pop`). `_valid_moves` est partagé et trié en place par l'IA (B39). Les drapeaux `checkmate` / `stalemate` sont des effets de bord de `getValidMoves()` | Génération sans effet de bord. Statut calculé par une fonction pure `status(position) -> GameResult` |
| Historique | Cinq piles parallèles (`move_log`, `enpassant_possible_log`, `castle_rights_log`, `fifty_move_counter_log`, `position_history_log`) et un `deepcopy` du dictionnaire à chaque coup | Une seule pile d'`UndoInfo` (droits, en passant, 50 coups, clé Zobrist) et une liste de clés pour la répétition |
| Duplication | `getRook/Bishop/QueenMoves` répètent la même boucle ; `squareUnderAttack` et `checkForPinsAndChecks` refont les rayons | Une fonction `_slide(directions)` et des tables de directions partagées |
| `flip_board` | Concept d'affichage dans le moteur (B26) | À supprimer du moteur |
| Nommage | `camelCase` (`getValidMoves`, `endRow`) mêlé au `snake_case` (`white_to_move`, `_add_pawn_move`) | `snake_case` (PEP 8), renommage outillé, en un seul commit |
| `Move` | Égalité par `moveID` (correct), mais `piece_moved` / `piece_captured` copiés du plateau à la création | `@dataclass(frozen=True, slots=True)` |
| Notation | `getChessNotation` / `__str__` non SAN (B19, B35) | Module `notation.py` : `to_san(position, move)` et `parse_san` (prérequis du PGN) |
| Constantes | Tables positionnelles en `numpy`, accès scalaire lent, seule utilisation de numpy dans le projet | Tuples en centipions. **Retirer `numpy`** des dépendances (packaging plus léger) |

#### `ChessAI.py` (152 lignes) — recherche et évaluation

| Sujet | Constat | Cible |
|---|---|---|
| Correction | B27 (pat ou nulle vu comme un mat), B30 (évaluation tronquée et biaisée), B31 (racine sans coup), B6 (table de transposition sans bornes) | À corriger **avant** tout gain de force, chaque correction accompagnée d'un test tactique |
| Scores | `CHECKMATE = 1000` sert à la fois de score de mat et de borne alpha-bêta | `INF = 10**6`, `MATE = 10**5`, `mate - ply`, centipions |
| Recherche | Approfondissement itératif sans réutilisation (accès à la table de transposition qui renvoie `None`), pas de limite de temps, pas de quiescence | `Searcher` avec `SearchLimits(depth, movetime, nodes)`, table de transposition avec bornes et coup mémorisé, quiescence, MVV-LVA et coups tueurs |
| Coût | B11 (génération légale complète à chaque feuille), B12 (jouer/annuler chaque coup pour le trier) | Mobilité retirée ou approchée, tri sans `makeMove` |
| Évaluation | Sécurité du roi calculée pour le seul camp au trait, bonus de centre ajouté aux tables (doublon), pas de phase de partie | Évaluation symétrique (`eval(position)` du point de vue blanc), tables début / fin de partie interpolées. **Test de symétrie** : `eval(p) == -eval(miroir(p))` |
| Interface | `findBestMove(gs, moves, queue)` couplé à `multiprocessing` | Fonction pure `search(position, limits) -> SearchResult(move, score, depth, nodes, pv)`. Le processus séparé devient un détail du contrôleur |
| Code mort | `get_board_hash`, `findRandomMove`, import `Callable` | À supprimer |

#### `ChessMain.py` (809 lignes) — interface et contrôleur

| Sujet | Constat | Cible |
|---|---|---|
| Typage | 0 annotation : c'est la plus grosse partie des 239 erreurs `mypy --strict` | Annoter en même temps que le découpage |
| Contrôleur | Drapeaux implicites (B28), fin de partie déterminée dans `draw()` (B34), validation en double (`makeMove(valid_move)` revalide un coup déjà légal) | Machine à états explicite (`HumanToMove`, `AiThinking`, `Animating`, `PromotionChoice`, `GameOver`), transitions testées |
| Rendu | Polices recréées à chaque image (B38), couleurs et dimensions en dur, mise en page fixe malgré `RESIZABLE` | `Theme` (couleurs, polices précalculées), mise en page calculée depuis la taille de fenêtre |
| Menus | Quatre fonctions quasi identiques (environ 40 lignes chacune), boucles bloquantes (B45) | Un widget `Menu(title, items)` réutilisable, et des scènes |
| IA | `Process` + `Queue` sans délai d'attente ni contrôle d'erreur (B33) | `AiWorker` (`concurrent.futures.ProcessPoolExecutor` ou processus `daemon`) avec délai d'attente, annulation et repli |
| Singleton | `ResourceManager.__new__` ignore les paramètres après le premier appel | Instance simple injectée (c'est déjà le cas, le singleton est inutile) |
| Fichier | 809 lignes, 6 responsabilités | Module `ui/` : `controller.py`, `renderer.py`, `widgets.py`, `clock.py`, `assets.py` |

#### `serialization.py` / `fen_utils.py` — persistance

- Points solides : version vérifiée, coups rejoués, `json` (pas d'exécution de code).
- B29 (promotion faussée en amont), B36 (compteurs FEN), B37 (mode non sauvegardé),
  B41 (position non validée).
- `fen_utils.py` est documenté comme « utilitaire de test » mais il est **utilisé en
  production** par `serialization.py`. Il doit devenir un module à part entière (`fen.py`),
  et `perft` doit rejoindre les tests.
- `to_fen` affiche `KQkq` d'après les seuls drapeaux (« à titre indicatif »). Après B26,
  la FEN devient exacte et peut servir de format de position de référence.
- Format v2 : `{"version": 2, "start_fen", "moves": [UCI…], "mode", "human_color",
  "clock": {...}, "result"}`. Les coups au format UCI (`e7e8n`) sont plus lisibles que
  des index et servent aussi au PGN.

#### Tests et outillage

| Sujet | Constat | Cible |
|---|---|---|
| Lanceurs | `unittest` partout, `pytest` en dépendance, pas de configuration | `pyproject.toml` (`[tool.pytest]`, marqueur `slow` à la place de la variable d'environnement `RUN_SLOW_PERFT`) |
| Duplication | `test_chess.py` redéfinit `Color` et importe `numpy` sans l'utiliser | Nettoyer, mutualiser les fabriques de positions (`conftest.py`) |
| Couverture | Aucune mesure | `pytest-cov`, seuil progressif (moteur ≥ 90 %) |
| Tests qui consacrent un bug | `test_roundtrip_preserves_flip_board` (B26), `test_roundtrip_preserves_promotion_choice` (B29) | À réécrire avec les corrections |
| Tests fragiles | `test_ai_performance` dépend du temps réel | Limite par nombre de nœuds ou profondeur fixe, plus tests tactiques |
| Manquants | IA (mat en 1/2/3, éviter le pat, capturer une pièce en prise), plateau retourné, contrôleur (`R`/`L`/`Z` dans chaque état), horloge, validation FEN | Voir la feuille de route |
| Tests différentiels | `python-chess` en option dans `requirements-dev.txt` mais non utilisé | Comparaison aléatoire : N parties aléatoires, mêmes coups légaux et même statut à chaque demi-coup. Filet idéal avant les refactors du moteur |
| CI | Aucune | GitHub Actions : ruff, mypy, pytest (rapide) sur Linux, Windows et macOS (cela détecte B32 et B42), perft lent la nuit |

### 3.3 Sécurité et robustesse

Pour un jeu local, la surface d'attaque est faible. La seule entrée externe est le fichier
de sauvegarde (bientôt PGN et FEN importés).

- ✅ Plus d'exécution de code (pickle supprimé), coups rejoués et validés par le moteur.
- ⚠️ Positions de départ non validées (B41). Entrées mal formées rejetées par des
  exceptions génériques (`ValueError` / `TypeError`), attrapées par un `except Exception`
  large dans l'UI (`ChessMain.py:706`) qui ne prévient pas l'utilisateur.
  → Exceptions dédiées (`SaveFormatError`, `FenError`, `PgnError`) et message affiché.
- ⚠️ Import PGN à venir : limiter la taille du fichier et le nombre de coups, et ne
  jamais faire confiance aux en-têtes (`[FEN]`, `[SetUp]`).
- ⚠️ Écriture de la sauvegarde non atomique : un arrêt pendant l'écriture corrompt
  le fichier. → Écrire dans un fichier temporaire puis `os.replace`.

### 3.4 Cas limites non gérés (récapitulatif)

| Cas | Référence |
|---|---|
| Jouer les Noirs contre l'IA (plateau retourné) | B26 |
| L'IA gagnante qui pate ; l'IA perdante sans coup renvoyé | B27, B31 |
| `R` / `L` quand l'IA a le trait ; crash du processus de l'IA | B28, B33 |
| Sous-promotion via l'UI ; annulation du popup | B29, B40 |
| Mat au 100ᵉ demi-coup (le mat doit primer) ; 5 répétitions et 75 coups (FIDE) | B34 |
| Position FEN sans roi, roque sans tour, compteurs FEN | B36, B41 |
| Menus ou animation pendant que la pendule tourne ; annulation et pendules | B44 |
| Fermeture pendant la réflexion de l'IA ou pendant une animation | B45 |
| Lancement depuis un autre dossier ; Windows et macOS (`spawn`) | B42, B32 |
| Redimensionnement de la fenêtre | B38 |
| Chargement d'une partie d'un autre mode ou d'une autre couleur | B37 |
| **À venir** : perte au temps contre matériel insuffisant (FIDE : nulle) ; incrément après le coup ; PGN avec variantes et commentaires (à ignorer proprement) | Cadence, PGN |

### 3.5 Architecture cible

Elle se construit progressivement, sans grande réécriture. Chaque étape est validée par
le perft et les tests.

```
chessproject/
  core/            # aucune dépendance à pygame
    types.py       # Piece, Color, Square
    position.py    # plateau + make/unmake + UndoInfo + Zobrist
    movegen.py     # génération légale (algorithme actuel, conservé)
    result.py      # GameResult, DrawReason, status(position)
    notation.py    # SAN <-> Move, UCI
    fen.py  pgn.py # import/export validés
  ai/
    evaluate.py    # centipions, tables début/fin de partie
    search.py      # negamax + table de transposition + quiescence + limites
    levels.py      # niveaux de difficulté -> SearchLimits + bruit
  app/
    controller.py  # machine à états, sans dessin
    clock.py       # cadence (temps + incrément), horloge injectable
    worker.py      # IA hors processus (délai d'attente, annulation)
    persistence.py # format v2, écriture atomique
  ui/              # pygame uniquement ici
    scenes.py  renderer.py  widgets.py  theme.py  assets.py
tests/
```

Règle de dépendance, vérifiable en CI : `core` ← `ai` ← `app` ← `ui`. Aucun module de
`core` n'importe `pygame`.

### 3.6 Synthèse de la phase 3

- **Bloquants pour la vitrine** : B26, B27, B28 (correction), puis B30, B31, B29, B33, B44.
- **Prérequis des fonctionnalités attendues** :
  - PGN : SAN (B19, B35), `GameResult` (B34), validation FEN (B41) ;
  - cadence : horloge pilotée (B44), `GameResult` ;
  - niveaux : recherche bornée en temps (B6, B30, B31) ;
  - packaging : ressources (B42), retrait de numpy, CI multi-OS.
- **Dette principale** : `GameState` trop large et à effets de bord, contrôleur à
  drapeaux, `ChessMain.py` sans types. On la traite progressivement, protégé par le perft
  et par des tests différentiels contre `python-chess`.

Prochaine étape : Phase 4 — Feuille de route (§4).

## 4. Phase 4 — Feuille de route (2026-10-22)

### 4.1 Règles de travail

1. **Une tâche = un commit (ou une PR) qui passe** : tests, perft rapide, ruff et mypy au vert.
2. **Un bug se corrige test d'abord** : le test qui reproduit le bug échoue avant le
   correctif et passe après. Les scripts de reproduction de la phase 1 servent de point de
   départ.
3. **Un refactor du moteur ne change aucun comportement** : perft exact, tests
   différentiels identiques. Le refactor et les changements de comportement ne vont jamais
   dans le même commit.
4. **Pas de grande réécriture** : l'architecture cible (§3.5) s'atteint par déplacements
   successifs.
5. Tailles : **S** ≤ ½ jour · **M** ≈ 1 jour · **L** 2–3 jours.

### 4.2 Vue d'ensemble

| Jalon | Objectif | Horizon | Effort |
|---|---|---|---|
| **J0** Outillage ✅ | Rendre la qualité mesurable et automatique | Court terme | ~1,5 j |
| **J1** Correction ✅ | Plus aucun bug connu bloquant (règles, IA, contrôleur) | Court terme | ~4–5 j |
| **J2** Socle moteur ✅ | Types, résultat de partie, SAN, FEN validée, moteur sans effets de bord | Moyen terme | ~5–6 j |
| **J3** IA ✅ | Un bon adversaire, borné en temps, avec des niveaux | Moyen terme | ~5–7 j |
| **J4** Fonctionnalités ✅ | PGN, cadence, niveaux dans l'UI, sauvegarde v2 | Moyen terme | ~5–6 j |
| **J5** Interface pro | Scènes, thème, mise en page adaptative, finition visuelle | Fin de parcours | ~5–7 j |
| **J6** Packaging et vitrine | Exécutables, README illustré, version publiée, UCI minimal (optionnel) | Fin de parcours | ~3–4 j |

Dépendances : J0 → J1 → J2 → {J3, J4} → J5 → J6. Dans J4, PGN et cadence ne dépendent
que de J2. Les niveaux de difficulté dépendent de J3.

---

### 4.3 Court terme

#### J0 — Outillage (filet de sécurité de la vitrine)

> ✅ **Réalisé le 2026-10-22** : `pyproject.toml` (J0.1), ruff appliqué (J0.2), mypy de 40 à 0
> erreur, sans `# type: ignore` dans le moteur (J0.3), CI `ci.yml` + `nightly.yml` (J0.4),
> `README.md` (J0.5). Points restants : licence à choisir par l'auteur ;
> `test_ai_performance` dépend du temps réel, il est donc fragile sur les runners
> Windows et macOS lents (à reprendre en J1.7).

| # | Tâche | Critère d'acceptation | Taille |
|---|---|---|---|
| J0.1 | `pyproject.toml` : métadonnées, dépendances, configuration `ruff` (`E,F,B,I,UP,SIM`, ligne de 100), `ruff format`, `mypy` (strict pour `ChessEngine`, `serialization`, `fen_utils`, souple pour `ChessMain`), `pytest` (marqueur `slow` à la place de `RUN_SLOW_PERFT`) | `ruff check`, `ruff format --check`, `mypy` et `pytest -m "not slow"` passent localement. Les fichiers `requirements*.txt` sont générés depuis le pyproject ou supprimés | M |
| J0.2 | Passage `ruff --fix` + `ruff format` (commit purement mécanique) et corrections des 4 constats `F/B` | Diff sans changement de comportement, tests au vert | S |
| J0.3 | Corriger les 9 erreurs mypy : `Optional[Square]` pour l'en passant et les broches, clé de la table de transposition, scores `int` | `mypy` sans erreur ni `# type: ignore` dans le moteur | S |
| J0.4 | CI GitHub Actions : lint, types, tests rapides sur **Linux, Windows et macOS** (Python 3.12 et 3.13), perft lent la nuit | Badge vert sur les 3 OS. *(Révisé : les tests actuels ne couvrent ni B32 ni B42 ; leurs tests multi-processus et hors du dossier courant arrivent avec J1.6 et J1.9.)* | M |
| J0.5 | `README.md` minimal : présentation, installation, lancement, tests, lien vers ce rapport | Lisible sur GitHub. Captures d'écran remises à J6 | S |

#### J1 — Correction (aucun bug bloquant connu)

> ✅ **Réalisé le 2026-10-22**, une tâche = un commit, chaque bug verrouillé par un test qui
> échouait avant le correctif. B26, B27, B28, B29, B30, B31, B32, B33, B40, B42, B43, B44 et
> B45 sont corrigés ; B11, B12 et B39 aussi, au passage (J1.5). Suite : 82 tests rapides (contre
> 35), perft rapide et profond inchangés.
> Écarts avec le plan :
> - J1.4 contient le retrait de la pénalité de répétition, sans lequel le test du pat
>   ne pouvait pas passer.
> - J1.2 supprime le drapeau `move_undone` plutôt que de le corriger : il n'avait pas
>   d'autre effet.
> - J1.9 ajoute la dépendance `platformdirs`.
> - J1.7 borne la réflexion de l'IA à 30 s ; la limite par niveau viendra en J3.2.

| # | Tâche | Critère d'acceptation | Taille |
|---|---|---|---|
| J1.1 | **B26** Rotation à 180° dans `Renderer` / `square_from_pixel` (rangées et colonnes, libellés a–h et 1–8). Suppression de `flip_board` du moteur. Sauvegarde **v2** qui refuse ou migre les v1 retournées. Réécriture de `test_roundtrip_preserves_flip_board` | Test : en mode Noirs, `GameState()` standard, roi en e1/e8, échec détecté, roque par le roi. Test de rendu : le clic sur e2 en vue retournée donne la case logique e2. Perft inchangé | M |
| J1.2 | **B28** Corriger le déblocage après `R` / `L` (correctif minimal d'abord ; la machine à états vient en J2/J5) | Test contrôleur : PvC avec l'humain aux Noirs, puis `R`, puis l'IA joue. IA contre IA, puis `R`, puis la partie reprend | S |
| J1.3 | **B29 + B40** Le popup sélectionne le `Move` dont `promotion_piece` correspond au choix. Suppression de `promotion_callback`. Annulation par `Échap` ou par un clic hors du popup | Test contrôleur : promotion en cavalier, historique `a8=N`, sauvegarde puis rechargement donnent `wN` | S |
| J1.4 | **B27 + B31** Nœud sans coup : `-MATE + ply` si échec, sinon 0. `INF` distinct de `MATE`. `best_move` initialisé au premier coup. Pas d'accès à la table de transposition à la racine | Tests tactiques : K+D contre R mate sans pater (profondeurs 1 à 4). Racine perdante : renvoie un coup. Mat en 2 trouvé et choisi le plus court | M |
| J1.5 | **B30** Évaluation en centipions entiers, retrait de la pénalité de répétition, mobilité retirée (traite aussi B11) | Tests : `eval(position initiale) == 0`. **Symétrie** `eval(p) == -eval(miroir(p))` sur 20 positions. Plus de `int()` final | S |
| J1.6 | **B32** Clé de position déterministe (provisoire : chaîne de type FEN sans les compteurs ; Zobrist en J3.1) | Test : clé identique sous `PYTHONHASHSEED=1` et `=2` (sous-processus). Le `xfail` de CI levé | S |
| J1.7 | **B33 + B45** Processus d'IA `daemon`, `get(timeout)`, vérification d'`exitcode`, repli journalisé, `terminate()` à la fermeture | Test : une IA factice qui lève une exception ne fige pas la boucle ; la fermeture pendant la réflexion est immédiate | S |
| J1.8 | **B44** Pause de l'horloge pendant les menus en jeu et l'animation ; horloge à temps injectable | Test : 10 s simulées dans un menu ne sont pas imputées | S |
| J1.9 | **B42** Ressources via `Path(__file__)` ; sauvegarde et journal dans un dossier utilisateur (`platformdirs`) ; **B43** logger par module, `INFO`, rotation | Lancement depuis un autre dossier : OK. Le `xfail` multi-OS est levé | S |

**Fin du court terme (J0 + J1, ~6 jours)** : CI verte sur 3 OS, B26–B33 et B40–B45
corrigés, chacun verrouillé par un test. C'est un bon moment pour un premier tag `v0.2`.

---

### 4.4 Moyen terme

#### J2 — Socle moteur (prérequis des fonctionnalités)

> **Avancement (2026-10-22)**
> - J2.1 ✅ : les tests différentiels contre python-chess ont trouvé **B46**. Un pion cloué ne
>   pouvait pas avancer le long du clouage en direction de son roi (ex. pion noir d6, roi d4,
>   tour blanche d8 : `d6-d5` refusé). Aucune des 6 positions perft ne contenait ce cas. Après
>   correction, les 1 000 parties aléatoires coïncident avec python-chess.
> - J2.2 ✅ : `GameResult` / `Termination`. Le mat prime sur les 50 coups, auparavant déclarés
>   nuls au 100ᵉ demi-coup. L'UI affiche le motif de fin.
> - J2.3 ✅ : numpy retiré, tables d'évaluation déplacées dans l'IA, `Move` avec `__slots__`.
>   **Écart** : les pièces restent des chaînes (`"wp"`) ; leur passage en entiers est reporté
>   en J3, à décider selon les mesures.
> - J2.4 ✅ : pile d'`UndoInfo`. Perft +24 %, et le coût d'un coup reste constant au fil de la
>   partie.
> - J2.5 ✅ : module `notation` (SAN/UCI), identique à python-chess sur ~160 000 demi-coups.
>   Historique SAN dans l'UI.
> - J2.6 ✅ : `FenError` et 13 règles de validation, compteurs FEN. Deux FEN de test
>   illégales sont corrigées.
> - J2.7 ✅ : `snake_case` partout, règles ruff `N`, paquet `chessproject/{core,ai,ui}` avec
>   `tests/`. Commande `chessproject` ou `python -m chessproject`, ressources incluses dans
>   le wheel.
> - Mesure globale : perft(3) Kiwipete passe de 98 k à 147 k nœuds/s.

| # | Tâche | Critère d'acceptation | Taille |
|---|---|---|---|
| J2.1 | **Tests différentiels** contre `python-chess` (dépendance de développement uniquement) : parties aléatoires, mêmes coups légaux et même statut à chaque demi-coup | 1 000 parties en mode `slow`, 50 en mode rapide, sans divergence | M |
| J2.2 | **`GameResult` / `DrawReason`** (mat, pat, 50/75 coups, 3/5 répétitions, matériel insuffisant, et plus tard abandon, temps, accord). Fonction pure `status(position)`. Le mat prime sur les 50 coups. Règles automatiques ou à réclamer documentées (**B34**) | L'UI affiche le motif. Test : mat au 100ᵉ demi-coup gagné. `game_over` retiré de `draw()` | M |
| J2.3 | **Types** : `Color`, `Piece`, `Square`, `Move` en `dataclass(frozen, slots)`. Une seule source de constantes. Retrait de numpy | `mypy --strict` sur le moteur. `numpy` retiré des dépendances. Perft et tests différentiels identiques | L |
| J2.4 | **Historique unifié** : pile d'`UndoInfo` à la place des 5 piles et du `deepcopy` (**B38**, partie moteur). Génération sans effet de bord sur `pins` ni sur le cache (**B39**) | Perft identique. Bench avant/après (nœuds par seconde, Kiwipete perft 4) consigné dans le rapport | M |
| J2.5 | **Notation SAN et UCI** : `to_san`, `parse_san` (désambiguïsation, `+`, `#`, `O-O`, `=N`), `to_uci`, `parse_uci` (**B19**, **B35**). Historique de l'UI en SAN | Aller-retour SAN sur toutes les positions des tests différentiels. Comparaison avec `python-chess` | M |
| J2.6 | **FEN** : `fen_utils` devient `fen.py` de production avec validation (**B41**) et compteurs (**B36**). `perft` part dans les tests | FEN invalides rejetées par une `FenError` (8 cas testés). Aller-retour exact des compteurs | S |
| J2.7 | `snake_case` partout (renommage outillé, un seul commit), passage au paquet `chessproject/core` | Aucun changement de comportement. Imports mis à jour | M |

#### J3 — IA : un bon adversaire

> **Avancement (2026-10-22)** : mesures par mini-ligue (`tools/match.py`) sur 48 parties
> (24 ouvertures, couleurs inversées), avec la suite tactique `tests/data/tactics.epd`
> (44 positions, solutions vérifiées par programme).
> - J3.0 ✅ : UCI minimal (`python -m chessproject.uci`), mini-ligue avec Elo, intervalle
>   de confiance et LOS, suite tactique.
> - J3.1 ✅ : Zobrist incrémental. Performance neutre ; sert de clé entière à la table de
>   transposition.
> - Génération des coups : perft +20 %, après profilage.
> - J3.2 – J3.5 ✅ : recherche bornée (temps / profondeur / nœuds), table de transposition
>   à bornes (B6), coups tueurs et historique, quiescence. Mesure contre la fin de J2,
>   **+545 Elo** (45 V / 2 N / 1 D) aussi bien à profondeur égale qu'à temps égal
>   (300 ms/coup) ; IC 95 % ≥ +400.
> - J3.6 ✅ : évaluation par phase. **+112 Elo à temps égal** [+18, +226], **+280 Elo à
>   profondeur égale** [+186, +428]. Le critère de +100 Elo est atteint en estimation
>   ponctuelle, mais sur 48 parties et non 200 comme prévu.
> - Suite tactique : **44/44 à profondeur 5**, **39/44 (89 %) en 1 s** (cible J3.5 : 80 %).
> - J3.7 ✅ : 5 niveaux, **strictement ordonnés** en mini-ligue (critère : au moins 70 % des
>   points contre le niveau inférieur) :
>
>   | Match | Résultat (V / N / D) | Score | Elo [IC 95 %] |
>   |---|---|---|---|
>   | Facile – Débutant | 45 / 2 / 1 | 95,8 % | +545 [+401, …] |
>   | Moyen – Facile | 47 / 1 / 0 | 99,0 % | +791 [+600, …] |
>   | Difficile – Moyen | 45 / 0 / 3 | 93,8 % | +470 [+329, …] |
>   | Expert – Difficile (24 parties) | 20 / 3 / 1 | 89,6 % | +374 [+237, +938] |
>
>   Les marches sont très hautes (400 à 800 Elo). À affiner avec des retours de joueurs
>   humains (bruit et temps des niveaux intermédiaires), par exemple au moment du menu de
>   choix (J4.6).
> - **Limite connue** : environ 10 k nœuds/s en Python pur. À 1 s par coup, l'IA atteint la
>   profondeur 3–4 en ouverture et 1–2 dans les positions très tactiques. Le passage des
>   pièces en entiers (reporté de J2.3) reste la principale piste de vitesse.

Les techniques sont classiques, et chaque étape est mesurée par une **mini-ligue** :
N parties contre la version précédente, avec un script `tools/match.py`.

| # | Tâche | Critère d'acceptation | Taille |
|---|---|---|---|
| J3.1 | **Zobrist** incrémental (clé de position, répétition, table de transposition) | Clé égale à un recalcul complet après chaque coup et chaque annulation (test sur les parties différentielles) | M |
| J3.2 | API `search(position, limits) -> SearchResult(move, score, depth, nodes, pv)` avec `SearchLimits(depth, movetime_ms, nodes)`. Approfondissement itératif interruptible | Respect du temps imparti (tolérance de 10 %). La meilleure ligne (PV) est affichable | M |
| J3.3 | **Table de transposition** à bornes EXACT/LOWER/UPPER et coup mémorisé, taille limitée (**B6**) | Mêmes résultats tactiques, moins de nœuds (mesuré) | M |
| J3.4 | **Ordonnancement** : coup de la table, MVV-LVA, coups tueurs, historique (**B12**) | Nœuds pour une profondeur 5 depuis Kiwipete réduits d'au moins 50 % | S |
| J3.5 | **Quiescence** (captures et promotions) | Suite tactique (environ 30 positions de type « gagner une pièce » ou « mat en 2–3 ») résolue à au moins 80 % en 1 s | M |
| J3.6 | **Évaluation** : tables début et fin de partie interpolées selon la phase, structure de pions (doublés, isolés, passés), paire de fous, abri du roi | Mini-ligue : au moins +100 Elo contre J3.5 sur 200 parties | L |
| J3.7 | **Niveaux de difficulté** (`levels.py`) : *Débutant / Facile / Moyen / Difficile / Expert*, chacun défini par temps, profondeur maximale, bruit d'évaluation et probabilité de coup sous-optimal | Les niveaux sont strictement ordonnés en mini-ligue (chaque niveau bat le précédent avec au moins 70 % des points) | M |

#### J4 — Fonctionnalités attendues

> ✅ **Réalisé le 2026-10-22**
> - Nouvelles fins de partie : temps, abandon, accord. Le mode `automatic_draws=False`
>   (FIDE stricte : 3 répétitions et 50 coups à réclamer, fin d'office à 5 et 75) sert à
>   l'import de parties réelles.
> - J4.1 : `core/clock.py`, pendule avec incrément Fischer, pause, annulation et
>   sérialisation.
> - J4.2 : temps de l'IA alloué selon sa pendule, moins son surcoût **mesuré** (lancement
>   du processus, échéance). Sans cette correction, une partie IA contre IA en 1+0 était
>   perdue au temps. Après correction : **0 perte au temps sur 8 parties en 1+0** au
>   niveau Expert, machine chargée. Le critère prévu (50 parties en 5+0) n'a pas été
>   déroulé tel quel ; la cadence testée est bien plus serrée.
> - J4.3 / J4.4 : `core/pgn.py`, export et import vérifiés contre python-chess, avec un
>   corpus de 9 fichiers (parties célèbres, annotations, FEN, cas d'erreur).
> - J4.5 : sauvegarde v3 (coups UCI, contexte de jeu, pendules, écriture atomique).
> - J4.6 : menus niveau et cadence, abandon (A), nulle (N), PGN (E / I).

| # | Tâche | Critère d'acceptation | Taille |
|---|---|---|---|
| J4.1 | **Cadence** `clock.py` : temps initial, incrément (Fischer), perte au temps (nulle si l'adversaire n'a pas de matériel suffisant pour mater), pause. Préréglages (Bullet 1+0, Blitz 3+2 et 5+0, Rapide 10+5 et 15+10, sans limite) | Tests à temps simulé : incrément crédité après le coup, perte au temps, nulle au temps contre un roi seul, annulation qui restaure la pendule | M |
| J4.2 | Cadence dans l'IA : temps alloué par coup selon le temps restant et l'incrément | L'IA ne perd jamais au temps en 5+0 (sur 50 parties) | S |
| J4.3 | **Export PGN** : sept en-têtes obligatoires (Seven Tag Roster), `[FEN]`/`[SetUp]` si nécessaire, `[TimeControl]`, `[Result]`, coups en SAN, retour à la ligne à 80 caractères | Le fichier produit est relu à l'identique par `python-chess` | S |
| J4.4 | **Import PGN** : en-têtes, SAN, commentaires `{}`, variantes `()` et NAG `$n` ignorés proprement, limites de taille | Corpus de test (10 PGN réels, dont une partie qui commence par une FEN). Erreurs explicites (`PgnError`) affichées dans l'UI | M |
| J4.5 | **Sauvegarde v2** (§3.2) : coups en UCI, mode, couleur de l'humain, cadence et pendules, résultat. Écriture atomique (**B37**) | Migration v1 vers v2 testée. Chargement d'une partie d'un autre mode : mode et couleur restaurés | S |
| J4.6 | UI : choix du niveau et de la cadence dans le menu de partie, abandon, proposition de nulle (contre l'IA : acceptée selon l'évaluation) | Parcours complet testé avec le contrôleur sans écran | M |

---

### 4.5 Fin de parcours

#### J5 — Interface « pro »

> ✅ **Réalisé le 2026-10-22**, d'après la maquette validée (écran de jeu sombre et clair,
> écran « Nouvelle partie », états de fin de partie, promotion, nulle et pendule).
> - J5.1 : `App` tient la scène courante (« Nouvelle partie » ou partie) et la **seule**
>   boucle `while True` du programme. Les menus bloquants ont disparu ; raccourcis,
>   apparence, confirmations, fin de partie et promotion sont des fenêtres superposées qui
>   reçoivent les événements et rendent une action. L'animation est calculée à chaque image
>   (**B45** définitif, plus de boucle d'animation). Une fenêtre modale ou la scène
>   « Nouvelle partie » arrête la pendule et l'IA ; le temps de pause n'est pas compté dans
>   la limite de réflexion de l'IA. Écart : à l'intérieur de la partie, l'état reste dérivé
>   d'attributs (`overlay`, `promotion_popup`, `ai_thinking`, `view_ply`) plutôt que d'une
>   énumération d'états ; chaque transition est néanmoins testée.
> - J5.2 : `theme.py` (2 thèmes, 4 échiquiers, couleurs des surlignages), polices IBM Plex
>   embarquées et mises en cache (**B38**). Aucune couleur en dur hors de `theme.py`.
>   Pièces vectorielles « Chessnut » (Apache 2.0) rastérisées à la taille exacte des cases.
>   Image en régime établi : **5,5 ms** (1280×800, mesuré dans l'environnement de
>   développement), bien sous les 16,7 ms d'une image à 60 images/s. Un pic de 30 à 60 ms survient une fois par nouvelle
>   position quand la barre d'évaluation est active (recherche de 25 ms sur une copie).
> - J5.3 : `layout.py`, fonction pure de la taille de fenêtre, testée sur 6 tailles de
>   960×640 à 2560×1440. Écart : la taille minimale est **960×640**, pas 800×600 ; en
>   dessous, la fenêtre est ramenée au minimum au lieu de replier le panneau.
> - J5.4 : glisser-déposer et clic-clic, points et anneaux de capture, flèches et marques
>   au clic droit, dernier coup, roi en échec, pendule au trait en couleur d'accent (rouge
>   sous 20 s), sons désactivables. Cibles cliquables de 34 à 52 px. La revue WCAG AA n'a
>   pas été faite avec un outil : les contrastes texte/fond ont été choisis au-dessus de
>   4,5:1 pour le texte courant.
> - J5.5 : historique SAN cliquable, flèches et `Origine`/`Fin`, échiquier en lecture
>   seule pendant la revue, partie inchangée (testé). Matériel pris et avance matérielle,
>   barre d'évaluation désactivable. Non fait : l'affichage de la variante principale de
>   l'IA en mode analyse.
> - En plus : préférences mémorisées (`settings.py`, lecture tolérante champ par champ),
>   notifications dans la ligne d'état (sauvegarde, chargement, PGN, nulle refusée),
>   confirmation avant d'abandonner ou de recommencer, retournement de l'échiquier (`F`).
> - Tests : 41 nouveaux tests d'interface (`tests/test_ui.py`) ; suite rapide à 503 tests.
>   Les tests qui lancent un processus ou un sous-processus ont désormais un délai d'attente
>   (deux jobs macOS de la CI s'étaient arrêtés sur le délai de 15 min sans journal
>   disponible) et pytest affiche la pile d'appels d'un test bloqué plus de 5 min.

Elle vient **après** J1–J4, pour habiller une logique stable et ne pas avoir à redessiner
deux fois.

| # | Tâche | Critère d'acceptation | Taille |
|---|---|---|---|
| J5.1 | Une seule boucle avec des **scènes** (menu, partie, popup, réglages) ; contrôleur en **machine à états** explicite ; animation avancée d'une étape par image (**B28** définitif, **B45**) | Plus aucun `while True` hors de la boucle principale. Toutes les transitions sont testées | L |
| J5.2 | **Système de design** : `theme.py` (palette, typographie embarquée, espacements, rayons), polices précalculées (**B38**), thèmes clair et sombre, 3–4 thèmes de plateau | Plus de couleur en dur hors de `theme.py`. 60 images/s stables | M |
| J5.3 | **Mise en page adaptative** : plateau carré qui s'adapte à la fenêtre, panneaux latéraux qui se replient, pièces mises à l'échelle (de préférence en SVG ou haute résolution) | Lisible de 800×600 à 4K, sans chevauchement | M |
| J5.4 | **Interactions** : glisser-déposer en plus du clic, prévisualisation des coups (points et anneaux de capture), flèches et surlignage au clic droit, dernier coup, roi en échec, pendules mises en avant au trait, sons discrets | Revue UX par une checklist (contraste WCAG AA, cibles ≥ 32 px, retour visuel < 100 ms) | M |
| J5.5 | Panneau de partie : historique SAN cliquable (navigation dans la partie), matériel capturé, barre d'évaluation (optionnelle), affichage de la PV de l'IA en mode analyse | Navigation dans l'historique sans modifier la partie en cours | M |

*Note* : la maquette visuelle peut être produite en amont (design artifact, ou le skill
« ui-ux-pro-max » s'il est disponible), puis traduite en `theme.py`.

#### J6 — Packaging et vitrine

> ✅ **Préparé le 2026-10-22** ; la publication de `v1.0.0` attend la fusion de la PR.
> - J6.1 : `chessproject --version` et `chessproject --smoke-test`. Vérifié depuis une
>   installation propre (non éditable) dans un environnement virtuel, équivalent de
>   `pipx install .` ; `pipx` lui-même n'était pas disponible pour le test.
> - J6.2 : `tools/build_exe.py` (PyInstaller 6.21, mode « onedir », paquet `.app` sous
>   macOS, icône générée par `tools/make_icon.py`). Le test de démarrage joue une partie
>   contre l'IA **dans son processus séparé**, ce qui vérifie `freeze_support()` et les
>   ressources embarquées. Workflow `release.yml` : construction et test sur Windows,
>   macOS et Linux (ubuntu-22.04, glibc 2.35) à chaque tag, puis release GitHub. La CI
>   construit et teste aussi l'exécutable Linux à chaque push. Vérifié en local sous
>   Linux (26 Mo compressé) ; Windows et macOS ne seront vérifiés qu'au premier passage
>   du workflow. Deux sons inutilisés (2,5 Mo) ont été retirés.
> - J6.3 : README réorganisé (GIF de démonstration de 600 Ko généré par
>   `tools/make_demo_gif.py`, téléchargements, schéma des couches, choix techniques).
>   Pas de badge de couverture : la couverture n'est pas mesurée en CI.
> - J6.4 : `CHANGELOG.md`, version 1.0.0 cohérente entre `pyproject.toml`, le paquet et le
>   changelog (testé), notes de release extraites du changelog (`tools/release_notes.py`).
> - J6.5 : déjà fait en J3.0 (`chessproject-uci`). L'Elo des niveaux contre Stockfish
>   bridé n'a pas été mesuré.
> - Correctif trouvé en préparant le GIF : la carte de fin de partie débordait quand le
>   motif tenait sur deux lignes ; sa hauteur suit maintenant le texte.
> - CI : les jobs macOS de la PR restent en attente sans runner attribué (`runner_id` 0)
>   et sont annulés à 15 min. Ce n'est pas un échec de test ; à vérifier côté compte
>   (quota de minutes ou disponibilité des runners macOS). Le workflow de release en
>   dépend aussi.

| # | Tâche | Critère d'acceptation | Taille |
|---|---|---|---|
| J6.1 | Point d'entrée `python -m chessproject` et script console `chessproject` ; installation par `pipx` | `pipx install .` puis `chessproject` fonctionne | S |
| J6.2 | **PyInstaller** (ou Briefcase) : exécutables Windows, macOS et Linux construits par la CI lors d'un tag, ressources embarquées | Les trois exécutables se lancent sur une machine sans Python (test de démarrage dans la CI) | M |
| J6.3 | README vitrine : GIF de partie, captures, architecture (schéma des couches), choix techniques (perft, tests différentiels, Zobrist, machine à états), badges CI et couverture | Relu comme une page portfolio | S |
| J6.4 | `CHANGELOG.md`, versionnage sémantique, release GitHub `v1.0` | Notes de version générées depuis le changelog | S |
| J6.5 | *(Optionnel)* **UCI minimal** (`uci`, `isready`, `ucinewgame`, `position`, `go movetime/wtime/btime/winc/binc`, `stop`, `bestmove`, `quit`) | Le moteur joue sous `cutechess-cli` contre Stockfish bridé. Elo estimé des niveaux publié dans le README | M |

---

### 4.6 Jalons de livraison et indicateurs

| Version | Contenu | Indicateurs |
|---|---|---|
| `v0.2` | J0 + J1 | CI verte sur 3 OS, 0 bug 🔴 ou 🟠 connu |
| `v0.5` | + J2 + J3 | `mypy --strict` sur le moteur, couverture moteur ≥ 90 %, 1 000 parties différentielles sans divergence, IA ≥ 80 % sur la suite tactique |
| `v0.8` | + J4 | PGN lu et écrit en accord avec `python-chess`, cadence testée, 5 niveaux ordonnés |
| `v1.0` | + J5 + J6 | Exécutables sur 3 OS, README vitrine, UI à 60 images/s |

### 4.7 Suite : feuille de route après la 1.0 (2026-10-22)

J0 à J6 sont réalisés et fusionnés. Le même principe s'applique pour la suite : une tâche
= un commit avec son test, et toute amélioration de l'IA est mesurée en mini-ligue.

#### J7 — Publier la 1.0 (une demi-journée)

| # | Tâche | Critère d'acceptation | Taille |
|---|---|---|---|
| J7.1 | Pousser le tag `v1.0.0` sur `master`, ou lancer « Release » sur `master` avec « publier » coché (la session de travail ne peut pas pousser de tag) | Release GitHub avec les trois zips et les notes du changelog | S |
| J7.2 | Lancer les exécutables à la main sur un vrai Windows et un vrai Mac (SmartScreen, Gatekeeper, fenêtre réelle, son) | Une partie complète jouée sur chaque système ; écarts consignés dans le README | S |
| J7.3 | Délai des jobs macOS porté à 30 min : l'attente d'une machine (environ 10 min observées) est comptée dans le délai | Plus d'annulation de job macOS sans test exécuté | S |

#### J8 — v1.1 : un adversaire calibré (2–3 j)

| # | Tâche | Critère d'acceptation | Taille |
|---|---|---|---|
| J8.1 | Recalibrer les niveaux (bruit, profondeur, temps) : les écarts actuels vont de 90 à 99 % des points | Entre deux niveaux voisins, 60 à 75 % des points pour le plus fort (mini-ligue, 100 parties) | M |
| J8.2 | Elo de chaque niveau contre Stockfish bridé (`UCI_LimitStrength`), affiché dans l'écran « Nouvelle partie » | Elo publié avec intervalle de confiance | M |
| J8.3 | Petit livre d'ouvertures (quelques centaines de lignes) et nom de l'ouverture dans l'historique | L'IA varie ses débuts ; nom affiché pour les ouvertures courantes | M |

**Plan détaillé (2026-10-25).** Mesures de départ : environ 10 à 13 k nœuds/s sur la
machine de développement (8 cœurs) ; Stockfish 19 accepte `UCI_Elo` de 1320 à 3190.

| # | Tâche | Critère d'acceptation | Taille |
|---|---|---|---|
| J8.0 | Outillage de calibration. Budget de **nœuds** par niveau (`Level.max_nodes`) : la force ne dépend plus de la vitesse de la machine ni du nombre de parties en parallèle, le temps reste un plafond. `--level-spec` pour le moteur UCI (essayer un réglage sans toucher au code). Options UCI par moteur dans `tools/match.py` (`--option-b UCI_Elo=1500`). `tools/calibrate.py` : échelle des niveaux voisins, Elo chaîné avec intervalle de confiance, sortie JSON | Tests unitaires des nouveaux paramètres et du chaînage des intervalles | S |
| J8.1 | Recalibrage par itérations sur l'échelle (100 parties par paire) : budgets de nœuds, profondeur, bruit et erreurs. Expert reste la pleine force ; l'écart total se resserre (environ 4 × 150 Elo au lieu de plus de 2 000) | 60 à 75 % des points pour le plus fort de chaque paire voisine, résultats consignés ici | M |
| J8.2 | Ancrage contre Stockfish bridé. Les niveaux au-dessus de 1320 sont mesurés directement, les autres par chaînage depuis l'échelle. `Level.elo` affiché sur la carte du niveau (« ≈ 1450 Elo ») ; README | Elo de chaque niveau avec IC 95 % dans ce rapport ; même chiffre dans l'interface | M |
| J8.3 | Livre d'ouvertures : `assets/openings.tsv` (ECO, nom français, coups SAN, environ 250 lignes), `ai/book.py` (arbre des suites de coups depuis la position initiale, coup tiré au hasard pondéré par le nombre de lignes). Profondeur de livre par niveau (`Level.book_plies`), option UCI `OwnBook`. Nom de l'ouverture dans le panneau d'historique, en-têtes PGN `ECO` / `Opening` | Toutes les lignes sont légales (test) ; l'IA varie ses débuts (test statistique sur graine) ; nom affiché pour les ouvertures courantes | M |
| J8.4 | Publication `v1.1.0` : version, CHANGELOG, README, rapport | CI verte, release créée | S |

État : J8.0, J8.3 ✅ ; J8.1 et J8.2 ✅ en mesure écourtée (voir ci-dessous) ; J8.4 : version,
CHANGELOG et README prêts, release à créer après fusion.

Le livre ne joue qu'à partir de la position initiale : les mini-ligues partent des FEN de
`tools/openings.txt`, les mesures de J8.1 et J8.2 n'en dépendent donc pas.

> **Avancement J8.1 (2026-10-25)** : échelles `tools/calibrate.py`, positions de départ
> tirées du livre (`--book-openings`), couleurs inversées, 8 parties en parallèle (sans
> effet sur la force : les niveaux sont bornés en nœuds).
>
> | Échelle | Réglages (nœuds / bruit cp / erreurs) | Scores du plus fort, de bas en haut |
> |---|---|---|
> | 1 (40 parties) | 500/100/15 % · 1 500/50/8 % · 4 000/20/3 % · 12 000 · 40 000 | 95 % · 90 % · interrompue |
> | 2 (40 parties) | 600/50/4 % · 1 500/30/2 % · 4 000/15/0 · 12 000 · 40 000 | 70 % · 77,5 % · 80 % · 83,8 % (écart total +888 Elo) |
>
> - Les « erreurs » (coup tiré parmi les meilleurs) affaiblissent bien plus que le bruit
>   ou le budget de nœuds : on les garde très rares.
> - **Bug trouvé** pendant l'échelle 1 : sans profondeur maximale, la réévaluation bruitée
>   des coups de la racine n'était pas bornée (un coup de plus de 120 s). Corrigé, test
>   d'abord : approfondissement borné par un second budget de nœuds et 30 % du temps.
> - À la demande du propriétaire, la mesure a été écourtée : l'échelle 3 (20 parties par
>   paire) a été interrompue après sa première paire (90 %), et la validation finale
>   s'est jouée sur **8 parties par paire** (4 positions du livre, couleurs inversées,
>   nulle par adjudication à 160 demi-coups). Le critère de 100 parties n'est donc pas
>   rempli : les écarts sont des estimations grossières.
>
> **Réglages retenus (v1.1.0)** : budgets de 3 500, 6 500, 12 000, 22 000 et 40 000
> nœuds ; bruit de ±20, ±10 et ±5 cp pour les trois premiers niveaux ; aucune erreur.
>
> | Match (8 parties) | V / N / D | Score | Écart Elo [IC 95 %] |
> |---|---|---|---|
> | Facile – Débutant | 6 / 0 / 2 | 75,0 % | +191 [−322, +704] |
> | Moyen – Facile | 6 / 1 / 1 | 81,2 % | +255 [−248, +757] |
> | Difficile – Moyen | 4 / 2 / 2 | 62,5 % | +89 [−173, +351] |
> | Expert – Difficile | 5 / 1 / 2 | 68,8 % | +137 [−262, +536] |
>
> **J8.2 — ancrage** : Expert contre Stockfish 19 (`UCI_LimitStrength`, `UCI_Elo`
> 1900, 1 s par coup), 8 parties : 4 / 1 / 3, +44 [−199, +352] (auparavant, 18 victoires
> sur 18 contre `UCI_Elo` 1320). Elo chaînés (échelle de Stockfish, pas l'Elo FIDE) :
>
> | Niveau | Elo affiché | Estimation | IC 95 % |
> |---|---|---|---|
> | Débutant | ≈ 1250 | 1272 | ± 905 |
> | Facile | ≈ 1450 | 1463 | ± 746 |
> | Moyen | ≈ 1700 | 1718 | ± 551 |
> | Difficile | ≈ 1800 | 1807 | ± 485 |
> | Expert | ≈ 1950 | 1944 | ± 276 |
>
> Écart total ≈ 670 Elo, contre plus de 2 000 en 1.0 : Débutant est nettement plus fort
> qu'avant. **Reste à faire** : valider sur 100 parties par paire quand du temps de
> calcul est disponible (`python tools/calibrate.py --book-openings 50 --games 100`), et
> envisager un sixième niveau très faible pour les grands débutants.

#### J9 — v1.2 : mode analyse (2–3 j)

| # | Tâche | Critère d'acceptation | Taille |
|---|---|---|---|
| J9.1 | Variante principale de l'IA affichée (écart resté ouvert de J5.5) | PV légale, mise à jour pendant la réflexion | M |
| J9.2 | Bouton « Indice » (meilleur coup en flèche) | Désactivé en partie classée contre l'IA si l'utilisateur le choisit | S |
| J9.3 | Courbe d'évaluation et bilan de fin de partie (imprécisions, erreurs, gaffes selon la chute d'évaluation) | Seuils documentés et testés sur des parties de référence | M |

> **J9.1 ✅ (2026-10-28)** : `Searcher.think(..., on_iteration=…)` signale chaque
> profondeur achevée avec sa variante principale (lue dans la table de transposition).
> `ai/analysis.py` : processus d'analyse de la position affichée (une ligne SAN par
> profondeur, score du point de vue des Blancs, arrêt de lui-même après 15 s) et
> `Analyzer`, qui le relance quand la position affichée change (coup joué, revue de la
> partie) et l'arrête quand l'option est coupée. Option « Variante principale » dans
> « Apparence » et touche `V`, désactivée par défaut ; la ligne s'affiche au-dessus de
> l'historique (« 4. Bxc6 dxc6 5. Nxe5 Nf6 · +0,7 · prof. 4 ») et la barre
> d'évaluation reprend son score. Analyse et IA tournent dans deux processus : la force
> de l'IA, bornée en nœuds, n'en dépend pas ; seul le plafond de temps peut être atteint
> plus tôt sur une machine chargée. 21 nouveaux tests.
>
> **J9.2 ✅ (2026-10-28)** : bouton « Indice » (ampoule dans l'en-tête, touche `B`).
> Le meilleur coup de la position actuelle est cherché pendant 1 s dans un processus
> (`analysis.HINT_LIMITS`, même `Analyzer` que l'analyse), puis tracé en flèche et
> annoncé dans la ligne d'état (« Indice : Nc3 ») ; la flèche s'efface au coup suivant.
> Demandé depuis la revue, il ramène à la position actuelle. Un coup joué ou annulé
> pendant la recherche abandonne l'indice. Indisponible au tour de l'IA, en IA contre
> IA et en fin de partie. Option « Indices contre l'IA » (Apparence, activée par
> défaut) : coupée, le bouton est désactivé contre l'IA ; elle ne s'applique pas entre
> deux joueurs. Le temps de recherche est décompté de la pendule du joueur. 6 nouveaux
> tests.
>
> **J9.3 ✅ (2026-10-28)** : `ai/review.py`, bilan calculé dans un processus.
>
> - **Mesure** : dans chaque position, meilleur coup à profondeur 3 (plafond de
>   20 000 nœuds), puis, si le coup joué diffère, ce coup évalué au même horizon depuis
>   la position suivante, avec la même table de transposition. Un premier essai
>   (évaluer chaque position séparément, 3 000 nœuds) signalait des imprécisions sur
>   e5 et a6 dans l'Espagnole : la profondeur atteinte alternait entre 3 et 4 et
>   l'évaluation oscillait de ±100 cp. À horizon égal, le meilleur coup perd
>   exactement 0. Environ 0,25 s par position (2,8 s pour une partie de 14 coups), et
>   le même bilan sur toutes les machines.
> - **Seuils** : chute du score attendu du camp qui joue (`1 / (1 + 10^(−cp/400))`, un
>   mat vaut 0 ou 1) d'au moins 20 points pour une imprécision `?!`, 30 pour une erreur
>   `?`, 40 pour une gaffe `??`, soit environ 150, 240 et 380 cp depuis l'égalité. Les
>   seuils habituels (10 / 20 / 30) supposent un moteur bien plus profond : sur cinq
>   parties de théorie, ce moteur voit des chutes allant jusqu'à 18 points sur des
>   coups corrects (Bxc6 puis Nxe5 semble gagner un pion à cet horizon). Une pièce en
>   prise coûte plus de 50 points, un mat concédé 100. Perte moyenne par coup en
>   centipions (scores bornés à ±1000).
> - **Parties de référence** (`tests/test_review.py`) : mat du lion (g4 gaffe), coup du
>   berger (Nf6 gaffe), fou en prise (Bg5 erreur ou gaffe, Qxg5 rien), quatre parties de
>   théorie de 20 demi-coups sans rien de signalé (trois en `slow`).
> - **Interface** : bouton « Bilan » de la carte de fin de partie et touche `G` (à tout
>   moment dès le premier coup). Courbe d'évaluation remplie au fur et à mesure,
>   pastilles colorées sur les coups fautifs, survol (coup et évaluation), clic pour
>   revoir la position ; tableau par camp. Les symboles s'ajoutent aux coups de
>   l'historique ; un coup joué ou annulé rend le bilan périmé. 20 nouveaux tests.
> - Limite : un moteur de profondeur 3 ne voit pas les fautes stratégiques ni les
>   tactiques longues ; le bilan signale surtout le matériel perdu et les mats.
>
> **Publication `v1.2.0` (2026-10-28)** : J9 terminé ; version, CHANGELOG et README à
> jour, avec le correctif Windows de la 1.1.1 (pièces PNG si le SVG est rendu
> transparent).

#### J10 — v1.3 : moteur plus rapide (3–5 j)

| # | Tâche | Critère d'acceptation | Taille |
|---|---|---|---|
| J10.1 | Profilage (environ 10 000 nœuds/s aujourd'hui) et optimisations ciblées | Gain mesuré en nœuds/s, perft inchangé | M |
| J10.2 | Null move, réductions des coups tardifs, PVS, fenêtres d'aspiration, chacun mesuré | Chaque technique gardée seulement si elle gagne en Elo à temps égal | L |
| J10.3 | Un seul calcul de temps de réflexion (UCI et pendule) | Tests de `allocate_think_time_ms` partagés | S |

Une réécriture en bitboards ne serait envisagée que si J10.1–J10.2 ne suffisent pas.

> **J10.1 ✅ (2026-10-28)** : `tools/bench.py`, recherche à profondeur 4 sur cinq
> positions (départ, Kiwipete, Italienne, deux finales), avec profil `--profile`. Le
> **nombre de nœuds** (110 534) est la signature de l'arbre : il n'a pas bougé, seule
> la vitesse change. `tests/test_optimizations.py` fige les valeurs d'avant J10
> (nœuds à profondeur 3, évaluation de 2 312 positions de parties aléatoires) et compare
> `has_legal_moves` à la génération complète.
>
> | Étape | Nœuds/s | Gain cumulé |
> |---|---|---|
> | Départ (1.2.0) | 10 700 | — |
> | Rayons, sauts et pas de roi précalculés (`square_under_attack`, pièces glissantes, cavalier) | 11 200 | +5 % |
> | Constructeur de `Move` sur variables locales (4,3 M appels pour 110 k nœuds) | 11 900 | +11 % |
> | Évaluation : valeur, table et signe fusionnés par pièce | 12 100 | +13 % |
> | Génération paresseuse en quiescence : `has_legal_moves()` s'arrête au premier coup légal, la liste n'est générée que si le *stand pat* ne coupe pas | 16 000 | +50 % |
> | Cache de la structure de pions (clé de Zobrist des pions) | 19 300 | **+81 %** |
>
> - Le profil de départ : 60 % du temps dans la génération des coups (environ 39 `Move`
>   créés par nœud, même aux feuilles de la quiescence, qui s'arrêtent pour la plupart
>   sur l'évaluation statique), 27 % dans l'évaluation.
> - Écarté : garder les clouages calculés par `has_legal_moves` pour `get_valid_moves`
>   (environ 4 %) ; l'interface et des tests modifient le plateau puis remettent
>   seulement `_valid_moves` à zéro, le cache serait fragile.
> - Les niveaux sont bornés en nœuds : leur force est inchangée, ils jouent environ
>   deux fois plus vite (Expert ≈ 2 s au lieu de 4). La suite rapide passe de 55 à 40 s.
> - Au passage : `test_random_games_long` (lent) échouait depuis J4.4 sur 10 parties
>   finies par la règle des 50 coups : la relecture PGN suit les règles FIDE strictes
>   (nulle à réclamer). Le test compare maintenant à règles égales.

> **J10.2 ✅ (2026-10-28, mesure écourtée)** : `SearchFeatures` (`pvs`, `aspiration`,
> `null_move`, `lmr`), option `--features` du moteur UCI et de `tools/bench.py`, pour
> opposer le même code avec et sans une technique. Budget fixé par le propriétaire :
> **30 min de calcul** au total.
>
> - PVS : fenêtre nulle après le premier coup, nouvelle recherche si le score en sort.
>   Coup nul : R = 2, dès la profondeur 3, jamais en échec ni sans pièce (zugzwang des
>   finales de pions) ; `GameState.make_null_move` / `undo_null_move`. LMR : coups
>   calmes à partir du 4e, sans échec donné ni subi, réduits d'un demi-coup dès la
>   profondeur 3, revus à pleine profondeur s'ils dépassent alpha ; **jamais à la
>   racine** (sinon le mat en deux 1. Ta6 ! bxa6 2. b7# n'est plus vu à profondeur 3,
>   `tests/test_ai.py`). Aspiration : ±50 cp dès la profondeur 4.
> - Nœuds pour la profondeur 5 (positions de `tools/bench.py`) : aucune technique
>   433 k ; PVS 306 k ; + aspiration 304 k ; PVS + coup nul 236 k ; PVS + LMR 154 k ;
>   PVS + coup nul + LMR hors racine **168 k (−61 %)**. À profondeur fixe, PVS rend
>   exactement les mêmes scores (60 positions sur 60).
> - Suite tactique à 1 s : 41/44 sans technique, 42/44 avec (mats en 2 : 11/11).
>
> | Match (moteur UCI, pleine force) | Parties | V / N / D | Écart Elo [IC 95 %] | LOS |
> |---|---|---|---|---|
> | PVS – aucune, 100 ms par coup | 200 | 61 / 43 / 96 | −61 [−106, −19] | 0,3 % |
> | PVS + coup nul + LMR – aucune, 400 ms | 96 | 35 / 32 / 29 | +22 [−35, +80] | 77 % |
> | idem, 48 autres ouvertures | 96 | 39 / 25 / 32 | +25 [−34, +87] | 80 % |
> | **400 ms, cumul** | **192** | **74 / 57 / 61** | **+24 [−18, +65]** | **87 %** |
>
> - À 100 ms, le moteur ne dépasse presque jamais la profondeur 2 (~1 800 nœuds) :
>   PVS n'y a rien à couper, et ce régime ne ressemble pas au jeu réel (3 500 à 40 000
>   nœuds par coup). Ce match a été écarté, et la mesure refaite à 400 ms.
> - Positions de départ : 96 positions du livre (`calibrate.book_openings`), chacune
>   jouée deux fois, couleurs inversées, 8 parties en parallèle.
> - **Décision** : PVS + coup nul + LMR pour la pleine force (moteur UCI, analyse,
>   indice) ; gain probable (87 %) mais non établi à 95 %. La racine exclue de LMR a
>   été décidée après les matchs (environ 16 % de nœuds en plus à profondeur 5) : non
>   remesuré. Aspiration écartée (−0,6 % de nœuds, gain non mesurable). **Les niveaux et
>   le bilan restent sans élagage** : bornés en nœuds, les niveaux ont été calibrés
>   ainsi (J8), et le bilan suppose qu'à horizon égal le meilleur coup perd 0.
> - Reste à faire quand du temps de calcul est disponible : chaque technique seule à
>   400 ms (environ 400 parties chacune pour un IC de ±35 Elo), puis, si les niveaux
>   doivent en profiter, recalibrer J8.1 et J8.2.
>
> **J10.3 ✅ (2026-10-28)** : `uci.allocate_time_ms` (restant / 30 + 0,8 × incrément)
> est supprimé ; le moteur UCI appelle `clock.allocate_think_time_ms`, celui de la
> pendule du jeu, qui gagne le paramètre `moves_to_go` (`movestogo` en UCI). Avec lui,
> `remaining / moves_to_go + 0,75 × incrément`, sans le plafond du tiers (le temps est
> rendu au contrôle suivant) ; sans lui, formule inchangée pour le jeu. Les demi-coups
> joués viennent du numéro de coup (une partie UCI peut commencer par une FEN). En UCI,
> début de partie à 60 s : 1,5 s par coup au lieu de 2 s, jamais plus du tiers du temps
> restant. Tests communs dans `tests/test_clock.py` ; `tests/test_uci.py` vérifie que
> `go` passe par ce calcul avec les bons arguments.

#### J11 — v1.4 : confort (2–3 j)

| # | Tâche | Critère d'acceptation | Taille |
|---|---|---|---|
| J11.1 | Choix du fichier de sauvegarde ou de PGN, plusieurs sauvegardes, choix d'une partie dans un PGN multiple | Parcours testé avec le contrôleur sans écran | M |
| J11.2 | Jouer au clavier en tapant le coup (SAN) | Saisie tolérante (`e4`, `Nf3`, `O-O`), erreurs signalées | S |
| J11.3 | Version anglaise | Toutes les chaînes de l'interface traduites, langue dans les préférences | M |
| J11.4 | Audit d'accessibilité WCAG avec un outil | Contrastes AA vérifiés, écarts corrigés | S |

#### En continu

- Couverture des tests mesurée en CI, avec un badge.
- Paquet AppImage pour Linux.
- Signature des exécutables Windows et notarisation macOS : nécessite des certificats
  payants, décision du propriétaire du projet.

Ordre proposé : J7, puis J8 (c'est ce qui se voit le plus en jouant), puis J9, J10, J11.

---

# Annexe A — Rapport du 2026-09-06 (historique des étapes 0 à 2)

> Document historique. Son plan (étapes 3 à 5) est **remplacé** par la feuille de route du §4.

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
