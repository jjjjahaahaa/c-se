"""Zählung: Zählsysteme aus der Konfiguration, Running/True Count, Restdecks, Ass-Nebenzähler,
Mischen, Statistik."""

import json

import pytest

from blackjack_assistant.counting.counter import Counter
from blackjack_assistant.counting.systems import CARDS_PER_DECK, get_system, load_systems
from blackjack_assistant.models import RANKS, VALUE_RANKS
from blackjack_assistant.recognition.events import CardEvent, EventType

# Erwartete Werte (unabhängig von der Konfigurationsdatei notiert, siehe PLAN.md)
EXPECTED = {
    "hi_lo":       [1, 1, 1, 1, 1, 0, 0, 0, -1, -1],
    "ko":          [1, 1, 1, 1, 1, 1, 0, 0, -1, -1],
    "hi_opt_2":    [1, 1, 2, 2, 1, 1, 0, 0, -2, 0],
    "omega_2":     [1, 1, 2, 2, 2, 1, 0, -1, -2, 0],
    "zen":         [1, 1, 2, 2, 2, 1, 0, 0, -2, -1],
    "wong_halves": [0.5, 1, 1, 1.5, 1, 0.5, 0, -0.5, -1, -1],
}


def full_shoe(decks=6):
    return [r for _ in range(decks * 4) for r in RANKS]


@pytest.mark.parametrize("key", EXPECTED)
def test_kartenwerte_aus_der_konfiguration(key):
    system = get_system(key)
    assert [system.values[r] for r in VALUE_RANKS] == EXPECTED[key]
    assert system.value("K") == system.value("10") == system.value("J")


def test_alle_sechs_systeme_vorhanden():
    assert set(EXPECTED) <= set(load_systems())


def test_ausgeglichen_und_unausgeglichen():
    for key in EXPECTED:
        s = get_system(key)
        assert s.balanced == (key != "ko")
        expected_sum = 4 if key == "ko" else 0
        assert s.deck_sum == pytest.approx(expected_sum)


def test_ass_nebenzaehler_nur_bei_hi_opt_ii_und_omega_ii():
    assert {k for k in EXPECTED if get_system(k).ace_side_count} == {"hi_opt_2", "omega_2"}


@pytest.mark.parametrize("key,factor", [("hi_lo", 1.0), ("wong_halves", 1.0), ("hi_opt_2", 1.5),
                                        ("omega_2", 1.6), ("zen", 1.7)])
def test_umrechnungsfaktor_der_indizes(key, factor):
    assert get_system(key).index_factor == pytest.approx(factor)


def test_ganzer_schuh_ergibt_null_bzw_ko_endwert():
    for key in EXPECTED:
        c = Counter(key, decks=6, deck_rounding=0)
        for r in full_shoe():
            c.add(r)
        if key == "ko":
            assert c.running_count == pytest.approx(-20 + 24)   # IRC + 4 pro Deck
        else:
            assert c.running_count == pytest.approx(0)


def test_hi_lo_running_und_true_count():
    c = Counter("hi_lo", decks=6)
    for r in ["2", "5", "K", "A", "7", "3", "6", "Q", "4"]:
        c.add(r)
    assert c.running_count == 2      # +1 +1 -1 -1 0 +1 +1 -1 +1
    assert c.cards_seen == 9
    assert c.decks_remaining == 6.0  # 5.83 → auf halbe Decks gerundet
    assert c.true_count == pytest.approx(2 / 6)


def test_true_count_nach_zwei_gespielten_decks():
    c = Counter("hi_lo", decks=6)
    # 104 Karten: 8 kleine mehr als hohe → RC +8, 4 Decks übrig → TC +2
    for _ in range(8):
        c.add("5")
    for _ in range(96):
        c.add("8")
    assert c.decks_remaining == 4.0
    assert c.true_count == pytest.approx(2.0)


