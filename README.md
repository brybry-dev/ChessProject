# ChessProject

![CI](https://github.com/brybry-dev/ChessProject/actions/workflows/ci.yml/badge.svg)

Jeu d'échecs en Python / Pygame avec une IA NegaMax. Projet personnel servant de vitrine
technique : l'accent est mis sur la justesse des règles, les tests et la qualité du code.

## Fonctionnalités

- **Règles complètes** : roque, prise en passant, promotion et sous-promotions (dame, tour,
  fou, cavalier), mat et pat, règle des 50 coups, triple répétition, matériel insuffisant.
- **Trois modes de jeu** : Joueur contre Joueur, Joueur contre IA (choix de la couleur),
  IA contre IA.
- **IA NegaMax avec élagage alpha-bêta** (profondeur 3, approfondissement itératif), exécutée
  dans un processus séparé pour que l'interface reste réactive pendant la réflexion.
- **Sauvegarde et chargement** au format JSON versionné ; les coups sont rejoués par le
  moteur au chargement.
- **Interface** : 3 thèmes de plateau, sons, animation des coups, surbrillance des coups
  légaux, historique des coups avec défilement, chronomètre.

Des bugs connus restent ouverts (par exemple l'orientation du plateau quand on joue les
Noirs, B26) ; ils sont suivis dans [RAPPORT_ANALYSE.md](RAPPORT_ANALYSE.md).

## Prérequis

- Python **3.12** ou plus récent.
- Dépendances (installées automatiquement) : `pygame` 2.6.1, `numpy`, `platformdirs`.

## Installation

```bash
# Avec les outils de développement (tests, lint, typage)
python -m pip install -e ".[dev]"

# Ou pour jouer uniquement
python -m pip install -e .
```

## Lancement

```bash
python ChessMain.py
```

Le jeu peut être lancé depuis n'importe quel dossier. La sauvegarde (`saved_game.json`)
et le journal (`chess.log`, tournant) sont écrits dans le dossier de données de
l'utilisateur (par exemple `~/.local/share/ChessProject` sous Linux), modifiable avec la
variable d'environnement `CHESSPROJECT_DATA_DIR`.

### Raccourcis clavier

| Touche | Action |
|---|---|
| `Z` | Annuler le dernier coup (contre l'IA, annule aussi la réponse de l'IA) |
| `R` | Réinitialiser la partie |
| `S` | Sauvegarder la partie |
| `L` | Charger la partie sauvegardée |
| `C` | Changer les couleurs du plateau |
| `H` | Afficher / masquer les raccourcis |

## Qualité

```bash
python -m pytest -q            # suite rapide (les tests « slow » sont exclus par défaut)
python -m pytest -q -m slow    # perft profond (plusieurs minutes)
ruff check .                   # lint
ruff format --check .          # formatage
python -m mypy .               # typage (strict sur le moteur, souple sur l'UI)
```

Le générateur de coups est validé par un **perft** sur 6 positions de référence (position
initiale, Kiwipete et positions 3 à 6 du Chess Programming Wiki) : le nombre de nœuds de
l'arbre des coups légaux est comparé aux valeurs publiées. Le détail des tests est dans
[TESTS.md](TESTS.md).

## Structure du dépôt

| Fichier | Rôle |
|---|---|
| `ChessMain.py` | Point d'entrée, interface Pygame (menus, rendu, animation) et contrôleur de partie |
| `ChessEngine.py` | Moteur de règles : plateau, coups, génération des coups légaux, fins de partie |
| `ChessAI.py` | IA : recherche NegaMax alpha-bêta et évaluation de position |
| `serialization.py` | Sauvegarde / chargement des parties en JSON, génération de FEN |
| `paths.py` | Chemins des ressources (images, sons) et des données utilisateur |
| `fen_utils.py` | Chargement d'une position FEN et fonctions `perft` (utilitaires de test) |
| `test_*.py` | Tests : perft, régressions de règles, sérialisation, contrôleur |
| `images/`, `sounds/` | Images des pièces et effets sonores |
| `pyproject.toml` | Métadonnées, dépendances, configuration de ruff, mypy et pytest |
| `RAPPORT_ANALYSE.md` | Audit du projet, suivi des bugs et feuille de route |

## Feuille de route

- **J0 — Outillage** : `pyproject.toml`, ruff, mypy, CI multi-OS, README.
- **J1 — Correction** : plus aucun bug bloquant connu (règles, IA, contrôleur).
- **J2 — Socle moteur** : types, modèle de résultat de partie, notation SAN, FEN validée.
- **J3 — IA** : adversaire solide, borné en temps, avec niveaux de difficulté.
- **J4 — Fonctionnalités** : import/export PGN, cadence (temps + incrément), sauvegarde v2.
- **J5 — Interface** : refonte visuelle, mise en page adaptative, interactions soignées.
- **J6 — Packaging et vitrine** : exécutables, README illustré, version publiée.

Le détail des tâches et des critères d'acceptation est dans
[RAPPORT_ANALYSE.md, §4](RAPPORT_ANALYSE.md#4-phase-4--feuille-de-route-2026-10-22).

## Captures d'écran

À venir (J6).

## Licence

À définir : le dépôt ne contient pas encore de fichier `LICENSE`.
