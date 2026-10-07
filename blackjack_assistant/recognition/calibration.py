"""Kalibrierung für externe Spiele: pro Rang eine Kartenecke markieren → Template speichern.

Ablauf: Screenshot aufnehmen, für jeden Rang (2–10, B/J, D/Q, K, A) mit der Maus ein
Rechteck um das Rangzeichen einer Karte ziehen und den Rang eintippen. Akzeptiert werden
beide Beschriftungen: J/Q/K (englisch) und B/D/K (deutsch). Gespeichert wird immer
kanonisch als J/Q/K.

Die Logik (`CalibrationSession`) ist ohne Bildschirm testbar; das Fenster (`run_calibration_window`)
braucht ein Display.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ..models import RANKS, normalize_rank
from .templates import TemplateSet, tight_crop, to_gray

# Anzeigename für die Benutzerführung
RANK_PROMPT = {
    "J": "Bube (J oder B)",
    "Q": "Dame (Q oder D)",
    "K": "König (K)",
    "A": "Ass (A)",
}


def rank_prompt(rank: str) -> str:
    return RANK_PROMPT.get(rank, rank)


class CalibrationSession:
    """Sammelt markierte Rang-Ausschnitte und speichert sie als Templates eines Profils."""

    def __init__(self, templates_dir: Path, keep_existing: bool = False):
        self.templates_dir = Path(templates_dir)
        self.templates = TemplateSet.load(self.templates_dir) if keep_existing else TemplateSet()

    def add(self, label: str, image: np.ndarray, rect: list[int] | tuple[int, int, int, int]) -> str:
        """Schneidet den markierten Bereich aus und speichert ihn unter dem Rang `label`.

        label: "2".."10", "J"/"B"/"Bube", "Q"/"D"/"Dame", "K", "A" … (Gross-/Kleinschreibung egal)
        rect:  [x, y, b, h] im Bild
        Rückgabe: kanonischer Rang.
        """
        rank = normalize_rank(label)
        x, y, w, h = (int(v) for v in rect)
        if w < 4 or h < 4:
            raise ValueError("Markierter Bereich ist zu klein")
        crop = to_gray(image)[max(0, y):y + h, max(0, x):x + w]
        if crop.size == 0:
            raise ValueError("Markierter Bereich liegt ausserhalb des Bildes")
        tpl = tight_crop(crop)
        if float(tpl.std()) < 5:
            raise ValueError("Im markierten Bereich ist kein Zeichen zu erkennen")
        self.templates.add(rank, tpl)
        return rank

    def missing_ranks(self) -> list[str]:
        return self.templates.missing_ranks()

    def next_rank(self) -> str | None:
        missing = self.missing_ranks()
        return missing[0] if missing else None

    @property
    def complete(self) -> bool:
        return not self.missing_ranks()

    def save(self) -> list[Path]:
        if self.templates_dir.exists():
            for old in self.templates_dir.glob("*.png"):
                old.unlink()
        return self.templates.save(self.templates_dir)


def run_calibration_window(image: np.ndarray, session: CalibrationSession, on_ready=None) -> bool:
    """Fenster zur Kalibrierung. Zeigt den Screenshot; der Benutzer zieht ein Rechteck um ein
    Rangzeichen und bestätigt den vorgeschlagenen Rang mit Enter (oder tippt einen anderen,
    z. B. B oder D). Rückgabe: True, wenn gespeichert wurde. Braucht ein Display.
    """
    import tkinter as tk
    from tkinter import messagebox

    from ..capture.region_select import RectangleDrag

    import base64

    root = tk.Tk()
    root.title("Kalibrierung – Rangzeichen markieren")
    h, w = image.shape[:2]
    # tkinter (Tk 8.6) kann PNG als base64-Text direkt als PhotoImage laden
    ok, png = cv2.imencode(".png", image)
    photo = tk.PhotoImage(data=base64.b64encode(png.tobytes()).decode("ascii"))

    canvas = tk.Canvas(root, width=min(w, 1600), height=min(h, 900), cursor="crosshair")
    canvas.create_image(0, 0, anchor="nw", image=photo)
    canvas.configure(scrollregion=(0, 0, w, h))
    canvas.pack(fill="both", expand=True)

    bar = tk.Frame(root)
    bar.pack(fill="x")
    info = tk.Label(bar, font=("Arial", 12))
    info.pack(side="left", padx=8)
    entry = tk.Entry(bar, width=6, font=("Arial", 14))
    entry.pack(side="left")
    status = tk.Label(bar, fg="#555")
    status.pack(side="left", padx=8)

    drag = RectangleDrag()
    state = {"rect": None, "shape": None, "saved": False}

    def refresh():
        nxt = session.next_rank()
        missing = ", ".join(session.missing_ranks()) or "keine"
        if nxt:
            info.config(text=f"Markiere: {rank_prompt(nxt)} – dann Enter")
            entry.delete(0, "end")
            entry.insert(0, nxt)
        else:
            info.config(text="Alle Ränge markiert – 's' speichert, weitere Markierungen möglich")
        status.config(text=f"Fehlt noch: {missing}")

    def canvas_xy(e):
        return int(canvas.canvasx(e.x)), int(canvas.canvasy(e.y))

    def on_press(e):
        drag.press(*canvas_xy(e))

    def on_drag(e):
        drag.drag(*canvas_xy(e))
        if state["shape"]:
            canvas.delete(state["shape"])
        (x0, y0), (x1, y1) = drag.start, drag.end
        state["shape"] = canvas.create_rectangle(x0, y0, x1, y1, outline="#ff0", width=2)

    def on_release(e):
        state["rect"] = drag.release(*canvas_xy(e))
        entry.focus_set()

    def on_enter(_e=None):
        if not state["rect"]:
            status.config(text="Zuerst ein Rechteck aufziehen")
            return
        try:
            rank = session.add(entry.get(), image, state["rect"])
            status.config(text=f"Gespeichert als {rank}")
        except ValueError as err:
            messagebox.showerror("Kalibrierung", str(err))
            return
        state["rect"] = None
        refresh()

    def on_save(_e=None):
        if not session.complete and not messagebox.askyesno(
            "Kalibrierung", "Es fehlen noch Ränge. Trotzdem speichern?"
        ):
            return
        session.save()
        state["saved"] = True
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    entry.bind("<Return>", on_enter)
    root.bind("<Control-s>", on_save)
    tk.Button(bar, text="Übernehmen (Enter)", command=on_enter).pack(side="left", padx=4)
    tk.Button(bar, text="Speichern", command=on_save).pack(side="right", padx=8)
    refresh()
    if on_ready is not None:  # für automatische Tests
        root.after(200, lambda: on_ready(root, canvas, entry))
    root.mainloop()
    return state["saved"]


def missing_for_display(templates: TemplateSet) -> list[str]:
    """Fehlende Ränge mit deutschem Namen (für Konsolenausgaben)."""
    return [rank_prompt(r) for r in RANKS if r in templates.missing_ranks()]
