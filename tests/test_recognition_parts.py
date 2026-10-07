"""Stabilitätsprüfung, Profile, Kalibrierung, Erkennungs-Log, Messwerkzeug und Pipeline."""

import json
from datetime import datetime, timedelta

import numpy as np
import pytest

from blackjack_assistant.capture.region_select import RectangleDrag
from blackjack_assistant.capture.screen import bounding_region
from blackjack_assistant.capture.sources import ImageSequenceSource, crop
from blackjack_assistant.capture.stability import StabilityGate
from blackjack_assistant.models import normalize_rank
from blackjack_assistant.profiles import Profile, ProfileManager, list_profiles, load_profile
from blackjack_assistant.recognition.calibration import CalibrationSession
from blackjack_assistant.recognition.events import CardEvent, EventType
from blackjack_assistant.recognition.pipeline import Recognizer
from blackjack_assistant.recognition.recognition_log import RecognitionLogger
from tests.helpers import fixture_expected, fixture_image
from tools.measure_accuracy import measure

# ----------------------------------------------------------------------
# Ränge
# ----------------------------------------------------------------------


@pytest.mark.parametrize("label,rank", [
    ("B", "J"), ("j", "J"), ("Bube", "J"), ("D", "Q"), ("dame", "Q"), ("Q", "Q"),
    ("K", "K"), ("König", "K"), ("A", "A"), ("As", "A"), ("T", "10"), ("10", "10"), ("7", "7"),
])
def test_rang_bezeichnungen_werden_vereinheitlicht(label, rank):
    assert normalize_rank(label) == rank


def test_unbekannter_rang_wird_abgelehnt():
    with pytest.raises(ValueError):
        normalize_rank("X")


# ----------------------------------------------------------------------
# Stabilitätsprüfung (300 ms)
# ----------------------------------------------------------------------


def blank(value=40):
    return np.full((200, 300, 3), value, np.uint8)


def test_bild_wird_erst_nach_300_ms_ruhe_ausgewertet():
    gate = StabilityGate(hold_ms=300)
    img = blank()
    assert gate.feed(img, 0.00) is None
    assert gate.feed(img, 0.10) is None
    assert gate.feed(img, 0.25) is None
    assert gate.feed(img, 0.31) is not None
    assert gate.feed(img, 0.50) is None  # nur einmal pro Ruhephase


def test_aenderung_startet_die_wartezeit_neu():
    gate = StabilityGate(hold_ms=300)
    a, b = blank(40), blank(40)
    b[50:90, 100:130] = 255  # eine "Karte" erscheint
    gate.feed(a, 0.0)
    assert gate.feed(a, 0.35) is not None
    assert gate.feed(b, 0.40) is None
    assert gate.feed(b, 0.60) is None
    assert gate.feed(b, 0.71) is not None


def test_kleine_aenderung_in_grossem_bild_wird_bemerkt():
    """Eine neue Kachel im grossen Verlaufs-Panel muss erkannt werden (Anzahl geänderter
    Pixel statt mittlerer Differenz)."""
    gate = StabilityGate(hold_ms=300)
    big = np.full((900, 500, 3), 30, np.uint8)
    changed = big.copy()
    changed[10:48, 10:36] = 255
    gate.feed(big, 0.0)
    assert gate.feed(big, 0.4) is not None
    assert gate.feed(changed, 0.5) is None
    assert gate.feed(changed, 0.85) is not None


# ----------------------------------------------------------------------
# Bereiche
# ----------------------------------------------------------------------


def test_rechteck_aus_mauszug_in_beliebiger_richtung():
    drag = RectangleDrag()
    drag.press(300, 200)
    drag.drag(250, 260)
    assert drag.release(100, 50) == [100, 50, 200, 150]
    tiny = RectangleDrag()
    tiny.press(10, 10)
    assert tiny.release(12, 11) is None  # versehentlicher Klick


def test_ausschnitt_und_gesamtbereich():
    img = np.arange(100 * 80).reshape(80, 100).astype(np.uint8)
    assert crop(img, [10, 5, 20, 30]).shape == (30, 20)
    assert crop(img, [90, 70, 50, 50]).shape == (10, 10)  # an den Rand beschnitten
    assert bounding_region([[10, 20, 100, 50], [200, 0, 30, 30]]) == [10, 0, 220, 70]


