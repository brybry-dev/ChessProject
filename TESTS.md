# Tests

## Installation

```bash
python -m pip install -e ".[dev]"
```

## Lancer les tests

```bash
# Suite rapide (~30 s) — les tests marqués `slow` sont exclus par défaut
python -m pytest -q
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
| `test_ai.py` | IA : mat préféré au pat, mat le plus court, coup toujours rendu, mat en 2, évaluation en centipions nulle au départ et antisymétrique par miroir, capture gratuite. |
| `test_game_controller.py` | Contrôleur sans écran (doublures de `Process` / `Queue`) : coup de l'IA après l'humain, reprise après R / L (avec confirmation), sous-promotion via le popup, robustesse du processus d'IA, pendule arrêtée pendant les fenêtres modales, animation non bloquante. |
| `test_ui.py` | Interface J5 : mise en page sur 6 tailles de fenêtre, préférences (aller-retour, champs invalides), écran « Nouvelle partie », glisser-déposer, clic-clic, flèches et marques, promotion au clavier, navigation dans l'historique sans modifier la partie, matériel et évaluation, fenêtres superposées, transitions de scènes, redimensionnement, dessin de chaque écran dans les deux thèmes. |
| `test_paths.py` | Lancement depuis un autre dossier, journal et sauvegarde dans le dossier de données utilisateur (sous-processus). |
| `test_differential.py` | Parties aléatoires comparées coup par coup à python-chess : coups légaux, échec, mat, pat, nulles (50 rapides, 1 000 en `slow`). |
| `test_fen.py` | Validation des FEN (31 FEN invalides, une par règle), aller-retour exact, compteurs. |
| `test_notation.py` | SAN / UCI : roques, désambiguïsation, en passant, promotions, échec et mat ; comparaison avec python-chess. |
| `test_game_result.py` | Résultat de partie : vainqueur, motif de fin, notation PGN, le mat prime sur les 50 coups. |

## Tests longs (`slow`, ~4 min)

```bash
python -m pytest -m slow -q
```

Perft profond (jusqu'à ~4 millions de nœuds par position : perft(5) sur la
position initiale, perft(4) sur Kiwipete, etc.), 1 000 parties différentielles
contre python-chess et 2 000 parties de comparaison SAN/UCI.
