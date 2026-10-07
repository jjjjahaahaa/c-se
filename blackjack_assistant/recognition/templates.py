"""Rang-Templates laden, speichern und vorbereiten.

Ein Template ist ein kleines Graustufenbild des Rangzeichens aus der linken oberen
Kartenecke (ohne Farbsymbol, denn es wird nur der Rang gebraucht). Pro Rang darf es
mehrere Templates geben (z. B. schwarz und rot oder zwei Kalibrierungen).

Dateinamen: <Rang>_<Zusatz>.png, z. B. "K_black.png", "Q_1.png". Beim Laden werden
auch B/D (Bube/Dame) akzeptiert und auf J/Q abgebildet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from ..models import RANKS, normalize_rank


def to_gray(image: np.ndarray) -> np.ndarray:
    """BGR/BGRA → Graustufen (Graustufenbilder werden unverändert zurückgegeben)."""
    if image.ndim == 2:
        return image
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def ink_mask(gray: np.ndarray, white: float | None = None, ratio: float = 0.6) -> np.ndarray:
    """Maske der "Tinte": Pixel, die deutlich dunkler als das Kartenweiss sind.

    Rote Zeichen sind in Graustufen ebenfalls dunkel genug (Herz-Rot ≈ 75 von 255).
    """
    if white is None:
        white = float(np.percentile(gray, 95))
    return gray < white * ratio


def tight_crop(gray: np.ndarray, pad: int = 2) -> np.ndarray:
    """Schneidet ein Template eng um das Rangzeichen zu (plus kleiner weisser Rand).

    So passen auch grob markierte Kalibrier-Ausschnitte zusammen.
    """
    mask = ink_mask(gray)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return gray
    y0, y1 = max(0, ys.min() - pad), min(gray.shape[0], ys.max() + pad + 1)
    x0, x1 = max(0, xs.min() - pad), min(gray.shape[1], xs.max() + pad + 1)
    return gray[y0:y1, x0:x1]


@dataclass
class TemplateSet:
    """Alle Templates eines Profils: Rang → Liste von Graustufenbildern."""

    templates: dict[str, list[np.ndarray]] = field(default_factory=dict)

    def add(self, rank_label: str, image: np.ndarray) -> str:
        rank = normalize_rank(rank_label)
        self.templates.setdefault(rank, []).append(to_gray(image))
        return rank

    @property
    def ranks(self) -> list[str]:
        return [r for r in RANKS if r in self.templates]

    def missing_ranks(self) -> list[str]:
        return [r for r in RANKS if r not in self.templates]

    def items(self):
        """(Rang, Template) für alle Templates."""
        for rank in self.ranks:
            for tpl in self.templates[rank]:
                yield rank, tpl

    def __len__(self) -> int:
        return sum(len(v) for v in self.templates.values())

    @property
    def typical_size(self) -> tuple[int, int]:
        """Median von (Breite, Höhe) aller Templates."""
        sizes = [(t.shape[1], t.shape[0]) for _, t in self.items()]
        if not sizes:
            return (0, 0)
        ws, hs = zip(*sizes)
        return int(np.median(ws)), int(np.median(hs))

    # ------------------------------------------------------------------

    @classmethod
    def load(cls, folder: Path) -> "TemplateSet":
        folder = Path(folder)
        result = cls()
        if not folder.exists():
            return result
        for path in sorted(folder.glob("*.png")):
            label = path.stem.split("_")[0]
            try:
                rank = normalize_rank(label)
            except ValueError:
                continue  # fremde Dateien ignorieren
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if image is not None:
                result.templates.setdefault(rank, []).append(image)
        return result

    def save(self, folder: Path) -> list[Path]:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        written = []
        for rank in self.ranks:
            for i, tpl in enumerate(self.templates[rank], start=1):
                path = folder / f"{rank}_{i}.png"
                cv2.imwrite(str(path), tpl)
                written.append(path)
        return written

    def scaled(self, scale: float) -> "TemplateSet":
        """Kopie mit skalierten Templates (Browser-Zoom, andere Bildschirmauflösung)."""
        if abs(scale - 1.0) < 1e-6:
            return self
        out = TemplateSet()
        interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
        for rank, tpl in self.items():
            w = max(4, round(tpl.shape[1] * scale))
            h = max(4, round(tpl.shape[0] * scale))
            out.templates.setdefault(rank, []).append(cv2.resize(tpl, (w, h), interpolation=interp))
        return out
