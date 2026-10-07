"""Zähler: Running Count, verbleibende Decks, True Count, Ass-Nebenzähler, Mischstatistik.

Der Zähler bekommt Ereignisse aus der Erkennung (oder direkt Karten aus der Simulation):
- sichere Karte        → add(rank)       zählt
- Korrektur            → remove(alt) + add(neu)
- ungesehene Karte     → add_unseen(n)   zählt NICHT, verringert aber die Restdecks
- Rundenende           → round_end()     bei "mischt jede Runde" Count auf 0
- Neu-Mischen          → shuffle()       Count zurücksetzen, Statistik schreiben
"""

from __future__ import annotations

import json
from collections import Counter as RankCounter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..models import value_rank
from ..recognition.events import CardEvent, EventType
from .systems import CountingSystem, get_system


@dataclass
class CountState:
    """Momentaufnahme für Strategie und Overlay."""

    system: str
    system_name: str
    balanced: bool
    running_count: float
    true_count: float | None          # None bei unausgeglichenen Systemen (KO)
    decks_remaining: float
    cards_seen: int
    cards_unseen: int
    aces_seen: int
    ace_surplus: float                # mehr (+) oder weniger (−) Asse im Rest als erwartet
    betting_count: float              # Count für den Einsatz (inkl. Ass-Korrektur)
    index_factor: float
    ineffective: bool                 # Spiel mischt jede Runde → Zählen wirkungslos
    rounds_since_shuffle: int
    seen_by_rank: dict[str, int] = field(default_factory=dict)


