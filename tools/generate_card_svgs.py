"""Erzeugt die Karten-SVGs für das Mock-Casino.

Ränge und Farbsymbole werden als Pfade gezeichnet (nicht als Text). Dadurch sehen die
Karten in jedem Browser und auf jedem Betriebssystem gleich aus, und die Templates für
die Erkennung (Phase 2) passen exakt zur Darstellung im Browser.

Aufruf:  python tools/generate_card_svgs.py
Ausgabe: mock_casino/assets/cards/<Rang><Farbe>.svg und back.svg
"""

from __future__ import annotations

import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = PROJECT_ROOT / "mock_casino" / "assets" / "cards"

RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
SUITS = ["S", "H", "D", "C"]  # Pik, Herz, Karo, Kreuz

# Kartengrösse in SVG-Einheiten (Seitenverhältnis 5:7 wie echte Pokerkarten)
CARD_W = 100
CARD_H = 140

RED = "#c8102e"
BLACK = "#111111"

# Rang-Glyphen als Strichpfade in einem Feld von 10 x 16 Einheiten.
# ("10" ist breiter: 13 Einheiten.) Gezeichnet mit runden Linienenden.
RANK_GLYPHS: dict[str, tuple[float, str]] = {
    "A": (10, "M0,16 L5,0 L10,16 M2,10 L8,10"),
    "2": (10, "M0.5,4 C0.5,-1 9.5,-1 9.5,4 C9.5,8 0,11 0,16 L10,16"),
    "3": (10, "M0.5,0 L9.5,0 L4.5,6.5 C10.5,6 10.5,16 5,16 C2.5,16 1,15 0,13.5"),
    "4": (10, "M7.5,16 L7.5,0 L0,11 L10,11"),
    "5": (10, "M9.5,0 L1.2,0 L0.5,7.2 C3,5.2 10,5 10,10.8 C10,17.3 2,17 0,13.8"),
    "6": (10, "M8.8,1.2 C4,-1.5 0,2.5 0,10 C0,17.5 10,17.5 10,11 C10,5.5 1.5,5 0.2,10"),
    "7": (10, "M0,0 L10,0 L3.5,16"),
    "8": (10, "M5,0 A4,4 0 1,0 5,8 A4,4 0 1,0 5,0 Z M5,8 A5,4 0 1,0 5,16 A5,4 0 1,0 5,8 Z"),
    "9": (10, "M1.2,14.8 C6,17.5 10,13.5 10,6 C10,-1.5 0,-1.5 0,5 C0,10.5 8.5,11 9.8,6"),
    "10": (13, "M0,3 L2.5,0 L2.5,16 M9.5,0 A3.5,8 0 1,0 9.5,16 A3.5,8 0 1,0 9.5,0 Z"),
    "J": (10, "M3,0 L10,0 M7.5,0 L7.5,11.5 C7.5,17 0.5,17 0.5,11.5"),
    "Q": (10, "M5,0 A5,8 0 1,0 5,16 A5,8 0 1,0 5,0 Z M6,11 L10.5,16.5"),
    "K": (10, "M0.5,0 L0.5,16 M10,0 L0.5,9.5 M3.8,6.3 L10,16"),
}

# Farbsymbole als gefüllte Pfade in einem Feld von 10 x 10 Einheiten
SUIT_PATHS: dict[str, str] = {
    "H": "M5,9.6 C3.8,8.4 0,5.9 0,3 C0,0.6 3.4,-0.6 5,2.4 C6.6,-0.6 10,0.6 10,3 C10,5.9 6.2,8.4 5,9.6 Z",
    "D": "M5,0 L9,5 L5,10 L1,5 Z",
    "S": (
        "M5,0 C3.5,2 0,4 0,6.4 C0,8.6 2.6,9.4 4.3,7.9 L3.4,10 L6.6,10 L5.7,7.9 "
        "C7.4,9.4 10,8.6 10,6.4 C10,4 6.5,2 5,0 Z"
    ),
    "C": (
        "M2.7,2.6 a2.3,2.3 0 1,0 4.6,0 a2.3,2.3 0 1,0 -4.6,0 Z "
        "M0.3,6.2 a2.3,2.3 0 1,0 4.6,0 a2.3,2.3 0 1,0 -4.6,0 Z "
        "M5.1,6.2 a2.3,2.3 0 1,0 4.6,0 a2.3,2.3 0 1,0 -4.6,0 Z "
        "M4.4,5 L3.4,10 L6.6,10 L5.6,5 Z"
    ),
}


def suit_color(suit: str) -> str:
    """Herz und Karo sind rot, Pik und Kreuz schwarz."""
    return RED if suit in ("H", "D") else BLACK


