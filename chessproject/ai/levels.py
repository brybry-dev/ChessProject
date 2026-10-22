"""
Niveaux de difficulté (J3.7)
----------------------------
Un niveau combine les limites de recherche (temps, profondeur) et deux façons
d'affaiblir le jeu de manière naturelle pour un humain :

- un **bruit d'évaluation** : chaque coup candidat de la racine reçoit une petite
  erreur aléatoire de jugement (en centipions) avant le choix ;
- une **probabilité d'erreur** : le coup est parfois choisi parmi les quelques
  meilleurs coups plutôt que le meilleur.

« Difficile » et « Expert » jouent le meilleur coup trouvé, sans bruit ; ils ne
diffèrent que par le temps et la profondeur de réflexion.
"""

import random
from dataclasses import dataclass

from chessproject.ai import search
from chessproject.ai.search import Searcher, SearchLimits
from chessproject.core import engine


@dataclass(frozen=True, slots=True)
class Level:
    name: str
    movetime_ms: int
    max_depth: int
    eval_noise_cp: int  # amplitude maximale de l'erreur de jugement (± centipions)
    mistake_probability: float  # probabilité de jouer un coup parmi les suivants
    mistake_pool: int  # nombre de coups candidats lors d'une « erreur »


LEVELS: tuple[Level, ...] = (
    Level(
        "Débutant",
        movetime_ms=150,
        max_depth=1,
        eval_noise_cp=250,
        mistake_probability=0.35,
        mistake_pool=5,
    ),
    Level(
        "Facile",
        movetime_ms=300,
        max_depth=2,
        eval_noise_cp=120,
        mistake_probability=0.20,
        mistake_pool=4,
    ),
    Level(
        "Moyen",
        movetime_ms=700,
        max_depth=3,
        eval_noise_cp=50,
        mistake_probability=0.08,
        mistake_pool=3,
    ),
    Level(
        "Difficile",
        movetime_ms=1500,
        max_depth=5,
        eval_noise_cp=0,
        mistake_probability=0.0,
        mistake_pool=1,
    ),
    Level(
        "Expert",
        movetime_ms=3000,
        max_depth=search.MAX_PLY,
        eval_noise_cp=0,
        mistake_probability=0.0,
        mistake_pool=1,
    ),
)
LEVELS_BY_NAME: dict[str, Level] = {level.name: level for level in LEVELS}
DEFAULT_LEVEL: Level = LEVELS_BY_NAME["Moyen"]


def choose_move(
    game_state: engine.GameState, level: Level, rng: random.Random | None = None
) -> engine.Move | None:
    """Coup joué par l'IA au niveau ``level`` (None s'il n'existe aucun coup légal)."""
    rng = rng or random.Random()
    moves = game_state.get_valid_moves()
    if not moves:
        return None
    searcher = Searcher()
    result = searcher.think(
        game_state, SearchLimits(depth=level.max_depth, movetime_ms=level.movetime_ms)
    )
    if level.eval_noise_cp == 0 and level.mistake_probability == 0.0:
        return result.move

    # Évaluation de chaque coup de la racine à la profondeur atteinte (moins un), avec la
    # table de transposition déjà remplie : rapide, et cohérent avec la recherche.
    depth = max(result.depth - 1, 0)
    scored: list[tuple[int, engine.Move]] = []
    for move in moves:
        game_state.make_move(move, validate=False)
        try:
            score, _ = searcher.negamax(
                game_state, game_state.get_valid_moves(), depth, -search.INF, search.INF, 1
            )
        finally:
            game_state.undo_move()
        noise = rng.randint(-level.eval_noise_cp, level.eval_noise_cp)
        # Un mat reste un mat : le bruit ne s'applique qu'aux scores ordinaires.
        if abs(score) < search.MATE_THRESHOLD:
            score += noise
        scored.append((-score, move))
    scored.sort(key=lambda item: item[0], reverse=True)
    if level.mistake_probability and rng.random() < level.mistake_probability:
        pool = scored[: max(1, level.mistake_pool)]
        # Jamais d'« erreur » qui laisse passer un mat contre soi.
        pool = [item for item in pool if item[0] > -search.MATE_THRESHOLD] or scored[:1]
        return rng.choice(pool)[1]
    return scored[0][1]
