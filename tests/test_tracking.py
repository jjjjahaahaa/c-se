"""Tisch-Modus (TableTracker) und Verlaufs-Modus (HistoryReader) mit künstlichen Treffern."""

from blackjack_assistant.recognition.events import EventType
from blackjack_assistant.recognition.history_mode import HistoryReader, reading_order
from blackjack_assistant.recognition.table_mode import TableTracker
from tests.helpers import det

# Bildgrösse 1000 × 600; Dealer oben (y < 240), Spieler darunter
SIZE = (1000, 600)
DEALER = [0.0, 0.0, 1.0, 0.4]
PLAYER = [0.0, 0.4, 1.0, 0.4]


def tracker(**kw):
    return TableTracker(DEALER, PLAYER, min_confidence=0.8, min_margin=0.03, **kw)


def types(events):
    return [e.type for e in events]


def new_cards(events):
    return [(e.rank, e.role) for e in events if e.type == EventType.NEW_CARD]


# ----------------------------------------------------------------------
# Tisch-Modus
# ----------------------------------------------------------------------


def test_karte_wird_trotz_vieler_bilder_nur_einmal_gezaehlt():
    t = tracker()
    frame = [det("K", 100, 50), det("9", 100, 300), det("7", 134, 300)]
    assert new_cards(t.update(frame, SIZE)) == [("K", "dealer"), ("9", "player"), ("7", "player")]
    for _ in range(5):
        assert t.update(frame, SIZE) == []
    # Kleine Verschiebung (Animation, Rundung) ist dieselbe Karte
    shifted = [det("K", 103, 51), det("9", 99, 302), det("7", 135, 300)]
    assert t.update(shifted, SIZE) == []


def test_neue_karten_werden_einzeln_hinzugefuegt():
    t = tracker()
    t.update([det("K", 100, 50), det("9", 100, 300)], SIZE)
    events = t.update([det("K", 100, 50), det("9", 100, 300), det("5", 134, 300)], SIZE)
    assert new_cards(events) == [("5", "player")]


def test_leerer_tisch_beendet_die_runde():
    t = tracker()
    t.update([det("K", 100, 50), det("Q", 134, 50), det("9", 100, 300), det("A", 134, 300)], SIZE)
    events = t.update([], SIZE)
    assert types(events) == [EventType.ROUND_END]
    # Nächste Runde: dieselben Positionen, neue Karten werden wieder gezählt
    events = t.update([det("K", 100, 50), det("9", 100, 300)], SIZE)
    assert len(new_cards(events)) == 2
    assert t.update([], SIZE)[-1].type == EventType.ROUND_END
    assert t.update([], SIZE) == []  # leerer Tisch ohne Karten: kein weiteres Rundenende


def test_treffer_ausserhalb_der_bereiche_werden_ignoriert():
    t = tracker()
    events = t.update([det("5", 100, 550), det("10", 500, 560)], SIZE)  # unten: Chips/Buttons
    assert events == []


def test_unsichere_karte_wird_erst_gezaehlt_wenn_sie_sicher_ist():
    t = tracker()
    events = t.update([det("8", 100, 300, score=0.72)], SIZE)
    assert types(events) == [EventType.UNCERTAIN]
    assert t.has_pending
    events = t.update([det("8", 101, 300, score=0.93)], SIZE)
    assert new_cards(events) == [("8", "player")]
    assert not t.has_pending


def test_knapper_abstand_zum_zweitbesten_rang_ist_unsicher():
    t = tracker()
    events = t.update([det("6", 100, 300, score=0.9, second=0.89)], SIZE)
    assert types(events) == [EventType.UNCERTAIN]


def test_unsicher_bis_rundenende_gilt_als_ungesehen():
    t = tracker()
    t.update([det("K", 100, 50), det("Q", 134, 50), det("8", 100, 300, score=0.7)], SIZE)
    events = t.update([], SIZE)
    assert types(events) == [EventType.UNCERTAIN, EventType.UNSEEN, EventType.ROUND_END]
    assert events[0].final
    assert events[1].count == 1 and events[1].info["reason"] == "unsicher"


def test_nicht_gezeigte_hole_card_ist_ungesehen():
    t = tracker(dealer_hole_card=True)
    t.update([det("4", 100, 50), det("10", 100, 300), det("6", 134, 300), det("K", 168, 300)], SIZE)
    events = t.update([], SIZE)
    unseen = [e for e in events if e.type == EventType.UNSEEN]
    assert len(unseen) == 1 and unseen[0].count == 1 and unseen[0].info["reason"] == "hole_card"


def test_ohne_hole_card_regel_keine_ungesehene_karte():
    t = tracker(dealer_hole_card=False)
    t.update([det("4", 100, 50), det("10", 100, 300)], SIZE)
    assert types(t.update([], SIZE)) == [EventType.ROUND_END]


def test_split_verschiebt_karte_ohne_doppelt_zu_zaehlen():
    t = tracker()
    t.update([det("K", 100, 50), det("8", 100, 300), det("8", 134, 300)], SIZE)
    # Split: zweite 8 wandert nach rechts in Hand 2, Hand 1 bekommt eine neue Karte (3)
    events = t.update([det("K", 100, 50), det("8", 100, 300), det("3", 134, 300),
                       det("8", 400, 300)], SIZE)
    assert new_cards(events) == [("3", "player")]
    assert t.player_hands() == [["8", "3"], ["8"]]
    events = t.update([det("K", 100, 50), det("8", 100, 300), det("3", 134, 300),
                       det("8", 400, 300), det("Q", 434, 300)], SIZE)
    assert new_cards(events) == [("Q", "player")]
    assert t.player_hands() == [["8", "3"], ["8", "Q"]]
    assert t.active_hand_index() == 1


