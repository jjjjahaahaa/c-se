"""Bildquellen. Die Erkennung bekommt Bilder immer über eine Quelle – egal ob echter
Bildschirm (screen.py), gespeicherte Screenshots (für Tests) oder ein Headless-Browser.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol

import cv2
import numpy as np


@dataclass
class Frame:
    """Ein aufgenommenes Bild mit Zeitstempel (Sekunden)."""

    image: np.ndarray          # BGR, wie OpenCV es erwartet
    timestamp: float


class FrameSource(Protocol):
    """Gemeinsame Schnittstelle aller Bildquellen."""

    def grab(self) -> Frame | None:
        """Nächstes Bild oder None, wenn die Quelle erschöpft ist."""
        ...


def crop(image: np.ndarray, region: list[int] | tuple[int, int, int, int]) -> np.ndarray:
    """Ausschnitt [x, y, b, h] aus einem Bild (auf die Bildgrenzen beschnitten)."""
    x, y, w, h = (int(v) for v in region)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(image.shape[1], x + w), min(image.shape[0], y + h)
    return image[y0:y1, x0:x1]


class ImageSequenceSource:
    """Spielt gespeicherte Screenshots ab (z. B. aus tools/record_mock_session.py).

    Erwartet einen Ordner mit PNG-Dateien und optional einer frames.jsonl mit
    {"file": "...", "t": Zeitstempel}. Ohne frames.jsonl wird ein fester Abstand angenommen.
    """

    def __init__(self, folder: Path, interval: float = 0.1):
        self.folder = Path(folder)
        index = self.folder / "frames.jsonl"
        if index.exists():
            entries = [json.loads(l) for l in index.read_text(encoding="utf-8").splitlines() if l]
            self.items = [(self.folder / e["file"], float(e["t"])) for e in entries]
        else:
            files = sorted(self.folder.glob("*.png"))
            self.items = [(f, i * interval) for i, f in enumerate(files)]
        self._pos = 0

    def __len__(self) -> int:
        return len(self.items)

    def grab(self) -> Frame | None:
        if self._pos >= len(self.items):
            return None
        path, t = self.items[self._pos]
        self._pos += 1
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise OSError(f"Bild nicht lesbar: {path}")
        return Frame(image, t)

    def __iter__(self) -> Iterator[Frame]:
        while (frame := self.grab()) is not None:
            yield frame


class StaticImageSource:
    """Liefert immer dasselbe Bild mit fortlaufender Zeit (für einfache Tests)."""

    def __init__(self, image: np.ndarray, step: float = 0.1, count: int | None = None):
        self.image = image
        self.step = step
        self.count = count
        self._t = 0.0
        self._n = 0

    def grab(self) -> Frame | None:
        if self.count is not None and self._n >= self.count:
            return None
        self._n += 1
        self._t += self.step
        return Frame(self.image, self._t)


class PlaywrightPageSource:
    """Screenshots einer Playwright-Seite (Headless-Browser) als Bildquelle.

    Damit lässt sich die ganze Erkennung ohne Bildschirm gegen das Mock-Casino testen.
    """

    def __init__(self, page):
        self.page = page
        # Chromium: Screenshot direkt über das DevTools-Protokoll ist etwa 4× schneller
        # als page.screenshot() (ca. 55 ms statt 210 ms) → mehr Bilder pro Sekunde.
        try:
            self._cdp = page.context.new_cdp_session(page)
        except Exception:  # noqa: BLE001 – anderer Browser: normaler Weg
            self._cdp = None

    def grab(self) -> Frame | None:
        if self._cdp is not None:
            data = self._cdp.send("Page.captureScreenshot",
                                  {"format": "png", "optimizeForSpeed": True})
            png = base64.b64decode(data["data"])
        else:
            png = self.page.screenshot(type="png")
        t = time.time()
        image = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        return Frame(image, t)
