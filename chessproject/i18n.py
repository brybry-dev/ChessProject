"""
Langue de l'interface (J11.3)
-----------------------------
Le français est la langue source : chaque texte affiché est écrit en français dans le
code et passe par :func:`tr`, qui renvoie sa traduction anglaise quand l'anglais est
choisi. Les textes à compléter s'écrivent avec des champs nommés :
``tr("Partie chargée ({n} demi-coups)", n=12)``.

La langue est une préférence (``Settings.language``) ; elle change à chaud, chaque
texte étant traduit au moment où il est dessiné. Les journaux, les messages d'erreur
internes et la ligne de commande restent en français.

Les noms d'ouvertures, trop nombreux pour ce catalogue, ont leur propre table
(``assets/openings_en.tsv``).
"""

import locale
import logging
import os
from functools import lru_cache

from chessproject import paths

logger = logging.getLogger(__name__)

LANGUAGES: tuple[str, ...] = ("fr", "en")
# Nom de chaque langue dans cette langue (sélecteur de l'interface, jamais traduit).
LANGUAGE_NAMES: dict[str, str] = {"fr": "Français", "en": "English"}

_language = "fr"


def set_language(code: str) -> None:
    global _language
    _language = code if code in LANGUAGES else "fr"


def language() -> str:
    return _language


def system_language() -> str:
    """Langue proposée au premier lancement : le français si le système est en
    français, l'anglais sinon."""
    for name in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = os.environ.get(name)
        if value:
            return "fr" if value.lower().startswith("fr") else "en"
    try:
        code = locale.getlocale()[0] or ""
    except ValueError:
        code = ""
    return "fr" if code.lower().startswith("fr") else "en"


def tr(text: str, /, **values: object) -> str:
    """Traduction de ``text`` (français) dans la langue courante, champs remplis.
    Un texte absent du catalogue est rendu tel quel (touches, notation, noms propres).
    Un même mot français aux sens différents porte un contexte après « | »
    (``"Annuler|coup"`` : « Undo », ``"Annuler"`` : « Cancel »), retiré en français."""
    if _language == "en":
        text = EN.get(text, text)
    text = text.partition("|")[0]
    return text.format(**values) if values else text


def plural(n: int, singular: str, plural_form: str, /) -> str:
    """``tr`` de la forme qui convient à ``n`` (le champ ``{n}`` est rempli). En
    français le singulier va jusqu'à 1, en anglais seul 1 est au singulier."""
    one = n == 1 if _language == "en" else abs(n) <= 1
    return tr(singular if one else plural_form, n=n)


def decimal(value: float, digits: int = 1) -> str:
    """Nombre décimal à la mode de la langue : « 0,4 » en français, « 0.4 » en anglais."""
    text = f"{value:.{digits}f}" if digits >= 0 else f"{value:g}"
    return text if _language == "en" else text.replace(".", ",")


@lru_cache(maxsize=1)
def _opening_names() -> dict[str, str]:
    names: dict[str, str] = {}
    path = paths.ASSETS_DIR / "openings_en.tsv"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as ex:
        logger.warning("Noms anglais des ouvertures indisponibles : %s", ex)
        return names
    for line in lines:
        if line.strip() and not line.startswith("#"):
            french, _, english = line.partition("\t")
            names[french.strip()] = english.strip()
    return names


def opening_name(name: str) -> str:
    """Nom d'une ouverture du livre (en français dans le livre) dans la langue courante."""
    if _language == "en":
        return _opening_names().get(name, name)
    return name


