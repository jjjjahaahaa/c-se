"""Erzeugt die Rang-Templates für das Mock-Casino automatisch aus den Karten-SVGs.

Die SVGs werden im Headless-Browser (Chromium über Playwright) in genau der Grösse
gerendert, in der sie auch auf dem Tisch erscheinen (90 px breit). Aus der linken oberen
Ecke wird der Rang ausgeschnitten. So stimmen Template und Bildschirmdarstellung überein.

Aufruf:  python tools/generate_templates.py [--profile profiles/mock_casino]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blackjack_assistant.models import RANKS  # noqa: E402
from blackjack_assistant.recognition.templates import TemplateSet, tight_crop, to_gray  # noqa: E402
from tools.browser import launch_chromium  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE = PROJECT_ROOT / "profiles" / "mock_casino"

# Breite einer Tischkarte im Mock-Casino (CSS --card-w) und SVG-Breite in Einheiten
CARD_PX = 90
SVG_UNITS = 100
# Bereich des Rangzeichens in SVG-Einheiten (siehe tools/generate_card_svgs.py, corner())
RANK_BOX_UNITS = (6, 4, 28, 33)  # x0, y0, x1, y1

# Ein Template pro Rang genügt: Die normierte Korrelation ist unabhängig vom Kontrast,
# rote und schwarze Zeichen haben dieselbe Form.
SUITS = {"black": "S"}


def render_cards(card_px: int = CARD_PX) -> dict[tuple[str, str], np.ndarray]:
    """Rendert alle benötigten Karten und gibt sie als BGR-Bilder zurück."""
    from playwright.sync_api import sync_playwright

    from mock_casino.server import BackgroundServer, CasinoConfig

    result = {}
    # Die SVGs über den Mock-Casino-Server laden (file://-Pfade blockiert der Browser hier)
    with BackgroundServer(CasinoConfig()) as server, sync_playwright() as pw:
        imgs = "".join(
            f'<img id="c_{rank}_{suit}" src="{server.url}/assets/cards/{rank}{suit}.svg" '
            f'style="width:{card_px}px;display:block;margin:4px">'
            for rank in RANKS
            for suit in SUITS.values()
        )
        html = f"<html><body style='margin:0;background:#0b4d22'>{imgs}</body></html>"
        browser = launch_chromium(pw)
        page = browser.new_page(device_scale_factor=1)
        page.goto(f"{server.url}/api/config")
        page.set_content(html)
        page.wait_for_function(
            "[...document.images].every((i) => i.complete && i.naturalWidth > 0)"
        )
        for rank in RANKS:
            for suit in SUITS.values():
                png = page.locator(f"#c_{rank}_{suit}").screenshot()
                result[(rank, suit)] = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        browser.close()
    return result


def extract_rank(card_image: np.ndarray, card_px: int = CARD_PX) -> np.ndarray:
    """Schneidet das Rangzeichen aus der linken oberen Ecke einer gerenderten Karte."""
    s = card_px / SVG_UNITS
    x0, y0, x1, y1 = (int(round(v * s)) for v in RANK_BOX_UNITS)
    corner = to_gray(card_image)[y0:y1, x0:x1]
    return tight_crop(corner, pad=2)


def generate(profile_dir: Path = DEFAULT_PROFILE) -> TemplateSet:
    cards = render_cards()
    templates = TemplateSet()
    for (rank, suit), image in cards.items():
        templates.add(rank, extract_rank(image))
    out = profile_dir / "templates"
    if out.exists():
        for old in out.glob("*.png"):
            old.unlink()
    templates.save(out)
    return templates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    args = parser.parse_args()
    templates = generate(args.profile)
    print(f"{len(templates)} Templates für {len(templates.ranks)} Ränge gespeichert in "
          f"{args.profile / 'templates'}")


if __name__ == "__main__":
    main()