class Counter:
    def __init__(self, system: CountingSystem | str = "hi_lo", decks: int = 6,
                 shuffle_every_round: bool = False, deck_rounding: float = 0.5,
                 stats_file: Path | None = None):
        self.system = get_system(system) if isinstance(system, str) else system
        self.decks = decks
        self.shuffle_every_round = shuffle_every_round
        self.deck_rounding = deck_rounding     # 0.5 = auf halbe Decks runden, 0 = exakt
        self.stats_file = Path(stats_file) if stats_file else None
        self.shuffle_history: list[dict] = []  # Runden pro Schuh (Statistik)
        self.paused = False
        self.reset()

    @classmethod
    def from_profile(cls, profile, stats_file: Path | None = None) -> "Counter":
        counting = profile.counting or {}
        return cls(
            system=counting.get("system", "hi_lo"),
            decks=profile.rules.decks,
            shuffle_every_round=bool(counting.get("shuffle_every_round",
                                                  profile.rules.shuffle_every_round)),
            deck_rounding=float(counting.get("deck_rounding", 0.5)),
            stats_file=stats_file,
        )

    # ------------------------------------------------------------------
    # Zustand ändern
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Count auf den Startwert (Hotkey "Count zurücksetzen" und nach dem Mischen)."""
        self.running_count = self.system.initial_count(self.decks)
        self.seen = RankCounter()
        self.unseen = 0
        self.rounds_since_shuffle = 0

    def add(self, rank: str) -> None:
        if self.paused:
            return
        self.running_count += self.system.value(rank)
        self.seen[value_rank(rank)] += 1

    def remove(self, rank: str) -> None:
        """Nimmt eine früher gezählte Karte zurück (Korrektur einer Fehllesung)."""
        v = value_rank(rank)
        if self.seen[v] > 0:
            self.seen[v] -= 1
            self.running_count -= self.system.value(rank)

    def add_unseen(self, count: int = 1) -> None:
        if not self.paused:
            self.unseen += count

    def round_end(self) -> None:
        self.rounds_since_shuffle += 1
        if self.shuffle_every_round:
            # Spiel mischt jede Runde → alles Gesehene ist wieder im Schuh
            self._record_shuffle("every_round")
            self.reset()
            self.rounds_since_shuffle = 0

    def shuffle(self, reason: str = "detected") -> None:
        self._record_shuffle(reason)
        self.reset()

    def apply(self, event: CardEvent) -> None:
        """Ereignis aus der Erkennung verarbeiten."""
        t = event.type
        if t == EventType.NEW_CARD:
            self.add(event.rank)
        elif t == EventType.CORRECTION:
            self.remove(event.old_rank)
            self.add(event.rank)
        elif t == EventType.UNSEEN:
            self.add_unseen(event.count)
        elif t == EventType.ROUND_END:
            self.round_end()
        elif t == EventType.SHUFFLE:
            self.shuffle("history_empty")
        # UNCERTAIN: wird nicht gezählt (Overlay zeigt die Warnung)

    def _record_shuffle(self, reason: str) -> None:
        """Statistik: nach wie vielen Runden wurde gemischt?"""
        if self.cards_seen == 0 and self.rounds_since_shuffle == 0:
            return  # nichts gespielt (z. B. doppeltes Mischsignal)
        entry = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "rounds": self.rounds_since_shuffle,
            "cards_seen": self.cards_seen,
            "cards_unseen": self.unseen,
            "penetration": round((self.cards_seen + self.unseen) / (self.decks * 52), 3),
            "reason": reason,
        }
        self.shuffle_history.append(entry)
        if self.stats_file:
            self.stats_file.parent.mkdir(parents=True, exist_ok=True)
            with self.stats_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # Werte lesen
    # ------------------------------------------------------------------

    @property
    def cards_seen(self) -> int:
        return sum(self.seen.values())

    @property
    def cards_out(self) -> int:
        """Gesehene + ungesehene Karten (alles, was nicht mehr im Schuh ist)."""
        return self.cards_seen + self.unseen

    @property
    def decks_remaining_exact(self) -> float:
        return max(0.0, self.decks - self.cards_out / 52)

    @property
    def decks_remaining(self) -> float:
        """Restdecks, auf halbe Decks gerundet (wie beim Schätzen am Tisch), mindestens 0.5."""
        exact = self.decks_remaining_exact
        if self.deck_rounding:
            exact = round(exact / self.deck_rounding) * self.deck_rounding
        return max(0.5, exact)

    @property
    def true_count(self) -> float | None:
        if not self.system.balanced:
            return None
        return self.running_count / self.decks_remaining

    @property
    def ace_surplus(self) -> float:
        """Überzählige Asse im Rest: übrig − erwartet (erwartet = 4 pro Restdeck)."""
        aces_left = self.decks * 4 - self.seen["A"]
        return aces_left - 4 * self.decks_remaining_exact

    @property
    def betting_count(self) -> float:
        """Count für die Einsatzhöhe.

        Ausgeglichen: True Count, bei Ass-Nebenzähler korrigiert um
        ace_adjust × überzählige Asse / Restdecks. Unausgeglichen: Running Count.
        """
        if not self.system.balanced:
            return self.running_count
        rc = self.running_count
        if self.system.ace_side_count:
            rc += self.system.ace_adjust * self.ace_surplus
        return rc / self.decks_remaining

    @property
    def ineffective(self) -> bool:
        return self.shuffle_every_round

    def state(self) -> CountState:
        return CountState(
            system=self.system.key,
            system_name=self.system.name,
            balanced=self.system.balanced,
            running_count=self.running_count,
            true_count=self.true_count,
            decks_remaining=self.decks_remaining,
            cards_seen=self.cards_seen,
            cards_unseen=self.unseen,
            aces_seen=self.seen["A"],
            ace_surplus=self.ace_surplus,
            betting_count=self.betting_count,
            index_factor=self.system.index_factor,
            ineffective=self.ineffective,
            rounds_since_shuffle=self.rounds_since_shuffle,
            seen_by_rank=dict(self.seen),
        )

    def remaining_composition(self) -> tuple[int, ...]:
        """Restkarten pro Rangklasse (2..9, 10, A) – nur gesehene Karten abgezogen."""
        from .systems import CARDS_PER_DECK
        from ..models import VALUE_RANKS

        return tuple(CARDS_PER_DECK[r] * self.decks - self.seen[r] for r in VALUE_RANKS)

    def shuffle_statistics(self) -> dict:
        """Zusammenfassung: nach wie vielen Runden wurde jeweils gemischt?"""
        rounds = [e["rounds"] for e in self.shuffle_history]
        if not rounds:
            return {"shoes": 0}
        return {
            "shoes": len(rounds),
            "rounds_mean": sum(rounds) / len(rounds),
            "rounds_min": min(rounds),
            "rounds_max": max(rounds),
            "penetration_mean": sum(e["penetration"] for e in self.shuffle_history) / len(rounds),
        }

    def summary(self) -> str:
        tc = f"TC {self.true_count:+.1f}" if self.true_count is not None else "unausgeglichen"
        return (f"RC {self.running_count:+g}  {tc}  Decks {self.decks_remaining:g}"
                f"  gesehen {self.cards_seen} (+{self.unseen} ungesehen)")
