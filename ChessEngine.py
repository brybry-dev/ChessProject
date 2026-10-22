"""
Module ChessEngine
-------------------
Gestion du plateau, des coups, de l’évaluation et du cache des mouvements.
"""

import copy
from collections.abc import Callable
from enum import Enum
from typing import Any

import numpy as np

# Constantes
DIMENSION: int = 8
CHECKMATE: int = 1000
STALEMATE: int = 0


class Color(Enum):
    WHITE = "w"
    BLACK = "b"


# Évaluations de base
piece_score: dict[str, int] = {"K": 0, "Q": 9, "R": 5, "B": 3, "N": 3, "p": 1}

knight_scores = np.array(
    [
        [0.0, 0.1, 0.2, 0.2, 0.2, 0.2, 0.1, 0.0],
        [0.1, 0.3, 0.5, 0.5, 0.5, 0.5, 0.3, 0.1],
        [0.2, 0.5, 0.6, 0.65, 0.65, 0.6, 0.5, 0.2],
        [0.2, 0.55, 0.65, 0.7, 0.7, 0.65, 0.55, 0.2],
        [0.2, 0.5, 0.65, 0.7, 0.7, 0.65, 0.5, 0.2],
        [0.2, 0.55, 0.6, 0.65, 0.65, 0.6, 0.55, 0.2],
        [0.1, 0.3, 0.5, 0.55, 0.55, 0.5, 0.3, 0.1],
        [0.0, 0.1, 0.2, 0.2, 0.2, 0.2, 0.1, 0.0],
    ]
)

bishop_scores = np.array(
    [
        [0.0, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.0],
        [0.2, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.2],
        [0.2, 0.4, 0.5, 0.6, 0.6, 0.5, 0.4, 0.2],
        [0.2, 0.5, 0.5, 0.6, 0.6, 0.5, 0.5, 0.2],
        [0.2, 0.4, 0.6, 0.6, 0.6, 0.6, 0.4, 0.2],
        [0.2, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.2],
        [0.2, 0.5, 0.4, 0.4, 0.4, 0.4, 0.5, 0.2],
        [0.0, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.0],
    ]
)

rook_scores = np.array(
    [
        [0.25] * DIMENSION,
        [0.5, 0.75, 0.75, 0.75, 0.75, 0.75, 0.75, 0.5],
        [0.0, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.0],
        [0.0, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.0],
        [0.0, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.0],
        [0.0, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.0],
        [0.0, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.0],
        [0.25, 0.25, 0.25, 0.5, 0.5, 0.25, 0.25, 0.25],
    ]
)

queen_scores = np.array(
    [
        [0.0, 0.2, 0.2, 0.3, 0.3, 0.2, 0.2, 0.0],
        [0.2, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.2],
        [0.2, 0.4, 0.5, 0.5, 0.5, 0.5, 0.4, 0.2],
        [0.3, 0.4, 0.5, 0.5, 0.5, 0.5, 0.4, 0.3],
        [0.4, 0.4, 0.5, 0.5, 0.5, 0.5, 0.4, 0.3],
        [0.2, 0.5, 0.5, 0.5, 0.5, 0.5, 0.4, 0.2],
        [0.2, 0.4, 0.5, 0.4, 0.4, 0.4, 0.4, 0.2],
        [0.0, 0.2, 0.2, 0.3, 0.3, 0.2, 0.2, 0.0],
    ]
)

pawn_scores = np.array(
    [
        [0.8] * DIMENSION,
        [0.7] * DIMENSION,
        [0.3, 0.3, 0.4, 0.5, 0.5, 0.4, 0.3, 0.3],
        [0.25, 0.25, 0.3, 0.45, 0.45, 0.3, 0.25, 0.25],
        [0.2] * DIMENSION,
        [0.25, 0.15, 0.1, 0.2, 0.2, 0.1, 0.15, 0.25],
        [0.25, 0.3, 0.3, 0.0, 0.0, 0.3, 0.3, 0.25],
        [0.2] * DIMENSION,
    ]
)

piece_position_scores = {
    "wN": knight_scores,
    "bN": knight_scores[::-1],
    "wB": bishop_scores,
    "bB": bishop_scores[::-1],
    "wQ": queen_scores,
    "bQ": queen_scores[::-1],
    "wR": rook_scores,
    "bR": rook_scores[::-1],
    "wp": pawn_scores,
    "bp": pawn_scores[::-1],
}


