"""
Module chessproject.core.engine
-------------------------------
Règles du jeu : plateau, génération des coups légaux, annulation, hachage de Zobrist et
fins de partie.
"""

import random
from dataclasses import dataclass
from enum import Enum
from typing import Any

# Constantes
DIMENSION: int = 8
# Case du plateau : (rangée, colonne), rangée 0 = 8e rangée, colonne 0 = colonne a.
Square = tuple[int, int]

# --------------------------------------------------------------------------
# Hachage de Zobrist (J3.1) : une clé de 64 bits par position, mise à jour par XOR à
# chaque coup. Graine fixe : les clés sont identiques d'un processus à l'autre (B32).
# --------------------------------------------------------------------------
_ZOBRIST_RNG = random.Random(20261022)
_PIECE_CODES = ("wp", "wN", "wB", "wR", "wQ", "wK", "bp", "bN", "bB", "bR", "bQ", "bK")
ZOBRIST_PIECES: dict[str, tuple[int, ...]] = {
    code: tuple(_ZOBRIST_RNG.getrandbits(64) for _ in range(64)) for code in _PIECE_CODES
}
ZOBRIST_BLACK_TO_MOVE: int = _ZOBRIST_RNG.getrandbits(64)
# Un nombre par combinaison des 4 droits de roque (masque wks|wqs|bks|bqs sur 4 bits).
ZOBRIST_CASTLING: tuple[int, ...] = tuple(_ZOBRIST_RNG.getrandbits(64) for _ in range(16))
# Case en passant : un nombre par colonne. Convention identique à la clé historique :
# la case compte dès qu'elle est posée, que la prise soit possible ou non.
ZOBRIST_EN_PASSANT: tuple[int, ...] = tuple(_ZOBRIST_RNG.getrandbits(64) for _ in range(8))


def _zobrist_square(piece: str, row: int, col: int) -> int:
    return ZOBRIST_PIECES[piece][row * 8 + col]


def _zobrist_en_passant(square: "Square | None") -> int:
    return ZOBRIST_EN_PASSANT[square[1]] if square else 0


class Color(Enum):
    WHITE = "w"
    BLACK = "b"


class Termination(Enum):
    """Motif de fin de partie.

    Choix de règles (documentés, cf. rapport B34) : la triple répétition et la règle des
    50 coups mettent fin à la partie automatiquement, sans réclamation (FIDE : nulles à
    réclamer ; automatiques à 5 répétitions et 75 coups). Le mat prime toujours sur ces
    nulles (FIDE 9.3).
    """

    CHECKMATE = "checkmate"
    STALEMATE = "stalemate"
    FIFTY_MOVES = "fifty_moves"
    THREEFOLD_REPETITION = "threefold_repetition"
    INSUFFICIENT_MATERIAL = "insufficient_material"


_DRAW_DESCRIPTIONS: dict[Termination, str] = {
    Termination.STALEMATE: "Nulle par pat",
    Termination.FIFTY_MOVES: "Nulle par la règle des 50 coups",
    Termination.THREEFOLD_REPETITION: "Nulle par triple répétition",
    Termination.INSUFFICIENT_MATERIAL: "Nulle par matériel insuffisant",
}


@dataclass(frozen=True)
class GameResult:
    """Résultat d'une partie : ``termination`` est None tant que la partie continue."""

    termination: Termination | None = None
    winner: Color | None = None

    @staticmethod
    def ongoing() -> "GameResult":
        return GameResult()

    @property
    def is_over(self) -> bool:
        return self.termination is not None

    @property
    def pgn(self) -> str:
        """Résultat au format PGN : ``1-0``, ``0-1``, ``1/2-1/2`` ou ``*``."""
        if not self.is_over:
            return "*"
        if self.winner is Color.WHITE:
            return "1-0"
        if self.winner is Color.BLACK:
            return "0-1"
        return "1/2-1/2"

    @property
    def description(self) -> str:
        if self.termination is None:
            return "Partie en cours"
        if self.termination is Termination.CHECKMATE:
            camp = "Blancs" if self.winner is Color.WHITE else "Noirs"
            return f"Les {camp} gagnent par échec et mat"
        return _DRAW_DESCRIPTIONS[self.termination]


def is_valid_index(index: int) -> bool:
    """Vérifier si un index est dans la plage du plateau."""
    return 0 <= index < DIMENSION