def test_korrektur_einer_fehllesung():
    t = tracker()
    t.update([det("K", 100, 50), det("6", 100, 300, score=0.82)], SIZE)
    events = t.update([det("K", 100, 50), det("8", 100, 300, score=0.97)], SIZE)
    assert types(events) == [EventType.CORRECTION]
    assert events[0].old_rank == "6" and events[0].rank == "8"


def test_neue_runde_ohne_leeren_tisch_wird_erkannt():
    """Spiel räumt ab und teilt sofort neu aus: viele andere Ränge an alten Stellen."""
    t = tracker()
    t.update([det("K", 100, 50), det("A", 134, 50), det("10", 100, 300), det("K", 134, 300)], SIZE)
    events = t.update([det("Q", 100, 50), det("10", 134, 50), det("6", 100, 300),
                       det("K", 134, 300)], SIZE)
    assert EventType.ROUND_END in types(events)
    assert sorted(new_cards(events)) == sorted([("Q", "dealer"), ("10", "dealer"),
                                                ("6", "player"), ("K", "player")])


def test_dealerkarten_nach_x_sortiert():
    t = tracker()
    t.update([det("9", 168, 50), det("K", 100, 50), det("2", 134, 50)], SIZE)
    assert t.dealer_cards() == ["K", "2", "9"]


# ----------------------------------------------------------------------
# Verlaufs-Modus
# ----------------------------------------------------------------------


def panel(ranks, per_row=16, score=0.95, uncertain_at=None):
    """Treffer wie in einem Verlaufs-Panel (Kacheln in Zeilen)."""
    out = []
    for i, r in enumerate(ranks):
        s = 0.7 if i == uncertain_at else score
        out.append(det(r, 5 + (i % per_row) * 29, 4 + (i // per_row) * 41, score=s))
    return out


def counted(events):
    return [e.rank for e in events if e.type == EventType.NEW_CARD]


def test_lesereihenfolge_zeilenweise():
    dets = panel(list("23456789") + ["10", "J", "Q", "K", "A"] * 4)
    shuffled = list(reversed(dets))
    assert [d.rank for d in reading_order(shuffled)] == [d.rank for d in dets]


def test_nur_neue_eintraege_werden_gezaehlt():
    r = HistoryReader()
    assert counted(r.update(panel(["5", "K"]))) == ["5", "K"]
    assert counted(r.update(panel(["5", "K"]))) == []
    assert counted(r.update(panel(["5", "K", "2", "A", "9"]))) == ["2", "A", "9"]


def test_leeres_panel_bedeutet_mischen():
    r = HistoryReader()
    r.update(panel(["5", "K", "2"]))
    events = r.update([])
    assert [e.type for e in events] == [EventType.SHUFFLE]
    assert r.update([]) == []  # leer bleibt leer: nur einmal melden
    assert counted(r.update(panel(["7"]))) == ["7"]


def test_mischen_ohne_leeres_bild_dazwischen():
    r = HistoryReader()
    r.update(panel(["5", "K", "2", "A", "9", "3"]))
    events = r.update(panel(["Q", "4"]))
    assert events[0].type == EventType.SHUFFLE and events[0].info["implicit"]
    assert counted(events) == ["Q", "4"]


def test_scrollendes_panel_mit_fester_laenge():
    r = HistoryReader(min_overlap=4)
    first = ["2", "3", "4", "5", "6", "7", "8", "9"]
    r.update(panel(first))
    # Panel zeigt nur die letzten 8 Karten: 3 alte fallen vorne weg, 3 neue kommen hinzu
    window = first[3:] + ["K", "Q", "J"]
    assert counted(r.update(panel(window))) == ["K", "Q", "J"]


def test_unsicherer_eintrag_stoppt_bis_er_sicher_ist():
    r = HistoryReader(uncertain_frames=3)
    r.update(panel(["5", "K"]))
    events = r.update(panel(["5", "K", "8", "2"], uncertain_at=2))
    assert counted(events) == []  # Reihenfolge muss stimmen → bei der unsicheren Stelle warten
    assert events[-1].type == EventType.UNCERTAIN and not events[-1].final
    assert counted(r.update(panel(["5", "K", "8", "2"]))) == ["8", "2"]


def test_dauerhaft_unsicherer_eintrag_wird_als_ungesehen_uebersprungen():
    r = HistoryReader(uncertain_frames=2)
    r.update(panel(["5"]))
    r.update(panel(["5", "8", "2"], uncertain_at=1))
    events = r.update(panel(["5", "8", "2"], uncertain_at=1))
    assert [e.type for e in events] == [EventType.UNCERTAIN, EventType.UNSEEN, EventType.NEW_CARD]
    assert counted(events) == ["2"]
    # Danach geht es normal weiter, der unsichere Eintrag wird nicht nochmals gemeldet
    assert counted(r.update(panel(["5", "8", "2", "4"], uncertain_at=1))) == ["4"]


def test_voruebergehender_unsicherer_treffer_wird_verworfen():
    """Halb eingeblendete Karte (Animation) liefert kurz einen unsicheren Phantom-Treffer.
    Ist er im nächsten Bild weg, darf er am Rundenende nicht als ungesehen zählen."""
    t = tracker(dealer_hole_card=False)
    t.update([det("K", 100, 50), det("7", 160, 140, score=0.71)], SIZE)
    t.update([det("K", 100, 50), det("5", 134, 50)], SIZE)
    assert not t.has_pending
    assert types(t.update([], SIZE)) == [EventType.ROUND_END]
