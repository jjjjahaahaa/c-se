"""Erkennungstest ohne Bildschirm: Das Mock-Casino spielt im Headless-Browser automatisch
(mit echten Animationen), laufend werden Screenshots gemacht und durch die komplette
Erkennungs-Pipeline geschickt – im Tisch-Modus und im Verlaufs-Modus gleichzeitig.
Am Ende wird mit der Ground Truth verglichen und die Genauigkeit ausgegeben.

Aufruf:  python tools/record_mock_session.py --rounds 30
         python tools/record_mock_session.py --rounds 20 --hide-hole --save-frames logs/frames
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blackjack_assistant.capture.sources import PlaywrightPageSource  # noqa: E402
from blackjack_assistant.profiles import load_profile  # noqa: E402
from blackjack_assistant.recognition.pipeline import Recognizer  # noqa: E402
from blackjack_assistant.recognition.recognition_log import RecognitionLogger  # noqa: E402
from mock_casino.server import BackgroundServer, CasinoConfig, GroundTruthLog  # noqa: E402
from tools.browser import launch_chromium  # noqa: E402
from tools.measure_accuracy import measure  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def element_region(page, selector: str, pad: int = 0) -> list[int]:
    b = page.locator(selector).bounding_box()
    return [round(b["x"]) - pad, round(b["y"]) - pad, round(b["width"]) + 2 * pad,
            round(b["height"]) + 2 * pad]


def run(rounds: int = 20, seed: int = 1, speed: float = 1.0, clear: int = 1500,
        hide_hole: bool = False, every_round: bool = False, out_dir: Path | None = None,
        save_frames: Path | None = None, extra_frames_s: float = 2.5, on_frame=None,
        pause_ms: int = 800, profile_name: str = "mock_casino", screen: bool = False,
        browser=None) -> dict:
    """Spielt `rounds` Runden und misst die Erkennung. Gibt die Berichte als dict zurück.

    browser: bereits gestarteter Playwright-Browser (z. B. aus einer pytest-Fixture);
    sonst wird ein eigener gestartet."""
    from contextlib import ExitStack

    from playwright.sync_api import sync_playwright

    out_dir = out_dir or PROJECT_ROOT / "logs" / f"mock_session_{datetime.now():%Y%m%d_%H%M%S}"
    out_dir.mkdir(parents=True, exist_ok=True)
    truth_path = out_dir / "ground_truth.jsonl"
    config = CasinoConfig(debug=True, log=GroundTruthLog(truth_path))

    base = load_profile(profile_name)
    recognizers: dict[str, Recognizer] = {}
    loggers: dict[str, RecognitionLogger] = {}
    frames_index = None

    with ExitStack() as stack:
        server = stack.enter_context(BackgroundServer(config))
        own_browser = browser is None
        if own_browser:
            pw = stack.enter_context(sync_playwright())
        if not own_browser:
            page = browser.new_page(viewport={"width": 1500, "height": 950})
        elif screen:
            # Sichtbares Browserfenster auf dem Bildschirm; aufgenommen wird mit mss wie im
            # echten Betrieb. Die Lage der Seite auf dem Bildschirm wird unten berechnet.
            browser = launch_chromium(pw, headless=False,
                                      args=["--window-position=0,0", "--window-size=1500,1000"])
            page = browser.new_page(no_viewport=True)
        else:
            browser = launch_chromium(pw)
            page = browser.new_page(viewport={"width": 1500, "height": 950})
        params = f"seed={seed}&speed={speed}&clear={clear}"
        if hide_hole:
            params += "&hide=1"
        if every_round:
            params += "&every=1"
        page.goto(f"{server.url}/index.html?{params}")
        page.wait_for_selector("body[data-ready='1']")

        regions = {"table": element_region(page, "#table"),
                   "history": element_region(page, "#history", pad=4)}
        # Die Höhe des Verlaufs wächst mit den Karten → grosszügig nach unten erweitern
        regions["history"][3] = page.evaluate("window.innerHeight") - regions["history"][1]
        if screen:
            # Seitenkoordinaten → Bildschirmkoordinaten
            ox, oy = page.evaluate("[window.screenX + (window.outerWidth - window.innerWidth),"
                                   " window.screenY + (window.outerHeight - window.innerHeight)]")
            for r in regions.values():
                r[0] += ox
                r[1] += oy
        for mode in ("table", "history"):
            profile = copy.deepcopy(base)
            profile.read_mode = mode
            profile.regions = dict(regions)
            loggers[mode] = RecognitionLogger(out_dir / f"recognition_{mode}", mode=mode)
            recognizers[mode] = Recognizer(profile, logger=loggers[mode])

        if save_frames:
            save_frames.mkdir(parents=True, exist_ok=True)
            frames_index = (save_frames / "frames.jsonl").open("w", encoding="utf-8")
            (save_frames / "regions.json").write_text(json.dumps(regions), encoding="utf-8")

        if screen:
            from blackjack_assistant.capture.screen import ScreenSource

            source = ScreenSource()
        else:
            source = PlaywrightPageSource(page)
        page.evaluate("([n, p]) => { window.__done = false; "
                      "window.casino.autoplay(n, p).then(() => { window.__done = true; }); }",
                      [rounds, pause_ms])
        n_frames = 0
        done_at = None
        while True:
            frame = source.grab()
            n_frames += 1
            for rec in recognizers.values():
                result = rec.process_frame(frame.image, frame.timestamp)
                if on_frame:
                    on_frame(rec.mode, result)
            if frames_index:
                name = f"{n_frames:05d}.png"
                cv2.imwrite(str(save_frames / name), frame.image)
                frames_index.write(json.dumps({"file": name, "t": frame.timestamp}) + "\n")
            if done_at is None and page.evaluate("window.__done"):
                done_at = time.time()
            if done_at is not None and time.time() - done_at > extra_frames_s:
                break
        page.evaluate("window.casino.logger.flush()")
        if own_browser:
            browser.close()
        else:
            page.close()
    if frames_index:
        frames_index.close()

    reports = {"frames": n_frames, "regions": regions}
    for mode, logger in loggers.items():
        logger.close()
        report = measure(truth_path, logger.events_file)
        reports[mode] = report
    reports["out_dir"] = out_dir
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--speed", type=float, default=1.0, help="Animationstempo (1 = normal)")
    parser.add_argument("--clear", type=int, default=1500, help="ms bis der Tisch geräumt wird")
    parser.add_argument("--hide-hole", action="store_true", help="Hole Card nicht immer zeigen")
    parser.add_argument("--every", action="store_true", help="nach jeder Runde mischen")
    parser.add_argument("--pause", type=int, default=800,
                        help="ms Pause zwischen den Runden (0 = sofort neu austeilen)")
    parser.add_argument("--save-frames", type=Path, help="Screenshots für spätere Tests speichern")
    parser.add_argument("--screen", action="store_true",
                        help="sichtbarer Browser + Bildschirmaufnahme mit mss (braucht ein Display)")
    args = parser.parse_args()
    reports = run(args.rounds, args.seed, args.speed, args.clear, args.hide_hole, args.every,
                  save_frames=args.save_frames, pause_ms=args.pause, screen=args.screen)
    print(f"{reports['frames']} Screenshots ausgewertet, Logs in {reports['out_dir']}\n")
    for mode, title in (("table", "TISCH-MODUS"), ("history", "VERLAUFS-MODUS")):
        print(f"=== {title} ===")
        print(reports[mode].format())
        print()


if __name__ == "__main__":
    main()
