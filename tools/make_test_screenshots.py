"""Erzeugt Test-Screenshots des Mock-Casinos im Headless-Browser (tests/data/).

Jeder Screenshot bekommt eine JSON-Datei mit den erwarteten Karten (aus dem Spielzustand).
Damit lassen sich Erkennung und Tracking ohne Bildschirm testen – auch auf Rechnern ohne
Playwright, denn die Bilder werden mit ins Repository eingecheckt.

Aufruf:  python tools/make_test_screenshots.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mock_casino.server import BackgroundServer, CasinoConfig  # noqa: E402
from tools.browser import launch_chromium  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT = PROJECT_ROOT / "tests" / "data"

# JavaScript: aktuellen Tischzustand als erwartete Ränge auslesen
STATE_JS = """() => {
  const g = window.casino.game;
  return {
    dealer: g.dealer.cards.filter((c, i) => !(i === 1 && g.dealer.holeHidden)).map((c) => c.rank),
    dealer_hidden: g.dealer.holeHidden ? 1 : 0,
    player: g.hands.map((h) => h.cards.map((c) => c.rank)),
    history: g.history.map((c) => c.rank),
  };
}"""

# JavaScript: n Runden sofort spielen (ohne Animation), einfache Strategie
PLAY_JS = """async (n) => {
  const g = window.casino.game;
  for (let i = 0; i < n; i++) {
    await g.deal(10);
    if (g.phase === 'insurance') await g.insurance(false);
    while (g.phase === 'player') {
      const t = g.currentHand.cards.reduce((s, c) => s + (c.rank === 'A' ? 11 :
        ['J','Q','K'].includes(c.rank) ? 10 : Number(c.rank)), 0);
      if (t < 13) await g.hit(); else await g.stand();
    }
  }
}"""

# JavaScript: nächste Karten im Schuh vorgeben
RIG_JS = """(ranks) => {
  const g = window.casino.game;
  const top = ranks.map((r, i) => ({ rank: r, suit: 'SHDC'[i % 4] }));
  g.shoe.cards.splice(g.shoe.position, 0, ...top);
}"""


def element_box(page, selector: str) -> list[int]:
    b = page.locator(selector).bounding_box()
    return [round(b["x"]), round(b["y"]), round(b["width"]), round(b["height"])]


def relative_area(inner: list[int], outer: list[int]) -> list[float]:
    """Bereich relativ zum äusseren Bereich als Anteile 0..1 (für profile.json)."""
    return [
        round((inner[0] - outer[0]) / outer[2], 3),
        round((inner[1] - outer[1]) / outer[3], 3),
        round(inner[2] / outer[2], 3),
        round(inner[3] / outer[3], 3),
    ]


def shot(page, name: str, selector: str, expected: dict) -> None:
    page.wait_for_timeout(50)
    page.locator(selector).screenshot(path=str(OUT / f"{name}.png"), animations="disabled")
    (OUT / f"{name}.json").write_text(json.dumps(expected, indent=1) + "\n", encoding="utf-8")
    print("  ", name)


def main() -> None:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    with BackgroundServer(CasinoConfig()) as server, sync_playwright() as pw:
        browser = launch_chromium(pw)

        def open_page(seed: int, extra: str = "", scale: float = 1.0, clear: int = 60000):
            page = browser.new_page(viewport={"width": 1500, "height": 950},
                                    device_scale_factor=scale)
            page.goto(f"{server.url}/index.html?speed=0&clear={clear}&seed={seed}{extra}")
            page.wait_for_selector("body[data-ready='1']")
            return page

        page = open_page(5)
        table = element_box(page, "#table")
        layout = {
            "table": table,
            "dealer_area": relative_area(element_box(page, ".dealer-area"), table),
            "player_area": relative_area(element_box(page, ".player-area"), table),
        }
        (OUT / "layout.json").write_text(json.dumps(layout, indent=1) + "\n", encoding="utf-8")
        print("Layout:", layout)

        # 1) Spielerentscheidung: Dealer zeigt eine Karte, Hole Card verdeckt
        page.evaluate(RIG_JS, ["3", "6", "6", "Q"])
        page.evaluate("() => { window.casino.game.deal(10); }")
        page.wait_for_function("window.casino.game.phase === 'player' && !window.casino.game.busy")
        shot(page, "table_player_turn", "#table", page.evaluate(STATE_JS))

        # 2) Runde fertig. Die letzte Karte jeder Hand ist eine 9 bzw. 6: deren gedrehte Ecke
        #    unten rechts sieht aus wie 6 bzw. 9 und darf NICHT erkannt werden.
        page.evaluate(RIG_JS, ["9"])
        page.evaluate("() => { window.casino.game.hit(); }")
        page.wait_for_function("window.casino.game.phase === 'player' && !window.casino.game.busy")
        page.evaluate(RIG_JS, ["6"])
        page.evaluate("() => { window.casino.game.stand(); }")
        page.wait_for_function("window.casino.game.phase === 'settled'")
        shot(page, "table_settled", "#table", page.evaluate(STATE_JS))
        page.close()

        # 3) Split mit zwei Händen, alle Bildkarten-Typen
        page = open_page(6)
        page.evaluate(RIG_JS, ["8", "K", "8", "J", "Q", "10", "A", "5", "3"])
        page.evaluate("() => { window.casino.game.deal(10); }")
        page.wait_for_function("window.casino.game.phase === 'player' && !window.casino.game.busy")
        page.evaluate("() => { window.casino.game.split(); }")
        page.wait_for_function("window.casino.game.phase === 'player' && !window.casino.game.busy")
        page.evaluate("() => { window.casino.game.stand(); }")
        page.wait_for_function("window.casino.game.phase === 'player' && !window.casino.game.busy")
        page.evaluate("() => { window.casino.game.hit(); }")
        page.wait_for_function("!window.casino.game.busy")
        shot(page, "table_split", "#table", page.evaluate(STATE_JS))
        page.close()

        # 4) Verlaufs-Panel nach vielen Runden
        page = open_page(9, clear=0)
        page.evaluate(PLAY_JS, 38)
        shot(page, "history_panel", "#history", page.evaluate(STATE_JS))
        page.close()

        # 5) Gezoomte Darstellung (Windows-Skalierung 125 %) für die Skalierungssuche
        page = open_page(5, scale=1.25)
        page.evaluate(RIG_JS, ["5", "K", "4", "7", "A"])
        page.evaluate("() => { window.casino.game.deal(10); }")
        page.wait_for_function("window.casino.game.phase === 'player' && !window.casino.game.busy")
        page.evaluate("() => { window.casino.game.hit(); }")
        page.wait_for_function("!window.casino.game.busy")
        shot(page, "table_zoom125", "#table", page.evaluate(STATE_JS))
        page.close()

        # 6) Hole Card bleibt verdeckt (Schalter aktiv), Spieler hat überkauft
        page = open_page(8, "&hide=1")
        page.evaluate(RIG_JS, ["10", "4", "6", "9", "K"])
        page.evaluate("() => { window.casino.game.deal(10); }")
        page.wait_for_function("window.casino.game.phase === 'player' && !window.casino.game.busy")
        page.evaluate("() => { window.casino.game.hit(); }")
        page.wait_for_function("window.casino.game.phase === 'settled'")
        shot(page, "table_hidden_hole", "#table", page.evaluate(STATE_JS))
        page.close()

        browser.close()


if __name__ == "__main__":
    main()
