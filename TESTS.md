# Tests

## Installation

```bash
python -m pip install -e ".[dev]"
```

## Lancer les tests

```bash
# Suite rapide (~30 s) — les tests marqués `slow` sont exclus par défaut
python -m pytest -q

# Couverture par paquet (seuil de 90 % sur core, comme en CI)
python -m pytest -q --cov --cov-report=json
python tools/coverage_report.py coverage.json
```

## Contenu

Les tests sont dans `tests/`.

| Fichier | Rôle |
|---|---|
| `test_chess.py` | Tests historiques : en passant, roque, répétition, règle des 50 coups, matériel insuffisant, performance de l'IA. |
| `test_perft.py` | **Validation de référence du générateur de coups.** Compte les nœuds de l'arbre des coups légaux (perft) sur 6 positions standard (position initiale, Kiwipete, positions 3 à 6 du Chess Programming Wiki) et compare aux valeurs publiées. |
| `test_rules_regression.py` | Verrouille les bugs de règles corrigés : pat, mat, matériel insuffisant resserré, triple répétition, roque à travers une case tenue par un pion, broches recalculées, sous-promotions, prise en passant exposant le roi. |
| `test_serialization.py` | Sauvegarde / chargement JSON des parties (`serialization.py`) : génération de FEN, aller-retour position + historique, conservation de l'orientation et du choix de sous-promotion, rejet d'une version inconnue, recalcul des drapeaux de fin de partie au chargement. |
| `test_orientation.py` | Plateau retourné (B26) : rotation de la vue à 180° (aller-retour pixel/case sur les 64 cases, libellés), position standard en jouant les Noirs, échec détecté, roque par le roi. |
| `test_ai.py` | IA : mat préféré au pat, mat le plus court, coup toujours rendu, mat en 2, évaluation en centipions nulle au départ et antisymétrique par miroir, capture gratuite, rappel à chaque profondeur achevée avec sa variante principale. |
| `test_review.py` | Bilan de partie (J9.3) : seuils sur la chute du score attendu, perte du point de vue du camp qui joue, parties de référence (coup du berger, mat du lion, fou en prise, parties de théorie sans aucune erreur signalée), pilotage du processus ; meilleur coup de chaque faute (J13.1) : variante légale, qui pare le mat du berger, tronquée au premier coup illégal ; annotations PGN (J13.2) relues par python-chess (NAG, `[%eval]`). |
| `test_analysis.py` | Mode analyse (J9.1) : une ligne par profondeur en SAN légale, score du point de vue des Blancs, numérotation, partie finie, pilotage du processus (relance quand la position change, arrêt), vrai processus. |
| `test_game_controller.py` | Contrôleur sans écran (doublures de `Process` / `Queue`) : coup de l'IA après l'humain, reprise après R / L (avec confirmation), sous-promotion via le popup, robustesse du processus d'IA, pendule arrêtée pendant les fenêtres modales, animation non bloquante. |
| `test_release.py` | Livraison J6 : version identique dans le paquet, `pyproject.toml` et le changelog, extraction des notes de version, noms des archives par système, test de démarrage de l'exécutable (partie contre l'IA). |
| `test_ui.py` | Interface J5 : mise en page sur 6 tailles de fenêtre, préférences (aller-retour, champs invalides), écran « Nouvelle partie », glisser-déposer, clic-clic, flèches et marques, promotion au clavier, coup tapé au clavier (J11.2), navigation dans l'historique sans modifier la partie, matériel et évaluation, fenêtres superposées, variante principale (J9.1), indice en flèche et son option contre l'IA (J9.2), fenêtre de bilan, clic sur la courbe et symboles dans l'historique (J9.3), meilleur coup en flèche et variante depuis une pastille, à la souris et au clavier (J13.1), export annoté depuis le bilan (J13.2), transitions de scènes, redimensionnement, dessin de chaque écran dans les deux thèmes. |
| `test_paths.py` | Lancement depuis un autre dossier, journal et sauvegarde dans le dossier de données utilisateur (sous-processus). |
| `test_differential.py` | Parties aléatoires comparées coup par coup à python-chess : coups légaux, échec, mat, pat, nulles (50 rapides, 1 000 en `slow`). |
| `test_fen.py` | Validation des FEN (31 FEN invalides, une par règle), aller-retour exact, compteurs. |
| `test_notation.py` | SAN / UCI : roques, désambiguïsation, en passant, promotions, échec et mat ; comparaison avec python-chess ; coup tapé au clavier (J11.2) : graphies tolérantes, initiales françaises, promotion sans pièce, erreurs expliquées. |
| `test_files.py` | Choix de fichier (J11.1), parcouru avec le contrôleur sans écran : sauvegarde sous un nom, remplacement confirmé, plusieurs sauvegardes et choix de celle à charger (clavier et souris), suppression, ancienne sauvegarde reprise, export et import dans un dossier choisi et retenu, choix d'une partie dans un PGN multiple, PGN invalide, depuis l'écran « Nouvelle partie ». |
| `test_i18n.py` | Version anglaise (J11.3) : chaque texte passé à `tr`, chaque bouton et chaque table affichée traduits, mêmes champs dans les deux langues, noms anglais des 268 ouvertures ; chaque écran dessiné en anglais sans un mot de français ; choix de la langue (écran « Nouvelle partie », Apparence), mémorisé. |
| `test_contrast.py` | Audit WCAG AA (J11.4) : formules de la norme, aucune paire de couleurs sous son seuil dans les deux thèmes et sur les quatre échiquiers (anneau de focus et curseur de case compris, J12). |
| `test_keyboard.py` | Clavier seul (J12.2, J12.3) : chaque fenêtre et l'écran « Nouvelle partie » (trois modes) parcourus avec `Tab` puis `Maj+Tab`, chaque bouton actif visité une fois dans l'ordre de lecture ; anneau de focus dessiné ; `Entrée` / `Espace` activent comme un clic (dossier, fichier, option) ; promotion aux flèches ; curseur de case (sens de l'échiquier retourné, bords, coup impossible, `Échap`) ; mat du lion joué au curseur ; parcours complet sans souris, des réglages à la carte de fin. |
| `test_puzzles.py` | Mode problèmes (J13.3) : série (positions à solution unique, ordre de difficulté), score ; chaque solution unique (solveur exhaustif) et trouvée par le moteur du jeu à la distance de mat annoncée ; parcours de toute la série sans écran (clavier et souris : coup faux repris, indice, solution, fin de série, nouvelle série), sortie du mode. |
| `test_coverage_report.py` | Couverture en CI (J12.1) : regroupement par paquet, badge shields.io, résumé Markdown, seuil bloquant sur `core`. |
| `test_game_result.py` | Résultat de partie : vainqueur, motif de fin, notation PGN, le mat prime sur les 50 coups. |

## Tests longs (`slow`, ~4 min)

```bash
python -m pytest -m slow -q
```

Perft profond (jusqu'à ~4 millions de nœuds par position : perft(5) sur la
position initiale, perft(4) sur Kiwipete, etc.), 1 000 parties différentielles
contre python-chess et 2 000 parties de comparaison SAN/UCI.