def is_valid_index(index: int) -> bool:
    """Vérifier si un index est dans la plage du plateau."""
    return 0 <= index < DIMENSION


class GameState:
    """
    Classe représentant l'état du jeu.
    """

    def __init__(self, flip_board: bool = False) -> None:
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

        # Si flip_board est True, échange la position du roi et de la reine pour chaque camp
        if flip_board:
            # Pour les blancs (ligne 7)
            self.board[7][3], self.board[7][4] = self.board[7][4], self.board[7][3]
            # Pour les noirs (ligne 0)
            self.board[0][3], self.board[0][4] = self.board[0][4], self.board[0][3]

        self.move_functions = {
            "p": self.getPawnMoves,
            "R": self.getRookMoves,
            "N": self.getKnightMoves,
            "B": self.getBishopMoves,
            "Q": self.getQueenMoves,
            "K": self.getKingMoves,
        }
        self.white_to_move: bool = True
        self.move_log: list[Move] = []
        self.white_king_location: tuple[int, int] = (7, 4)
        self.black_king_location: tuple[int, int] = (0, 4)
        self.checkmate: bool = False
        self.stalemate: bool = False
        self.in_check: bool = False
        self.pins: list[tuple[int, int, int, int]] = []
        self.checks: list[tuple[int, int, int, int]] = []
        # Case d'en passant, ou None si aucune prise en passant n'est possible.
        self.enpassant_possible: tuple[int, int] | None = None
        self.enpassant_possible_log: list[tuple[int, int] | None] = [self.enpassant_possible]
        self.current_castling_rights: CastleRights = CastleRights(True, True, True, True)
        self.castle_rights_log: list[CastleRights] = [
            CastleRights(
                self.current_castling_rights.wks,
                self.current_castling_rights.bks,
                self.current_castling_rights.wqs,
                self.current_castling_rights.bqs,
            )
        ]
        self._valid_moves: list[Move] | None = None

        # Pour la règle des 50 coups
        self.fifty_move_counter: int = 0
        self.fifty_move_counter_log: list[int] = [0]
        # Pour la répétition de positions (utilise une chaîne de hash)
        self.position_history: dict[str, int] = {}
        self.position_history_log: list[dict[str, int]] = [copy.deepcopy(self.position_history)]
        # On met à jour l'historique avec la position initiale
        self._update_position_history()

    def _update_position_history(self) -> None:
        """Met à jour le dictionnaire de répétition de positions."""
        pos_hash: str = self.get_board_hash_str()
        self.position_history[pos_hash] = self.position_history.get(pos_hash, 0) + 1

    def get_board_hash_str(self) -> str:
        """Retourne une chaîne représentant l'état complet de la position.

        Inclut le plateau, le trait, les droits de roque et la case d'en passant :
        c'est nécessaire pour que la triple répétition (règle FIDE) et la table de
        transposition ne confondent pas deux positions réellement différentes.
        """
        board_tuple = tuple(tuple(row) for row in self.board)
        cr = self.current_castling_rights
        castle = (cr.wks, cr.wqs, cr.bks, cr.bqs)
        # `or ()` : la clé reste identique à l'ancienne représentation (absence == ()).
        ep = self.enpassant_possible or ()
        return str(hash((board_tuple, self.white_to_move, castle, ep)))

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

    def makeMove(
        self,
        move: "Move",
        promotion_callback: Callable[[], str] | None = None,
        validate: bool = True,
    ) -> None:
        """
        Applique un mouvement sur le plateau.
        Vérifie que le mouvement est valide avant application.
        Met à jour le compteur des 50 coups et l'historique de position.
        """
        if validate and move not in self.getValidMoves():
            raise ValueError("Mouvement non valide.")
            # Sauvegarde des compteurs pour pouvoir annuler
        self.fifty_move_counter_log.append(self.fifty_move_counter)
        self.position_history_log.append(copy.deepcopy(self.position_history))
        self.board[move.start_row][move.start_col] = "--"
        self.board[move.end_row][move.end_col] = move.piece_moved
        self.move_log.append(move)
        self.white_to_move = not self.white_to_move
        if move.piece_moved == "wK":
            self.white_king_location = (move.end_row, move.end_col)
        elif move.piece_moved == "bK":
            self.black_king_location = (move.end_row, move.end_col)
        # Si le mouvement est une promotion, on demande le choix
        if move.is_pawn_promotion:
            promoted_piece = (
                promotion_callback() if promotion_callback else (move.promotion_piece or "Q")
            )
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
        self.enpassant_possible_log.append(self.enpassant_possible)
        self.updateCastleRights(move)
        self.castle_rights_log.append(
            CastleRights(
                self.current_castling_rights.wks,
                self.current_castling_rights.bks,
                self.current_castling_rights.wqs,
                self.current_castling_rights.bqs,
            )
        )
        self._valid_moves = None
        # Met à jour l'historique des positions
        self._update_position_history()

    def undoMove(self) -> None:
        """Annule le dernier mouvement effectué et restaure les compteurs et l'historique."""
        if not self.move_log:
            return
        move = self.move_log.pop()
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
        self.enpassant_possible_log.pop()
        self.enpassant_possible = self.enpassant_possible_log[-1]
        self.castle_rights_log.pop()
        # Copie défensive : sinon current_castling_rights aliaserait une entrée du log,
        # que le prochain updateCastleRights corromprait en la modifiant en place.
        last_rights = self.castle_rights_log[-1]
        self.current_castling_rights = CastleRights(
            last_rights.wks, last_rights.bks, last_rights.wqs, last_rights.bqs
        )
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
        self._valid_moves = None
        # Restaure les compteurs
        self.fifty_move_counter = self.fifty_move_counter_log.pop()
        self.position_history = self.position_history_log.pop()

    def updateCastleRights(self, move: "Move") -> None:
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

    def getValidMoves(self) -> list["Move"]:
        """Retourne la liste des mouvements valides en tenant compte de l’état actuel.
        En plus des vérifications classiques, cette méthode applique les règles
        du pat par insuffisance de matériel, de la règle des 50 coups et de la répétition
        de positions.
        """
        if self._valid_moves is not None:
            return self._valid_moves
        # Les broches et échecs doivent être calculés AVANT la génération des coups,
        # sinon les pièces clouées sont filtrées avec les broches de la position précédente.
        self.in_check, self.pins, self.checks = self.checkForPinsAndChecks()
        moves: list[Move] = self.getAllPossibleMoves()
        kingRow, kingCol = (
            self.white_king_location if self.white_to_move else self.black_king_location
        )
        if self.in_check:
            if len(self.checks) == 1:
                # Filtrer les coups pour ne sauver le roi que dans des cases autorisées
                check = self.checks[0]
                validSquares: list[tuple[int, int]] = []
                if self.board[check[0]][check[1]][1] == "N":
                    validSquares = [(check[0], check[1])]
                else:
                    for i in range(1, DIMENSION):
                        validSquare = (kingRow + check[2] * i, kingCol + check[3] * i)
                        validSquares.append(validSquare)
                        if validSquare == (check[0], check[1]):
                            break
                check_square = (check[0], check[1])
                moves = [
                    move
                    for move in moves
                    if move.piece_moved[1] == "K"
                    or (move.end_row, move.end_col) in validSquares
                    # Prise en passant du pion qui donne l'échec : la case d'arrivée
                    # diffère de celle du pion capturé, il faut donc l'autoriser à part.
                    or (move.is_enpassant_move and (move.start_row, move.end_col) == check_square)
                ]
            else:
                # Échec double : seuls les mouvements du roi sont autorisés
                moves = []
                self.getKingMoves(kingRow, kingCol, moves)
        else:
            # Ajout des mouvements de roque
            if self.white_to_move:
                self.getCastleMoves(self.white_king_location[0], self.white_king_location[1], moves)
            else:
                self.getCastleMoves(self.black_king_location[0], self.black_king_location[1], moves)
        # Nulles automatiques : 50 coups, matériel insuffisant, triple répétition
        current_hash: str = self.get_board_hash_str()
        repetition = self.position_history.get(current_hash, 0)
        if self.fifty_move_counter >= 100 or self.insufficient_material() or repetition >= 3:
            moves = []
            self.stalemate = True
            self.checkmate = False
        elif not moves:
            # Aucun coup légal : échec et mat si le roi est en échec, pat sinon
            self.checkmate = self.in_check
            self.stalemate = not self.in_check
        else:
            self.checkmate = False
            self.stalemate = False
        self._valid_moves = moves
        return moves

    def inCheck(self) -> bool:
        """Retourne True si le roi du joueur courant est en échec."""
        if self.white_to_move:
            return self.squareUnderAttack(self.white_king_location[0], self.white_king_location[1])
        else:
            return self.squareUnderAttack(self.black_king_location[0], self.black_king_location[1])

    def squareUnderAttack(self, r: int, c: int) -> bool:
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

    def getAllPossibleMoves(self) -> list["Move"]:
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

    def getPawnMoves(self, row: int, col: int, moves: list["Move"]) -> None:
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
            if not piece_pinned or pin_direction == (move_amount, 0):
                self._add_pawn_move(moves, (row, col), (row + move_amount, col))
                if row == start_row and self.board[row + 2 * move_amount][col] == "--":
                    moves.append(Move((row, col), (row + 2 * move_amount, col), self.board))
        # Captures et en passant
        for dc in (-1, 1):
            new_col = col + dc
            if is_valid_index(new_col) and is_valid_index(row + move_amount):
                if not piece_pinned or pin_direction == (move_amount, dc):
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
        in_check = self.inCheck()
        self.board[sr][sc] = moving
        self.board[cr][cc] = captured
        self.board[er][ec] = dest
        return in_check

    def getRookMoves(self, r: int, c: int, moves: list["Move"]) -> None:
        """
        Ajoute à la liste 'moves' tous les mouvements valides de la tour située en (r, c).
        Prend en compte les broches (pins).
        """
        piecePinned: bool = False
        pinDirection: tuple[int, int] = (0, 0)
        for i in range(len(self.pins) - 1, -1, -1):
            if self.pins[i][0] == r and self.pins[i][1] == c:
                piecePinned = True
                pinDirection = (self.pins[i][2], self.pins[i][3])
                if self.board[r][c][1] != "Q":
                    self.pins.pop(i)
                break

        directions: list[tuple[int, int]] = [(-1, 0), (0, -1), (1, 0), (0, 1)]
        enemyColor: str = "b" if self.white_to_move else "w"
        for d in directions:
            for i in range(1, DIMENSION):
                endRow: int = r + d[0] * i
                endCol: int = c + d[1] * i
                if is_valid_index(endRow) and is_valid_index(endCol):
                    if not piecePinned or pinDirection == d or pinDirection == (-d[0], -d[1]):
                        endPiece: str = self.board[endRow][endCol]
                        if endPiece == "--":
                            moves.append(Move((r, c), (endRow, endCol), self.board))
                        else:
                            if endPiece[0] == enemyColor:
                                moves.append(Move((r, c), (endRow, endCol), self.board))
                            break
                else:
                    break

    def getKnightMoves(self, r: int, c: int, moves: list["Move"]) -> None:
        """
        Ajoute à la liste 'moves' tous les mouvements valides du cavalier situé en (r, c).
        Les cavaliers ne bougent pas lorsqu'ils sont brochés.
        """
        piecePinned: bool = False
        for i in range(len(self.pins) - 1, -1, -1):
            if self.pins[i][0] == r and self.pins[i][1] == c:
                piecePinned = True
                self.pins.pop(i)
                break

        knightMoves: list[tuple[int, int]] = [
            (-2, -1),
            (-2, 1),
            (-1, -2),
            (-1, 2),
            (1, -2),
            (1, 2),
            (2, -1),
            (2, 1),
        ]
        allyColor: str = "w" if self.white_to_move else "b"
        if not piecePinned:
            for m in knightMoves:
                endRow: int = r + m[0]
                endCol: int = c + m[1]
                if is_valid_index(endRow) and is_valid_index(endCol):
                    endPiece: str = self.board[endRow][endCol]
                    if endPiece[0] != allyColor:
                        moves.append(Move((r, c), (endRow, endCol), self.board))

    def getBishopMoves(self, r: int, c: int, moves: list["Move"]) -> None:
        """
        Ajoute à la liste 'moves' tous les mouvements valides du fou situé en (r, c).
        Prend en compte les broches.
        """
        piecePinned: bool = False
        pinDirection: tuple[int, int] = (0, 0)
        for i in range(len(self.pins) - 1, -1, -1):
            if self.pins[i][0] == r and self.pins[i][1] == c:
                piecePinned = True
                pinDirection = (self.pins[i][2], self.pins[i][3])
                self.pins.pop(i)
                break

        directions: list[tuple[int, int]] = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
        enemyColor: str = "b" if self.white_to_move else "w"
        for d in directions:
            for i in range(1, DIMENSION):
                endRow: int = r + d[0] * i
                endCol: int = c + d[1] * i
                if is_valid_index(endRow) and is_valid_index(endCol):
                    if not piecePinned or pinDirection == d or pinDirection == (-d[0], -d[1]):
                        endPiece: str = self.board[endRow][endCol]
                        if endPiece == "--":
                            moves.append(Move((r, c), (endRow, endCol), self.board))
                        else:
                            if endPiece[0] == enemyColor:
                                moves.append(Move((r, c), (endRow, endCol), self.board))
                            break
                else:
                    break

    def getQueenMoves(self, r: int, c: int, moves: list["Move"]) -> None:
        """
        Ajoute à la liste 'moves' tous les mouvements valides de la reine située en (r, c).
        La reine combine les mouvements de la tour et du fou.
        """
        self.getRookMoves(r, c, moves)
        self.getBishopMoves(r, c, moves)

    def getKingMoves(self, r: int, c: int, moves: list["Move"]) -> None:
        """
        Ajoute à la liste 'moves' tous les mouvements valides du roi situé en (r, c).
        Vérifie que le déplacement ne met pas le roi en échec.
        """
        rowMoves: tuple[int, ...] = (-1, -1, -1, 0, 0, 1, 1, 1)
        colMoves: tuple[int, ...] = (-1, 0, 1, -1, 1, -1, 0, 1)
        allyColor: str = "w" if self.white_to_move else "b"
        for i in range(8):
            endRow: int = r + rowMoves[i]
            endCol: int = c + colMoves[i]
            if is_valid_index(endRow) and is_valid_index(endCol):
                endPiece: str = self.board[endRow][endCol]
                if endPiece[0] != allyColor:
                    # Sauvegarde de la position du roi pour le restaurer ensuite
                    original_king_location: tuple[int, int] = (
                        self.white_king_location if self.white_to_move else self.black_king_location
                    )
                    if allyColor == "w":
                        self.white_king_location = (endRow, endCol)
                    else:
                        self.black_king_location = (endRow, endCol)
                    inCheck, _, _ = self.checkForPinsAndChecks()
                    if not inCheck:
                        moves.append(Move((r, c), (endRow, endCol), self.board))
                    if allyColor == "w":
                        self.white_king_location = original_king_location
                    else:
                        self.black_king_location = original_king_location

    def getCastleMoves(self, row: int, col: int, moves: list["Move"]) -> None:
        """
        Ajoute à la liste 'moves' les mouvements de roque possibles pour le roi en (row, col).
        Vérifie que le roi n'est pas en échec et que les cases intermédiaires sont libres
        et non attaquées.
        """
        if self.squareUnderAttack(row, col):
            return
        if (self.white_to_move and self.current_castling_rights.wks) or (
            not self.white_to_move and self.current_castling_rights.bks
        ):
            self.getKingsideCastleMoves(row, col, moves)
        if (self.white_to_move and self.current_castling_rights.wqs) or (
            not self.white_to_move and self.current_castling_rights.bqs
        ):
            self.getQueensideCastleMoves(row, col, moves)

    def getKingsideCastleMoves(self, row: int, col: int, moves: list["Move"]) -> None:
        if col + 2 >= DIMENSION:
            return
        if self.board[row][col + 1] == "--" and self.board[row][col + 2] == "--":
            if not self.squareUnderAttack(row, col + 1) and not self.squareUnderAttack(
                row, col + 2
            ):
                moves.append(Move((row, col), (row, col + 2), self.board, is_castle_move=True))

    def getQueensideCastleMoves(self, row: int, col: int, moves: list["Move"]) -> None:
        if col - 3 < 0:
            return
        if (
            self.board[row][col - 1] == "--"
            and self.board[row][col - 2] == "--"
            and self.board[row][col - 3] == "--"
        ):
            if not self.squareUnderAttack(row, col - 1) and not self.squareUnderAttack(
                row, col - 2
            ):
                moves.append(Move((row, col), (row, col - 2), self.board, is_castle_move=True))

    def checkForPinsAndChecks(
        self,
    ) -> tuple[bool, list[tuple[int, int, int, int]], list[tuple[int, int, int, int]]]:
        """
        Analyse le plateau pour déterminer si le roi est en échec, et renvoie :
         - inCheck : booléen indiquant si le roi est en échec,
         - pins : liste des pièces qui sont brochées,
         - checks : liste des coups adverses qui mettent le roi en échec.
        """
        pins = []  # Pièces protégées
        checks = []  # Mouvements qui mettent le roi en échec
        inCheck = False
        if self.white_to_move:
            enemyColor = "b"
            allyColor = "w"
            kingRow, kingCol = self.white_king_location
        else:
            enemyColor = "w"
            allyColor = "b"
            kingRow, kingCol = self.black_king_location
        directions = [(-1, 0), (0, -1), (1, 0), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]
        for j, d in enumerate(directions):
            possiblePin: tuple[int, int, int, int] | None = None
            for i in range(1, DIMENSION):
                endRow = kingRow + d[0] * i
                endCol = kingCol + d[1] * i
                if is_valid_index(endRow) and is_valid_index(endCol):
                    endPiece = self.board[endRow][endCol]
                    if endPiece[0] == allyColor and endPiece[1] != "K":
                        if possiblePin is None:
                            possiblePin = (endRow, endCol, d[0], d[1])
                        else:
                            break
                    elif endPiece[0] == enemyColor:
                        typ = endPiece[1]
                        if (
                            (0 <= j <= 3 and typ == "R")
                            or (4 <= j <= 7 and typ == "B")
                            or (
                                i == 1
                                and typ == "p"
                                and (
                                    (enemyColor == Color.WHITE.value and 6 <= j <= 7)
                                    or (enemyColor == Color.BLACK.value and 4 <= j <= 5)
                                )
                            )
                            or (typ == "Q")
                            or (i == 1 and typ == "K")
                        ):
                            if possiblePin is None:
                                inCheck = True
                                checks.append((endRow, endCol, d[0], d[1]))
                                break
                            else:
                                pins.append(possiblePin)
                                break
                        else:
                            break
                else:
                    break
        knightMoves = [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]
        for m in knightMoves:
            endRow = kingRow + m[0]
            endCol = kingCol + m[1]
            if is_valid_index(endRow) and is_valid_index(endCol):
                endPiece = self.board[endRow][endCol]
                if endPiece[0] == enemyColor and endPiece[1] == "N":
                    inCheck = True
                    checks.append((endRow, endCol, m[0], m[1]))
        return inCheck, pins, checks