def test_restdecks_mindestens_halbes_deck():
    c = Counter("hi_lo", decks=1)
    for _ in range(50):
        c.add("8")
    assert c.decks_remaining == 0.5


def test_ungesehene_karten_zaehlen_nicht_verringern_aber_die_restdecks():
    c = Counter("hi_lo", decks=6, deck_rounding=0)
    c.add("5")
    c.add_unseen(51)
    assert c.running_count == 1
    assert c.cards_seen == 1 and c.cards_out == 52
    assert c.decks_remaining == pytest.approx(5.0)


def test_ereignisse_aus_der_erkennung():
    c = Counter("hi_lo", decks=6)
    c.apply(CardEvent(EventType.NEW_CARD, rank="6"))
    c.apply(CardEvent(EventType.NEW_CARD, rank="K"))
    c.apply(CardEvent(EventType.UNCERTAIN, rank="5"))                 # nicht zählen
    c.apply(CardEvent(EventType.CORRECTION, rank="2", old_rank="K"))  # K war falsch → 2
    c.apply(CardEvent(EventType.UNSEEN, count=1))
    assert c.running_count == 2
    assert c.cards_seen == 2 and c.unseen == 1
    c.apply(CardEvent(EventType.SHUFFLE))
    assert c.running_count == 0 and c.cards_out == 0


def test_mischen_setzt_ko_auf_startwert():
    c = Counter("ko", decks=6)
    assert c.running_count == -20
    assert c.true_count is None
    c.add("5")
    c.shuffle()
    assert c.running_count == -20


def test_spiel_mischt_jede_runde():
    c = Counter("hi_lo", decks=6, shuffle_every_round=True)
    for r in ["2", "3", "4"]:
        c.add(r)
    assert c.running_count == 3
    c.round_end()
    assert c.running_count == 0 and c.cards_out == 0
    assert c.ineffective
    assert c.state().ineffective


def test_mischstatistik_runden_pro_schuh(tmp_path):
    stats = tmp_path / "shuffle_stats.jsonl"
    c = Counter("hi_lo", decks=6, stats_file=stats)
    for rounds in (5, 7):
        for _ in range(rounds):
            c.add("8")
            c.round_end()
        c.shuffle("history_empty")
    lines = [json.loads(l) for l in stats.read_text().splitlines()]
    assert [l["rounds"] for l in lines] == [5, 7]
    s = c.shuffle_statistics()
    assert s == pytest.approx({"shoes": 2, "rounds_mean": 6.0, "rounds_min": 5, "rounds_max": 7,
                               "penetration_mean": s["penetration_mean"]})


def test_ass_ueberschuss_erhoeht_den_einsatz_count():
    """Hi-Opt II zählt Asse nicht mit (Wert 0). Sind viele kleine Karten und keine Asse
    gefallen, sind überdurchschnittlich viele Asse übrig → Einsatz-Count steigt."""
    plain = Counter("hi_opt_2", decks=6, deck_rounding=0)
    for _ in range(52):
        plain.add("8")
    assert plain.ace_surplus == pytest.approx(4.0)   # 24 Asse übrig, erwartet 20
    assert plain.betting_count == pytest.approx((0 + 2 * 4) / 5)
    assert plain.true_count == pytest.approx(0)


def test_restzusammensetzung_fuer_die_exakte_strategie():
    c = Counter("hi_lo", decks=6)
    for r in ["K", "Q", "A", "5"]:
        c.add(r)
    comp = c.remaining_composition()
    assert comp[VALUE_RANKS.index("10")] == CARDS_PER_DECK["10"] * 6 - 2
    assert comp[VALUE_RANKS.index("A")] == 23
    assert sum(comp) == 312 - 4


def test_pause_zaehlt_nichts():
    c = Counter("hi_lo")
    c.paused = True
    c.add("5")
    c.add_unseen(2)
    assert c.running_count == 0 and c.cards_out == 0