# --------------------------------------------------------------------------
# Catalogue anglais : texte français -> texte anglais
# --------------------------------------------------------------------------
EN: dict[str, str] = {
    # Écran « Nouvelle partie »
    "Nouvelle partie": "New game",
    "Tous les réglages sur un seul écran, modifiables avant de commencer.": (
        "Every setting on one screen, all adjustable before you start."
    ),
    "MODE": "MODE",
    "VOUS JOUEZ": "YOU PLAY",
    "NIVEAU DE L'IA": "AI LEVEL",
    "CADENCE": "TIME CONTROL",
    "Joueur vs IA": "Player vs AI",
    "Joueur vs Joueur": "Player vs Player",
    "IA vs IA": "AI vs AI",
    "Blancs": "White",
    "Noirs": "Black",
    "Au hasard": "Random",
    "pour débuter": "for starters",
    "imprécis": "inaccurate",
    "solide": "solid",
    "précis": "accurate",
    "pleine force": "full strength",
    "≈ {elo} Elo": "≈ {elo} Elo",
    "{seconds} s": "{seconds} s",
    "Deux joueurs se partagent l'écran : l'échiquier reste côté blancs.": (
        "Two players share the screen: the board stays on White's side."
    ),
    "Commencer": "Start",
    "Importer un PGN": "Import a PGN",
    "Charger une partie": "Load a game",
    "Retour à la partie": "Back to the game",
    "sans pendule": "no clock",
    "cadence {control}": "{control} time control",
    "Deux joueurs sur le même écran, {cadence}.": "Two players on the same screen, {cadence}.",
    "L'IA {level} joue contre elle-même, {cadence}.": "The {level} AI plays itself, {cadence}.",
    "Vous jouez les blancs contre l'IA {level}, {cadence}.": (
        "You play White against the {level} AI, {cadence}."
    ),
    "Vous jouez les noirs contre l'IA {level}, {cadence}.": (
        "You play Black against the {level} AI, {cadence}."
    ),
    "Vous jouez une couleur tirée au sort contre l'IA {level}, {cadence}.": (
        "You play a random colour against the {level} AI, {cadence}."
    ),
    # Niveaux (identifiants des sauvegardes et des préférences, traduits à l'affichage)
    "Débutant": "Beginner",
    "Facile": "Easy",
    "Moyen": "Medium",
    "Difficile": "Hard",
    "Expert": "Expert",
    # Cadences
    "Sans limite": "Unlimited",
    "Rapide": "Rapid",
    "Bullet": "Bullet",
    "Blitz": "Blitz",
    # En-tête et panneau
    "Sauvegarder (S)": "Save (S)",
    "Charger (L)": "Load (L)",
    "Exporter en PGN (E)": "Export to PGN (E)",
    "Importer un PGN (I)": "Import a PGN (I)",
    "Indice (B)": "Hint (B)",
    "Retourner l'échiquier (F)": "Flip the board (F)",
    "Apparence (C)": "Appearance (C)",
    "Raccourcis (H)": "Shortcuts (H)",
    "Début (Origine)": "Start (Home)",
    "Coup précédent (←)": "Previous move (←)",
    "Coup suivant (→)": "Next move (→)",
    "Position actuelle": "Current position",
    "Annuler|coup": "Undo",
    "Nulle": "Draw",
    "Accepter": "Accept",
    "Abandonner": "Resign",
    "Coups": "Moves",
    "Aucun coup joué": "No moves yet",
    "{name} · réfléchit": "{name} · thinking",
    "Entrée : jouer · Échap : annuler": "Enter: play · Esc: cancel",
    "Vous": "You",
    "IA · {level}": "AI · {level}",
    "Joueur blanc": "White player",
    "Joueur noir": "Black player",
    "Niveau {level}": "{level} level",
    # Ligne d'état
    "Revue : position de départ · Fin pour revenir à la partie": (
        "Review: starting position · End to return to the game"
    ),
    "Revue : après {san} · Fin pour revenir à la partie": (
        "Review: after {san} · End to return to the game"
    ),
    "Les Blancs proposent la nulle · N pour accepter": "White offers a draw · N to accept",
    "Les Noirs proposent la nulle · N pour accepter": "Black offers a draw · N to accept",
    "L'IA réfléchit…": "The AI is thinking…",
    "Recherche d'un indice…": "Looking for a hint…",
    "À vous de jouer": "Your move",
    "Échec ! À vous de jouer": "Check! Your move",
    "Aux blancs de jouer": "White to move",
    "Aux noirs de jouer": "Black to move",
    "Échec ! Aux blancs de jouer": "Check! White to move",
    "Échec ! Aux noirs de jouer": "Check! Black to move",
    "Analyse…": "Analysing…",
    "{score} · prof. {depth}": "{score} · depth {depth}",
    # Résultats (GameResult.description)
    "Partie en cours": "Game in progress",
    "Les Blancs gagnent par échec et mat": "White wins by checkmate",
    "Les Noirs gagnent par échec et mat": "Black wins by checkmate",
    "Les Blancs gagnent au temps": "White wins on time",
    "Les Noirs gagnent au temps": "Black wins on time",
    "Les Blancs gagnent par abandon": "White wins by resignation",
    "Les Noirs gagnent par abandon": "Black wins by resignation",
    "Nulle par pat": "Draw by stalemate",
    "Nulle par la règle des 50 coups": "Draw by the 50-move rule",
    "Nulle par triple répétition": "Draw by threefold repetition",
    "Nulle par matériel insuffisant": "Draw by insufficient material",
    "Nulle par la règle des 75 coups": "Draw by the 75-move rule",
    "Nulle par quintuple répétition": "Draw by fivefold repetition",
    "Nulle au temps (matériel insuffisant pour mater)": (
        "Draw on time (insufficient material to mate)"
    ),
    "Nulle par accord mutuel": "Draw by agreement",
    # Fin de partie
    "Partie nulle": "Draw",
    "Victoire des blancs": "White wins",
    "Victoire des noirs": "Black wins",
    "Victoire !": "Victory!",
    "Défaite": "Defeat",
    "{n} coup": "{n} move",
    "{n} coups": "{n} moves",
    "Rejouer": "Play again",
    "Revoir la partie": "Review the game",
    "Exporter PGN": "Export PGN",
    "Bilan": "Report",
    # Notifications
    "La partie est terminée": "The game is over",
    "Ce n'est pas à vous de jouer": "It is not your turn",
    "Coup impossible": "Illegal move",
    "Coup ambigu : {options} ?": "Ambiguous move: {options}?",
    " ou ": " or ",
    "Coup illégal : {text}": "Illegal move: {text}",
    "Notation non reconnue : {text}": "Unrecognised notation: {text}",
    "Indice : {san}": "Hint: {san}",
    "Aucun coup à analyser": "No moves to analyse",
    "Partie sauvegardée : {name}": "Game saved: {name}",
    "Échec de la sauvegarde (voir le journal)": "Saving failed (see the log)",
    "Aucune sauvegarde à charger": "No saved game to load",
    "Sauvegarde illisible : chargement impossible": "Unreadable save: cannot load it",
    "Partie chargée ({n} demi-coup)": "Game loaded ({n} ply)",
    "Partie chargée ({n} demi-coups)": "Game loaded ({n} plies)",
    "Export PGN impossible (voir le journal)": "PGN export failed (see the log)",
    "PGN exporté : {path}": "PGN exported: {path}",
    "Import impossible : {name} illisible ou invalide": (
        "Cannot import: {name} is unreadable or invalid"
    ),
    "Import impossible : aucune partie dans {name}": "Cannot import: no game in {name}",
    "Import impossible : partie invalide": "Cannot import: invalid game",
    "PGN importé ({n} demi-coup)": "PGN imported ({n} ply)",
    "PGN importé ({n} demi-coups)": "PGN imported ({n} plies)",
    "L'IA refuse la nulle : elle estime sa position meilleure": (
        "The AI declines the draw: it thinks its position is better"
    ),
    # Confirmations
    "Recommencer la partie ?": "Restart the game?",
    "La partie en cours sera perdue si elle n'a pas été sauvegardée.": (
        "The current game will be lost unless it has been saved."
    ),
    "Recommencer": "Restart",
    "Abandonner la partie ?": "Resign the game?",
    "La victoire sera attribuée à l'adversaire.": "The win will go to your opponent.",
    "Entrée": "Enter",
    "Annuler": "Cancel",
    # Export PGN
    "Partie ChessProject": "ChessProject game",
    "Humain": "Human",
    # Raccourcis
    "Raccourcis clavier": "Keyboard shortcuts",
    "Fermer": "Close",
    "Taper un coup (e4, Nf3, O-O)": "Type a move (e4, Nf3, O-O)",
    "Annuler le dernier coup": "Take back the last move",
    "Proposer / accepter la nulle": "Offer / accept a draw",
    "Rejouer avec les mêmes réglages": "Play again with the same settings",
    "Sauvegarder la partie": "Save the game",
    "Charger une sauvegarde": "Load a saved game",
    "Exporter en PGN": "Export to PGN",
    "Retourner l'échiquier": "Flip the board",
    "Apparence": "Appearance",
    "Afficher la variante principale": "Show the principal variation",
    "Indice : meilleur coup en flèche": "Hint: best move as an arrow",
    "Bilan de la partie": "Game report",
    "Afficher les raccourcis": "Show the shortcuts",
    "Coup précédent / suivant": "Previous / next move",
    "Orig. Fin": "Home End",
    "Début / position actuelle": "Start / current position",
    "Échap": "Esc",
    "Tab": "Tab",
    "Annuler la sélection, fermer": "Cancel the selection, close",
    "Échiquier au clavier (flèches, Entrée)": "Board from the keyboard (arrows, Enter)",
    "Fenêtres : bouton suivant (Entrée)": "Windows: next button (Enter)",
    "Clic droit": "Right-click",
    "Flèche (glisser) ou marque": "Arrow (drag) or mark",
    # Apparence
    "THÈME": "THEME",
    "Sombre": "Dark",
    "Clair": "Light",
    "ÉCHIQUIER": "BOARD",
    "AFFICHAGE": "DISPLAY",
    "LANGUE": "LANGUAGE",
    "Barre d'évaluation": "Evaluation bar",
    "Variante principale (analyse)": "Principal variation (analysis)",
    "Indices contre l'IA": "Hints against the AI",
    "Coordonnées sur l'échiquier": "Board coordinates",
    "Coups possibles de la pièce choisie": "Legal moves of the selected piece",
    "Sons": "Sounds",
    "Ardoise": "Slate",
    "Noyer": "Walnut",
    "Forêt": "Forest",
    "Marine": "Navy",
    # Bilan
    "Analyse des positions… {done} / {total}": "Analysing positions… {done} / {total}",
    "Survolez la courbe pour lire l'évaluation, cliquez pour voir la position.": (
        "Hover over the graph to read the evaluation, click to see the position."
    ),
    "Position de départ": "Starting position",
    "Demi-coup {n}": "Ply {n}",
    "BLANCS": "WHITE",
    "NOIRS": "BLACK",
    "Imprécisions": "Inaccuracies",
    "Erreurs": "Mistakes",
    "Gaffes": "Blunders",
    "Perte moyenne (cp)": "Average loss (cp)",
    # Fichiers (J11.1)
    "Enregistrer": "Save",
    "Ouvrir": "Open",
    "Charger": "Load",
    "Exporter": "Export",
    "Importer": "Import",
    "Dossier illisible": "Unreadable folder",
    "Tapez un nom de fichier": "Type a file name",
    "Choisissez un fichier": "Choose a file",
    "« {name} » existe déjà : Entrée pour le remplacer": (
        "“{name}” already exists: Enter to replace it"
    ),
    "Supprimer « {name} » ? Suppr pour confirmer": "Delete “{name}”? Del to confirm",
    "Suppression impossible": "Cannot delete the file",
    "« {name} » supprimé": "“{name}” deleted",
    "Aucun fichier {extension} dans ce dossier": "No {extension} file in this folder",
    "NOM DU FICHIER": "FILE NAME",
    "Supprimer": "Delete",
    "Suppr": "Del",
    "Choisir une partie": "Choose a game",
    "{name} contient {n} parties.": "{name} contains {n} games.",
    "Données du jeu": "Game data",
    "Dossier personnel": "Home folder",
    "Documents": "Documents",
    "Téléchargements": "Downloads",
    "partie": "game",
}
