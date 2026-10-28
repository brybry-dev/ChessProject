"""
Évaluation statique (J3.6)
--------------------------
Score en centipions entiers, du point de vue des Blancs (positif = avantage blanc).

Chaque terme est calculé pour les deux camps, par symétrie : l'évaluation est exactement
antisymétrique par miroir des couleurs (testé). Deux scores sont tenus en parallèle,
« milieu de partie » (mg) et « finale » (eg), puis interpolés selon la phase de jeu,
mesurée par le matériel restant (24 = toutes les pièces, 0 = rois et pions) :

    score = (mg × phase + eg × (24 − phase)) / 24

Termes : matériel, tables positionnelles (dont roi abrité en milieu de partie et roi
centralisé en finale), pions doublés / isolés / passés, paire de fous, tours sur colonne
ouverte ou semi-ouverte, bouclier de pions devant le roi.
"""

from chessproject.core import engine

PIECE_VALUES: dict[str, int] = {"K": 0, "Q": 900, "R": 500, "B": 330, "N": 320, "p": 100}

PHASE_WEIGHTS: dict[str, int] = {"N": 1, "B": 1, "R": 2, "Q": 4}
MAX_PHASE: int = 24

# Tables du point de vue des Blancs, rangée 0 = 8e rangée (les Noirs lisent la rangée
# miroir). Valeurs en centipions.
_Table = tuple[tuple[int, ...], ...]

KNIGHT: _Table = (
    (-50, -40, -30, -30, -30, -30, -40, -50),
    (-40, -20, 0, 0, 0, 0, -20, -40),
    (-30, 0, 10, 15, 15, 10, 0, -30),
    (-30, 5, 15, 20, 20, 15, 5, -30),
    (-30, 0, 15, 20, 20, 15, 0, -30),
    (-30, 5, 10, 15, 15, 10, 5, -30),
    (-40, -20, 0, 5, 5, 0, -20, -40),
    (-50, -40, -30, -30, -30, -30, -40, -50),
)
BISHOP: _Table = (
    (-20, -10, -10, -10, -10, -10, -10, -20),
    (-10, 0, 0, 0, 0, 0, 0, -10),
    (-10, 0, 5, 10, 10, 5, 0, -10),
    (-10, 5, 5, 10, 10, 5, 5, -10),
    (-10, 0, 10, 10, 10, 10, 0, -10),
    (-10, 10, 10, 10, 10, 10, 10, -10),
    (-10, 5, 0, 0, 0, 0, 5, -10),
    (-20, -10, -10, -10, -10, -10, -10, -20),
)
ROOK: _Table = (
    (0, 0, 0, 0, 0, 0, 0, 0),
    (5, 10, 10, 10, 10, 10, 10, 5),
    (-5, 0, 0, 0, 0, 0, 0, -5),
    (-5, 0, 0, 0, 0, 0, 0, -5),
    (-5, 0, 0, 0, 0, 0, 0, -5),
    (-5, 0, 0, 0, 0, 0, 0, -5),
    (-5, 0, 0, 0, 0, 0, 0, -5),
    (0, 0, 0, 5, 5, 0, 0, 0),
)
QUEEN: _Table = (
    (-20, -10, -10, -5, -5, -10, -10, -20),
    (-10, 0, 0, 0, 0, 0, 0, -10),
    (-10, 0, 5, 5, 5, 5, 0, -10),
    (-5, 0, 5, 5, 5, 5, 0, -5),
    (0, 0, 5, 5, 5, 5, 0, -5),
    (-10, 5, 5, 5, 5, 5, 0, -10),
    (-10, 0, 5, 0, 0, 0, 0, -10),
    (-20, -10, -10, -5, -5, -10, -10, -20),
)
PAWN_MG: _Table = (
    (0, 0, 0, 0, 0, 0, 0, 0),
    (50, 50, 50, 50, 50, 50, 50, 50),
    (10, 10, 20, 30, 30, 20, 10, 10),
    (5, 5, 10, 25, 25, 10, 5, 5),
    (0, 0, 0, 20, 20, 0, 0, 0),
    (5, -5, -10, 0, 0, -10, -5, 5),
    (5, 10, 10, -20, -20, 10, 10, 5),
    (0, 0, 0, 0, 0, 0, 0, 0),
)
PAWN_EG: _Table = (
    (0, 0, 0, 0, 0, 0, 0, 0),
    (80, 80, 80, 80, 80, 80, 80, 80),
    (50, 50, 50, 50, 50, 50, 50, 50),
    (30, 30, 30, 30, 30, 30, 30, 30),
    (20, 20, 20, 20, 20, 20, 20, 20),
    (10, 10, 10, 10, 10, 10, 10, 10),
    (0, 0, 0, 0, 0, 0, 0, 0),
    (0, 0, 0, 0, 0, 0, 0, 0),
)
KING_MG: _Table = (
    (-30, -40, -40, -50, -50, -40, -40, -30),
    (-30, -40, -40, -50, -50, -40, -40, -30),
    (-30, -40, -40, -50, -50, -40, -40, -30),
    (-30, -40, -40, -50, -50, -40, -40, -30),
    (-20, -30, -30, -40, -40, -30, -30, -20),
    (-10, -20, -20, -20, -20, -20, -20, -10),
    (20, 20, 0, 0, 0, 0, 20, 20),
    (20, 30, 10, 0, 0, 10, 30, 20),
)
KING_EG: _Table = (
    (-50, -40, -30, -20, -20, -30, -40, -50),
    (-30, -20, -10, 0, 0, -10, -20, -30),
    (-30, -10, 20, 30, 30, 20, -10, -30),
    (-30, -10, 30, 40, 40, 30, -10, -30),
    (-30, -10, 30, 40, 40, 30, -10, -30),
    (-30, -10, 20, 30, 30, 20, -10, -30),
    (-30, -30, 0, 0, 0, 0, -30, -30),
    (-50, -30, -30, -30, -30, -30, -30, -50),
)
# (table milieu de partie, table finale) par type de pièce.
TABLES: dict[str, tuple[_Table, _Table]] = {
    "N": (KNIGHT, KNIGHT),
    "B": (BISHOP, BISHOP),
    "R": (ROOK, ROOK),
    "Q": (QUEEN, QUEEN),
    "p": (PAWN_MG, PAWN_EG),
    "K": (KING_MG, KING_EG),
}

