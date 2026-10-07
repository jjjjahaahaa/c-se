"""Gemeinsame Test-Hilfen: Mock-Casino-Server im Hintergrund und Headless-Browser."""

from __future__ import annotations

import glob
import os
import threading
from pathlib import Path

import pytest

from mock_casino.server import CasinoConfig, GroundTruthLog, create_server


class RunningServer:
    """Startet den Mock-Casino-Server auf einem freien Port in einem Thread."""

    def __init__(self, config: CasinoConfig):
        self.config = config
        self.httpd = create_server(config, port=0)  # Port 0 = Betriebssystem wählt frei
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def debug_server(tmp_path: Path):
    """Server im Debug-Modus, schreibt die Ground Truth in ein temporäres Verzeichnis."""
    log = GroundTruthLog(tmp_path / "ground_truth.jsonl")
    with RunningServer(CasinoConfig(debug=True, log=log)) as server:
        yield server


@pytest.fixture
def plain_server():
    """Server ohne Debug-Modus."""
    with RunningServer(CasinoConfig(debug=False)) as server:
        yield server


# ----------------------------------------------------------------------
# Headless-Browser (optional)
# ----------------------------------------------------------------------


def _launch_chromium(playwright):
    """Chromium starten. Fällt auf eine vorinstallierte Version zurück, falls die
    zur Playwright-Version passende fehlt (Pfad über BJ_CHROMIUM überschreibbar)."""
    try:
        return playwright.chromium.launch()
    except Exception as first_error:  # noqa: BLE001 – wir probieren Alternativen
        candidates = [os.environ.get("BJ_CHROMIUM")]
        candidates += sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))
        for path in candidates:
            if path and Path(path).exists():
                return playwright.chromium.launch(executable_path=path)
        pytest.skip(f"Kein Chromium für Playwright verfügbar: {first_error}")


@pytest.fixture(scope="session")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api", reason="Playwright nicht installiert")
    with sync_api.sync_playwright() as pw:
        b = _launch_chromium(pw)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(viewport={"width": 1500, "height": 950})
    pg = context.new_page()
    errors: list[str] = []
    pg.on("pageerror", lambda exc: errors.append(str(exc)))
    pg.js_errors = errors  # im Test prüfbar
    yield pg
    context.close()


@pytest.fixture
def casino_page(page, plain_server):
    """Mock-Casino ohne Animationen geladen; Module per import() verfügbar."""
    page.goto(f"{plain_server.url}/index.html?speed=0&clear=0&seed=1")
    page.wait_for_selector("body[data-ready='1']")
    return page
