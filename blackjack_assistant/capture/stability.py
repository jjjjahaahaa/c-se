"""Stabilitätsprüfung: Ein Bild wird erst ausgewertet, wenn es sich eine Weile nicht
verändert hat (Standard 300 ms). So werden Karten während Animationen nicht gelesen.

Arbeitet nur mit numpy-Arrays und Zeitstempeln → ohne Bildschirm testbar.
"""

from __future__ import annotations

import cv2
import numpy as np


# Ab dieser Helligkeitsänderung (0–255) gilt ein Pixel als verändert
PIXEL_DELTA = 24


def _small_gray(frame: np.ndarray, size: int = 320) -> np.ndarray:
    """Verkleinertes Graustufenbild für einen schnellen, rauscharmen Vergleich."""
    gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    scale = size / max(h, w)
    if scale < 1:
        gray = cv2.resize(gray, (max(1, int(w * scale)), max(1, int(h * scale))),
                          interpolation=cv2.INTER_AREA)
    return gray.astype(np.int16)


class StabilityGate:
    """Meldet ein Bild genau einmal, sobald es `hold_ms` lang unverändert war.

    Ablauf: Für jedes neue Bild `feed(frame, t)` aufrufen. Rückgabe ist das Bild, wenn es
    gerade stabil geworden ist, sonst None. Ändert sich das Bild danach wieder, beginnt
    die Wartezeit von vorne.
    """

    def __init__(self, hold_ms: int = 300, threshold: float = 3):
        """threshold = so viele Pixel (im auf 320 px verkleinerten Bild) dürfen sich ändern,
        ohne dass das Bild als verändert gilt. Bewusst die ANZAHL geänderter Pixel und nicht
        die mittlere Differenz: Eine neue kleine Karte in einem grossen Bereich ändert den
        Mittelwert kaum, muss aber erkannt werden."""
        self.hold = hold_ms / 1000.0
        self.threshold = threshold
        self._last_small: np.ndarray | None = None
        self._last_change: float | None = None
        self._emitted = False

    def reset(self) -> None:
        self._last_small = None
        self._last_change = None
        self._emitted = False

    def difference(self, frame: np.ndarray) -> float:
        """Anzahl deutlich veränderter Pixel gegenüber dem vorherigen Bild (0 = identisch)."""
        if self._last_small is None:
            return float("inf")
        small = _small_gray(frame)
        if small.shape != self._last_small.shape:
            return float("inf")
        return float(np.count_nonzero(np.abs(small - self._last_small) > PIXEL_DELTA))

    def feed(self, frame: np.ndarray, timestamp: float) -> np.ndarray | None:
        diff = self.difference(frame)
        self._last_small = _small_gray(frame)
        if diff > self.threshold:
            # Bild hat sich verändert → Wartezeit neu starten
            self._last_change = timestamp
            self._emitted = False
            return None
        if self._last_change is None:
            self._last_change = timestamp
        if not self._emitted and timestamp - self._last_change >= self.hold:
            self._emitted = True
            return frame
        return None
