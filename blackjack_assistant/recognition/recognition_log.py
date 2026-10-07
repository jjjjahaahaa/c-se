"""Erkennungs-Log: Jede erkannte Karte mit kleinem Screenshot speichern.

Damit lässt sich bei externen Spielen (ohne Ground Truth) die Genauigkeit von Hand prüfen:
logs/recognition/<Datum_Zeit>/
    events.jsonl      eine Zeile pro Ereignis (Zeit, Typ, Rang, Konfidenz, Bilddatei)
    crops/0001_K.png  Ausschnitt der Kartenecke
    index.html        Übersicht aller Ausschnitte zum Durchklicken (unsichere gelb markiert)
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .events import CardEvent, EventType

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = PROJECT_ROOT / "logs" / "recognition"

LOGGED = {EventType.NEW_CARD, EventType.UNCERTAIN, EventType.CORRECTION}


class RecognitionLogger:
    def __init__(self, folder: Path | None = None, mode: str = "", save_images: bool = True):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.folder = Path(folder) if folder else DEFAULT_DIR / stamp
        self.crops = self.folder / "crops"
        self.crops.mkdir(parents=True, exist_ok=True)
        self.mode = mode
        self.save_images = save_images
        self.counter = 0
        self.events_file = self.folder / "events.jsonl"
        self._marker("session_start")

    def _marker(self, kind: str) -> None:
        record = {"time": datetime.now().isoformat(timespec="milliseconds"), "type": kind,
                  "mode": self.mode}
        with self.events_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def close(self) -> Path:
        """Sitzung beenden und index.html schreiben."""
        self._marker("session_end")
        return self.write_index()

    def log(self, event: CardEvent, frame: np.ndarray | None = None, timestamp: float | None = None,
            extra: dict | None = None) -> None:
        """Schreibt ein Ereignis; bei Karten zusätzlich einen Ausschnitt aus `frame`."""
        when = datetime.fromtimestamp(timestamp) if timestamp else datetime.now()
        record = {
            "time": when.isoformat(timespec="milliseconds"),
            "type": event.type.value,
            "rank": event.rank,
            "confidence": round(event.confidence, 4),
            "role": event.role,
            "source": event.source,
            "mode": self.mode,
            "final": event.final,
            "count": event.count,
            **({"old_rank": event.old_rank} if event.old_rank else {}),
            **(extra or {}),
        }
        if event.type in LOGGED and frame is not None and event.box and self.save_images:
            self.counter += 1
            name = f"{self.counter:04d}_{event.rank}.png"
            cv2.imwrite(str(self.crops / name), _corner_crop(frame, event.box))
            record["image"] = f"crops/{name}"
        with self.events_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def write_index(self) -> Path:
        """Erzeugt index.html mit allen Ausschnitten."""
        return write_index(self.folder)


def _corner_crop(frame: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    """Ausschnitt um das Rangzeichen, etwas grösser (inkl. Farbsymbol darunter)."""
    x, y, w, h = box
    x0, y0 = max(0, int(x - 0.4 * w)), max(0, int(y - 0.3 * h))
    x1, y1 = min(frame.shape[1], int(x + 1.4 * w)), min(frame.shape[0], int(y + 1.9 * h))
    crop = frame[y0:y1, x0:x1]
    # Auf eine gut sichtbare Grösse bringen
    scale = 64 / max(1, crop.shape[0])
    return cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)


def write_index(folder: Path) -> Path:
    folder = Path(folder)
    lines = []
    events_file = folder / "events.jsonl"
    if events_file.exists():
        lines = [json.loads(l) for l in events_file.read_text(encoding="utf-8").splitlines() if l]
    tiles = []
    for i, e in enumerate(lines, start=1):
        if e["type"] in ("session_start", "session_end"):
            continue
        if e["type"] not in ("new_card", "uncertain", "correction"):
            label = {"round_end": "Rundenende", "shuffle": "GEMISCHT",
                     "unseen": f"{e.get('count', 1)}× ungesehen"}
            tiles.append(f'<div class="sep">{html.escape(label.get(e["type"], e["type"]))}</div>')
            continue
        cls = "unsure" if e["type"] == "uncertain" else ("fix" if e["type"] == "correction" else "")
        img = f'<img src="{html.escape(e["image"])}">' if e.get("image") else ""
        text = f'{html.escape(str(e["rank"]))} · {e["confidence"]:.2f}'
        if e["type"] == "correction":
            text = f'{html.escape(str(e.get("old_rank")))}→{text}'
        tiles.append(f'<div class="tile {cls}" title="{html.escape(e["time"])}">{img}'
                     f'<span>{i}: {text}</span></div>')
    page = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<title>Erkennungs-Log</title><style>
body {{ font-family: system-ui, sans-serif; background: #222; color: #eee; }}
.grid {{ display: flex; flex-wrap: wrap; gap: 6px; }}
.tile {{ background: #333; padding: 4px; border-radius: 4px; text-align: center; font-size: 12px; }}
.tile img {{ display: block; height: 64px; margin: 0 auto 2px; image-rendering: pixelated; }}
.unsure {{ background: #8a6d00; }} .fix {{ background: #1d4f8a; }}
.sep {{ width: 100%; border-top: 1px solid #666; color: #aaa; font-size: 12px; padding-top: 2px; }}
</style></head><body>
<h1>Erkennungs-Log</h1>
<p>Gelb = unsicher (nicht gezählt), Blau = Korrektur. Bitte von Hand mit dem Spiel vergleichen.</p>
<div class="grid">{''.join(tiles)}</div></body></html>"""
    target = folder / "index.html"
    target.write_text(page, encoding="utf-8")
    return target
