"""End-to-End-Test: Mock-Casino über die Oberfläche spielen (Tastatur) und prüfen,
ob Verlaufs-Panel und Ground-Truth-Log übereinstimmen."""

import json

import pytest

pytestmark = pytest.mark.browser


def play_rounds(page, rounds):
    """Spielt Runden über die Tastatur: Enter = Austeilen, N = keine Versicherung,
    H/S nach einer sehr einfachen Regel (unter 12 ziehen)."""
    for _ in range(rounds):
        page.wait_for_function("!document.getElementById('btn-deal').disabled")
        page.keyboard.press("Enter")
        while True:
            page.wait_for_function("!window.casino.game.busy")
            phase = page.evaluate("window.casino.game.phase")
            if phase == "insurance":
                page.keyboard.press("n")
            elif phase == "player":
                total = page.evaluate("""() => {
                  const g = window.casino.game;
                  return g.currentHand.cards.reduce((s, c) =>
                    s + (c.rank === 'A' ? 11 : ['J','Q','K'].includes(c.rank) ? 10 : Number(c.rank)), 0);
                }""")
                page.keyboard.press("h" if total < 12 else "s")
            else:
                break


def read_log(server):
    lines = server.config.log.path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def flush(page):
    page.evaluate("window.casino.logger.flush()")


def test_verlauf_und_ground_truth_stimmen_ueberein(page, debug_server):
    page.goto(f"{debug_server.url}/index.html?speed=0&clear=0&seed=3&penetration=0.2")
    page.wait_for_selector("body[data-ready='1']")
    assert page.is_visible("#debug-badge")

    play_rounds(page, 40)
    flush(page)
    events = read_log(debug_server)
    cards = [e for e in events if e["type"] == "card"]
    shuffles = [e for e in events if e["type"] == "shuffle"]

    assert events[0]["type"] == "session_start"
    assert len(shuffles) >= 2, "bei 20 % Penetration muss in 40 Runden gemischt werden"
    assert sum(1 for e in events if e["type"] == "round_end") == 40

    # Pro Schuh: seq läuft lückenlos 1, 2, 3, …
    by_shoe = {}
    for c in cards:
        by_shoe.setdefault(c["shoe"], []).append(c)
    for shoe, items in by_shoe.items():
        assert [c["seq"] for c in items] == list(range(1, len(items) + 1)), f"Schuh {shoe}"

    # Das Verlaufs-Panel zeigt genau die Karten des aktuellen Schuhs in derselben Reihenfolge
    current_shoe = page.evaluate("window.casino.game.shoeNumber")
    panel = page.eval_on_selector_all("#history .history-tile", "els => els.map(e => e.dataset.rank)")
    assert panel == [c["rank"] for c in by_shoe.get(current_shoe, [])]
    assert page.text_content("#history-count") == str(len(panel))

    # Am Rundenende ist der Tisch leer (Voraussetzung für den Tisch-Modus)
    assert page.eval_on_selector_all(".table img.card", "els => els.length") == 0

    # Genau eine Hole Card pro Runde
    assert sum(1 for c in cards if c["hole"]) == 40
    assert page.js_errors == []


def test_mischen_nach_jeder_runde_leert_das_panel(page, debug_server):
    page.goto(f"{debug_server.url}/index.html?speed=0&clear=0&seed=4&every=1")
    page.wait_for_selector("body[data-ready='1']")
    play_rounds(page, 5)
    flush(page)
    events = read_log(debug_server)
    shuffles = [e for e in events if e["type"] == "shuffle"]
    assert len(shuffles) == 5
    assert all(s["reason"] == "every_round" and s["roundsSinceShuffle"] == 1 for s in shuffles)
    assert page.eval_on_selector_all("#history .history-tile", "els => els.length") == 0


def test_ohne_debug_kein_badge(page, plain_server):
    page.goto(f"{plain_server.url}/index.html?speed=0&clear=0")
    page.wait_for_selector("body[data-ready='1']")
    assert not page.is_visible("#debug-badge")
    assert page.js_errors == []
