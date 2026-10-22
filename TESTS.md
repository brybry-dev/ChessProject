# Tests

## Installation

```bash
python -m pip install -e ".[dev]"
```

## Lancer les tests

```bash
# Suite rapide (~7 s) — les tests marqués `slow` sont exclus par défaut
python -m pytest -q
```

## Contenu

| Fichier | Rôle |
|---|---|
| `test_chess.py` | Tests historiques : en passant, roque, répétition, règle des 50 coups, matériel insuffisant, performance de l'IA. |
| `test_perft.py` | **Validation de référence du générateur de coups.** Compte les nœuds de l'arbre des coups légaux (perft) sur 6 positions standard (position initiale, Kiwipete, positions 3 à 6 du Chess Programming Wiki) et compare aux valeurs publiées. |
| `test_rules_regression.py` | Verrouille les bugs de règles corrigés : pat, mat, matériel insuffisant resserré, triple répétition, roque à travers une case tenue par un pion, broches recalculées, sous-promotions, prise en passant exposant le roi. |
| `test_serialization.py` | Sauvegarde / chargement JSON des parties (`serialization.py`) : génération de FEN, aller-retour position + historique, conservation de l'orientation et du choix de sous-promotion, rejet d'une version inconnue, recalcul des drapeaux de fin de partie au chargement. |
| `test_orientation.py` | Plateau retourné (B26) : rotation de la vue à 180° (aller-retour pixel/case sur les 64 cases, libellés), position standard en jouant les Noirs, échec détecté, roque par le roi. |
| `test_ai.py` | IA : mat préféré au pat, mat le plus court, coup toujours rendu, mat en 2, évaluation en centipions nulle au départ et antisymétrique par miroir, capture gratuite. |
| `test_game_controller.py` | Contrôleur sans écran (doublures de `Process` / `Queue`) : coup de l'IA après l'humain, reprise après R / L, sous-promotion via le popup, robustesse du processus d'IA, pendule hors menus et animations. |
| `test_paths.py` | Lancement depuis un autre dossier, journal et sauvegarde dans le dossier de données utilisateur (sous-processus). |
| `fen_utils.py` | Chargement d'une position FEN + fonctions `perft` / `perft_divide` (utilitaires de test, pas du code de jeu). |

## Perft profond (lent, ~150 s)

```bash
python -m pytest -m slow -q
```

Vérifie jusqu'à ~4 millions de nœuds par position (perft(5) sur la position
initiale, perft(4) sur Kiwipete, etc.). Toutes ces valeurs sont exactes :
le générateur de coups est conforme.

## Tests différentiels (optionnel)

Avec `python-chess` installé, on peut comparer coup par coup le générateur du
moteur à un moteur de référence (voir l'historique Git pour le script `_diff.py`
utilisé pendant la campagne de correction).