class GameState:
    """
    Classe représentant l'état du jeu.
    """

    def __init__(self) -> None:
        self.board: list[list[str]] = [
            ["bR", "bN", "bB", "bQ", "bK", "bB", "bN", "bR"],
            ["bp"] * DIMENSION,
            ["--"] * DIMENSION,
            ["--"] * DIMENSION,
            ["--"] * DIMENSION,
            ["--"] * DIMENSION,
            ["wp"] * DIMENSION,
            ["wR", "wN", "wB", "wQ", "wK", "wB", "wN", "wR"],
        ]

        self.move_functions = {
            "p": self.get_pawn_moves,
            "R": self.get_rook_moves,
            "N": self.get_knight_moves,
            "B": self.get_bishop_moves,
            "Q": self.get_queen_moves,
            "K": self.get_king_moves,
        }
        self.white_to_move: bool = True
        self.move_log: list[Move] = []
        self.white_king_location: Square = (7, 4)
        self.black_king_location: Square = (0, 4)
        self.checkmate: bool = False
        self.stalemate: bool = False
        # Motif de fin de la position courante, positionné par get_valid_moves().
        self.termination: Termination | None = None
        self.in_check: bool = False
        self.pins: list[tuple[int, int, int, int]] = []
        self.checks: list[tuple[int, int, int, int]] = []
        # Case d'en passant, ou None si aucune prise en passant n'est possible.
        self.enpassant_possible: Square | None = None
        self.current_castling_rights: CastleRights = CastleRights(True, True, True, True)
        self._valid_moves: list[Move] | None = None

        # Pour la règle des 50 coups
        self.fifty_move_counter: int = 0
        # Numéro de coup FEN de la position de départ (1 sauf partie chargée par FEN).
        self.start_fullmove: int = 1
        # Historique d'annulation : un UndoInfo par coup joué (J2.4).
        self.undo_stack: list[UndoInfo] = []
        # Répétitions : clés des positions rencontrées depuis le départ (pile) et nombre
        # d'occurrences de chacune, tenus à jour coup par coup (plus de deepcopy).
        self.position_keys: list[int] = []
        self.position_history: dict[int, int] = {}
        self.zobrist_key: int = 0
        self.reset_history()

    def reset_history(self) -> None:
        """Fait de la position courante le départ de la partie (après un chargement FEN)."""
        self.move_log = []
        self.undo_stack = []
        self.zobrist_key = self.compute_zobrist_key()
        self.position_keys = [self.zobrist_key]
        self.position_history = {self.zobrist_key: 1}
        self._valid_moves = None

    def compute_zobrist_key(self) -> int:
        """Clé de Zobrist recalculée entièrement (référence des mises à jour incrémentales)."""
        key = 0
        for r in range(DIMENSION):
            for c in range(DIMENSION):
                piece = self.board[r][c]
                if piece != "--":
                    key ^= _zobrist_square(piece, r, c)
        if not self.white_to_move:
            key ^= ZOBRIST_BLACK_TO_MOVE
        key ^= ZOBRIST_CASTLING[self.current_castling_rights.mask()]
        key ^= _zobrist_en_passant(self.enpassant_possible)
        return key

    def repetition_count(self) -> int:
        """Nombre d'occurrences de la position courante depuis le début de la partie."""
        return self.position_history.get(self.zobrist_key, 0)

    def get_board_hash_str(self) -> str:
        """Retourne une chaîne représentant l'état complet de la position.

        Inclut le plateau, le trait, les droits de roque et la case d'en passant :
        c'est nécessaire pour que la triple répétition (règle FIDE) et la table de
        transposition ne confondent pas deux positions réellement différentes.
        """
        # Clé lisible, utile au diagnostic ; le moteur et l'IA utilisent zobrist_key.
        # Chaîne explicite et non ``hash()``, randomisé par processus (cf. B32).
        cr = self.current_castling_rights
        castle = "".join("1" if right else "0" for right in (cr.wks, cr.wqs, cr.bks, cr.bqs))
        ep = self.enpassant_possible
        ep_str = f"{ep[0]}{ep[1]}" if ep else "-"
        turn = "w" if self.white_to_move else "b"
        return "".join("".join(row) for row in self.board) + turn + castle + ep_str

    def insufficient_material(self) -> bool:
        """
        Vérifie si la position est une nulle automatique par matériel insuffisant.

        Cas traités (règles FIDE des positions mortes) :
          - roi contre roi ;
          - roi + un fou ou un cavalier contre roi ;
          - roi + fou contre roi + fou, les deux fous sur des cases de même couleur.
        Toute présence de dame, tour ou pion exclut l'insuffisance de matériel.
        """
        white_minors: list[str] = []
        black_minors: list[str] = []
        bishop_square_colors: list[int] = []
        for r in range(DIMENSION):
            for c in range(DIMENSION):
                piece = self.board[r][c]
                if piece == "--" or piece[1] == "K":
                    continue
                if piece[1] in ("Q", "R", "p"):
                    return False
                (white_minors if piece[0] == "w" else black_minors).append(piece[1])
                if piece[1] == "B":
                    bishop_square_colors.append((r + c) % 2)
        if len(white_minors) <= 1 and not black_minors:
            return True
        if len(black_minors) <= 1 and not white_minors:
            return True
        if white_minors == ["B"] and black_minors == ["B"]:
            return bishop_square_colors[0] == bishop_square_colors[1]
        return False

    def make_move(
        self,
        move: "Move",
        validate: bool = True,
    ) -> None:
        """
        Applique un mouvement sur le plateau.
        Vérifie que le mouvement est valide avant application.
        Met à jour le compteur des 50 coups et l'historique de position.
        """
        if validate and move not in self.get_valid_moves():
            raise ValueError("Mouvement non valide.")
        # Tout ce que le coup écrase et qu'on ne peut pas recalculer, pour undo_move.
        self.undo_stack.append(
            UndoInfo(
                castling_rights=self.current_castling_rights.copy(),
                enpassant_possible=self.enpassant_possible,
                fifty_move_counter=self.fifty_move_counter,
            )
        )
        old_castling_mask = self.current_castling_rights.mask()
        old_enpassant = self.enpassant_possible
        key = self.zobrist_key ^ _zobrist_square(move.piece_moved, move.start_row, move.start_col)
        if move.is_enpassant_move:
            key ^= _zobrist_square(move.piece_captured, move.start_row, move.end_col)
        elif move.piece_captured != "--":
            key ^= _zobrist_square(move.piece_captured, move.end_row, move.end_col)
        self.board[move.start_row][move.start_col] = "--"
        self.board[move.end_row][move.end_col] = move.piece_moved
        self.move_log.append(move)
        self.white_to_move = not self.white_to_move
        if move.piece_moved == "wK":
            self.white_king_location = (move.end_row, move.end_col)
        elif move.piece_moved == "bK":
            self.black_king_location = (move.end_row, move.end_col)
        # Promotion : la pièce est portée par le coup (cf. Move.promotion_piece).
        if move.is_pawn_promotion:
            promoted_piece = move.promotion_piece or "Q"
            self.board[move.end_row][move.end_col] = move.piece_moved[0] + promoted_piece
        # En passant
        if move.is_enpassant_move:
            self.board[move.start_row][move.end_col] = "--"
        # Compteur des 50 coups : remis à zéro sur une capture ou un coup de pion
        if move.is_capture or move.piece_moved[1] == "p":
            self.fifty_move_counter = 0
        else:
            self.fifty_move_counter += 1
        # Mise à jour de l'en passant
        if move.piece_moved[1] == "p" and abs(move.start_row - move.end_row) == 2:
            self.enpassant_possible = ((move.start_row + move.end_row) // 2, move.start_col)
        else:
            self.enpassant_possible = None
        # Roque
        if move.is_castle_move:
            if move.end_col - move.start_col == 2:  # Roque court
                self.board[move.end_row][move.end_col - 1] = self.board[move.end_row][
                    move.end_col + 1
                ]
                self.board[move.end_row][move.end_col + 1] = "--"
            else:
                self.board[move.end_row][move.end_col + 1] = self.board[move.end_row][
                    move.end_col - 2
                ]
                self.board[move.end_row][move.end_col - 2] = "--"
        self.update_castle_rights(move)
        self._valid_moves = None
        # Fin de la mise à jour de Zobrist : pièce d'arrivée (éventuellement promue), tour
        # du roque, trait, droits de roque et case en passant.
        key ^= _zobrist_square(self.board[move.end_row][move.end_col], move.end_row, move.end_col)
        if move.is_castle_move:
            rook = move.piece_moved[0] + "R"
            if move.end_col - move.start_col == 2:
                rook_from, rook_to = move.end_col + 1, move.end_col - 1
            else:
                rook_from, rook_to = move.end_col - 2, move.end_col + 1
            key ^= _zobrist_square(rook, move.end_row, rook_from)
            key ^= _zobrist_square(rook, move.end_row, rook_to)
        key ^= ZOBRIST_BLACK_TO_MOVE
        key ^= ZOBRIST_CASTLING[old_castling_mask]
        key ^= ZOBRIST_CASTLING[self.current_castling_rights.mask()]
        key ^= _zobrist_en_passant(old_enpassant) ^ _zobrist_en_passant(self.enpassant_possible)
        self.zobrist_key = key
        self.position_keys.append(key)
        self.position_history[key] = self.position_history.get(key, 0) + 1

    def undo_move(self) -> None:
        """Annule le dernier mouvement effectué et restaure les compteurs et l'historique."""
        if not self.move_log:
            return
        move = self.move_log.pop()
        info = self.undo_stack.pop()
        key = self.position_keys.pop()
        if self.position_history[key] == 1:
            del self.position_history[key]
        else:
            self.position_history[key] -= 1
        self.zobrist_key = self.position_keys[-1]
        self.board[move.start_row][move.start_col] = move.piece_moved
        self.board[move.end_row][move.end_col] = move.piece_captured
        self.white_to_move = not self.white_to_move
        if move.piece_moved == "wK":
            self.white_king_location = (move.start_row, move.start_col)
        elif move.piece_moved == "bK":
            self.black_king_location = (move.start_row, move.start_col)
        if move.is_enpassant_move:
            self.board[move.end_row][move.end_col] = "--"
            self.board[move.start_row][move.end_col] = move.piece_captured
        self.enpassant_possible = info.enpassant_possible
        # L'UndoInfo garde sa propre copie : la réutiliser telle quelle est sûr, car
        # elle n'est plus référencée ailleurs une fois dépilée (cf. B24).
        self.current_castling_rights = info.castling_rights
        self.fifty_move_counter = info.fifty_move_counter
        if move.is_castle_move:
            if move.end_col - move.start_col == 2:
                self.board[move.end_row][move.end_col + 1] = self.board[move.end_row][
                    move.end_col - 1
                ]
                self.board[move.end_row][move.end_col - 1] = "--"
            else:
                self.board[move.end_row][move.end_col - 2] = self.board[move.end_row][
                    move.end_col + 1
                ]
                self.board[move.end_row][move.end_col + 1] = "--"
        self.checkmate = False
        self.stalemate = False
        self.termination = None
        self._valid_moves = None

    def update_castle_rights(self, move: "Move") -> None:
        """Met à jour les droits de roque en fonction du mouvement."""
        # Une tour capturée n'affecte les droits de roque que sur sa rangée de départ :
        # sans le test de rangée, une tour issue d'une promotion capturée en a1/h1/a8/h8
        # supprimerait à tort un droit de roque (cf. perft position 4).
        if move.piece_captured == "wR" and move.end_row == 7:
            if move.end_col == 0:
                self.current_castling_rights.wqs = False
            elif move.end_col == 7:
                self.current_castling_rights.wks = False
        elif move.piece_captured == "bR" and move.end_row == 0:
            if move.end_col == 0:
                self.current_castling_rights.bqs = False
            elif move.end_col == 7:
                self.current_castling_rights.bks = False
        if move.piece_moved == "wK":
            self.current_castling_rights.wqs = False
            self.current_castling_rights.wks = False
        elif move.piece_moved == "bK":
            self.current_castling_rights.bqs = False
            self.current_castling_rights.bks = False
        elif move.piece_moved == "wR":
            if move.start_row == 7:
                if move.start_col == 0:
                    self.current_castling_rights.wqs = False
                elif move.start_col == 7:
                    self.current_castling_rights.wks = False
        elif move.piece_moved == "bR":
            if move.start_row == 0:
                if move.start_col == 0:
                    self.current_castling_rights.bqs = False
                elif move.start_col == 7:
                    self.current_castling_rights.bks = False

    def get_valid_moves(self) -> list["Move"]:
        """Retourne la liste des mouvements valides en tenant compte de l’état actuel.
        En plus des vérifications classiques, cette méthode applique les règles
        du pat par insuffisance de matériel, de la règle des 50 coups et de la répétition
        de positions.
        """
        if self._valid_moves is not None:
            return self._valid_moves
        # Les broches et échecs doivent être calculés AVANT la génération des coups,
        # sinon les pièces clouées sont filtrées avec les broches de la position précédente.
        self.in_check, self.pins, self.checks = self.check_for_pins_and_checks()
        moves: list[Move] = self.get_all_possible_moves()
        king_row, king_col = (
            self.white_king_location if self.white_to_move else self.black_king_location
        )
        if self.in_check:
            if len(self.checks) == 1:
                # Filtrer les coups pour ne sauver le roi que dans des cases autorisées
                check = self.checks[0]
                valid_squares: list[tuple[int, int]] = []
                if self.board[check[0]][check[1]][1] == "N":
                    valid_squares = [(check[0], check[1])]
                else:
                    for i in range(1, DIMENSION):
                        valid_square = (king_row + check[2] * i, king_col + check[3] * i)
                        valid_squares.append(valid_square)
                        if valid_square == (check[0], check[1]):
                            break
                check_square = (check[0], check[1])
                moves = [
                    move
                    for move in moves
                    if move.piece_moved[1] == "K"
                    or (move.end_row, move.end_col) in valid_squares
                    # Prise en passant du pion qui donne l'échec : la case d'arrivée
                    # diffère de celle du pion capturé, il faut donc l'autoriser à part.
                    or (move.is_enpassant_move and (move.start_row, move.end_col) == check_square)
                ]
            else:
                # Échec double : seuls les mouvements du roi sont autorisés
                moves = []
                self.get_king_moves(king_row, king_col, moves)
        else:
            # Ajout des mouvements de roque
            if self.white_to_move:
                self.get_castle_moves(
                    self.white_king_location[0], self.white_king_location[1], moves
                )
            else:
                self.get_castle_moves(
                    self.black_king_location[0], self.black_king_location[1], moves
                )
        # Fin de partie. Le mat est examiné en premier : il prime sur les nulles
        # automatiques (FIDE 9.3), y compris s'il est donné au 100e demi-coup.
        # ``stalemate`` reste vrai pour toute nulle (compatibilité IA / sauvegarde).
        self.termination = self._termination(moves)
        if self.termination not in (None, Termination.CHECKMATE):
            moves = []
        self.checkmate = self.termination is Termination.CHECKMATE
        self.stalemate = self.termination not in (None, Termination.CHECKMATE)
        self._valid_moves = moves
        return moves

    def _termination(self, moves: list["Move"]) -> Termination | None:
        if not moves:
            return Termination.CHECKMATE if self.in_check else Termination.STALEMATE
        if self.fifty_move_counter >= 100:
            return Termination.FIFTY_MOVES
        if self.insufficient_material():
            return Termination.INSUFFICIENT_MATERIAL
        if self.repetition_count() >= 3:
            return Termination.THREEFOLD_REPETITION
        return None

    def result(self) -> GameResult:
        """Résultat de la position courante (calcule les coups légaux au besoin)."""
        self.get_valid_moves()
        if self.termination is Termination.CHECKMATE:
            winner = Color.BLACK if self.white_to_move else Color.WHITE
            return GameResult(Termination.CHECKMATE, winner)
        return GameResult(self.termination)

    def king_in_check(self) -> bool:
        """Retourne True si le roi du joueur courant est en échec."""
        if self.white_to_move:
            return self.square_under_attack(
                self.white_king_location[0], self.white_king_location[1]
            )
        else:
            return self.square_under_attack(
                self.black_king_location[0], self.black_king_location[1]
            )

    def square_under_attack(self, r: int, c: int) -> bool:
        """Vérifie si la case (r, c) est attaquée par l'adversaire du joueur au trait.

        Détection directe (rayons glissants + cavaliers + pions + roi) sans passer par
        la génération de coups. Cela prend notamment en compte le contrôle des cases
        vides par les pions, ce que la génération de coups ne fait pas.
        """
        ally: str = "w" if self.white_to_move else "b"
        enemy: str = "b" if self.white_to_move else "w"
        directions = [(-1, 0), (0, -1), (1, 0), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]
        for j, d in enumerate(directions):
            for i in range(1, DIMENSION):
                er = r + d[0] * i
                ec = c + d[1] * i
                if not (is_valid_index(er) and is_valid_index(ec)):
                    break
                piece = self.board[er][ec]
                if piece == "--":
                    continue
                if piece[0] == ally:
                    break
                kind = piece[1]
                if j <= 3:
                    if kind in ("R", "Q"):
                        return True
                else:
                    if kind in ("B", "Q"):
                        return True
                    if i == 1 and kind == "p":
                        if enemy == "w" and d[0] == 1:
                            return True
                        if enemy == "b" and d[0] == -1:
                            return True
                if i == 1 and kind == "K":
                    return True
                break
        knight_moves = [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]
        for m in knight_moves:
            er = r + m[0]
            ec = c + m[1]
            if is_valid_index(er) and is_valid_index(ec):
                piece = self.board[er][ec]
                if piece != "--" and piece[0] == enemy and piece[1] == "N":
                    return True
        return False

    def get_all_possible_moves(self) -> list["Move"]:
        """Retourne tous les mouvements possibles sans filtrer pour les échecs."""
        moves: list[Move] = []
        for r in range(DIMENSION):
            for c in range(DIMENSION):
                if self.board[r][c] == "--":
                    continue
                turn: str = self.board[r][c][0]
                if (turn == Color.WHITE.value and self.white_to_move) or (
                    turn == Color.BLACK.value and not self.white_to_move
                ):
                    piece: str = self.board[r][c][1]
                    self.move_functions[piece](r, c, moves)
        return moves

    def get_pawn_moves(self, row: int, col: int, moves: list["Move"]) -> None:
        """Ajoute les mouvements possibles pour un pion situé en (row, col) à la liste moves."""
        piece_pinned: bool = False
        pin_direction: tuple[int, int] = (0, 0)
        for i in range(len(self.pins) - 1, -1, -1):
            if self.pins[i][0] == row and self.pins[i][1] == col:
                piece_pinned = True
                pin_direction = (self.pins[i][2], self.pins[i][3])
                self.pins.pop(i)
                break
        if self.white_to_move:
            move_amount: int = -1
            start_row: int = 6
            enemy_color: str = "b"
        else:
            move_amount = 1
            start_row = 1
            enemy_color = "w"

        # Avance d'une case (et de deux depuis la rangée de départ)
        if is_valid_index(row + move_amount) and self.board[row + move_amount][col] == "--":
            # Un pion cloué peut se déplacer le long de la ligne de clouage, dans un sens
            # comme dans l'autre (vers son roi ou vers le cloueur) : B46.
            if not piece_pinned or pin_direction in ((move_amount, 0), (-move_amount, 0)):
                self._add_pawn_move(moves, (row, col), (row + move_amount, col))
                if row == start_row and self.board[row + 2 * move_amount][col] == "--":
                    moves.append(Move((row, col), (row + 2 * move_amount, col), self.board))
        # Captures et en passant
        for dc in (-1, 1):
            new_col = col + dc
            if is_valid_index(new_col) and is_valid_index(row + move_amount):
                if not piece_pinned or pin_direction in ((move_amount, dc), (-move_amount, -dc)):
                    target = self.board[row + move_amount][new_col]
                    if target[0] == enemy_color:
                        self._add_pawn_move(moves, (row, col), (row + move_amount, new_col))
                    if (row + move_amount, new_col) == self.enpassant_possible:
                        if not self._enpassant_leaves_king_in_check(
                            (row, col), (row + move_amount, new_col), (row, new_col)
                        ):
                            moves.append(
                                Move(
                                    (row, col),
                                    (row + move_amount, new_col),
                                    self.board,
                                    is_enpassant_move=True,
                                )
                            )

    def _add_pawn_move(
        self, moves: list["Move"], start: tuple[int, int], end: tuple[int, int]
    ) -> None:
        """Ajoute un coup de pion, en développant les 4 sous-promotions sur la dernière rangée."""
        end_row = end[0]
        if (self.white_to_move and end_row == 0) or (not self.white_to_move and end_row == 7):
            for promo in ("Q", "R", "B", "N"):
                moves.append(Move(start, end, self.board, promotion_piece=promo))
        else:
            moves.append(Move(start, end, self.board))

    def _enpassant_leaves_king_in_check(
        self, start: tuple[int, int], end: tuple[int, int], captured_sq: tuple[int, int]
    ) -> bool:
        """Simule la prise en passant : détecte un échec à la découverte sur la rangée du roi."""
        sr, sc = start
        er, ec = end
        cr, cc = captured_sq
        moving = self.board[sr][sc]
        captured = self.board[cr][cc]
        dest = self.board[er][ec]
        self.board[sr][sc] = "--"
        self.board[cr][cc] = "--"
        self.board[er][ec] = moving
        in_check = self.king_in_check()
        self.board[sr][sc] = moving
        self.board[cr][cc] = captured
        self.board[er][ec] = dest
        return in_check

    def get_rook_moves(self, r: int, c: int, moves: list["Move"]) -> None:
        """
        Ajoute à la liste 'moves' tous les mouvements valides de la tour située en (r, c).
        Prend en compte les broches (pins).
        """
        piece_pinned: bool = False
        pin_direction: tuple[int, int] = (0, 0)
        for i in range(len(self.pins) - 1, -1, -1):
            if self.pins[i][0] == r and self.pins[i][1] == c:
                piece_pinned = True
                pin_direction = (self.pins[i][2], self.pins[i][3])
                if self.board[r][c][1] != "Q":
                    self.pins.pop(i)
                break

        directions: list[tuple[int, int]] = [(-1, 0), (0, -1), (1, 0), (0, 1)]
        enemy_color: str = "b" if self.white_to_move else "w"
        for d in directions:
            for i in range(1, DIMENSION):
                end_row: int = r + d[0] * i
                end_col: int = c + d[1] * i
                if is_valid_index(end_row) and is_valid_index(end_col):
                    if not piece_pinned or pin_direction == d or pin_direction == (-d[0], -d[1]):
                        end_piece: str = self.board[end_row][end_col]
                        if end_piece == "--":
                            moves.append(Move((r, c), (end_row, end_col), self.board))
                        else:
                            if end_piece[0] == enemy_color:
                                moves.append(Move((r, c), (end_row, end_col), self.board))
                            break
                else:
                    break

    def get_knight_moves(self, r: int, c: int, moves: list["Move"]) -> None:
        """
        Ajoute à la liste 'moves' tous les mouvements valides du cavalier situé en (r, c).
        Les cavaliers ne bougent pas lorsqu'ils sont brochés.
        """
        piece_pinned: bool = False
        for i in range(len(self.pins) - 1, -1, -1):
            if self.pins[i][0] == r and self.pins[i][1] == c:
                piece_pinned = True
                self.pins.pop(i)
                break

        knight_moves: list[tuple[int, int]] = [
            (-2, -1),
            (-2, 1),
            (-1, -2),
            (-1, 2),
            (1, -2),
            (1, 2),
            (2, -1),
            (2, 1),
        ]
        ally_color: str = "w" if self.white_to_move else "b"
        if not piece_pinned:
            for m in knight_moves:
                end_row: int = r + m[0]
                end_col: int = c + m[1]
                if is_valid_index(end_row) and is_valid_index(end_col):
                    end_piece: str = self.board[end_row][end_col]
                    if end_piece[0] != ally_color:
                        moves.append(Move((r, c), (end_row, end_col), self.board))

    def get_bishop_moves(self, r: int, c: int, moves: list["Move"]) -> None:
        """
        Ajoute à la liste 'moves' tous les mouvements valides du fou situé en (r, c).
        Prend en compte les broches.
        """
        piece_pinned: bool = False
        pin_direction: tuple[int, int] = (0, 0)
        for i in range(len(self.pins) - 1, -1, -1):
            if self.pins[i][0] == r and self.pins[i][1] == c:
                piece_pinned = True
                pin_direction = (self.pins[i][2], self.pins[i][3])
                self.pins.pop(i)
                break

        directions: list[tuple[int, int]] = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
        enemy_color: str = "b" if self.white_to_move else "w"
        for d in directions:
            for i in range(1, DIMENSION):
                end_row: int = r + d[0] * i
                end_col: int = c + d[1] * i
                if is_valid_index(end_row) and is_valid_index(end_col):
                    if not piece_pinned or pin_direction == d or pin_direction == (-d[0], -d[1]):
                        end_piece: str = self.board[end_row][end_col]
                        if end_piece == "--":
                            moves.append(Move((r, c), (end_row, end_col), self.board))
                        else:
                            if end_piece[0] == enemy_color:
                                moves.append(Move((r, c), (end_row, end_col), self.board))
                            break
                else:
                    break

    def get_queen_moves(self, r: int, c: int, moves: list["Move"]) -> None:
        """
        Ajoute à la liste 'moves' tous les mouvements valides de la reine située en (r, c).
        La reine combine les mouvements de la tour et du fou.
        """
        self.get_rook_moves(r, c, moves)
        self.get_bishop_moves(r, c, moves)

    def get_king_moves(self, r: int, c: int, moves: list["Move"]) -> None:
        """
        Ajoute à la liste 'moves' tous les mouvements valides du roi situé en (r, c).
        Vérifie que le déplacement ne met pas le roi en échec.
        """
        row_moves: tuple[int, ...] = (-1, -1, -1, 0, 0, 1, 1, 1)
        col_moves: tuple[int, ...] = (-1, 0, 1, -1, 1, -1, 0, 1)
        ally_color: str = "w" if self.white_to_move else "b"
        for i in range(8):
            end_row: int = r + row_moves[i]
            end_col: int = c + col_moves[i]
            if is_valid_index(end_row) and is_valid_index(end_col):
                end_piece: str = self.board[end_row][end_col]
                if end_piece[0] != ally_color:
                    # Sauvegarde de la position du roi pour le restaurer ensuite
                    original_king_location: tuple[int, int] = (
                        self.white_king_location if self.white_to_move else self.black_king_location
                    )
                    if ally_color == "w":
                        self.white_king_location = (end_row, end_col)
                    else:
                        self.black_king_location = (end_row, end_col)
                    king_in_check, _, _ = self.check_for_pins_and_checks()
                    if not king_in_check:
                        moves.append(Move((r, c), (end_row, end_col), self.board))
                    if ally_color == "w":
                        self.white_king_location = original_king_location
                    else:
                        self.black_king_location = original_king_location

    def get_castle_moves(self, row: int, col: int, moves: list["Move"]) -> None:
        """
        Ajoute à la liste 'moves' les mouvements de roque possibles pour le roi en (row, col).
        Vérifie que le roi n'est pas en échec et que les cases intermédiaires sont libres
        et non attaquées.
        """
        if self.square_under_attack(row, col):
            return
        if (self.white_to_move and self.current_castling_rights.wks) or (
            not self.white_to_move and self.current_castling_rights.bks
        ):
            self.get_kingside_castle_moves(row, col, moves)
        if (self.white_to_move and self.current_castling_rights.wqs) or (
            not self.white_to_move and self.current_castling_rights.bqs
        ):
            self.get_queenside_castle_moves(row, col, moves)

    def get_kingside_castle_moves(self, row: int, col: int, moves: list["Move"]) -> None:
        if col + 2 >= DIMENSION:
            return
        if self.board[row][col + 1] == "--" and self.board[row][col + 2] == "--":
            if not self.square_under_attack(row, col + 1) and not self.square_under_attack(
                row, col + 2
            ):
                moves.append(Move((row, col), (row, col + 2), self.board, is_castle_move=True))

    def get_queenside_castle_moves(self, row: int, col: int, moves: list["Move"]) -> None:
        if col - 3 < 0:
            return
        if (
            self.board[row][col - 1] == "--"
            and self.board[row][col - 2] == "--"
            and self.board[row][col - 3] == "--"
        ):
            if not self.square_under_attack(row, col - 1) and not self.square_under_attack(
                row, col - 2
            ):
                moves.append(Move((row, col), (row, col - 2), self.board, is_castle_move=True))

    def check_for_pins_and_checks(
        self,
    ) -> tuple[bool, list[tuple[int, int, int, int]], list[tuple[int, int, int, int]]]:
        """
        Analyse le plateau pour déterminer si le roi est en échec, et renvoie :
         - king_in_check : booléen indiquant si le roi est en échec,
         - pins : liste des pièces qui sont brochées,
         - checks : liste des coups adverses qui mettent le roi en échec.
        """
        pins = []  # Pièces protégées
        checks = []  # Mouvements qui mettent le roi en échec
        king_in_check = False
        if self.white_to_move:
            enemy_color = "b"
            ally_color = "w"
            king_row, king_col = self.white_king_location
        else:
            enemy_color = "w"
            ally_color = "b"
            king_row, king_col = self.black_king_location
        directions = [(-1, 0), (0, -1), (1, 0), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]
        for j, d in enumerate(directions):
            possible_pin: tuple[int, int, int, int] | None = None
            for i in range(1, DIMENSION):
                end_row = king_row + d[0] * i
                end_col = king_col + d[1] * i
                if is_valid_index(end_row) and is_valid_index(end_col):
                    end_piece = self.board[end_row][end_col]
                    if end_piece[0] == ally_color and end_piece[1] != "K":
                        if possible_pin is None:
                            possible_pin = (end_row, end_col, d[0], d[1])
                        else:
                            break
                    elif end_piece[0] == enemy_color:
                        typ = end_piece[1]
                        if (
                            (0 <= j <= 3 and typ == "R")
                            or (4 <= j <= 7 and typ == "B")
                            or (
                                i == 1
                                and typ == "p"
                                and (
                                    (enemy_color == Color.WHITE.value and 6 <= j <= 7)
                                    or (enemy_color == Color.BLACK.value and 4 <= j <= 5)
                                )
                            )
                            or (typ == "Q")
                            or (i == 1 and typ == "K")
                        ):
                            if possible_pin is None:
                                king_in_check = True
                                checks.append((end_row, end_col, d[0], d[1]))
                                break
                            else:
                                pins.append(possible_pin)
                                break
                        else:
                            break
                else:
                    break
        knight_moves = [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]
        for m in knight_moves:
            end_row = king_row + m[0]
            end_col = king_col + m[1]
            if is_valid_index(end_row) and is_valid_index(end_col):
                end_piece = self.board[end_row][end_col]
                if end_piece[0] == enemy_color and end_piece[1] == "N":
                    king_in_check = True
                    checks.append((end_row, end_col, m[0], m[1]))
        return king_in_check, pins, checks


@dataclass(slots=True)
class UndoInfo:
    """État écrasé par un coup et nécessaire pour l'annuler."""

    castling_rights: "CastleRights"
    enpassant_possible: Square | None
    fifty_move_counter: int


class CastleRights:
    def __init__(self, wks: bool, bks: bool, wqs: bool, bqs: bool) -> None:
        self.wks = wks
        self.bks = bks
        self.wqs = wqs
        self.bqs = bqs

    def mask(self) -> int:
        """Les 4 droits sur 4 bits (index des clés de Zobrist)."""
        return self.wks | (self.wqs << 1) | (self.bks << 2) | (self.bqs << 3)

    def copy(self) -> "CastleRights":
        return CastleRights(self.wks, self.bks, self.wqs, self.bqs)


class Move:
    # Des millions de Move sont créés pendant une recherche : __slots__ réduit la mémoire
    # et accélère l'accès aux attributs.
    __slots__ = (
        "start_row",
        "start_col",
        "end_row",
        "end_col",
        "piece_moved",
        "piece_captured",
        "is_pawn_promotion",
        "promotion_piece",
        "move_id",
        "is_enpassant_move",
        "is_castle_move",
        "is_capture",
    )

    ranks_to_rows: dict[str, int] = {"1": 7, "2": 6, "3": 5, "4": 4, "5": 3, "6": 2, "7": 1, "8": 0}
    rows_to_ranks: dict[int, str] = {v: k for k, v in ranks_to_rows.items()}
    files_to_cols: dict[str, int] = {"a": 0, "b": 1, "c": 2, "d": 3, "e": 4, "f": 5, "g": 6, "h": 7}
    cols_to_files: dict[int, str] = {v: k for k, v in files_to_cols.items()}

    def __init__(
        self,
        start_sq: Square,
        end_sq: Square,
        board: list[list[str]],
        is_enpassant_move: bool = False,
        is_castle_move: bool = False,
        promotion_piece: str | None = None,
    ) -> None:
        self.start_row, self.start_col = start_sq
        self.end_row, self.end_col = end_sq
        self.piece_moved: str = board[self.start_row][self.start_col]
        self.piece_captured: str = board[self.end_row][self.end_col]
        self.is_pawn_promotion: bool = (self.piece_moved == "wp" and self.end_row == 0) or (
            self.piece_moved == "bp" and self.end_row == 7
        )
        # Pièce de promotion : par défaut la dame. None hors promotion.
        if self.is_pawn_promotion:
            self.promotion_piece: str | None = (
                promotion_piece if promotion_piece in ("Q", "R", "B", "N") else "Q"
            )
        else:
            self.promotion_piece = None
        promo_code: int = {"Q": 1, "R": 2, "B": 3, "N": 4}.get(self.promotion_piece or "", 0)
        self.move_id: int = (
            promo_code * 10000
            + self.start_row * 1000
            + self.start_col * 100
            + self.end_row * 10
            + self.end_col
        )
        self.is_enpassant_move: bool = is_enpassant_move
        if self.is_enpassant_move:
            self.piece_captured = "wp" if self.piece_moved == "bp" else "bp"
        self.is_castle_move: bool = is_castle_move
        self.is_capture: bool = self.piece_captured != "--"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Move) and self.move_id == other.move_id

    def __hash__(self) -> int:
        return self.move_id

    def get_rank_file(self, r: int, c: int) -> str:
        return self.cols_to_files[c] + self.rows_to_ranks[r]

    def get_chess_notation(self) -> str:
        if self.is_pawn_promotion:
            return (
                self.get_rank_file(self.end_row, self.end_col) + "=" + (self.promotion_piece or "Q")
            )
        if self.is_castle_move:
            return "0-0" if self.end_col == 6 else "0-0-0"
        if self.is_enpassant_move:
            return (
                self.get_rank_file(self.start_row, self.start_col)[0]
                + "x"
                + self.get_rank_file(self.end_row, self.end_col)
                + " e.p."
            )
        if self.piece_captured != "--":
            if self.piece_moved[1] == "p":
                return (
                    self.get_rank_file(self.start_row, self.start_col)[0]
                    + "x"
                    + self.get_rank_file(self.end_row, self.end_col)
                )
            else:
                return self.piece_moved[1] + "x" + self.get_rank_file(self.end_row, self.end_col)
        else:
            if self.piece_moved[1] == "p":
                return self.get_rank_file(self.end_row, self.end_col)
            else:
                return self.piece_moved[1] + self.get_rank_file(self.end_row, self.end_col)
        return "error"

    def __str__(self) -> str:
        if self.is_castle_move:
            return "0-0" if self.end_col == 6 else "0-0-0"
        end_square: str = self.get_rank_file(self.end_row, self.end_col)
        if self.piece_moved[1] == "p":
            if self.is_capture:
                return self.cols_to_files[self.start_col] + "x" + end_square
            else:
                return (
                    end_square + "=" + (self.promotion_piece or "Q")
                    if self.is_pawn_promotion
                    else end_square
                )
        move_string: str = self.piece_moved[1]
        if self.is_capture:
            move_string += "x"
        return move_string + end_square
