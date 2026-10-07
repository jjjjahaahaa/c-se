"""Gesamtablauf auf einem (echten oder virtuellen) Bildschirm: Mock-Casino im sichtbaren
Browser, Assistent mit Bildschirmaufnahme (mss), Worker-Thread und tkinter-Overlay.
Am Ende wird der angezeigte Running Count mit der Ground Truth verglichen und ein
Bildschirmfoto gespeichert.

Aufruf:  python tools/screen_demo.py --rounds 5 --shot logs/overlay_demo.png
         (ohne Bildschirm:  xvfb-run -a -s "-screen 0 1600x1000x24" python tools/screen_demo.py)
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blackjack_assistant.app import Assistant, AssistantWorker  # noqa: E402
from blackjack_assistant.capture.screen import ScreenSource, bounding_region, open_mss  # noqa: E402
from blackjack_assistant.counting.systems import get_system  # noqa: E402
from blackjack_assistant.profiles import load_profile  # noqa: E402
from mock_casino.server import BackgroundServer, CasinoConfig, GroundTruthLog  # noqa: E402
from tools.browser import launch_chromium  # noqa: E402
from tools.record_mock_session import element_region  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def truth_running_count(path: Path) -> tuple[float, int]:
    """Hi-Lo-Count aus der Ground Truth (nur aufgedeckte Karten des aktuellen Schuhs)."""
    hilo = get_system("hi_lo")
    rc, n = 0.0, 0
    for line in path.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e["type"] == "shuffle":
            rc, n = 0.0, 0
        elif e["type"] == "card":
            rc += hilo.value(e["rank"])
            n += 1
    return rc, n


def run(rounds: int = 5, seed: int = 7, mode: str = "history", out: Path | None = None,
        shot: Path | None = None) -> dict:
    from playwright.sync_api import sync_playwright

    from blackjack_assistant.overlay.window import OverlayWindow

    out = out or PROJECT_ROOT / "logs" / f"screen_demo_{time.strftime('%Y%m%d_%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    truth = out / "ground_truth.jsonl"
    with BackgroundServer(CasinoConfig(debug=True, log=GroundTruthLog(truth))) as server, \
            sync_playwright() as pw:
        browser = launch_chromium(pw, headless=False,
                                  args=["--window-position=0,0", "--window-size=1500,1000"])
        page = browser.new_page(no_viewport=True)
        page.goto(f"{server.url}/index.html?seed={seed}&speed=1&clear=1200")
        page.wait_for_selector("body[data-ready='1']")
        ox, oy = page.evaluate("[window.screenX + (window.outerWidth - window.innerWidth),"
                               " window.screenY + (window.outerHeight - window.innerHeight)]")
        regions = {"table": element_region(page, "#table"),
                   "history": element_region(page, "#history", pad=4)}
        regions["history"][3] = page.evaluate("window.innerHeight") - regions["history"][1]
        for r in regions.values():
            r[0] += ox
            r[1] += oy

        profile = copy.deepcopy(load_profile("mock_casino"))
        profile.read_mode = mode
        profile.regions = regions
        assistant = Assistant(profile, log_dir=out)
        source = ScreenSource(bounding_region(list(regions.values())))
        worker = AssistantWorker(assistant, source, source.origin, interval=0.05)
        actions = {"pause": lambda: worker.command("pause"), "reset": lambda: worker.command("reset")}
        window = OverlayWindow(worker, actions, "F8 Pause · F9 Reset", poll_ms=50)
        window.root.geometry("+1100+560")  # neben das Verlaufs-Panel

        worker.start()
        page.evaluate("([n, p]) => { window.__done = false; "
                      "window.casino.autoplay(n, p).then(() => { window.__done = true; }); }",
                      [rounds, 700])
        done_at = None
        decisions = set()
        while True:
            window.root.update()
            window.drain()
            if window.last_state is not None and window.last_state.decision is not None:
                decisions.add(window.last_state.decision.action.value)
            if done_at is None and page.evaluate("window.__done"):
                done_at = time.time()
            if done_at is not None and time.time() - done_at > 2.5:
                break
            time.sleep(0.03)
        page.evaluate("window.casino.logger.flush()")
        rc_truth, n_truth = truth_running_count(truth)
        state = window.last_state
        # Zum Schluss eine Spielsituation stehen lassen (für das Bildschirmfoto)
        page.evaluate("() => { window.casino.game.deal(10); }")
        t_end = time.time() + 3.0
        while time.time() < t_end:
            window.root.update()
            window.drain()
            time.sleep(0.03)
        if shot:
            import cv2
            import numpy as np

            shot.parent.mkdir(parents=True, exist_ok=True)
            with open_mss() as sct:
                mon = sct.monitors[0]
                img = np.asarray(sct.grab(mon))[:, :, :3]
            cv2.imwrite(str(shot), img)
        worker.stop()
        window.root.destroy()
        browser.close()
    log = assistant.close()
    return {"state": state, "truth_rc": rc_truth, "truth_cards": n_truth,
            "decisions": decisions, "log": log, "out": out}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--mode", choices=["table", "history"], default="history")
    parser.add_argument("--shot", type=Path, help="Bildschirmfoto am Ende speichern")
    args = parser.parse_args()
    r = run(args.rounds, args.seed, args.mode, shot=args.shot)
    s = r["state"]
    print(f"Overlay: RC {s.running_count:+g}, TC {s.true_count:+.2f}, {s.cards_seen} Karten gesehen")
    print(f"Ground Truth (vor der letzten Runde): RC {r['truth_rc']:+g}, {r['truth_cards']} Karten")
    print(f"Empfehlungen gesehen: {sorted(r['decisions'])}")
    print(f"Log: {r['log']}")


if __name__ == "__main__":
    main()
