"""Kartenerkennung mit OpenCV Template Matching auf der Kartenecke.

Ablauf pro Bild:
1. Graustufen, für jedes Rang-Template `cv2.matchTemplate` (normierte Kreuzkorrelation,
   unabhängig von Helligkeit und Kontrast → rote und schwarze Zeichen passen gleich gut).
2. Lokale Maxima über einer Mindestschwelle sind Kandidaten.
3. Non-Maximum-Suppression: Überlappen sich Kandidaten, gewinnt der beste. Der beste
   Kandidat eines ANDEREN Rangs an derselben Stelle wird als "zweitbester" gemerkt
   (kleiner Abstand = Verwechslungsgefahr, z. B. 6/8).
4. Orientierungsprüfung: Die Ecke unten rechts ist um 180° gedreht (eine 6 sieht dann
   wie eine 9 aus, eine 7 wie ein L). Bei einer echten Ecke oben links liegt UNTER dem
   Rang ein kompaktes Farbsymbol, das die Ränder des Prüfbands nicht berührt. Bei der
   gedrehten Ecke kommt darunter der Kartenrand und dahinter der Tisch, der bis an den
   Rand des Prüfbands reicht, und ÜBER dem Rang liegt das gedrehte Farbsymbol
   → wird verworfen. (Für Spiele mit senkrecht gestapelten Karten im Profil abschaltbar.)
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .templates import TemplateSet, ink_mask, to_gray


@dataclass
class Detection:
    """Ein erkannter Rang an einer Bildposition."""

    rank: str
    score: float                 # Übereinstimmung 0..1
    x: int
    y: int
    w: int
    h: int
    second_score: float = 0.0    # bester Treffer eines anderen Rangs an derselben Stelle

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2, self.y + self.h / 2)

    @property
    def margin(self) -> float:
        return self.score - self.second_score

    def is_confident(self, min_confidence: float, min_margin: float) -> bool:
        return self.score >= min_confidence and self.margin >= min_margin

    def box(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)


def iou(a: Detection, b: Detection) -> float:
    """Überlappung zweier Rechtecke (Intersection over Union)."""
    x0, y0 = max(a.x, b.x), max(a.y, b.y)
    x1, y1 = min(a.x + a.w, b.x + b.w), min(a.y + a.h, b.y + b.h)
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    union = a.w * a.h + b.w * b.h - inter
    return inter / union if union else 0.0


class TemplateMatcher:
    """Findet alle Kartenecken (Ränge) in einem Bild."""

    def __init__(
        self,
        templates: TemplateSet,
        scale: float = 1.0,
        min_candidate: float = 0.75,
        nms_iou: float = 0.25,
        orientation_check: bool = True,
        card_brightness: int | None = 170,
    ):
        """card_brightness: Karten sind hell. Gesucht wird nur in zusammenhängenden Flächen,
        die mindestens so hell sind (Graustufe 0–255) – das spart viel Rechenzeit.
        None = ganzes Bild durchsuchen (z. B. für Spiele mit dunklen Karten)."""
        if len(templates) == 0:
            raise ValueError("Keine Templates vorhanden – zuerst kalibrieren oder generieren")
        self.base_templates = templates
        self.scale = scale
        self.templates = templates.scaled(scale)
        self.min_candidate = min_candidate
        self.nms_iou = nms_iou
        self.orientation_check = orientation_check
        self.card_brightness = card_brightness
        tw, th = self.templates.typical_size
        self.min_roi = (max(4, int(tw * 0.8)), max(4, int(th * 0.8)))

    # ------------------------------------------------------------------

    def card_regions(self, gray: np.ndarray) -> list[tuple[int, int, int, int]]:
        """Helle, zusammenhängende Flächen, die gross genug für eine Kartenecke sind."""
        if self.card_brightness is None:
            return [(0, 0, gray.shape[1], gray.shape[0])]
        mask = (gray >= self.card_brightness).astype(np.uint8)
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        rects = []
        for x, y, w, h, _area in stats[1:]:
            if w >= self.min_roi[0] and h >= self.min_roi[1]:
                rects.append([x - 2, y - 2, x + w + 2, y + h + 2])
        # Überlappende Bereiche zusammenfassen
        merged = True
        while merged:
            merged = False
            for i in range(len(rects)):
                for j in range(i + 1, len(rects)):
                    a, b = rects[i], rects[j]
                    if a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]:
                        rects[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                        del rects[j]
                        merged = True
                        break
                if merged:
                    break
        h_img, w_img = gray.shape
        return [(max(0, x0), max(0, y0), min(w_img, x1) - max(0, x0), min(h_img, y1) - max(0, y0))
                for x0, y0, x1, y1 in rects]

    def _candidates(self, gray: np.ndarray, threshold: float) -> list[Detection]:
        found: list[Detection] = []
        for rx, ry, rw, rh in self.card_regions(gray):
            for d in self._candidates_in(gray[ry:ry + rh, rx:rx + rw], threshold):
                d.x += rx
                d.y += ry
                found.append(d)
        return found

    def _candidates_in(self, gray: np.ndarray, threshold: float) -> list[Detection]:
        found: list[Detection] = []
        for rank, tpl in self.templates.items():
            th, tw = tpl.shape
            if th > gray.shape[0] or tw > gray.shape[1]:
                continue
            # Einfarbige Templates (z. B. leer) würden NaN liefern
            if float(tpl.std()) < 1.0:
                continue
            res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
            res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)
            # Lokale Maxima: Wert = Maximum der Umgebung
            k = max(3, (min(tw, th) // 2) | 1)
            local_max = cv2.dilate(res, np.ones((k, k), np.uint8))
            ys, xs = np.nonzero((res >= threshold) & (res >= local_max - 1e-6))
            for y, x in zip(ys, xs):
                found.append(Detection(rank, float(res[y, x]), int(x), int(y), tw, th))
        return found

    def _nms(self, candidates: list[Detection]) -> list[Detection]:
        candidates.sort(key=lambda d: d.score, reverse=True)
        kept: list[Detection] = []
        for cand in candidates:
            overlapping = [k for k in kept if iou(k, cand) > self.nms_iou]
            if not overlapping:
                kept.append(cand)
                continue
            for k in overlapping:
                if k.rank != cand.rank and cand.score > k.second_score:
                    k.second_score = cand.score
        return kept

    @staticmethod
    def _first_ink_is_compact(band: np.ndarray, from_top: bool) -> bool | None:
        """Liegt die erste Tinte im Band (von oben bzw. unten gelesen) mittig, ohne die
        Ränder zu berühren? None = keine Tinte im Band."""
        rows = np.nonzero(band.any(axis=1))[0]
        if len(rows) == 0 or band.mean() < 0.02:
            return None
        if from_top:
            first = band[rows[0]:rows[0] + 3]
        else:
            first = band[max(0, rows[-1] - 2):rows[-1] + 1]
        return not (first[:, :2].any() or first[:, -2:].any())

    def orientation_ok(self, gray: np.ndarray, det: Detection) -> bool:
        """Orientierungsprüfung (siehe Moduldokumentation): unter dem Rang muss ein kompaktes
        Farbsymbol liegen, über dem Rang darf keines liegen."""
        # Band etwas breiter als das Template: Ein Farbsymbol liegt mittig und berührt keinen
        # der beiden Ränder. Der Tisch hinter einer Kartenkante oder eine abgerundete
        # Kartenecke berührt dagegen mindestens einen Rand.
        cx = det.x + det.w / 2
        x0 = max(0, int(round(cx - 0.6 * det.w)))
        x1 = min(gray.shape[1], int(round(cx + 0.6 * det.w)))
        if x1 - x0 < 4:
            return True
        box = gray[det.y:det.y + det.h, det.x:det.x + det.w]
        white = float(np.percentile(box, 95))

        # Unten: Farbsymbol erwartet
        y0 = int(round(det.y + det.h + 0.02 * det.h))
        y1 = min(gray.shape[0], int(round(det.y + det.h + 0.6 * det.h)))
        if y1 - y0 >= 0.25 * det.h:  # sonst am Bildrand: keine Aussage möglich
            below = self._first_ink_is_compact(ink_mask(gray[y0:y1, x0:x1], white=white), True)
            if not below:
                return False

        # Oben: Bei der gedrehten Ecke liegt das (gedrehte) Farbsymbol über dem Rang
        y1 = int(round(det.y - 0.02 * det.h))
        y0 = max(0, int(round(det.y - 0.6 * det.h)))
        if y1 - y0 >= 0.25 * det.h:
            above_band = ink_mask(gray[y0:y1, x0:x1], white=white)
            above = self._first_ink_is_compact(above_band, from_top=False)
            ink_rows = int(above_band.any(axis=1).sum())
            if above and ink_rows >= 0.2 * det.h:
                return False
        return True

    def detect(self, image: np.ndarray, threshold: float | None = None) -> list[Detection]:
        """Alle Ränge im Bild, sortiert nach Position (oben links zuerst)."""
        gray = to_gray(image)
        candidates = self._candidates(gray, self.min_candidate if threshold is None else threshold)
        kept = self._nms(candidates)
        if self.orientation_check:
            kept = [d for d in kept if self.orientation_ok(gray, d)]
        kept.sort(key=lambda d: (d.y, d.x))
        return kept


def estimate_scale(
    image: np.ndarray,
    templates: TemplateSet,
    scales: np.ndarray | list[float] | None = None,
    top_n: int = 3,
) -> tuple[float, float]:
    """Sucht die Template-Skalierung, bei der die Ränge im Bild am besten passen.

    Nützlich bei Browser-Zoom oder Windows-Skalierung (125 %, 150 %). Rückgabe:
    (beste Skalierung, mittlerer Score der besten Treffer). Für ein sinnvolles Ergebnis
    sollten mindestens zwei, drei Karten sichtbar sein.
    """
    if scales is None:
        scales = np.round(np.arange(0.5, 2.51, 0.05), 3)
    gray = to_gray(image)

    def quality(s: float) -> float:
        matcher = TemplateMatcher(templates, scale=float(s), min_candidate=0.4,
                                  orientation_check=False)
        dets = matcher.detect(gray)
        if not dets:
            return 0.0
        best = sorted((d.score for d in dets), reverse=True)[:top_n]
        return float(np.mean(best))

    results = [(float(s), quality(float(s))) for s in scales]
    best_scale, best_quality = max(results, key=lambda r: r[1])
    # Feinsuche um den besten Wert
    step = (scales[1] - scales[0]) if len(scales) > 1 else 0.05
    fine = np.round(np.arange(best_scale - step, best_scale + step + 1e-9, step / 5), 3)
    fine = [s for s in fine if s > 0.1]
    results = [(float(s), quality(float(s))) for s in fine] + [(best_scale, best_quality)]
    return max(results, key=lambda r: r[1])
