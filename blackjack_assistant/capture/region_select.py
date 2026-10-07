"""Bildschirmbereich per Maus aufziehen (halbtransparentes Vollbild-Fenster mit tkinter).

Die Rechteck-Logik steckt in `RectangleDrag` und ist ohne Bildschirm testbar.
Das Fenster selbst (`select_region`) braucht ein Display (siehe LOCAL_TESTS.md).
"""

from __future__ import annotations

import sys


def make_dpi_aware() -> None:
    """Windows: Prozess DPI-aware machen, damit tkinter- und mss-Koordinaten übereinstimmen.

    Ohne diesen Aufruf skaliert Windows bei 125 %/150 % Anzeige die Koordinaten von tkinter,
    mss liefert aber echte Pixel – der ausgewählte Bereich wäre dann verschoben.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # pro Monitor DPI-aware
    except Exception:  # noqa: BLE001 – ältere Windows-Versionen
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


class RectangleDrag:
    """Merkt sich Start- und Endpunkt eines Maus-Zugs und liefert [x, y, b, h]."""

    MIN_SIZE = 5  # kleinere Rechtecke gelten als versehentlicher Klick

    def __init__(self):
        self.start: tuple[int, int] | None = None
        self.end: tuple[int, int] | None = None

    def press(self, x: int, y: int) -> None:
        self.start = (x, y)
        self.end = (x, y)

    def drag(self, x: int, y: int) -> None:
        if self.start is not None:
            self.end = (x, y)

    def release(self, x: int, y: int) -> list[int] | None:
        self.drag(x, y)
        return self.rect()

    def rect(self) -> list[int] | None:
        if self.start is None or self.end is None:
            return None
        (x0, y0), (x1, y1) = self.start, self.end
        x, y = min(x0, x1), min(y0, y1)
        w, h = abs(x1 - x0), abs(y1 - y0)
        if w < self.MIN_SIZE or h < self.MIN_SIZE:
            return None
        return [x, y, w, h]


def virtual_screen() -> list[int]:
    """Gesamter Bildschirmbereich über alle Monitore [x, y, b, h]."""
    from .screen import open_mss

    with open_mss() as sct:
        mon = sct.monitors[0]
        return [mon["left"], mon["top"], mon["width"], mon["height"]]


def select_region(prompt: str = "Bereich mit der Maus aufziehen – Esc bricht ab",
                  on_ready=None) -> list[int] | None:
    """Zeigt ein halbtransparentes Fenster über allen Monitoren. Rückgabe: Bereich in
    Bildschirmpixeln oder None bei Abbruch.

    on_ready(root, canvas): wird aufgerufen, sobald das Fenster steht (für automatische Tests,
    die Mausereignisse erzeugen)."""
    import tkinter as tk

    make_dpi_aware()
    vx, vy, vw, vh = virtual_screen()

    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry(f"{vw}x{vh}+{vx}+{vy}")
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", 0.35)
    except tk.TclError:
        pass  # manche Linux-Fenstermanager unterstützen keine Transparenz
    root.configure(bg="black", cursor="crosshair")

    canvas = tk.Canvas(root, bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_text(vw // 2, 40, text=prompt, fill="white", font=("Arial", 20, "bold"))

    drag = RectangleDrag()
    result: dict[str, list[int] | None] = {"rect": None}
    shape = {"id": None}

    def on_press(e):
        drag.press(e.x_root, e.y_root)

    def on_drag(e):
        drag.drag(e.x_root, e.y_root)
        if shape["id"] is not None:
            canvas.delete(shape["id"])
        (x0, y0), (x1, y1) = drag.start, drag.end
        shape["id"] = canvas.create_rectangle(x0 - vx, y0 - vy, x1 - vx, y1 - vy,
                                              outline="#ffd700", width=3)

    def on_release(e):
        result["rect"] = drag.release(e.x_root, e.y_root)
        if result["rect"] is not None:
            root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", lambda e: root.destroy())
    root.focus_force()
    if on_ready is not None:
        root.after(200, lambda: on_ready(root, canvas))
    root.mainloop()
    return result["rect"]