class CastleRights:
    def __init__(self, wks: bool, bks: bool, wqs: bool, bqs: bool) -> None:
        self.wks = wks
        self.bks = bks
        self.wqs = wqs
        self.bqs = bqs


class Move:
    ranks_to_rows: dict[str, int] = {"1": 7, "2": 6, "3": 5, "4": 4, "5": 3, "6": 2, "7": 1, "8": 0}
    rows_to_ranks: dict[int, str] = {v: k for k, v in ranks_to_rows.items()}
    files_to_cols: dict[str, int] = {"a": 0, "b": 1, "c": 2, "d": 3, "e": 4, "f": 5, "g": 6, "h": 7}
    cols_to_files: dict[int, str] = {v: k for k, v in files_to_cols.items()}

    def __init__(
        self,
        startSq: tuple[int, int],
        endSq: tuple[int, int],
        board: list[list[str]],
        is_enpassant_move: bool = False,
        is_castle_move: bool = False,
        promotion_piece: str | None = None,
    ) -> None:
        self.start_row, self.start_col = startSq
        self.end_row, self.end_col = endSq
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
        self.moveID: int = (
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
        return isinstance(other, Move) and self.moveID == other.moveID

    def __hash__(self) -> int:
        return self.moveID

    def getRankFile(self, r: int, c: int) -> str:
        return self.cols_to_files[c] + self.rows_to_ranks[r]

    def getChessNotation(self) -> str:
        if self.is_pawn_promotion:
            return (
                self.getRankFile(self.end_row, self.end_col) + "=" + (self.promotion_piece or "Q")
            )
        if self.is_castle_move:
            return "0-0" if self.end_col == 6 else "0-0-0"
        if self.is_enpassant_move:
            return (
                self.getRankFile(self.start_row, self.start_col)[0]
                + "x"
                + self.getRankFile(self.end_row, self.end_col)
                + " e.p."
            )
        if self.piece_captured != "--":
            if self.piece_moved[1] == "p":
                return (
                    self.getRankFile(self.start_row, self.start_col)[0]
                    + "x"
                    + self.getRankFile(self.end_row, self.end_col)
                )
            else:
                return self.piece_moved[1] + "x" + self.getRankFile(self.end_row, self.end_col)
        else:
            if self.piece_moved[1] == "p":
                return self.getRankFile(self.end_row, self.end_col)
            else:
                return self.piece_moved[1] + self.getRankFile(self.end_row, self.end_col)
        return "error"

    def __str__(self) -> str:
        if self.is_castle_move:
            return "0-0" if self.end_col == 6 else "0-0-0"
        end_square: str = self.getRankFile(self.end_row, self.end_col)
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
