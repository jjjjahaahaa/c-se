"""Hilfsfunktionen für den Headless-Browser (Playwright), genutzt von Tools und Tests."""

from __future__ import annotations

import glob
import os
from pathlib import Path


class BrowserUnavailable(RuntimeError):
    """Playwright oder Chromium ist nicht installiert."""


def launch_chromium(playwright, **kwargs):
    """Chromium starten. Fällt auf eine vorinstallierte Version zurück, falls die zur
    Playwright-Version passende fehlt (Pfad über die Umgebungsvariable BJ_CHROMIUM)."""
    try:
        return playwright.chromium.launch(**kwargs)
    except Exception as first_error:  # noqa: BLE001 – Alternativen probieren
        candidates = [os.environ.get("BJ_CHROMIUM")]
        candidates += sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))
        for path in candidates:
            if path and Path(path).exists():
                return playwright.chromium.launch(executable_path=path, **kwargs)
        raise BrowserUnavailable(
            f"Kein Chromium für Playwright gefunden ({first_error}). "
            "Abhilfe: python -m playwright install chromium"
        ) from first_error
