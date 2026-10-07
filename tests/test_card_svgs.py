"""Tests für die Karten-SVGs des Mock-Casinos."""

import xml.etree.ElementTree as ET

from tools.generate_card_svgs import DEFAULT_OUT, RANKS, SUITS, back_svg, card_svg, generate


def test_alle_52_karten_und_rueckseite_vorhanden():
    for suit in SUITS:
        for rank in RANKS:
            assert (DEFAULT_OUT / f"{rank}{suit}.svg").exists(), f"{rank}{suit} fehlt"
    assert (DEFAULT_OUT / "back.svg").exists()


def test_eingecheckte_svgs_sind_aktuell():
    """Wer den Generator ändert, muss die SVGs neu erzeugen."""
    for suit in SUITS:
        for rank in RANKS:
            on_disk = (DEFAULT_OUT / f"{rank}{suit}.svg").read_text(encoding="utf-8")
            assert on_disk == card_svg(rank, suit), (
                f"{rank}{suit}.svg veraltet – python tools/generate_card_svgs.py ausführen"
            )
    assert (DEFAULT_OUT / "back.svg").read_text(encoding="utf-8") == back_svg()


def test_svgs_sind_gueltiges_xml_ohne_text_elemente(tmp_path):
    """Ränge müssen Pfade sein, kein <text> – sonst hängt das Aussehen von Schriften ab."""
    for path in generate(tmp_path):
        root = ET.fromstring(path.read_text(encoding="utf-8"))
        assert root.tag.endswith("svg")
        assert not any(el.tag.endswith("text") for el in root.iter()), path.name


def test_rote_und_schwarze_farben():
    assert "#c8102e" in card_svg("A", "H")
    assert "#c8102e" in card_svg("A", "D")
    assert "#c8102e" not in card_svg("A", "S")
    assert "#c8102e" not in card_svg("A", "C")