def corner(rank: str, suit: str) -> str:
    """Kartenecke: Rang oben, Farbsymbol darunter (links oben ausgerichtet).

    Die Ecke liegt im Bereich x 0..32, y 0..47 – diesen Ausschnitt verwenden auch das
    Verlaufs-Panel und die Templates. Rechts davon (ab x 35) beginnt erst der Rahmen
    der Bildkarten, damit er nicht in den Ausschnitt ragt.
    """
    color = suit_color(suit)
    glyph_w, glyph_path = RANK_GLYPHS[rank]
    scale = 1.45  # Rang wird 16 * 1.45 = 23 Einheiten hoch
    # "10" ist breiter und wird schmaler skaliert, damit es in die Ecke passt
    if glyph_w > 10:
        scale_x = 1.45 * 10.5 / glyph_w
    else:
        scale_x = scale
    gx = 17 - glyph_w * scale_x / 2  # horizontal in der Ecke zentrieren
    return (
        f'<g transform="translate({gx:.2f},7) scale({scale_x:.3f},{scale})">'
        f'<path d="{glyph_path}" fill="none" stroke="{color}" stroke-width="{2.1 / scale:.3f}" '
        f'stroke-linecap="round" stroke-linejoin="round"/></g>'
        f'<g transform="translate(10.5,33) scale(1.3)">'
        f'<path d="{SUIT_PATHS[suit]}" fill="{color}"/></g>'
    )


def card_svg(rank: str, suit: str) -> str:
    """Komplette Vorderseite einer Karte als SVG-Text."""
    color = suit_color(suit)
    is_face = rank in ("J", "Q", "K")
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CARD_W} {CARD_H}" '
        f'width="{CARD_W}" height="{CARD_H}">',
        f'<rect x="0.5" y="0.5" width="{CARD_W - 1}" height="{CARD_H - 1}" rx="7" '
        f'fill="#ffffff" stroke="#9a9a9a" stroke-width="1"/>',
        corner(rank, suit),
        # Ecke unten rechts: um 180° gedreht
        f'<g transform="rotate(180 {CARD_W / 2} {CARD_H / 2})">{corner(rank, suit)}</g>',
    ]
    if is_face:
        # Bildkarten: Rahmen und grosser Rang in der Mitte
        parts.append(
            f'<rect x="35" y="22" width="30" height="96" rx="4" fill="none" '
            f'stroke="{color}" stroke-width="1.5"/>'
        )
        glyph_w, glyph_path = RANK_GLYPHS[rank]
        parts.append(
            f'<g transform="translate(40,42) scale(2)"><path d="{glyph_path}" fill="none" '
            f'stroke="{color}" stroke-width="1.4" stroke-linecap="round" '
            f'stroke-linejoin="round"/></g>'
        )
        parts.append(
            f'<g transform="translate(42,82) scale(1.6)"><path d="{SUIT_PATHS[suit]}" '
            f'fill="{color}"/></g>'
        )
    else:
        # Zahlenkarten und Ass: grosses Farbsymbol in der Mitte
        parts.append(
            f'<g transform="translate(29,49) scale(4.2)"><path d="{SUIT_PATHS[suit]}" '
            f'fill="{color}"/></g>'
        )
    parts.append("</svg>")
    return "".join(parts)


def back_svg() -> str:
    """Rückseite (verdeckte Hole Card des Dealers)."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CARD_W} {CARD_H}" '
        f'width="{CARD_W}" height="{CARD_H}">'
        '<defs><pattern id="p" width="10" height="10" patternUnits="userSpaceOnUse" '
        'patternTransform="rotate(45)"><rect width="10" height="10" fill="#1f3f8f"/>'
        '<rect width="5" height="10" fill="#2b54b5"/></pattern></defs>'
        f'<rect x="0.5" y="0.5" width="{CARD_W - 1}" height="{CARD_H - 1}" rx="7" '
        'fill="#ffffff" stroke="#9a9a9a" stroke-width="1"/>'
        f'<rect x="6" y="6" width="{CARD_W - 12}" height="{CARD_H - 12}" rx="4" fill="url(#p)"/>'
        "</svg>"
    )


def generate(out_dir: Path = DEFAULT_OUT) -> list[Path]:
    """Schreibt alle 52 Karten plus Rückseite. Gibt die erzeugten Dateien zurück."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for suit in SUITS:
        for rank in RANKS:
            path = out_dir / f"{rank}{suit}.svg"
            path.write_text(card_svg(rank, suit), encoding="utf-8")
            written.append(path)
    back = out_dir / "back.svg"
    back.write_text(back_svg(), encoding="utf-8")
    written.append(back)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Zielordner")
    args = parser.parse_args()
    files = generate(args.out)
    print(f"{len(files)} SVG-Dateien geschrieben nach {args.out}")


if __name__ == "__main__":
    main()