# ----------------------------------------------------------------------
# Profile
# ----------------------------------------------------------------------


def test_beide_beispielprofile_sind_gueltig():
    names = list_profiles()
    assert {"mock_casino", "playtech_blackjack_surrender"} <= set(names)
    for name in names:
        assert load_profile(name).validate() == []


def test_playtech_profil_hat_die_geforderten_regeln():
    p = load_profile("playtech_blackjack_surrender")
    r = p.rules
    assert r.decks == 6 and not r.hit_soft_17 and r.dealer_peek
    assert r.double_after_split and r.late_surrender
    assert r.max_hands == 2 and not r.resplit_aces          # kein Re-Split
    assert r.seven_card_charlie
    assert r.shuffle_every_round                             # standardmässig aktiv


def test_profil_speichern_und_laden(tmp_path):
    p = Profile(name="test", read_mode="history", regions={"table": [1, 2, 300, 200], "history": None})
    p.rules.decks = 2
    p.save(tmp_path / "test")
    loaded = load_profile(tmp_path / "test")
    assert loaded.read_mode == "history"
    assert loaded.regions["table"] == [1, 2, 300, 200]
    assert loaded.rules.decks == 2
    assert loaded.templates_dir == tmp_path / "test" / "templates"


def test_ungueltiges_profil_wird_abgelehnt(tmp_path):
    p = Profile(name="kaputt", read_mode="irgendwas")
    p.save(tmp_path / "kaputt")
    with pytest.raises(ValueError):
        load_profile(tmp_path / "kaputt")


def test_profilwechsel_reihum(tmp_path):
    for name in ("a", "b", "c"):
        Profile(name=name).save(tmp_path / name)
    manager = ProfileManager(root=tmp_path, active="b")
    assert manager.next().name == "c"
    assert manager.next().name == "a"
    assert manager.switch("b").name == "b"


# ----------------------------------------------------------------------
# Kalibrierung (Logik)
# ----------------------------------------------------------------------


def test_kalibrierung_akzeptiert_jqk_und_bdk(tmp_path):
    img = np.full((60, 200, 3), 255, np.uint8)
    img[10:40, 10:25] = 0
    session = CalibrationSession(tmp_path)
    assert session.next_rank() == "2"
    assert session.add("B", img, [5, 5, 30, 40]) == "J"
    assert session.add("q", img, [5, 5, 30, 40]) == "Q"
    assert session.add("D", img, [5, 5, 30, 40]) == "Q"   # zweites Template für die Dame
    assert session.add("König", img, [5, 5, 30, 40]) == "K"
    assert "J" not in session.missing_ranks()
    session.save()
    names = sorted(p.name for p in tmp_path.glob("*.png"))
    assert names == ["J_1.png", "K_1.png", "Q_1.png", "Q_2.png"]


def test_kalibrierung_lehnt_leere_auswahl_ab(tmp_path):
    img = np.full((60, 200, 3), 255, np.uint8)
    session = CalibrationSession(tmp_path)
    with pytest.raises(ValueError):
        session.add("5", img, [5, 5, 30, 40])   # nur weiss, kein Zeichen
    with pytest.raises(ValueError):
        session.add("5", img, [5, 5, 2, 2])     # zu klein
    with pytest.raises(ValueError):
        session.add("X", img, [5, 5, 30, 40])   # unbekannter Rang


# ----------------------------------------------------------------------
# Erkennungs-Log und Genauigkeitsmessung
# ----------------------------------------------------------------------


