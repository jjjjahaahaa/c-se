"""Gemeinsame Datenobjekte und Hilfsfunktionen für alle Module.

Dieses Modul importiert keine Bildschirm- oder GUI-Bibliotheken und ist überall
(Tests, Simulation, Erkennung) verwendbar.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from enum import Enum

# Kanonische Ränge. Bildkarten intern immer als J/Q/K, auch wenn ein Spiel B/D/K zeigt.
RANKS: tuple[str, ...] = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")

# Für Zählung und Strategie zählt nur der Punktwert: 2..9, 10 (für 10/J/Q/K) und A
VALUE_RANKS: tuple[str, ...] = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "A")

# Alle akzeptierten Schreibweisen (Gross-/Kleinschreibung egal) → kanonischer Rang
_RANK_ALIASES: dict[str, str] = {
    "T": "10", "10": "10", "ZEHN": "10",
    "J": "J", "B": "J", "BUBE": "J", "JACK": "J",
    "Q": "Q", "D": "Q", "DAME": "Q", "QUEEN": "Q",
    "K": "K", "KÖNIG": "K", "KOENIG": "K", "KING": "K",
    "A": "A", "AS": "A", "ASS": "A", "ACE": "A", "1": "A", "11": "A",
}


def normalize_rank(label: str) -> str:
    """Wandelt eine Rang-Bezeichnung in den kanonischen Rang um.

    Akzeptiert z. B. "B"/"J"/"Bube" → "J", "D"/"Q" → "Q", "T"/"10" → "10", "As" → "A".
    Löst ValueError aus, wenn die Bezeichnung unbekannt ist.
    """
    key = str(label).strip().upper()
    if key in _RANK_ALIASES:
        return _RANK_ALIASES[key]
    if key in {"2", "3", "4", "5", "6", "7", "8", "9"}:
        return key
    raise ValueError(f"Unbekannter Rang: {label!r}")


def value_rank(rank: str) -> str:
    """Rang → Punktwert-Klasse: J/Q/K werden zu "10"."""
    rank = normalize_rank(rank)
    return "10" if rank in ("J", "Q", "K") else rank


def card_points(rank: str) -> int:
    """Punktwert einer Karte, Ass = 1 (die Soft-Logik steckt in hand_total)."""
    v = value_rank(rank)
    return 1 if v == "A" else int(v)


def hand_total(ranks: list[str] | tuple[str, ...]) -> tuple[int, bool]:
    """Handwert und ob die Hand soft ist (ein Ass zählt als 11)."""
    total = 0
    aces = 0
    for r in ranks:
        p = card_points(r)
        total += p
        if p == 1:
            aces += 1
    if aces and total + 10 <= 21:
        return total + 10, True
    return total, False


def is_blackjack(ranks: list[str] | tuple[str, ...]) -> bool:
    return len(ranks) == 2 and hand_total(ranks)[0] == 21


@dataclass(frozen=True)
class Card:
    """Eine erkannte oder simulierte Karte."""

    rank: str
    suit: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "rank", normalize_rank(self.rank))


class Action(str, Enum):
    """Mögliche Spielzüge."""

    HIT = "hit"
    STAND = "stand"
    DOUBLE = "double"
    SPLIT = "split"
    SURRENDER = "surrender"

    @property
    def german(self) -> str:
        return {
            "hit": "Ziehen",
            "stand": "Stehen",
            "double": "Verdoppeln",
            "split": "Teilen",
            "surrender": "Aufgeben",
        }[self.value]


@dataclass
class Rules:
    """Tischregeln. Standard = Projektauftrag (6 Decks, S17, DAS, Late Surrender)."""

    decks: int = 6
    penetration: float = 0.75
    hit_soft_17: bool = False          # False = Dealer steht auf Soft 17 (S17)
    blackjack_pays: float = 1.5        # 3:2
    double_any_two: bool = True
    double_after_split: bool = True    # DAS
    max_hands: int = 4                 # 4 = bis zu dreimal teilen; 2 = kein Re-Split
    resplit_aces: bool = False
    hit_split_aces: bool = False
    late_surrender: bool = True
    dealer_peek: bool = True           # Dealer prüft bei A/10 auf Blackjack
    insurance: bool = True
    seven_card_charlie: bool = False   # 7 Karten ohne Überkaufen gewinnen automatisch
    shuffle_every_round: bool = False  # z. B. viele Online-Spiele (CSM/RNG)

    @classmethod
    def from_dict(cls, data: dict | None) -> "Rules":
        """Erzeugt Regeln aus einem Dictionary; unbekannte Schlüssel werden ignoriert."""
        data = data or {}
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def total_cards(self) -> int:
        return self.decks * 52


@dataclass
class HandState:
    """Was die Strategie für eine Entscheidung wissen muss."""

    player: list[str]                       # Ränge der Spielerhand
    dealer_up: str                          # offene Dealer-Karte
    can_double: bool = True
    can_split: bool = True
    can_surrender: bool = True
    from_split: bool = False
    hand_count: int = 1                     # Anzahl Hände (nach Split > 1)

    @property
    def total(self) -> int:
        return hand_total(self.player)[0]

    @property
    def soft(self) -> bool:
        return hand_total(self.player)[1]

    @property
    def is_pair(self) -> bool:
        return len(self.player) == 2 and value_rank(self.player[0]) == value_rank(self.player[1])


@dataclass
class Decision:
    """Empfehlung der Entscheidungs-Engine."""

    action: Action
    source: str = "basic"                   # "basic", "deviation", "jev", "exact", …
    note: str = ""                          # z. B. "I18: 16 vs 10 stehen ab TC 0"
    probabilities: dict[str, float] = field(default_factory=dict)
    take_insurance: bool = False
