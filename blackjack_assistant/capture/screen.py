"""Bildschirmaufnahme mit mss. Braucht einen Bildschirm (lokal testen, siehe LOCAL_TESTS.md)."""

from __future__ import annotations

import time

import numpy as np

from .sources import Frame


def open_mss():
    """mss-Objekt öffnen (neuere Versionen heissen mss.MSS, ältere mss.mss)."""
    import mss  # erst hier importieren: braucht ein Display

    factory = getattr(mss, "MSS", None) or mss.mss
    return factory()


class ScreenSource:
    """Nimmt den ganzen Bildschirm (alle Monitore zusammen) oder einen Bereich auf.

    Es wird bewusst der gesamte benötigte Bereich in einem Bild aufgenommen; Tisch und
    Verlaufs-Panel werden danach mit `crop()` ausgeschnitten.
    """

    def __init__(self, region: list[int] | None = None):
        self._mss = open_mss()
        if region is None:
            mon = self._mss.monitors[0]  # virtueller Bildschirm über alle Monitore
            region = [mon["left"], mon["top"], mon["width"], mon["height"]]
        self.region = region

    @property
    def origin(self) -> tuple[int, int]:
        """Bildschirmkoordinate der linken oberen Ecke des aufgenommenen Bildes."""
        return self.region[0], self.region[1]

    def grab(self) -> Frame:
        x, y, w, h = self.region
        shot = self._mss.grab({"left": x, "top": y, "width": w, "height": h})
        # mss liefert BGRA → BGR für OpenCV
        image = np.asarray(shot)[:, :, :3].copy()
        return Frame(image, time.time())

    def close(self) -> None:
        self._mss.close()


def bounding_region(regions: list[list[int]]) -> list[int]:
    """Kleinstes Rechteck, das alle Bereiche enthält (so reicht eine Aufnahme pro Durchlauf)."""
    xs = [r[0] for r in regions] + [r[0] + r[2] for r in regions]
    ys = [r[1] for r in regions] + [r[1] + r[3] for r in regions]
    return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]
