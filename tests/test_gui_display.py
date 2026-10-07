"""Tests, die ein Display brauchen (tkinter-Fenster, Bildschirmaufnahme, globale Hotkeys).

Ohne Display (z. B. in CI) werden sie übersprungen. In der Entwicklungsumgebung laufen sie
auf einem virtuellen Bildschirm:   xvfb-run -a python -m pytest tests/test_gui_display.py
Lokal mit echtem Bildschirm laufen sie einfach mit `pytest`.
"""

import os
import queue
import sys

import numpy as np
import pytest

pytestmark = pytest.mark.display

if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
    pytest.skip("Kein Display (DISPLAY nicht gesetzt)", allow_module_level=True)
tk = pytest.importorskip("tkinter", reason="tkinter nicht installiert")

from blackjack_assistant.app import OverlayState  # noqa: E402
from blackjack_assistant.models import Action, Decision  # noqa: E402
from blackjack_assistant.strategy.betting import BetAdvice  # noqa: E402


class FakeWorker:
    def __init__(self):
        self.states = queue.Queue()
        self.error = None


def test_overlay_zeigt_werte_und_warnungen():
    from blackjack_assistant.overlay.window import OverlayWindow

    worker = FakeWorker()
    calls = []
    actions = {"pause": lambda: calls.append("pause"), "reset": lambda: calls.append("reset"),
               "switch": lambda: calls.append("switch")}
    win = OverlayWindow(worker, actions, "F8 Pause · F9 Reset · F10 Profil", poll_ms=20)
    try:
        # "-topmost" wirkt nur mit Fenstermanager (nicht auf Xvfb) → lokal prüfen (LOCAL_TESTS.md)
        state = OverlayState(profile="Mock", system="Hi-Lo", engine="strategy", running_count=4,
                             true_count=2.0, decks_remaining=2, bet=BetAdvice(2, 20, 2),
                             decision=Decision(Action.DOUBLE, "deviation", "11 gegen Ass"),
                             dealer=["A"], player_hands=[["6", "5"]], uncertain=True,
                             ineffective=True)
        worker.states.put(state)
        win.drain()           # holt den Zustand aus der Queue (wie im laufenden Programm)
        win.root.update()
        assert win.vars["rc"].get() == "+4"
        assert win.vars["tc"].get() == "+2.0"
        assert win.vars["action"].get() == "VERDOPPELN"
        assert win.vars["bet"].get() == "20 (2 E.)"
        texts = win.warning_texts()
        assert any("wirkungslos" in t for t in texts)
        assert any("Unsichere" in t for t in texts)
        # Tasten im Fenster
        win.root.focus_force()
        for key in ("<F8>", "<F9>", "<F10>"):
            win.root.event_generate(key)
        win.root.update()
        assert calls == ["pause", "reset", "switch"]
    finally:
        win.root.destroy()


def test_bildschirmaufnahme_mit_mss():
    from blackjack_assistant.capture.screen import ScreenSource

    src = ScreenSource([0, 0, 200, 100])
    frame = src.grab()
    src.close()
    assert frame.image.shape == (100, 200, 3)
    assert frame.image.dtype == np.uint8


def test_bereich_per_maus_aufziehen():
    from blackjack_assistant.capture.region_select import select_region

    def drag(root, canvas):
        canvas.event_generate("<ButtonPress-1>", x=100, y=80, rootx=100, rooty=80)
        canvas.event_generate("<B1-Motion>", x=250, y=200, rootx=250, rooty=200)
        canvas.event_generate("<ButtonRelease-1>", x=300, y=240, rootx=300, rooty=240)

    assert select_region(on_ready=drag) == [100, 80, 200, 160]


def test_bereichsauswahl_mit_esc_abbrechen():
    from blackjack_assistant.capture.region_select import select_region

    def escape(root, canvas):
        root.event_generate("<Escape>")

    assert select_region(on_ready=escape) is None


def test_kalibrierfenster(tmp_path):
    from blackjack_assistant.recognition.calibration import CalibrationSession, run_calibration_window
    from tests.helpers import fixture_image

    image = fixture_image("table_split")    # Dealer-K bei (37, 59), Template ca. 19×26
    session = CalibrationSession(tmp_path)

    def mark_king(root, canvas, entry):
        canvas.event_generate("<ButtonPress-1>", x=34, y=56)
        canvas.event_generate("<B1-Motion>", x=50, y=70)
        canvas.event_generate("<ButtonRelease-1>", x=59, y=88)
        entry.delete(0, "end")
        entry.insert(0, "K")
        entry.event_generate("<Return>")
        root.update()
        root.destroy()

    run_calibration_window(image, session, on_ready=mark_king)
    assert "K" not in session.missing_ranks()


def test_globale_hotkeys_starten():
    from blackjack_assistant.overlay.hotkeys import HotkeyListener

    listener = HotkeyListener({"pause": lambda: None})
    ok = listener.start()
    listener.stop()
    assert ok, listener.error


def _temp_profile_root(tmp_path):
    from blackjack_assistant.profiles import load_profile

    p = load_profile("mock_casino")
    p.regions = {"table": [0, 0, 300, 200], "history": None}
    p.read_mode = "table"
    p.save(tmp_path / "profiles" / "mock_casino")
    import shutil

    shutil.copytree(load_profile("mock_casino").templates_dir,
                    tmp_path / "profiles" / "mock_casino" / "templates")
    return tmp_path / "profiles"


def test_run_ohne_overlay_startet_und_endet(tmp_path, capsys, monkeypatch):
    from blackjack_assistant import app

    monkeypatch.setattr(app, "LOG_DIR", tmp_path / "logs")
    assert app.run_app("mock_casino", no_overlay=True, profiles_root=_temp_profile_root(tmp_path),
                       duration=1.5) == 0
    out = capsys.readouterr().out
    assert "Profil: mock_casino" in out and "F8 Pause" in out


def test_run_mit_overlay_startet_und_endet(tmp_path, monkeypatch):
    from blackjack_assistant import app

    monkeypatch.setattr(app, "LOG_DIR", tmp_path / "logs")
    assert app.run_app("mock_casino", profiles_root=_temp_profile_root(tmp_path), duration=1.5) == 0


def test_gesamtablauf_browser_bildschirm_overlay(tmp_path):
    """Mock-Casino im sichtbaren Browser, Aufnahme mit mss, Worker-Thread und Overlay.
    Der im Overlay angezeigte Running Count muss der Ground Truth entsprechen."""
    pytest.importorskip("playwright.sync_api", reason="Playwright nicht installiert")
    from tools.browser import BrowserUnavailable
    from tools.screen_demo import run

    try:
        result = run(rounds=3, seed=7, mode="history", out=tmp_path)
    except BrowserUnavailable as err:
        pytest.skip(str(err))
    state = result["state"]
    assert state.cards_seen == result["truth_cards"] > 10
    assert state.running_count == result["truth_rc"]
