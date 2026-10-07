"""Ereignisse, die die Erkennung an Zählung, Strategie und Overlay meldet."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EventType(str, Enum):
    NEW_CARD = "new_card"        # Karte sicher erkannt → zählen
    UNCERTAIN = "uncertain"      # Karte unsicher → NICHT zählen, im Overlay gelb markieren
    UNSEEN = "unseen"            # Karte wurde ausgeteilt, aber nie gezeigt/gelesen → nur für Decks
    CORRECTION = "correction"    # früher gezählte Karte war falsch gelesen (old_rank → rank)
    ROUND_END = "round_end"      # Tisch ist leer geworden
    SHUFFLE = "shuffle"          # Verlaufs-Panel leer → neu gemischt


@dataclass
class CardEvent:
    type: EventType
    rank: str | None = None
    confidence: float = 0.0
    role: str | None = None              # "dealer", "player" oder None (Verlaufs-Panel)
    position: tuple[float, float] | None = None
    box: tuple[int, int, int, int] | None = None
    source: str = ""                     # "table" oder "history"
    final: bool = False                  # bei UNCERTAIN: endgültig (wird als ungesehen gewertet)
    old_rank: str | None = None          # bei CORRECTION
    count: int = 1                       # bei UNSEEN: Anzahl Karten
    info: dict = field(default_factory=dict)

    def describe(self) -> str:
        """Kurze deutsche Beschreibung für Log und Konsole."""
        t = self.type
        if t == EventType.NEW_CARD:
            return f"Karte {self.rank} ({self.confidence:.2f}, {self.role or self.source})"
        if t == EventType.UNCERTAIN:
            state = "endgültig unsicher" if self.final else "unsicher"
            return f"{state}: {self.rank}? ({self.confidence:.2f})"
        if t == EventType.UNSEEN:
            return f"{self.count} ungesehene Karte(n)"
        if t == EventType.CORRECTION:
            return f"Korrektur {self.old_rank} → {self.rank}"
        if t == EventType.ROUND_END:
            return "Rundenende"
        return "Neu gemischt"
