"""Zählsysteme aus config/counting_systems.toml laden.

Die Kartenwerte stehen in der Konfigurationsdatei, nicht im Code. Neue Systeme lassen sich
dort ergänzen, ohne Python zu ändern.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ..models import VALUE_RANKS, value_rank

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = PROJECT_ROOT / "config" / "counting_systems.toml"

# Karten pro Deck je Punktwert-Klasse (Zehnerwerte: 10, J, Q, K → 16)
CARDS_PER_DECK = {r: (16 if r == "10" else 4) for r in VALUE_RANKS}


@dataclass(frozen=True)
class CountingSystem:
    key: str
    name: str
    values: dict[str, float]
    balanced: bool = True
    level: float = 1
    ace_side_count: bool = False
    ace_adjust: float = 0.0
    index_factor_override: float | None = None
    # nur für unausgeglichene Systeme (KO)
    irc_per_deck: float = 0.0
    irc_offset: float = 0.0
    key_count: float | None = None
    pivot: float | None = None
    insurance_rc: float | None = None
    reference_depth: float = 0.375
    extra: dict = field(default_factory=dict)

    def value(self, rank: str) -> float:
        """Zählwert einer Karte (J/Q/K wie 10)."""
        return self.values[value_rank(rank)]

    @property
    def deck_sum(self) -> float:
        """Summe der Werte über ein ganzes Deck (0 bei ausgeglichenen Systemen)."""
        return sum(self.values[r] * CARDS_PER_DECK[r] for r in VALUE_RANKS)

    @property
    def index_factor(self) -> float:
        """Umrechnung eines Hi-Lo-Index in einen Index dieses Systems.

        Ohne Angabe in der Konfiguration: Regressionskoeffizient der Kartenwerte gegenüber
        Hi-Lo (wie stark der Count dieses Systems im Mittel steigt, wenn der Hi-Lo-Count um 1
        steigt). Hi-Lo = 1.0, Zen ≈ 1.7, Wong Halves = 1.0.
        """
        if self.index_factor_override is not None:
            return self.index_factor_override
        hilo = {"2": 1, "3": 1, "4": 1, "5": 1, "6": 1, "7": 0, "8": 0, "9": 0, "10": -1, "A": -1}
        num = sum(self.values[r] * hilo[r] * CARDS_PER_DECK[r] for r in VALUE_RANKS)
        den = sum(hilo[r] ** 2 * CARDS_PER_DECK[r] for r in VALUE_RANKS)
        return num / den

    def initial_count(self, decks: int) -> float:
        """Start-Count nach dem Mischen (0 bei ausgeglichenen Systemen, KO: IRC)."""
        if self.balanced:
            return 0.0
        return self.irc_per_deck * decks + self.irc_offset

    def ko_threshold(self, hilo_true_count: float, decks: int) -> float:
        """Feste Running-Count-Schwelle für ein unausgeglichenes System, die einem
        Hi-Lo-True-Count entspricht (bei der Referenztiefe des Schuhs).

        Erwarteter KO-Count nach d gespielten Decks ohne Vorteil: IRC + 4·d.
        Dazu kommt TC × Restdecks. Bei TC = +4 ergibt das unabhängig von der Tiefe genau
        den Pivot (+4) – das ist die Idee des KO-Systems.
        """
        played = decks * self.reference_depth
        unbalance = self.deck_sum  # +4 pro Deck bei KO
        return self.initial_count(decks) + unbalance * played + hilo_true_count * (decks - played)


def _parse(key: str, data: dict) -> CountingSystem:
    values = {str(k): float(v) for k, v in data["values"].items()}
    missing = [r for r in VALUE_RANKS if r not in values]
    if missing:
        raise ValueError(f"Zählsystem '{key}': Werte fehlen für {missing}")
    known = {"name", "values", "balanced", "level", "ace_side_count", "ace_adjust", "index_factor",
             "irc_per_deck", "irc_offset", "key_count", "pivot", "insurance", "reference_depth"}
    system = CountingSystem(
        key=key,
        name=data.get("name", key),
        values=values,
        balanced=bool(data.get("balanced", True)),
        level=data.get("level", 1),
        ace_side_count=bool(data.get("ace_side_count", False)),
        ace_adjust=float(data.get("ace_adjust", 0.0)),
        index_factor_override=data.get("index_factor"),
        irc_per_deck=float(data.get("irc_per_deck", 0.0)),
        irc_offset=float(data.get("irc_offset", 0.0)),
        key_count=data.get("key_count"),
        pivot=data.get("pivot"),
        insurance_rc=data.get("insurance"),
        reference_depth=float(data.get("reference_depth", 0.375)),
        extra={k: v for k, v in data.items() if k not in known},
    )
    if system.balanced and abs(system.deck_sum) > 1e-9:
        raise ValueError(f"Zählsystem '{key}' ist als ausgeglichen markiert, "
                         f"Summe pro Deck ist aber {system.deck_sum}")
    return system


@lru_cache(maxsize=8)
def _load_cached(path: str, mtime: float) -> dict[str, CountingSystem]:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return {key: _parse(key, entry) for key, entry in data.get("systems", {}).items()}


def load_systems(path: Path = CONFIG_FILE) -> dict[str, CountingSystem]:
    """Alle Zählsysteme aus der Konfigurationsdatei."""
    path = Path(path)
    return _load_cached(str(path), path.stat().st_mtime)


def get_system(key: str, path: Path = CONFIG_FILE) -> CountingSystem:
    systems = load_systems(path)
    if key not in systems:
        raise KeyError(f"Unbekanntes Zählsystem '{key}'. Verfügbar: {', '.join(systems)}")
    return systems[key]
