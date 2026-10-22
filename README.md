# ChessProject

![CI](https://github.com/brybry-dev/ChessProject/actions/workflows/ci.yml/badge.svg)

Jeu d'échecs en Python / Pygame avec une IA NegaMax. Projet personnel servant de vitrine
technique : l'accent est mis sur la justesse des règles, les tests et la qualité du code.

## Fonctionnalités

- **Règles complètes** : roque, prise en passant, promotion et sous-promotions, mat et pat,
  50 coups, triple répétition, matériel insuffisant. Générateur de coups validé par perft
  et par 1 000 parties comparées coup par coup à python-chess.
- **Trois modes de jeu** : Joueur contre Joueur, Joueur contre IA (choix de la couleur),
  IA contre IA.
- **IA** : NegaMax alpha-bêta, approfondissement itératif limité en temps, table de
  transposition (Zobrist), quiescence, évaluation par phase de jeu. Cinq niveaux, de
  Débutant à Expert, dans un processus séparé pour que l'interface reste réactive.
- **Cadences** : Bullet 1+0, Blitz 3+2 et 5+0, Rapide 10+5 et 15+10, ou sans limite.
  Incrément Fischer, perte au temps (nulle si l'adversaire n'a pas de quoi mater). L'IA
  gère son temps.
- **Fin de partie** : abandon, proposition de nulle (l'IA accepte selon son évaluation),
  motif de fin affiché.
- **PGN** : export et import (commentaires, variantes et NAG ignorés à la lecture).
  **Sauvegarde** JSON versionnée, avec mode, niveau et pendules.
- **Protocole UCI** (`chessproject-uci`) : le moteur se branche dans une interface
  d'échecs ou joue contre d'autres moteurs.
- **Interface** : plateau retourné quand on joue les Noirs, historique en notation SAN,
  3 thèmes de plateau, sons, animation des coups.

L'état du projet, les bugs suivis et la feuille de route sont dans
[RAPPORT_ANALYSE.md](RAPPORT_ANALYSE.md).

## Prérequis

- Python **3.12** ou plus récent.
- Dépendances (installées automatiquement) : `pygame` 2.6.1, `platformdirs`.

## Installation

```bash
# Avec les outils de développement (tests, lint, typage)
python -m pip install -e ".[dev]"

# Ou pour jouer uniquement
python -m pip install -e .
```

## Lancement

```bash
chessproject            # commande installée par pip
python -m chessproject  # équivalent
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
| `S` / `L` | Sauvegarder / charger la partie |
| `E` / `I` | Exporter / importer la partie en PGN |
| `A` | Abandonner |
| `N` | Proposer la nulle (en Joueur contre Joueur, l'adversaire accepte avec `N`) |
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

Architecture en couches : `core` ← `ai` ← `ui` (le cœur ne dépend pas de pygame).

| Chemin | Rôle |
|---|---|
| `chessproject/core/engine.py` | Moteur de règles : plateau, génération des coups légaux, annulation, fins de partie (`GameResult`) |
| `chessproject/core/fen.py` | Lecture validée des positions FEN |
| `chessproject/core/notation.py` | Notation SAN et UCI (lecture et écriture) |
| `chessproject/core/perft.py` | Comptage perft, validation du générateur de coups |
| `chessproject/ai/search.py` | IA : NegaMax alpha-bêta, table de transposition, évaluation en centipions |
| `chessproject/serialization.py` | Sauvegarde / chargement JSON versionné, export FEN |
| `chessproject/paths.py` | Chemins des ressources et des données utilisateur |
| `chessproject/ui/app.py` | Interface pygame : menus, rendu, contrôleur de partie, point d'entrée |
| `chessproject/assets/` | Images des pièces et effets sonores |
| `tests/` | Tests : perft, différentiels contre python-chess, règles, IA, notation, FEN, UI |
| `pyproject.toml` | Métadonnées, dépendances, configuration de ruff, mypy et pytest |
| `RAPPORT_ANALYSE.md` | Audit du projet, suivi des bugs et feuille de route |

## Feuille de route

- **J0 — Outillage** ✅ : `pyproject.toml`, ruff, mypy, CI multi-OS, README.
- **J1 — Correction** ✅ : plus aucun bug bloquant connu (règles, IA, contrôleur).
- **J2 — Socle moteur** ✅ : types, modèle de résultat de partie, notation SAN, FEN validée.
- **J3 — IA** ✅ : adversaire solide, borné en temps, avec niveaux de difficulté.
- **J4 — Fonctionnalités** ✅ : import/export PGN, cadence (temps + incrément), sauvegarde v2.
- **J5 — Interface** : refonte visuelle, mise en page adaptative, interactions soignées.
- **J6 — Packaging et vitrine** : exécutables, README illustré, version publiée.

Le détail des tâches et des critères d'acceptation est dans
[RAPPORT_ANALYSE.md, §4](RAPPORT_ANALYSE.md#4-phase-4--feuille-de-route-2026-10-22).

## Captures d'écran

À venir (J6).

## Licence

[MIT](LICENSE).
