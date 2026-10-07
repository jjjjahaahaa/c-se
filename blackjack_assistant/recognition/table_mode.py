"""TISCH-MODUS: Karten auf dem Tisch verfolgen und jede Karte nur EINMAL zählen.

Eine Karte ist in vielen Bildern sichtbar. Deshalb merkt sich der Tracker pro Runde jede
Karte mit Rang und Position ("Track"). Ein Treffer an derselben Stelle mit demselben Rang
ist dieselbe Karte. Wird der Tisch leer, ist die Runde zu Ende und alles wird vergessen.

Sonderfälle:
- Split: Eine Karte wandert in eine neue Hand. Verschwindet ein gezählter Track und taucht
  im selben Bild derselbe Rang in derselben Rolle (Dealer/Spieler) an neuer Stelle auf,
  gilt das als Verschiebung, nicht als neue Karte.
- Unsichere Treffer werden als "pending" geführt und erst gezählt, wenn ein späteres Bild
  sie sicher erkennt. Bleiben sie bis Rundenende unsicher, gelten sie als ungesehen.
  Verschwindet ein unsicherer Treffer wieder, war er vorübergehend (Animation) und wird verworfen.
- Korrektur: Liest ein späteres Bild an derselben Stelle sicher einen anderen Rang mit
  höherem Score, wird die frühere Zählung korrigiert.
- Hole Card: Hat der Dealer am Rundenende weniger als 2 sichtbare Karten, wurde die
  Hole Card nicht gezeigt → als ungesehen melden (nur wenn das Profil eine Hole Card hat).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..models import hand_total
from .events import CardEvent, EventType
from .matcher import Detection


@dataclass
class Track:
    rank: str
    x: float
    y: float
    role: str
    score: float
    counted: bool
    pending_frames: int = 0
    box: tuple[int, int, int, int] | None = None


def area_contains(area: list[float], frame_size: tuple[int, int], point: tuple[float, float]) -> bool:
    """Liegt ein Punkt (Pixel) in einem relativen Bereich [x, y, b, h] (Anteile 0..1)?"""
    w, h = frame_size
    ax, ay, aw, ah = area
    px, py = point
    return ax * w <= px <= (ax + aw) * w and ay * h <= py <= (ay + ah) * h


class TableTracker:
    def __init__(
        self,
        dealer_area: list[float],
        player_area: list[float],
        min_confidence: float = 0.80,
        min_margin: float = 0.03,
        dealer_hole_card: bool = True,
        position_tolerance: float = 12.0,
        hand_gap: float | None = None,
    ):
        self.dealer_area = dealer_area
        self.player_area = player_area
        self.min_confidence = min_confidence
        self.min_margin = min_margin
        self.dealer_hole_card = dealer_hole_card
        self.tol = position_tolerance
        self.hand_gap = hand_gap
        self.tracks: list[Track] = []
        self.rounds = 0

    # ------------------------------------------------------------------

    def role_of(self, det: Detection, frame_size: tuple[int, int]) -> str | None:
        c = det.center
        if area_contains(self.dealer_area, frame_size, c):
            return "dealer"
        if area_contains(self.player_area, frame_size, c):
            return "player"
        return None  # ausserhalb (z. B. Buttons, Chips) → ignorieren

    def _confident(self, det: Detection) -> bool:
        return det.is_confident(self.min_confidence, self.min_margin)

    def _event(self, type_: EventType, det: Detection | Track, role: str, **kw) -> CardEvent:
        pos = det.center if isinstance(det, Detection) else (det.x, det.y)
        box = det.box() if isinstance(det, Detection) else det.box
        return CardEvent(type_, rank=det.rank, confidence=det.score, role=role, position=pos,
                         box=box, source="table", **kw)

    # ------------------------------------------------------------------

    def update(self, detections: list[Detection], frame_size: tuple[int, int]) -> list[CardEvent]:
        """Verarbeitet die Treffer eines stabilen Bildes. frame_size = (Breite, Höhe)."""
        dets = [(d, r) for d in detections if (r := self.role_of(d, frame_size)) is not None]

        if not dets:
            return self._end_round() if self.tracks else []

        events: list[CardEvent] = []
        matched_tracks: set[int] = set()
        unmatched: list[tuple[Detection, str]] = []

        # 1) Gleicher Rang an (fast) gleicher Stelle = dieselbe Karte
        for det, role in dets:
            cx, cy = det.center
            best, best_dist = None, self.tol
            for i, t in enumerate(self.tracks):
                if i in matched_tracks or t.rank != det.rank or t.role != role:
                    continue
                dist = math.hypot(t.x - cx, t.y - cy)
                if dist <= best_dist:
                    best, best_dist = i, dist
            if best is None:
                unmatched.append((det, role))
                continue
            matched_tracks.add(best)
            t = self.tracks[best]
            t.x, t.y, t.box = cx, cy, det.box()
            if not t.counted:
                if self._confident(det):
                    t.counted, t.score = True, det.score
                    events.append(self._event(EventType.NEW_CARD, det, role))
                else:
                    t.pending_frames += 1
                    t.score = max(t.score, det.score)
            else:
                t.score = max(t.score, det.score)

        missing = [i for i in range(len(self.tracks)) if i not in matched_tracks]

        # Mehrere Karten mit anderem Rang an bekannten Stellen → neue Runde, ohne dass wir den
        # leeren Tisch gesehen haben (Spiel räumt ab und teilt sofort neu aus). Innerhalb einer
        # Runde ändert sich höchstens einmal ein Rang (Korrektur einer Fehllesung).
        conflicts = [
            (det, role) for det, role in unmatched
            if self._confident(det) and any(
                self.tracks[i].counted and self.tracks[i].role == role
                and math.hypot(self.tracks[i].x - det.center[0], self.tracks[i].y - det.center[1])
                <= self.tol for i in missing)
        ]
        if len(conflicts) >= 2:
            events += self._end_round()
            return events + self.update(detections, frame_size)

        # 2) Verschiebung (Split): fehlender gezählter Track mit gleichem Rang und gleicher
        #    Rolle. Zuerst für ALLE Treffer prüfen, damit der frei gewordene Platz nicht
        #    fälschlich als Korrektur gilt.
        after_moves: list[tuple[Detection, str]] = []
        for det, role in unmatched:
            move = next((i for i in missing
                         if self.tracks[i].counted and self.tracks[i].rank == det.rank
                         and self.tracks[i].role == role), None)
            if move is None:
                after_moves.append((det, role))
                continue
            missing.remove(move)
            t = self.tracks[move]
            t.x, t.y, t.box = det.center[0], det.center[1], det.box()

        # 3) Anderer Rang an der Stelle eines fehlenden Tracks → Korrektur oder ignorieren
        still_unmatched: list[tuple[Detection, str]] = []
        for det, role in after_moves:
            cx, cy = det.center
            at_place = next((i for i in missing
                             if math.hypot(self.tracks[i].x - cx, self.tracks[i].y - cy) <= self.tol
                             and self.tracks[i].role == role), None)
            if at_place is None:
                still_unmatched.append((det, role))
                continue
            t = self.tracks[at_place]
            missing.remove(at_place)
            if self._confident(det) and det.score > t.score:
                old_rank, was_counted = t.rank, t.counted
                t.rank, t.score, t.counted, t.box = det.rank, det.score, True, det.box()
                if was_counted:
                    events.append(self._event(EventType.CORRECTION, det, role, old_rank=old_rank))
                else:
                    events.append(self._event(EventType.NEW_CARD, det, role))

        # Unsichere Tracks, die jetzt nicht mehr zu sehen sind, waren vorübergehend
        # (z. B. halb eingeblendete Karte während einer Animation) → verwerfen
        transient = {i for i in missing if not self.tracks[i].counted}
        if transient:
            self.tracks = [t for i, t in enumerate(self.tracks) if i not in transient]

        # 4) Neue Karten
        for det, role in still_unmatched:
            cx, cy = det.center
            confident = self._confident(det)
            self.tracks.append(Track(det.rank, cx, cy, role, det.score, counted=confident,
                                     box=det.box()))
            if confident:
                events.append(self._event(EventType.NEW_CARD, det, role))
            else:
                events.append(self._event(EventType.UNCERTAIN, det, role))
        return events

    def _end_round(self) -> list[CardEvent]:
        events: list[CardEvent] = []
        for t in self.tracks:
            if not t.counted:
                events.append(self._event(EventType.UNCERTAIN, t, t.role, final=True))
        uncertain_final = sum(1 for t in self.tracks if not t.counted)
        if uncertain_final:
            events.append(CardEvent(EventType.UNSEEN, count=uncertain_final, source="table",
                                    info={"reason": "unsicher"}))
        dealer_visible = sum(1 for t in self.tracks if t.role == "dealer")
        if self.dealer_hole_card and 0 < dealer_visible < 2:
            events.append(CardEvent(EventType.UNSEEN, count=2 - dealer_visible, role="dealer",
                                    source="table", info={"reason": "hole_card"}))
        events.append(CardEvent(EventType.ROUND_END, source="table",
                                info={"cards": len(self.tracks)}))
        self.tracks = []
        self.rounds += 1
        return events

    # ------------------------------------------------------------------
    # Handzustand für die Strategie
    # ------------------------------------------------------------------

    @property
    def has_pending(self) -> bool:
        return any(not t.counted for t in self.tracks)

    def dealer_cards(self) -> list[str]:
        return [t.rank for t in sorted(self.tracks, key=lambda t: t.x) if t.role == "dealer"]

    def _player_track_groups(self) -> list[list[Track]]:
        cards = sorted((t for t in self.tracks if t.role == "player"), key=lambda t: t.x)
        if not cards:
            return []
        width = cards[0].box[2] if cards[0].box else 20
        gap = self.hand_gap if self.hand_gap is not None else width * 4
        groups: list[list[Track]] = [[cards[0]]]
        for t in cards[1:]:
            if t.x - groups[-1][-1].x > gap:
                groups.append([t])
            else:
                groups[-1].append(t)
        return groups

    def player_hands(self) -> list[list[str]]:
        """Spielerkarten nach Händen gruppiert (grosse Lücke in x-Richtung = neue Hand)."""
        return [[t.rank for t in group] for group in self._player_track_groups()]

    def active_hand_index(self) -> int:
        """Die Hand, die zuletzt eine Karte bekommen hat (dort wird gerade gespielt)."""
        groups = self._player_track_groups()
        player_tracks = [t for t in self.tracks if t.role == "player"]
        if not player_tracks:
            return 0
        newest = player_tracks[-1]
        for i, group in enumerate(groups):
            if any(t is newest for t in group):
                return i
        return 0
