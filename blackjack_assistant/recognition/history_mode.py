"""VERLAUFS-MODUS: Nur das Verlaufs-Panel lesen und neu hinzugekommene Karten zählen.

Die Karten im Panel werden in Lesereihenfolge (Zeile für Zeile, links nach rechts) als Liste
gelesen und mit der bereits gezählten Liste verglichen:
- Die alte Liste ist der Anfang der neuen → nur die neuen Einträge am Ende zählen.
- Panel zeigt nur die letzten N Karten (scrollt) → längste Überlappung "Ende alt = Anfang neu"
  suchen, Rest zählen.
- Panel ist leer → Neu-Mischen.
- Keine Überlappung und die Liste ist kürzer → es wurde gemischt, bevor wir das leere Panel
  gesehen haben → Mischen melden und alle sichtbaren Karten zählen.

Unsichere Einträge stoppen das Zählen an dieser Stelle (die Reihenfolge muss stimmen).
Bleibt ein Eintrag mehrere stabile Bilder lang unsicher, wird er als "?" übernommen, nicht
gezählt und als ungesehene Karte gemeldet.
"""

from __future__ import annotations

from .events import CardEvent, EventType
from .matcher import Detection

UNKNOWN = "?"


def reading_order(detections: list[Detection], row_tolerance: float | None = None) -> list[Detection]:
    """Sortiert Treffer zeilenweise von oben nach unten, innerhalb der Zeile von links nach rechts."""
    if not detections:
        return []
    dets = sorted(detections, key=lambda d: d.center[1])
    tol = row_tolerance if row_tolerance is not None else max(4.0, dets[0].h * 0.5)
    rows: list[list[Detection]] = [[dets[0]]]
    for d in dets[1:]:
        if abs(d.center[1] - rows[-1][0].center[1]) <= tol:
            rows[-1].append(d)
        else:
            rows.append([d])
    return [d for row in rows for d in sorted(row, key=lambda d: d.center[0])]


def _same(a: str, b: str) -> bool:
    return a == b or a == UNKNOWN or b == UNKNOWN


def _is_prefix(old: list[str], new: list[str], max_mismatch: int) -> bool:
    if len(new) < len(old):
        return False
    mismatches = sum(1 for a, b in zip(old, new) if not _same(a, b))
    return mismatches <= max_mismatch


def _overlap(old: list[str], new: list[str], min_overlap: int) -> int:
    """Längste Überlappung: old[-k:] == new[:k]. 0 = keine (mit mindestens min_overlap)."""
    for k in range(min(len(old), len(new)), min_overlap - 1, -1):
        if all(_same(a, b) for a, b in zip(old[-k:], new[:k])):
            return k
    return 0


class HistoryReader:
    def __init__(
        self,
        min_confidence: float = 0.80,
        min_margin: float = 0.03,
        uncertain_frames: int = 3,
        min_overlap: int = 4,
    ):
        self.min_confidence = min_confidence
        self.min_margin = min_margin
        self.uncertain_frames = uncertain_frames
        self.min_overlap = min_overlap
        self.committed: list[str] = []     # bereits verarbeitete Einträge (Ränge oder "?")
        self.pending_frames = 0            # wie lange der nächste Eintrag schon unsicher ist
        self.shuffles = 0

    def reset(self) -> None:
        self.committed = []
        self.pending_frames = 0

    def update(self, detections: list[Detection]) -> list[CardEvent]:
        entries = reading_order(detections)
        events: list[CardEvent] = []

        if not entries:
            if self.committed:
                events.append(CardEvent(EventType.SHUFFLE, source="history",
                                        info={"cards_before": len(self.committed)}))
                self.shuffles += 1
                self.reset()
            return events

        ranks = [d.rank for d in entries]
        if _is_prefix(self.committed, ranks, max_mismatch=max(1, len(self.committed) // 50)):
            start = len(self.committed)
        else:
            k = _overlap(self.committed, ranks, self.min_overlap)
            if k:
                # Panel zeigt nur ein Fenster, ältere Einträge sind weggescrollt.
                # Ab jetzt reicht es, das sichtbare Fenster zu kennen.
                self.committed = ranks[:k]
                start = k
            else:
                # Neu gemischt, ohne dass wir das leere Panel gesehen haben
                events.append(CardEvent(EventType.SHUFFLE, source="history",
                                        info={"cards_before": len(self.committed), "implicit": True}))
                self.shuffles += 1
                self.reset()
                start = 0

        for det in entries[start:]:
            if det.is_confident(self.min_confidence, self.min_margin):
                self.committed.append(det.rank)
                self.pending_frames = 0
                events.append(CardEvent(EventType.NEW_CARD, rank=det.rank, confidence=det.score,
                                        position=det.center, box=det.box(), source="history"))
                continue
            # Unsicher: warten, ob ein späteres Bild ihn sicher liest
            self.pending_frames += 1
            final = self.pending_frames >= self.uncertain_frames
            events.append(CardEvent(EventType.UNCERTAIN, rank=det.rank, confidence=det.score,
                                    position=det.center, box=det.box(), source="history",
                                    final=final))
            if not final:
                break
            self.committed.append(UNKNOWN)
            self.pending_frames = 0
            events.append(CardEvent(EventType.UNSEEN, count=1, source="history",
                                    info={"reason": "unsicher"}))
        return events