# Structure de pions (mg, eg)
DOUBLED_PAWN: tuple[int, int] = (-10, -20)  # par pion en trop sur une colonne
ISOLATED_PAWN: tuple[int, int] = (-10, -15)
# Pion passé : bonus selon la rangée atteinte (index = rangées avancées depuis la 2e).
PASSED_PAWN_MG: tuple[int, ...] = (0, 5, 10, 15, 30, 50, 80, 0)
PASSED_PAWN_EG: tuple[int, ...] = (0, 10, 20, 35, 60, 90, 140, 0)
BISHOP_PAIR: tuple[int, int] = (30, 50)
ROOK_OPEN_FILE: tuple[int, int] = (20, 10)
ROOK_SEMI_OPEN_FILE: tuple[int, int] = (10, 5)
KING_SHELTER_PAWN: int = 10  # milieu de partie, par pion ami devant le roi


def _signed_tables(piece: str, eg: bool) -> tuple[int, ...]:
    """Valeur + table positionnelle de ``piece`` (« wN », « bp »…), signée du point de vue
    des Blancs, indexée par case (rangée × 8 + colonne)."""
    color, kind = piece[0], piece[1]
    sign = 1 if color == "w" else -1
    table = TABLES[kind][1 if eg else 0]
    return tuple(
        sign * (PIECE_VALUES[kind] + table[r if color == "w" else 7 - r][c])
        for r in range(8)
        for c in range(8)
    )


# Tables fusionnées (J10.1) : une lecture par pièce au lieu de quatre.
_PIECES: tuple[str, ...] = tuple(color + kind for color in "wb" for kind in TABLES)
_MG: dict[str, tuple[int, ...]] = {piece: _signed_tables(piece, eg=False) for piece in _PIECES}
_EG: dict[str, tuple[int, ...]] = {piece: _signed_tables(piece, eg=True) for piece in _PIECES}
_PHASE: dict[str, int] = {piece: PHASE_WEIGHTS.get(piece[1], 0) for piece in _PIECES}


# Cache de la structure de pions (J10.1) : elle ne change qu'aux coups de pion et aux
# captures de pion, et revient sans cesse pendant une recherche. Clé de Zobrist des seuls
# pions ; vidé au-delà de PAWN_CACHE_MAX_ENTRIES.
PAWN_CACHE_MAX_ENTRIES: int = 1 << 16
# Clé des pions -> (mg, eg, colonnes des pions blancs, colonnes des pions noirs), les
# colonnes en masque de 8 bits (bit c = au moins un pion sur la colonne c).
_PawnInfo = tuple[int, int, int, int]
_pawn_cache: dict[int, _PawnInfo] = {}
_PAWN_KEYS: dict[str, tuple[int, ...]] = {
    "wp": engine.ZOBRIST_PIECES["wp"],
    "bp": engine.ZOBRIST_PIECES["bp"],
}


