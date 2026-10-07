"""Overlay-Fenster mit tkinter: klein, immer im Vordergrund, verschiebbar.

Zeigt Running Count, True Count, Restdecks, Einsatz, Spielzug, aktives Profil und Warnungen.
Neue Zustände kommen aus der Queue des Worker-Threads (tkinter darf nur im Hauptthread
verändert werden, deshalb wird die Queue alle 100 ms abgefragt).
"""

from __future__ import annotations

import queue
import tkinter as tk
from typing import Callable

from ..app import OverlayState, format_state, warnings
from .hotkeys import DEFAULT_KEYS, tk_sequence

BG = "#101820"
FG = "#f2f2f2"
MUTED = "#8fa3b0"
ACCENT = "#e3c15b"
COLORS = {"yellow": ("#ffd84d", "#3a3000"), "red": ("#ff6b6b", "#3a0d0d")}
ACTION_COLORS = {
    "ZIEHEN": "#6ec1ff", "STEHEN": "#7ee08a", "VERDOPPELN": "#ffb84d",
    "TEILEN": "#d59cff", "AUFGEBEN": "#ff8a8a",
}


class OverlayWindow:
    def __init__(self, worker, actions: dict[str, Callable[[], None]], hotkey_text: str = "",
                 alpha: float = 0.92, poll_ms: int = 100):
        self.worker = worker
        self.actions = actions
        self.poll_ms = poll_ms
        self.root = tk.Tk()
        self.root.title("Blackjack-Assistent")
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", alpha)
        except tk.TclError:
            pass
        self.root.resizable(False, False)
        self.vars: dict[str, tk.StringVar] = {}
        self._build(hotkey_text)
        # Dieselben Tasten auch im Fenster (falls globale Hotkeys nicht gehen)
        for name, key in DEFAULT_KEYS.items():
            if name in actions:
                self.root.bind(tk_sequence(key), lambda e, fn=actions[name]: fn())
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.last_state: OverlayState | None = None

    # ------------------------------------------------------------------

    def _var(self, name: str) -> tk.StringVar:
        self.vars[name] = tk.StringVar(value="–")
        return self.vars[name]

    def _build(self, hotkey_text: str) -> None:
        pad = {"padx": 10}
        tk.Label(self.root, textvariable=self._var("profile"), bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(8, 0), **pad)

        grid = tk.Frame(self.root, bg=BG)
        grid.pack(fill="x", pady=4, **pad)
        cells = [("Running Count", "rc"), ("True Count", "tc"), ("Decks übrig", "decks"),
                 ("Einsatz", "bet")]
        for col, (label, key) in enumerate(cells):
            tk.Label(grid, text=label, bg=BG, fg=MUTED, font=("Segoe UI", 8)).grid(
                row=0, column=col, sticky="w", padx=(0, 14))
            tk.Label(grid, textvariable=self._var(key), bg=BG, fg=FG,
                     font=("Segoe UI", 16, "bold")).grid(row=1, column=col, sticky="w", padx=(0, 14))

        tk.Label(self.root, textvariable=self._var("hand"), bg=BG, fg=MUTED,
                 font=("Segoe UI", 10)).pack(anchor="w", **pad)
        self.action_label = tk.Label(self.root, textvariable=self._var("action"), bg=BG, fg=ACCENT,
                                     font=("Segoe UI", 22, "bold"))
        self.action_label.pack(anchor="w", **pad)
        tk.Label(self.root, textvariable=self._var("detail"), bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", **pad)
        tk.Label(self.root, textvariable=self._var("probabilities"), bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", **pad)
        tk.Label(self.root, textvariable=self._var("insurance"), bg=BG, fg=ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", **pad)

        self.warning_frame = tk.Frame(self.root, bg=BG)
        self.warning_frame.pack(fill="x", pady=(4, 0), **pad)
        tk.Label(self.root, text=hotkey_text, bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(
            anchor="w", pady=(4, 8), **pad)

        # Fenster mit der Maus verschieben
        self.root.bind("<ButtonPress-1>", self._start_move)
        self.root.bind("<B1-Motion>", self._move)

    def _start_move(self, event) -> None:
        self._drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _move(self, event) -> None:
        dx, dy = self._drag
        self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    # ------------------------------------------------------------------

    def show(self, state: OverlayState) -> None:
        """Zustand anzeigen (auch direkt aus Tests aufrufbar)."""
        self.last_state = state
        texts = format_state(state)
        for key, var in self.vars.items():
            var.set(texts.get(key, ""))
        self.action_label.configure(fg=ACTION_COLORS.get(texts["action"], ACCENT))
        for child in self.warning_frame.winfo_children():
            child.destroy()
        for level, text in warnings(state):
            fg, bg = COLORS[level]
            tk.Label(self.warning_frame, text="⚠ " + text, bg=bg, fg=fg,
                     font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x", pady=1)

    def warning_texts(self) -> list[str]:
        return [c.cget("text") for c in self.warning_frame.winfo_children()]

    def poll(self) -> None:
        """Queue abfragen und sich selbst nach poll_ms erneut einplanen."""
        self.drain()
        self.root.after(self.poll_ms, self.poll)

    def drain(self) -> None:
        """Neuesten Zustand aus der Queue des Workers anzeigen (ältere werden übersprungen)."""
        latest = None
        try:
            while True:
                latest = self.worker.states.get_nowait()
        except queue.Empty:
            pass
        if latest is not None:
            self.show(latest)
        if self.worker.error is not None:
            self.vars["detail"].set(f"Fehler: {self.worker.error}")

    def run(self) -> None:
        self.root.after(self.poll_ms, self.poll)
        self.root.mainloop()
