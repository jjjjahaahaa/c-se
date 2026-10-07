"""Globale Hotkeys (funktionieren auch, wenn das Casino-Fenster den Fokus hat).

Standard: F8 = Pause, F9 = Count zurücksetzen, F10 = Profil wechseln.
Globale Hotkeys brauchen pynput. Unter macOS muss dafür die Berechtigung
"Bedienungshilfen" erteilt werden; unter Linux braucht es X11 (nicht Wayland).
Geht das nicht, funktionieren dieselben Tasten im Overlay-Fenster (wenn es den Fokus hat).
"""

from __future__ import annotations

from typing import Callable

DEFAULT_KEYS = {"pause": "f8", "reset": "f9", "switch": "f10"}
LABELS = {"pause": "Pause", "reset": "Reset", "switch": "Profil"}


def pynput_combo(key: str) -> str:
    """'f8' → '<f8>', 'ctrl+shift+p' → '<ctrl>+<shift>+p' (Format von pynput)."""
    parts = []
    for part in key.lower().split("+"):
        parts.append(part if len(part) == 1 else f"<{part}>")
    return "+".join(parts)


def tk_sequence(key: str) -> str:
    """'f8' → '<F8>' (Format von tkinter, nur einfache Tasten)."""
    return f"<{key.upper()}>" if len(key) > 1 else f"<Key-{key}>"


class HotkeyListener:
    def __init__(self, actions: dict[str, Callable[[], None]], keys: dict[str, str] | None = None):
        self.actions = actions
        self.keys = {**DEFAULT_KEYS, **(keys or {})}
        self._listener = None
        self.error: str | None = None

    def mapping(self) -> dict[str, Callable[[], None]]:
        return {pynput_combo(self.keys[name]): fn for name, fn in self.actions.items()
                if name in self.keys}

    def start(self) -> bool:
        """Startet die globalen Hotkeys. False, wenn das System es nicht erlaubt."""
        try:
            from pynput import keyboard

            self._listener = keyboard.GlobalHotKeys(self.mapping())
            self._listener.start()
            return True
        except Exception as err:  # noqa: BLE001 – z. B. kein X-Server, fehlende Berechtigung
            self.error = f"Globale Hotkeys nicht verfügbar ({err}); Tasten im Overlay nutzen"
            self._listener = None
            return False

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def describe(self) -> str:
        return " · ".join(f"{self.keys[n].upper()} {LABELS[n]}" for n in ("pause", "reset", "switch")
                          if n in self.actions)
