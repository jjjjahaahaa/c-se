"""Gemeinsame Test-Hilfen: Mock-Casino-Server im Hintergrund und Headless-Browser."""

from __future__ import annotations

from pathlib import Path

import pytest

from mock_casino.server import BackgroundServer, CasinoConfig, GroundTruthLog
from tools.browser import BrowserUnavailable, launch_chromium


RunningServer = BackgroundServer  # kurzer Name für die Tests


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


@pytest.fixture(scope="session")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api", reason="Playwright nicht installiert")
    with sync_api.sync_playwright() as pw:
        try:
            b = launch_chromium(pw)
        except BrowserUnavailable as err:
            pytest.skip(str(err))
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
