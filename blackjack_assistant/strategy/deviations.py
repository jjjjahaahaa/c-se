"""Index-Spiele (Illustrious 18, Fab 4) aus config/deviations.toml.

Die Indizes gelten für Hi-Lo. Für andere Systeme:
- ausgeglichen: Index × index_factor des Systems (Näherung)
- unausgeglichen (KO): feste Running-Count-Schwelle, siehe CountingSystem.ko_threshold
- eigene Werte pro System unter [overrides.<system>] haben Vorrang
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..counting.counter import CountState
from ..counting.systems import get_system
from ..models import Action, HandState, hand_total, value_rank

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEVIATIONS_FILE = PROJECT_ROOT / "config" / "deviations.toml"

ACTIONS = {
    "stand": Action.STAND, "hit": Action.HIT, "double": Action.DOUBLE,
    "split": Action.SPLIT, "surrender": Action.SURRENDER,
}


@dataclass(frozen=True)
class Deviation:
    name: str
    hand: str            # "hard 16", "soft 18", "pair 10", "insurance"
    dealer: str
    index: float         # Hi-Lo-Index
    when: str            # ">=" oder "<"
    action: str
    otherwise: str | None = None
    group: str = ""

    def matches(self, hand: HandState) -> bool:
        if value_rank(hand.dealer_up) != self.dealer:
            return False
        kind, value = self.hand.split()
        if kind == "pair":
            return hand.is_pair and value_rank(hand.player[0]) == value
        total, soft = hand_total(hand.player)
        if kind == "soft":
            return soft and str(total) == value
        if kind == "hard":
            return not soft and str(total) == value and not (hand.is_pair and self._pair_row(hand))
        return False

    @staticmethod
    def _pair_row(hand: HandState) -> bool:
        """Paare, die als Paar gespielt werden, zählen nicht als harte Summe
        (Ausnahme 5,5 – wird wie hart 10 gespielt)."""
        return hand.can_split and value_rank(hand.player[0]) != "5"

    def threshold(self, count: CountState, decks: int, override: float | None = None) -> float:
        """Index im Massstab des aktiven Zählsystems."""
        if override is not None:
            return override
        system = get_system(count.system)
        if not system.balanced:
            if self.hand == "insurance" and system.insurance_rc is not None:
                return float(system.insurance_rc)
            return system.ko_threshold(self.index, decks)
        return self.index * count.index_factor

    def active(self, count: CountState, decks: int, override: float | None = None) -> bool:
        """Ist die Bedingung erfüllt? Ausgeglichen: True Count, KO: Running Count."""
        value = count.true_count if count.balanced else count.running_count
        thr = self.threshold(count, decks, override)
        return value >= thr if self.when == ">=" else value < thr


@lru_cache(maxsize=4)
def _load(path: str) -> tuple[tuple[Deviation, ...], dict]:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    items = tuple(
        Deviation(
            name=d["name"], hand=d["hand"], dealer=str(d["dealer"]), index=float(d["index"]),
            when=d.get("when", ">="), action=d["action"], otherwise=d.get("else"),
            group=d.get("group", ""),
        )
        for d in data.get("deviation", [])
    )
    return items, data.get("overrides", {})


def load_deviations(path: Path = DEVIATIONS_FILE) -> list[Deviation]:
    return list(_load(str(path))[0])


def overrides_for(system: str, path: Path = DEVIATIONS_FILE) -> dict[str, float]:
    return dict(_load(str(path))[1].get(system, {}))


class DeviationSet:
    """Alle Abweichungen für ein Zählsystem."""

    def __init__(self, system: str, decks: int, path: Path = DEVIATIONS_FILE):
        self.items = load_deviations(path)
        self.overrides = overrides_for(system, path)
        self.decks = decks

    def _active(self, dev: Deviation, count: CountState) -> bool:
        return dev.active(count, self.decks, self.overrides.get(dev.name))

    def insurance(self, count: CountState) -> tuple[bool, Deviation | None]:
        for dev in self.items:
            if dev.hand == "insurance":
                return self._active(dev, count), dev
        return False, None

    def surrender(self, hand: HandState, count: CountState) -> tuple[bool | None, Deviation | None]:
        """True = aufgeben, False = ausdrücklich nicht aufgeben, None = keine Regel → Basic."""
        for dev in self.items:
            if dev.action == "surrender" and dev.matches(hand):
                if self._active(dev, count):
                    return True, dev
                if dev.otherwise == "no_surrender":
                    return False, dev
        return None, None

    def play(self, hand: HandState, count: CountState) -> tuple[Action | None, Deviation | None]:
        """Aktion aus einer aktiven Abweichung (ohne Surrender/Insurance) oder None."""
        for dev in self.items:
            if dev.action in ("surrender", "insurance") or not dev.matches(hand):
                continue
            if self._active(dev, count):
                return ACTIONS[dev.action], dev
            if dev.otherwise and dev.otherwise in ACTIONS:
                return ACTIONS[dev.otherwise], dev
        return None, None
