"""Kartenerkennung auf eingecheckten Headless-Screenshots des Mock-Casinos (tests/data).

Läuft ohne Bildschirm und ohne Browser.
"""

from collections import Counter

import cv2
import pytest

from blackjack_assistant.profiles import load_profile
from blackjack_assistant.recognition.calibration import CalibrationSession
from blackjack_assistant.recognition.history_mode import reading_order
from blackjack_assistant.recognition.matcher import TemplateMatcher, estimate_scale
from blackjack_assistant.recognition.table_mode import TableTracker
from blackjack_assistant.recognition.templates import TemplateSet
from tests.helpers import fixture_expected, fixture_image

TABLE_FIXTURES = ["table_player_turn", "table_settled", "table_split", "table_hidden_hole"]


@pytest.fixture(scope="module")
def profile():
    return load_profile("mock_casino")


@pytest.fixture(scope="module")
def templates(profile):
    return TemplateSet.load(profile.templates_dir)


def read_table(image, templates, profile, scale=1.0):
    """Erkennt die Karten eines Tischbildes und teilt sie in Dealer/Spieler-Hände auf."""
    matcher = TemplateMatcher(templates, scale=scale)
    tracker = TableTracker(profile.areas["dealer"], profile.areas["player"])
    h, w = image.shape[:2]
    tracker.update(matcher.detect(image), (w, h))
    return tracker.dealer_cards(), tracker.player_hands()


def test_alle_13_raenge_haben_templates(templates):
    assert templates.missing_ranks() == []


@pytest.mark.parametrize("name", TABLE_FIXTURES)
def test_tischkarten_werden_exakt_erkannt(name, templates, profile):
    dealer, hands = read_table(fixture_image(name), templates, profile)
    expected = fixture_expected(name)
    assert dealer == expected["dealer"]
    assert hands == expected["player"]


def test_verdeckte_hole_card_wird_nicht_als_karte_erkannt(templates, profile):
    dealer, _ = read_table(fixture_image("table_player_turn"), templates, profile)
    assert dealer == ["6"]  # Rückseite liefert keinen Treffer


def test_gedrehte_ecken_werden_aussortiert(templates):
    """table_settled: Die letzte 9 und 6 zeigen unten rechts eine gedrehte Ecke (sieht aus
    wie 6 bzw. 9). Mit Orientierungsprüfung darf es keine Zusatztreffer geben."""
    image = fixture_image("table_settled")
    expected = fixture_expected("table_settled")
    n_expected = len(expected["dealer"]) + sum(len(h) for h in expected["player"])
    with_check = TemplateMatcher(templates).detect(image)
    without = TemplateMatcher(templates, orientation_check=False).detect(image, threshold=0.8)
    assert len(with_check) == n_expected
    assert len(without) > n_expected  # zeigt, dass die Prüfung nötig ist


def test_verlaufs_panel_in_richtiger_reihenfolge(templates, profile):
    image = fixture_image("history_panel")
    matcher = TemplateMatcher(templates, scale=profile.recognition.history_scale)
    ranks = [d.rank for d in reading_order(matcher.detect(image))]
    assert ranks == fixture_expected("history_panel")["history"]


def test_konfidenz_und_abstand_zum_zweitbesten_rang(templates, profile):
    image = fixture_image("history_panel")
    dets = TemplateMatcher(templates, scale=profile.recognition.history_scale).detect(image)
    rec = profile.recognition
    assert all(d.is_confident(rec.min_confidence, rec.uncertain_margin) for d in dets)


def test_skalierung_wird_bei_125_prozent_gefunden(templates, profile):
    image = fixture_image("table_zoom125")
    scale, quality = estimate_scale(image, templates)
    assert 1.12 <= scale <= 1.32
    assert quality > 0.9
    dealer, hands = read_table(image, templates, profile, scale=scale)
    expected = fixture_expected("table_zoom125")
    assert dealer == expected["dealer"] and hands == expected["player"]


def test_unscharfes_bild_liefert_unsichere_treffer_statt_falscher(templates):
    """Stark verkleinertes und wieder vergrössertes Bild: Treffer dürfen unsicher werden,
    aber sicher erkannte Ränge müssen stimmen."""
    image = fixture_image("history_panel")
    small = cv2.resize(image, None, fx=0.45, fy=0.45, interpolation=cv2.INTER_AREA)
    blurry = cv2.resize(small, (image.shape[1], image.shape[0]), interpolation=cv2.INTER_LINEAR)
    expected = fixture_expected("history_panel")["history"]
    dets = reading_order(TemplateMatcher(templates, scale=0.95).detect(blurry))
    confident = [d for d in dets if d.is_confident(0.8, 0.03)]
    # Position in der Liste ist bei fehlenden Treffern verschoben → Vergleich als Multimenge
    assert not (Counter(d.rank for d in confident) - Counter(expected))


def test_kalibrierung_mit_deutschen_buchstaben_ergibt_funktionierende_templates(templates, profile, tmp_path):
    """Simuliert die Kalibrierung: Für jeden Rang wird ein Rechteck auf dem Verlaufs-Panel
    markiert, Bildkarten mit B/D/K beschriftet. Die neuen Templates müssen danach die
    Tischbilder genauso gut erkennen (andere Grösse → automatische Skalierung)."""
    image = fixture_image("history_panel")
    dets = TemplateMatcher(templates, scale=0.95).detect(image)
    german = {"J": "B", "Q": "D", "K": "K", "A": "A"}
    session = CalibrationSession(tmp_path / "templates")
    for rank in session.missing_ranks():
        d = next(d for d in dets if d.rank == rank)
        # Rechteck etwas grösser als das Zeichen, wie bei einer Markierung von Hand
        rect = [d.x - 3, d.y - 3, d.w + 6, d.h + 6]
        assert session.add(german.get(rank, rank), image, rect) == rank
    assert session.complete
    session.save()
    calibrated = TemplateSet.load(tmp_path / "templates")
    assert sorted(p.name for p in (tmp_path / "templates").glob("*.png"))[-4:] == [
        "A_1.png", "J_1.png", "K_1.png", "Q_1.png"]
    table = fixture_image("table_split")
    scale, _ = estimate_scale(table, calibrated)
    dealer, hands = read_table(table, calibrated, profile, scale=scale)
    expected = fixture_expected("table_split")
    assert dealer == expected["dealer"] and hands == expected["player"]
