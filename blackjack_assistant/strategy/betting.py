"""Einsatzempfehlung: 1 Einheit bis True Count +1, danach steigend.

Die Staffelung steht im Profil, z. B. "ramp": [[2, 2], [3, 4], [4, 6], [5, 8]]
→ ab TC +2: 2 Einheiten, ab +3: 4, ab +4: 6, ab +5: 8, darunter 1 Einheit.

Die Schwellen sind Hi-Lo-True-Counts. Für andere Systeme werden sie wie die Indizes
umgerechnet (Faktor bzw. feste KO-Schwelle).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..counting.counter import CountState
from ..counting.systems import get_system

DEFAULT_RAMP = [[2, 2], [3, 4], [4, 6], [5, 8]]


@dataclass
class BetAdvice:
    units: int
    amount: float
    count_used: float
    note: str = ""


class BetRamp:
    def __init__(self, ramp: list[list[float]] | None = None, unit: float = 10, decks: int = 6):
        self.ramp = sorted((float(t), int(u)) for t, u in (ramp or DEFAULT_RAMP))
        self.unit = unit
        self.decks = decks

    @classmethod
    def from_profile(cls, profile) -> "BetRamp":
        betting = profile.betting or {}
        return cls(betting.get("ramp"), betting.get("unit", 10), profile.rules.decks)

    def threshold(self, hilo_tc: float, count: CountState) -> float:
        system = get_system(count.system)
        if not system.balanced:
            return system.ko_threshold(hilo_tc, self.decks)
        return hilo_tc * count.index_factor

    def advise(self, count: CountState) -> BetAdvice:
        if count.ineffective:
            return BetAdvice(1, self.unit, 0.0, "Spiel mischt jede Runde – minimaler Einsatz")
        value = count.betting_count
        units = 1
        for tc, u in self.ramp:
            if value >= self.threshold(tc, count):
                units = u
        return BetAdvice(units, units * self.unit, value)
