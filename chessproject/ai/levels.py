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

La réflexion est bornée par un budget de **nœuds** (J8.0) : la force d'un niveau ne
dépend ni de la vitesse de la machine ni de la charge (mini-ligues en parallèle). Le temps
reste un plafond, pour qu'une machine lente ne fasse pas attendre le joueur.

Chaque niveau suit le livre d'ouvertures (J8.3) pendant ses ``book_plies`` premiers
demi-coups : les niveaux faibles en sortent tôt, les plus forts connaissent plus de
théorie.
"""

import random
from dataclasses import asdict, dataclass

from chessproject.ai import book, search
from chessproject.ai.search import Searcher, SearchLimits
from chessproject.core import engine, fen


@dataclass(frozen=True, slots=True)
class Level:
    name: str
    movetime_ms: int
    max_depth: int
    eval_noise_cp: int  # amplitude maximale de l'erreur de jugement (± centipions)
    mistake_probability: float  # probabilité de jouer un coup parmi les suivants
    mistake_pool: int  # nombre de coups candidats lors d'une « erreur »
    max_nodes: int | None = None  # budget de nœuds de la recherche (None : temps seul)
    book_plies: int = 0  # demi-coups (depuis le début de partie) joués dans le livre
    # Force mesurée contre Stockfish bridé (J8.2) : Elo et demi-largeur de l'IC à 95 %
    elo: int | None = None
    elo_margin: int | None = None


LEVELS: tuple[Level, ...] = (
    Level(
        "Débutant",
        movetime_ms=150,
        max_depth=1,
        eval_noise_cp=250,
        mistake_probability=0.35,
        mistake_pool=5,
        book_plies=4,
    ),
    Level(
        "Facile",
        movetime_ms=300,
        max_depth=2,
        eval_noise_cp=120,
        mistake_probability=0.20,
        mistake_pool=4,
        book_plies=6,
    ),
    Level(
        "Moyen",
        movetime_ms=700,
        max_depth=3,
        eval_noise_cp=50,
        mistake_probability=0.08,
        mistake_pool=3,
        book_plies=10,
    ),
    Level(
        "Difficile",
        movetime_ms=1500,
        max_depth=5,
        eval_noise_cp=0,
        mistake_probability=0.0,
        mistake_pool=1,
        book_plies=14,
    ),
    Level(
        "Expert",
        movetime_ms=3000,
        max_depth=search.MAX_PLY,
        eval_noise_cp=0,
        mistake_probability=0.0,
        mistake_pool=1,
        book_plies=20,
    ),
)
LEVELS_BY_NAME: dict[str, Level] = {level.name: level for level in LEVELS}
DEFAULT_LEVEL: Level = LEVELS_BY_NAME["Moyen"]

# Clés de parse_level_spec -> champ de Level
_SPEC_FIELDS: dict[str, str] = {
    "movetime": "movetime_ms",
    "depth": "max_depth",
    "noise": "eval_noise_cp",
    "mistake": "mistake_probability",
    "pool": "mistake_pool",
    "nodes": "max_nodes",
    "book": "book_plies",
}


def parse_level_spec(spec: str) -> Level:
    """Niveau décrit par ``"base=Moyen,nodes=4000,noise=40"`` (outil de calibration, J8.0).

    ``base`` (défaut : niveau par défaut) donne les valeurs de départ ; les autres clés
    les remplacent : ``movetime``, ``depth``, ``noise``, ``mistake``, ``pool``, ``nodes``
    (``nodes=0`` : pas de budget de nœuds), ``book`` et ``name``. ``ValueError`` si la description
    est invalide.
    """
    values: dict[str, str] = {}
    for item in spec.split(","):
        if not item.strip():
            continue
        key, sep, value = item.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not value:
            raise ValueError(f"élément sans valeur : {item.strip()!r}")
        if key not in _SPEC_FIELDS and key not in ("base", "name"):
            raise ValueError(f"clé inconnue : {key!r}")
        values[key] = value
    base_name = values.pop("base", DEFAULT_LEVEL.name)
    if base_name not in LEVELS_BY_NAME:
        raise ValueError(f"niveau de base inconnu : {base_name!r}")
    fields = asdict(LEVELS_BY_NAME[base_name])
    fields["name"] = values.pop("name", f"{base_name}*" if values else base_name)
    for key, value in values.items():
        field = _SPEC_FIELDS[key]
        number: int | float = float(value) if field == "mistake_probability" else int(value)
        if number < 0 or (field == "mistake_probability" and number > 1):
            raise ValueError(f"valeur hors limites pour {key} : {value}")
        fields[field] = number
    if fields["max_nodes"] == 0:
        fields["max_nodes"] = None
    if fields["movetime_ms"] < 1 or fields["max_depth"] < 1 or fields["mistake_pool"] < 1:
        raise ValueError("movetime, depth et pool doivent valoir au moins 1")
    return Level(**fields)


def game_ply(game_state: engine.GameState) -> int:
    """Demi-coups joués depuis le début de la partie (d'après le numéro de coup FEN)."""
    return 2 * (fen.fullmove_number(game_state) - 1) + (0 if game_state.white_to_move else 1)


def book_choice(
    game_state: engine.GameState, level: Level, rng: random.Random | None = None
) -> engine.Move | None:
    """Coup du livre pour ce niveau, ou None (hors livre, ou au-delà de ``book_plies``)."""
    if game_ply(game_state) >= level.book_plies:
        return None
    return book.book_move(game_state, rng)


def choose_move(
    game_state: engine.GameState,
    level: Level,
    rng: random.Random | None = None,
    movetime_ms: int | None = None,
    use_book: bool = True,
) -> engine.Move | None:
    """Coup joué par l'IA au niveau ``level`` (None s'il n'existe aucun coup légal).

    ``movetime_ms`` plafonne le temps de réflexion du niveau (cadence, J4.2) ;
    ``use_book=False`` ignore le livre d'ouvertures (mesures de force, J8.1).
    """
    rng = rng or random.Random()
    moves = game_state.get_valid_moves()
    if not moves:
        return None
    if use_book:
        move = book_choice(game_state, level, rng)
        if move is not None:
            return move
    searcher = Searcher()
    result = searcher.think(
        game_state,
        SearchLimits(
            depth=level.max_depth,
            movetime_ms=min(level.movetime_ms, movetime_ms or level.movetime_ms),
            nodes=level.max_nodes,
        ),
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
