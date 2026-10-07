"""Basic Strategy aus config/basic_strategy.toml, angepasst an die Regeln eines Profils.

Die Tabelle gilt für 6 Decks, S17, DAS, Late Surrender. Andere Regeln werden hier
umgesetzt:
- H17 (Dealer zieht auf Soft 17): Einträge aus dem Abschnitt [h17] überschreiben
- kein DAS: "Ph" (Teilen nur mit DAS) wird zu Ziehen
- kein Surrender: "Rh"/"Rs"/"Rp" werden zu Ziehen/Stehen/Teilen
- Verdoppeln nicht möglich (mehr als zwei Karten, Regel): "D" → Ziehen, "Ds" → Stehen
- Teilen nicht möglich: Paar wird als normale Hand gespielt
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

from ..models import Action, HandState, Rules, hand_total, value_rank

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TABLE_FILE = PROJECT_ROOT / "config" / "basic_strategy.toml"

DEALER_COLUMNS = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "A")


@lru_cache(maxsize=4)
def load_table(path: str = str(TABLE_FILE)) -> dict:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    if tuple(data["dealer"]) != DEALER_COLUMNS:
        raise ValueError("Spalten der Basic-Strategy-Tabelle müssen 2..10, A sein")
    for section in ("hard", "soft", "pairs"):
        for key, row in data[section].items():
            if len(row) != 10:
                raise ValueError(f"Zeile {section} {key} hat nicht 10 Einträge")
    return data


def hand_key(hand: HandState) -> tuple[str, str]:
    """Ordnet eine Hand einer Tabellenzeile zu: ("pairs", "8"), ("soft", "18"), ("hard", "16")."""
    if hand.is_pair and hand.can_split:
        return "pairs", value_rank(hand.player[0])
    total, soft = hand_total(hand.player)
    if soft and total >= 12:
        return "soft", str(total)
    return "hard", str(max(4, min(total, 21)))


def table_code(hand: HandState, rules: Rules, path: Path = TABLE_FILE) -> str:
    """Roher Tabellencode für eine Hand (inkl. H17-Anpassung)."""
    data = load_table(str(path))
    section, key = hand_key(hand)
    dealer = value_rank(hand.dealer_up)
    code = data[section][key][DEALER_COLUMNS.index(dealer)]
    if rules.hit_soft_17:
        label = {"pairs": "pair", "soft": "soft", "hard": "hard"}[section]
        code = data.get("h17", {}).get(f"{label} {key}:{dealer}", code)
    return code


def resolve(code: str, hand: HandState, rules: Rules) -> Action:
    """Tabellencode → Aktion unter Berücksichtigung, was gerade erlaubt ist."""
    can_surrender = (hand.can_surrender and rules.late_surrender and len(hand.player) == 2
                     and not hand.from_split and hand.hand_count == 1)
    can_double = hand.can_double and len(hand.player) == 2
    can_split = hand.can_split and hand.is_pair
    if code.startswith("R"):
        if can_surrender:
            return Action.SURRENDER
        code = {"Rh": "H", "Rs": "S", "Rp": "P"}[code]
    if code == "Ph":
        code = "P" if rules.double_after_split else "H"
    if code == "P":
        if can_split:
            return Action.SPLIT
        # Teilen nicht möglich → als normale Hand spielen
        fallback = HandState(hand.player, hand.dealer_up, hand.can_double, False,
                             hand.can_surrender, hand.from_split, hand.hand_count)
        return resolve(table_code(fallback, rules), fallback, rules)
    if code == "D":
        return Action.DOUBLE if can_double else Action.HIT
    if code == "Ds":
        return Action.DOUBLE if can_double else Action.STAND
    if code == "H":
        return Action.HIT
    if code == "S":
        return Action.STAND
    raise ValueError(f"Unbekannter Tabellencode: {code}")


def basic_action(hand: HandState, rules: Rules) -> Action:
    """Empfohlene Aktion nach Basic Strategy."""
    total, _ = hand_total(hand.player)
    if total >= 21:
        return Action.STAND
    return resolve(table_code(hand, rules), hand, rules)
