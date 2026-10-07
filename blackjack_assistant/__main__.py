"""Kommandozeile des Blackjack-Assistenten.

  python -m blackjack_assistant profiles
  python -m blackjack_assistant select-region --profile mock_casino --region table
  python -m blackjack_assistant calibrate --profile mein_spiel
  python -m blackjack_assistant scale --profile mock_casino
  python -m blackjack_assistant replay --profile mock_casino --frames logs/frames

Befehle, die den Bildschirm brauchen (select-region, calibrate, scale), werden lokal
getestet (siehe LOCAL_TESTS.md). Alle anderen laufen auch ohne Display.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _load(name: str):
    from .profiles import load_profile

    return load_profile(name)


# ----------------------------------------------------------------------
# Befehle
# ----------------------------------------------------------------------


def cmd_profiles(args) -> int:
    from .profiles import list_profiles
    from .recognition.templates import TemplateSet

    for name in list_profiles():
        p = _load(name)
        templates = TemplateSet.load(p.templates_dir)
        regions = ", ".join(k for k, v in p.regions.items() if v) or "keine"
        missing = templates.missing_ranks()
        print(f"{name:32s} Modus={p.read_mode:8s} Decks={p.rules.decks} "
              f"Templates={len(templates):2d}{' (fehlen: ' + ','.join(missing) + ')' if missing else ''} "
              f"Bereiche={regions}")
    return 0


def cmd_select_region(args) -> int:
    from .capture.region_select import select_region

    profile = _load(args.profile)
    labels = {"table": "Tischbereich (Dealer- und Spielerkarten)",
              "history": "Verlaufs-Panel (Liste der gespielten Karten)"}
    rect = select_region(f"{labels[args.region]} aufziehen – Esc bricht ab")
    if rect is None:
        print("Abgebrochen.")
        return 1
    profile.regions[args.region] = rect
    profile.save()
    print(f"Bereich '{args.region}' gespeichert: {rect}")
    return 0


def _grab_region(profile, region: str | None):
    from .capture.screen import ScreenSource

    rect = profile.regions.get(region) if region else None
    source = ScreenSource(rect)
    frame = source.grab()
    source.close()
    return frame.image


def cmd_calibrate(args) -> int:
    from .recognition.calibration import CalibrationSession, run_calibration_window

    profile = _load(args.profile)
    print("Tipp: Vorher im Spiel so viele verschiedene Karten wie möglich aufdecken lassen.")
    print("Pro Rang ein Rechteck eng um das Rangzeichen oben links ziehen, Enter bestätigt.")
    print("Bildkarten dürfen als J/Q/K oder B/D/K eingegeben werden.")
    session = CalibrationSession(profile.templates_dir, keep_existing=args.keep)
    shots = 0
    while True:
        image = _grab_region(profile, args.region)
        shots += 1
        run_calibration_window(image, session)
        session.save()
        missing = session.missing_ranks()
        if not missing:
            break
        answer = input(f"Es fehlen noch {', '.join(missing)}. Neuen Screenshot machen? [J/n] ")
        if answer.strip().lower() in ("n", "nein"):
            break
    print(f"{len(session.templates)} Templates gespeichert in {profile.templates_dir}")
    # Templates stammen aus diesem Bereich → dort Skalierung 1.0
    if args.region:
        setattr(profile.recognition, f"{args.region}_scale", 1.0)
        other = "history" if args.region == "table" else "table"
        setattr(profile.recognition, f"{other}_scale", None)  # automatisch suchen
        profile.save()
    return 0


def cmd_scale(args) -> int:
    from .recognition.matcher import estimate_scale
    from .recognition.templates import TemplateSet

    profile = _load(args.profile)
    templates = TemplateSet.load(profile.templates_dir)
    for region in ("table", "history"):
        if not profile.regions.get(region):
            continue
        scale, quality = estimate_scale(_grab_region(profile, region), templates)
        print(f"{region}: Skalierung {scale:.2f} (Übereinstimmung {quality:.2f})")
        if quality >= 0.85:
            setattr(profile.recognition, f"{region}_scale", round(scale, 3))
        else:
            print("  → zu unsicher, nicht gespeichert (sind Karten sichtbar?)")
    profile.save()
    return 0


def cmd_replay(args) -> int:
    from .capture.sources import ImageSequenceSource
    from .recognition.pipeline import Recognizer
    from .recognition.recognition_log import RecognitionLogger

    import json

    profile = _load(args.profile)
    if args.mode:
        profile.read_mode = args.mode
    # Aufnahmen von tools/record_mock_session.py enthalten die passenden Bereiche
    regions_file = Path(args.frames) / "regions.json"
    if regions_file.exists():
        profile.regions.update(json.loads(regions_file.read_text(encoding="utf-8")))
    logger = RecognitionLogger(mode=profile.read_mode)
    recognizer = Recognizer(profile, logger=logger)
    for frame in ImageSequenceSource(args.frames):
        result = recognizer.process_frame(frame.image, frame.timestamp,
                                          origin=tuple(args.origin))
        for event in result.events:
            print(f"{frame.timestamp:10.2f}  {event.describe()}")
    print(f"Log: {logger.close()}")
    return 0


def cmd_report(args) -> int:
    from .recognition.recognition_log import write_index

    print(write_index(Path(args.folder)))
    return 0


# ----------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m blackjack_assistant",
                                     description="Blackjack-Assistent (Schulprojekt)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("profiles", help="Profile auflisten").set_defaults(func=cmd_profiles)

    p = sub.add_parser("select-region", help="Bildschirmbereich per Maus festlegen")
    p.add_argument("--profile", required=True)
    p.add_argument("--region", choices=["table", "history"], required=True)
    p.set_defaults(func=cmd_select_region)

    p = sub.add_parser("calibrate", help="Templates für ein externes Spiel aufnehmen")
    p.add_argument("--profile", required=True)
    p.add_argument("--region", choices=["table", "history"], default="table",
                   help="Bereich, in dem die Karten markiert werden")
    p.add_argument("--keep", action="store_true", help="vorhandene Templates behalten")
    p.set_defaults(func=cmd_calibrate)

    p = sub.add_parser("scale", help="Template-Skalierung automatisch bestimmen")
    p.add_argument("--profile", required=True)
    p.set_defaults(func=cmd_scale)

    p = sub.add_parser("replay", help="Gespeicherte Screenshots offline auswerten")
    p.add_argument("--profile", required=True)
    p.add_argument("--frames", type=Path, required=True)
    p.add_argument("--mode", choices=["table", "history"])
    p.add_argument("--origin", type=int, nargs=2, default=[0, 0],
                   help="Bildschirmposition der linken oberen Bildecke")
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser("report", help="index.html für ein Erkennungs-Log erzeugen")
    p.add_argument("folder")
    p.set_defaults(func=cmd_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
