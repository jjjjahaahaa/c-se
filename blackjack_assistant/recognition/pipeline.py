"""Erkennungs-Pipeline: Bild → Bereiche ausschneiden → Stabilitätsprüfung → Template
Matching → Tisch-/Verlaufs-Tracking → Ereignisse + aktueller Handzustand.

Die Pipeline arbeitet nur mit Bildern (numpy) und ist daher ohne Bildschirm testbar,
z. B. mit gespeicherten Screenshots oder einem Headless-Browser als Bildquelle.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..capture.sources import crop
from ..capture.stability import StabilityGate
from ..profiles import Profile
from .events import CardEvent, EventType
from .history_mode import HistoryReader
from .matcher import Detection, TemplateMatcher, estimate_scale
from .recognition_log import RecognitionLogger
from .table_mode import TableTracker
from .templates import TemplateSet

# Ab diesem Score gilt eine automatisch gefundene Skalierung als zuverlässig
AUTO_SCALE_MIN_QUALITY = 0.85


@dataclass
class RecognitionResult:
    """Ergebnis für ein Bild: Ereignisse für die Zählung und der aktuelle Tischzustand."""

    events: list[CardEvent] = field(default_factory=list)
    dealer: list[str] = field(default_factory=list)
    player_hands: list[list[str]] = field(default_factory=list)
    active_hand: int = 0
    uncertain: bool = False          # gerade unsichere Karte(n) im Bild
    evaluated: bool = False          # wurde in diesem Durchlauf ein stabiles Bild ausgewertet?


class Recognizer:
    """Verbindet alle Erkennungsschritte für ein Profil."""

    def __init__(self, profile: Profile, templates: TemplateSet | None = None,
                 logger: RecognitionLogger | None = None):
        self.profile = profile
        rec = profile.recognition
        self.templates = templates if templates is not None else TemplateSet.load(profile.templates_dir)
        if len(self.templates) == 0:
            raise ValueError(f"Profil '{profile.name}' hat keine Templates – zuerst kalibrieren")
        self.logger = logger
        self.mode = profile.read_mode
        self.scales = {"table": rec.table_scale, "history": rec.history_scale}
        self.matchers: dict[str, TemplateMatcher | None] = {"table": None, "history": None}
        self.gates = {
            "table": StabilityGate(rec.stable_ms, rec.stable_threshold),
            "history": StabilityGate(rec.stable_ms, rec.stable_threshold),
        }
        self.table = TableTracker(
            dealer_area=profile.areas["dealer"],
            player_area=profile.areas["player"],
            min_confidence=rec.min_confidence,
            min_margin=rec.uncertain_margin,
            dealer_hole_card=profile.dealer_hole_card,
        )
        self.history = HistoryReader(
            min_confidence=rec.min_confidence,
            min_margin=rec.uncertain_margin,
            uncertain_frames=rec.uncertain_frames,
        )
        self.last_detections: dict[str, list[Detection]] = {"table": [], "history": []}

    # ------------------------------------------------------------------

    def _matcher(self, region: str, image: np.ndarray) -> TemplateMatcher | None:
        """Matcher für einen Bereich. Ist keine Skalierung gesetzt, wird sie automatisch gesucht."""
        if self.matchers[region] is not None:
            return self.matchers[region]
        scale = self.scales[region]
        if scale is None:
            scale, quality = estimate_scale(image, self.templates)
            if quality < AUTO_SCALE_MIN_QUALITY:
                return None  # noch keine Karten sichtbar – später erneut versuchen
            self.scales[region] = scale
        rec = self.profile.recognition
        self.matchers[region] = TemplateMatcher(
            self.templates, scale=scale, min_candidate=rec.min_candidate,
            orientation_check=rec.orientation_check, card_brightness=rec.card_brightness,
        )
        return self.matchers[region]

    def detect(self, region: str, image: np.ndarray) -> list[Detection]:
        matcher = self._matcher(region, image)
        if matcher is None:
            return []
        dets = matcher.detect(image)
        self.last_detections[region] = dets
        return dets

    def process_regions(self, table_img: np.ndarray | None, history_img: np.ndarray | None,
                        timestamp: float) -> RecognitionResult:
        """Verarbeitet bereits ausgeschnittene Bereiche (für Tests und die Hauptschleife)."""
        result = RecognitionResult()

        if table_img is not None and table_img.size:
            stable = self.gates["table"].feed(table_img, timestamp)
            if stable is not None:
                result.evaluated = True
                h, w = stable.shape[:2]
                events = self.table.update(self.detect("table", stable), (w, h))
                for ev in events:
                    # Im Verlaufs-Modus zählt nur das Panel; vom Tisch kommen Rundenende
                    # und die nicht gezeigte Hole Card.
                    use = self.mode == "table" or ev.type == EventType.ROUND_END or (
                        ev.type == EventType.UNSEEN and ev.info.get("reason") == "hole_card")
                    if use:
                        result.events.append(ev)
                    self._log(ev, stable, timestamp, counted=use)

        if self.mode == "history" and history_img is not None and history_img.size:
            stable = self.gates["history"].feed(history_img, timestamp)
            if stable is not None:
                result.evaluated = True
                events = self.history.update(self.detect("history", stable))
                result.events.extend(events)
                for ev in events:
                    self._log(ev, stable, timestamp, counted=True)

        result.dealer = self.table.dealer_cards()
        result.player_hands = self.table.player_hands()
        result.active_hand = self.table.active_hand_index()
        result.uncertain = self.table.has_pending or (
            self.mode == "history" and self.history.pending_frames > 0)
        return result

    def process_frame(self, image: np.ndarray, timestamp: float,
                      origin: tuple[int, int] = (0, 0)) -> RecognitionResult:
        """Verarbeitet ein Bildschirmbild. origin = Bildschirmkoordinate der linken oberen Ecke."""
        ox, oy = origin

        def region_img(name: str) -> np.ndarray | None:
            region = self.profile.regions.get(name)
            if not region:
                return None
            x, y, w, h = region
            return crop(image, [x - ox, y - oy, w, h])

        return self.process_regions(region_img("table"), region_img("history"), timestamp)

    def _log(self, event: CardEvent, frame: np.ndarray, timestamp: float, counted: bool) -> None:
        if self.logger is not None:
            self.logger.log(event, frame, timestamp, extra={"counted": counted})

    def reset(self) -> None:
        """Count-Reset per Hotkey: Tracking vergessen (Templates/Skalierung bleiben)."""
        self.table.tracks = []
        self.history.reset()
        for gate in self.gates.values():
            gate.reset()