def test_erkennungs_log_mit_ausschnitten_und_uebersicht(tmp_path):
    logger = RecognitionLogger(tmp_path / "rec", mode="table")
    frame = fixture_image("table_settled")
    logger.log(CardEvent(EventType.NEW_CARD, rank="6", confidence=0.99, role="dealer",
                         box=(36, 59, 19, 26), source="table"), frame, 1000.0)
    logger.log(CardEvent(EventType.UNCERTAIN, rank="8", confidence=0.7, box=(70, 59, 19, 26)),
               frame, 1001.0)
    logger.log(CardEvent(EventType.ROUND_END), frame, 1002.0)
    index = logger.close()
    lines = [json.loads(l) for l in logger.events_file.read_text().splitlines()]
    assert [l["type"] for l in lines] == ["session_start", "new_card", "uncertain", "round_end",
                                          "session_end"]
    assert (tmp_path / "rec" / lines[1]["image"]).exists()
    html = index.read_text(encoding="utf-8")
    assert "unsure" in html and "Rundenende" in html


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_genauigkeitsmessung(tmp_path):
    t0 = datetime(2026, 10, 7, 12, 0, 0)

    def ts(sec):
        return (t0 + timedelta(seconds=sec)).isoformat(timespec="milliseconds")

    truth = [
        {"server_time": ts(1), "type": "round_start"},
        *[{"server_time": ts(1.1 + i / 10), "type": "card", "rank": r} for i, r in enumerate("K92")],
        {"server_time": ts(5), "type": "round_start"},
        *[{"server_time": ts(5.1 + i / 10), "type": "card", "rank": r} for i, r in enumerate("A5Q8")],
        {"server_time": ts(9), "type": "round_start"},
        {"server_time": ts(9.1), "type": "card", "rank": "3"},
        {"server_time": ts(9.5), "type": "unseen", "rank": "7"},
    ]
    rec = [
        {"time": ts(0.5), "type": "session_start"},
        # Runde 1 korrekt, die 2 aber erst kurz nach Beginn von Runde 2 erkannt
        {"time": ts(3), "type": "new_card", "rank": "K"},
        {"time": ts(3), "type": "new_card", "rank": "9"},
        {"time": ts(5.2), "type": "new_card", "rank": "2"},
        # Runde 2: Q als K gelesen, 8 doppelt gezählt, A erst falsch (4) und dann korrigiert
        {"time": ts(7), "type": "new_card", "rank": "4"},
        {"time": ts(7), "type": "new_card", "rank": "5"},
        {"time": ts(7), "type": "new_card", "rank": "K"},
        {"time": ts(7), "type": "new_card", "rank": "8"},
        {"time": ts(7.5), "type": "new_card", "rank": "8"},
        {"time": ts(8), "type": "correction", "rank": "A", "old_rank": "4"},
        # Runde 3: 3 erkannt, Hole Card als ungesehen gemeldet
        {"time": ts(10), "type": "new_card", "rank": "3"},
        {"time": ts(10), "type": "unseen", "count": 1},
        {"time": ts(30), "type": "session_end"},
    ]
    _write_jsonl(tmp_path / "t.jsonl", truth)
    _write_jsonl(tmp_path / "r.jsonl", rec)
    report = measure(tmp_path / "t.jsonl", tmp_path / "r.jsonl")
    assert report.rounds == 3
    assert report.truth_cards == 8
    assert report.correct == 7            # K 9 2 | A 5 8 | 3
    assert report.missed == 1             # Q
    assert report.extra == 2              # K statt Q, zweite 8
    assert report.confusions[("Q", "K")] == 1
    assert report.recognized_unseen == 1 and report.truth_unseen == 1
    assert report.accuracy == pytest.approx(100 * 7 / 10)


# ----------------------------------------------------------------------
# Pipeline mit einer Bildfolge
# ----------------------------------------------------------------------


def test_pipeline_zaehlt_bildfolge_einer_runde(tmp_path):
    """Spielerentscheidung → Runde fertig → leerer Tisch, jeweils mehrere Bilder lang."""
    profile = load_profile("mock_casino")
    profile.read_mode = "table"
    rec = Recognizer(profile)
    turn, settled = fixture_image("table_player_turn"), fixture_image("table_settled")
    empty = np.full_like(turn, 0)
    empty[:] = (34, 77, 11)  # Tischfarbe
    sequence = [turn] * 5 + [settled] * 5 + [empty] * 5
    events = []
    for i, img in enumerate(sequence):
        events += rec.process_regions(img, None, i * 0.1).events
    cards = [e.rank for e in events if e.type == EventType.NEW_CARD]
    expected = fixture_expected("table_settled")
    assert sorted(cards) == sorted(expected["history"])
    assert events[-1].type == EventType.ROUND_END


def test_bildfolge_aus_ordner_abspielen(tmp_path):
    import cv2

    for i, name in enumerate(["table_player_turn", "table_settled"]):
        cv2.imwrite(str(tmp_path / f"{i:03d}.png"), fixture_image(name))
    src = ImageSequenceSource(tmp_path, interval=0.2)
    frames = list(src)
    assert len(frames) == 2 and frames[1].timestamp == pytest.approx(0.2)