def evaluate(game_state: engine.GameState) -> int:
    board = game_state.board
    mg = eg = 0
    phase = 0
    pawn_key = 0
    white_bishops = black_bishops = 0
    rooks: list[tuple[str, int]] = []
    mg_tables, eg_tables, phase_weights = _MG, _EG, _PHASE

    square = -1
    for row in board:
        for piece in row:
            square += 1
            if piece == "--":
                continue
            mg += mg_tables[piece][square]
            eg += eg_tables[piece][square]
            phase += phase_weights[piece]
            kind = piece[1]
            if kind == "p":
                pawn_key ^= _PAWN_KEYS[piece][square]
            elif kind == "B":
                if piece[0] == "w":
                    white_bishops += 1
                else:
                    black_bishops += 1
            elif kind == "R":
                rooks.append((piece[0], square & 7))

    pawns = _pawn_cache.get(pawn_key)
    if pawns is None:
        pawns = _pawn_structure(board)
        if len(_pawn_cache) >= PAWN_CACHE_MAX_ENTRIES:
            _pawn_cache.clear()
        _pawn_cache[pawn_key] = pawns
    pawn_mg, pawn_eg, white_files, black_files = pawns
    mg += pawn_mg
    eg += pawn_eg

    if white_bishops >= 2:
        mg += BISHOP_PAIR[0]
        eg += BISHOP_PAIR[1]
    if black_bishops >= 2:
        mg -= BISHOP_PAIR[0]
        eg -= BISHOP_PAIR[1]

    for color, c in rooks:
        own, enemy = (white_files, black_files) if color == "w" else (black_files, white_files)
        bit = 1 << c
        if not own & bit:
            bonus = ROOK_OPEN_FILE if not enemy & bit else ROOK_SEMI_OPEN_FILE
            sign = 1 if color == "w" else -1
            mg += sign * bonus[0]
            eg += sign * bonus[1]

    mg += _king_shelter(board, game_state.white_king_location, "w")
    mg -= _king_shelter(board, game_state.black_king_location, "b")

    phase = min(phase, MAX_PHASE)
    blended = mg * phase + eg * (MAX_PHASE - phase)
    # Arrondi vers zéro (et non vers -∞ comme //) : garde l'antisymétrie exacte.
    return blended // MAX_PHASE if blended >= 0 else -(-blended // MAX_PHASE)


def _pawn_structure(board: list[list[str]]) -> _PawnInfo:
    """Pions doublés, isolés et passés des deux camps, et colonnes occupées par des pions."""
    pawn_rows: dict[str, list[list[int]]] = {
        "w": [[] for _ in range(8)],
        "b": [[] for _ in range(8)],
    }
    for r, row in enumerate(board):
        for c, piece in enumerate(row):
            if piece[1:] == "p":
                pawn_rows[piece[0]][c].append(r)
    mg = eg = 0
    for color, sign in (("w", 1), ("b", -1)):
        enemy = "b" if color == "w" else "w"
        own_files, enemy_files = pawn_rows[color], pawn_rows[enemy]
        for c in range(8):
            pawns = own_files[c]
            if not pawns:
                continue
            if len(pawns) > 1:
                extra = len(pawns) - 1
                mg += sign * DOUBLED_PAWN[0] * extra
                eg += sign * DOUBLED_PAWN[1] * extra
            neighbours = [f for f in (c - 1, c + 1) if 0 <= f < 8]
            if not any(own_files[f] for f in neighbours):
                mg += sign * ISOLATED_PAWN[0] * len(pawns)
                eg += sign * ISOLATED_PAWN[1] * len(pawns)
            for r in pawns:
                if _is_passed(color, r, c, enemy_files):
                    advance = (6 - r) if color == "w" else (r - 1)
                    mg += sign * PASSED_PAWN_MG[advance]
                    eg += sign * PASSED_PAWN_EG[advance]
    white_files = sum(1 << c for c in range(8) if pawn_rows["w"][c])
    black_files = sum(1 << c for c in range(8) if pawn_rows["b"][c])
    return mg, eg, white_files, black_files


def _is_passed(color: str, row: int, col: int, enemy_files: list[list[int]]) -> bool:
    """Aucun pion adverse devant ce pion, sur sa colonne ou les colonnes voisines."""
    for f in (col - 1, col, col + 1):
        if not 0 <= f < 8:
            continue
        for enemy_row in enemy_files[f]:
            if (color == "w" and enemy_row < row) or (color == "b" and enemy_row > row):
                return False
    return True


def _king_shelter(board: list[list[str]], king: engine.Square, color: str) -> int:
    """Pions amis sur les deux rangées devant le roi, colonnes du roi et voisines."""
    row, col = king
    forward = -1 if color == "w" else 1
    pawn = color + "p"
    count = 0
    for dr in (forward, 2 * forward):
        r = row + dr
        if not 0 <= r < 8:
            continue
        for c in (col - 1, col, col + 1):
            if 0 <= c < 8 and board[r][c] == pawn:
                count += 1
    return KING_SHELTER_PAWN * min(count, 3)
