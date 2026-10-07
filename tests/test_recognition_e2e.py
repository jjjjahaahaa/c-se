"""End-to-End ohne Bildschirm: Mock-Casino spielt im Headless-Browser mit echten Animationen,
die komplette Erkennungs-Pipeline liest laufend Screenshots, Ergebnis wird mit der
Ground Truth verglichen (Abnahmekriterium Phase 2: Verlauf ≥ 99 %, Tisch ≥ 97 %)."""

import pytest

pytest.importorskip("playwright.sync_api", reason="Playwright nicht installiert")

from tools.browser import BrowserUnavailable  # noqa: E402
from tools.record_mock_session import run  # noqa: E402

pytestmark = pytest.mark.browser


def _run(**kw):
    try:
        return run(**kw)
    except BrowserUnavailable as err:
        pytest.skip(str(err))


def test_erkennung_gegen_ground_truth(tmp_path, browser):
    reports = _run(browser=browser, rounds=8, seed=11, speed=1.0, clear=1200, pause_ms=600,
                   hide_hole=True, out_dir=tmp_path)
    table, history = reports["table"], reports["history"]
    assert table.rounds >= 7 and table.truth_cards >= 30
    assert history.accuracy >= 99.0, history.format()
    assert table.accuracy >= 97.0, table.format()
    # Nicht gezeigte Hole Cards werden als "ungesehen" erkannt
    assert table.recognized_unseen >= table.truth_unseen
    assert table.recognized_round_ends >= 7


def test_mischen_nach_jeder_runde_wird_im_verlauf_erkannt(tmp_path, browser):
    reports = _run(browser=browser, rounds=4, seed=12, speed=0.5, clear=900, pause_ms=500,
                   every_round=True, out_dir=tmp_path)
    history = reports["history"]
    assert history.accuracy >= 99.0, history.format()
    assert history.recognized_shuffles == history.truth_shuffles >= 3
