"""Basic Strategy, Regelanpassungen, Abweichungen (Illustrious 18 / Fab 4) und Einsatz."""

from dataclasses import replace

import pytest

from blackjack_assistant.counting.counter import Counter, CountState
from blackjack_assistant.models import Action, HandState, Rules
from blackjack_assistant.strategy.basic import DEALER_COLUMNS, basic_action, load_table
from blackjack_assistant.strategy.betting import BetRamp
from blackjack_assistant.strategy.engine import StrategyEngine

S17 = Rules()
H17 = Rules(hit_soft_17=True)
NO_DAS = Rules(double_after_split=False)
NO_LS = Rules(late_surrender=False)

H, S, D, P, R = Action.HIT, Action.STAND, Action.DOUBLE, Action.SPLIT, Action.SURRENDER


def hand(cards, up, **kw):
    return HandState(list(cards), up, **kw)


def count_state(tc: float, system: str = "hi_lo", decks: float = 3.0, **kw) -> CountState:
    """Zählstand mit einem bestimmten True Count (Running Count = TC × Restdecks)."""
    c = Counter(system, decks=6)
    state = c.state()
    rc = tc * decks
    return replace(state, running_count=rc, true_count=tc if state.balanced else None,
                   decks_remaining=decks, betting_count=tc if state.balanced else rc, **kw)


# ----------------------------------------------------------------------
# Tabelle
# ----------------------------------------------------------------------


def test_tabelle_ist_vollstaendig():
    t = load_table()
    assert set(t["hard"]) == {str(v) for v in range(4, 22)}
    assert set(t["soft"]) == {str(v) for v in range(12, 22)}
    assert set(t["pairs"]) == {"2", "3", "4", "5", "6", "7", "8", "9", "10", "A"}
    assert t["dealer"] == list(DEALER_COLUMNS)


@pytest.mark.parametrize("cards,up,expected", [
    (["10", "6"], "10", R), (["10", "6"], "9", R), (["9", "7"], "A", R), (["10", "5"], "10", R),
    (["10", "6"], "6", S), (["10", "2"], "4", S), (["10", "2"], "3", H), (["10", "2"], "2", H),
    (["6", "5"], "6", D), (["6", "5"], "A", H), (["6", "4"], "9", D), (["6", "4"], "10", H),
    (["5", "4"], "2", H), (["5", "4"], "3", D), (["7", "2"], "7", H),
    (["A", "7"], "2", S), (["A", "7"], "3", D), (["A", "7"], "9", H), (["A", "8"], "6", S),
    (["A", "2"], "5", D), (["A", "2"], "4", H), (["A", "6"], "3", D),
    (["8", "8"], "10", P), (["8", "8"], "A", P), (["9", "9"], "7", S), (["9", "9"], "8", P),
    (["A", "A"], "6", P), (["K", "Q"], "6", S), (["5", "5"], "9", D), (["4", "4"], "5", P),
    (["2", "2"], "2", P), (["6", "6"], "2", P), (["7", "7"], "8", H),
    (["10", "7"], "A", S), (["10", "3", "5"], "2", S), (["A", "5", "5"], "10", S),
])
def test_basic_strategy_6_decks_s17_das_ls(cards, up, expected):
    assert basic_action(hand(cards, up), S17) == expected


def test_verdoppeln_mit_drei_karten_wird_ziehen_oder_stehen():
    assert basic_action(hand(["2", "3", "6"], "6"), S17) == H     # 11 mit 3 Karten: D → H
    assert basic_action(hand(["A", "2", "4"], "4"), S17) == H     # Soft 17 vs 4: D → H
    assert basic_action(hand(["A", "3", "3"], "4"), S17) == H     # soft 17 vs 4: D → H
    assert basic_action(hand(["A", "4", "2"], "3"), S17) == H


def test_soft_18_mit_drei_karten_stehen_statt_verdoppeln():
    assert basic_action(hand(["A", "4", "3"], "4"), S17) == S     # Ds → S


def test_h17_anpassungen():
    assert basic_action(hand(["6", "5"], "A"), H17) == D
    assert basic_action(hand(["10", "5"], "A"), H17) == R
    assert basic_action(hand(["10", "7"], "A"), H17) == R
    assert basic_action(hand(["A", "7"], "2"), H17) == D
    assert basic_action(hand(["A", "8"], "6"), H17) == D
    assert basic_action(hand(["8", "8"], "A"), H17) == R


def test_ohne_double_after_split():
    assert basic_action(hand(["2", "2"], "2"), NO_DAS) == H
    assert basic_action(hand(["4", "4"], "5"), NO_DAS) == H
    assert basic_action(hand(["6", "6"], "2"), NO_DAS) == H
    assert basic_action(hand(["2", "2"], "4"), NO_DAS) == P


def test_ohne_surrender():
    assert basic_action(hand(["10", "6"], "10"), NO_LS) == H
    assert basic_action(hand(["10", "6"], "10", can_surrender=False), S17) == H
    assert basic_action(hand(["10", "6"], "10", from_split=True, hand_count=2), S17) == H


def test_teilen_nicht_moeglich_paar_als_summe():
    assert basic_action(hand(["8", "8"], "10", can_split=False), S17) == R
    assert basic_action(hand(["8", "8"], "10", can_split=False, can_surrender=False), S17) == H
    assert basic_action(hand(["5", "5"], "6", can_split=False), S17) == D
    assert basic_action(hand(["A", "A"], "6", can_split=False), S17) == H   # soft 12


def test_basic_strategy_stimmt_mit_exakter_berechnung_ueberein():
    """Unabhängige Prüfung der Tabelle: Für alle Zwei-Karten-Hände gegen alle Upcards wird
    die beste Aktion aus der exakten Restzusammensetzung (voller 6-Deck-Schuh) berechnet.
    Basic Strategy ist eine totalabhängige Näherung – wenige knappe Ausnahmen sind normal."""
    from blackjack_assistant.simulation.exact import ExactCalculator, full_shoe, remove_cards

    calc = ExactCalculator(S17)
    ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "A"]
    total, diffs = 0, []
    for i, a in enumerate(ranks):
        for b in ranks[i:]:
            for up in ranks:
                h = hand([a, b], up)
                shoe = remove_cards(full_shoe(6), [a, b, up])
                best, evs = calc.best_action(shoe, h)
                ours = basic_action(h, S17)
                total += 1
                if ours != best:
                    diffs.append((a, b, up, ours.value, best.value, evs[best] - evs.get(ours, -9)))
    # Unterschiede dürfen nur sehr knapp sein (weniger als 0.5 % des Einsatzes)
    big = [d for d in diffs if d[-1] > 0.005]
    assert big == [], big
    assert len(diffs) <= 0.03 * total, diffs


# ----------------------------------------------------------------------
# Abweichungen
# ----------------------------------------------------------------------


def engine(rules=S17, system="hi_lo"):
    return StrategyEngine(rules, system)


@pytest.mark.parametrize("cards,up,tc,expected,source", [
    # 16 vs 10: mit Surrender immer aufgeben, ohne Surrender ab TC 0 stehen
    (["10", "6"], "10", -2, R, "basic"),
    (["10", "6"], "10", 2, R, "basic"),
    (["9", "7"], "9", 6, R, "basic"),
    # Fab 4: 15 vs 10 erst ab TC 0 aufgeben, darunter ziehen
    (["10", "5"], "10", -1, H, "basic"),
    (["10", "5"], "10", 0, R, "basic"),
    (["10", "4"], "10", 3, R, "deviation"),
    (["10", "4"], "10", 2, H, "basic"),
    (["10", "5"], "9", 2, R, "deviation"),
    (["10", "5"], "A", 1, R, "deviation"),
    # Illustrious 18
    (["10", "2"], "4", -0.5, H, "deviation"),
    (["10", "2"], "4", 0, S, "basic"),
    (["10", "2"], "3", 2, S, "deviation"),
    (["10", "2"], "2", 3, S, "deviation"),
    (["10", "3"], "2", -1.5, H, "deviation"),
    (["6", "5"], "A", 1, D, "deviation"),
    (["6", "4"], "10", 4, D, "deviation"),
    (["5", "4"], "2", 1, D, "deviation"),
    (["5", "4"], "7", 3, D, "deviation"),
    (["K", "Q"], "6", 4, P, "deviation"),
    (["K", "Q"], "5", 4.9, S, "basic"),
    (["K", "Q"], "5", 5, P, "deviation"),
])
def test_illustrious_18_und_fab_4(cards, up, tc, expected, source):
    d = engine().decide(hand(cards, up), count_state(tc))
    assert (d.action, d.source) == (expected, source)


def test_16_gegen_10_ohne_surrender():
    e = engine(NO_LS)
    assert e.decide(hand(["10", "6"], "10"), count_state(-0.5)).action == H
    assert e.decide(hand(["10", "6"], "10"), count_state(0)).action == S
    assert e.decide(hand(["10", "5"], "10"), count_state(4)).action == S


def test_16_gegen_10_mit_drei_karten_stehen_ab_tc_0():
    e = engine()
    assert e.decide(hand(["4", "2", "10"], "10"), count_state(1)).action == S
    assert e.decide(hand(["4", "2", "10"], "10"), count_state(-1)).action == H


def test_abweichung_nur_wenn_aktion_erlaubt():
    e = engine()
    # 10 vs 10 mit drei Karten: Verdoppeln nicht möglich → Basic (Ziehen)
    assert e.decide(hand(["4", "3", "3"], "10"), count_state(6)).action == H
    # 8,8 wird nicht als "hart 16" behandelt
    assert e.decide(hand(["8", "8"], "10"), count_state(2)).action == P


def test_versicherung_ab_true_count_3():
    e = engine()
    assert not e.take_insurance(count_state(2.9))
    assert e.take_insurance(count_state(3))


def test_level_2_system_rechnet_index_um():
    """Zen: Faktor 1.7 → 11 vs A verdoppeln ab Zen-TC 1.7 (statt 1)."""
    e = engine(system="zen")
    s = count_state(1.5, system="zen")
    assert e.decide(hand(["6", "5"], "A"), replace(s, index_factor=1.7)).action == H
    s = count_state(1.8, system="zen")
    assert e.decide(hand(["6", "5"], "A"), replace(s, index_factor=1.7)).action == D


def test_ko_mit_festen_schwellen():
    from blackjack_assistant.counting.systems import get_system

    ko = get_system("ko")
    assert ko.ko_threshold(4, 6) == pytest.approx(4)        # Pivot unabhängig von der Tiefe
    e = engine(system="ko")
    base = Counter("ko", decks=6).state()
    assert base.true_count is None
    # Versicherung über die KO-Schwelle +3
    assert not e.take_insurance(replace(base, running_count=2))
    assert e.take_insurance(replace(base, running_count=3))
    # 10,10 vs 6 teilen erst bei sehr hohem RC (≈ Pivot)
    assert e.decide(hand(["K", "Q"], "6"), replace(base, running_count=0)).action == S
    assert e.decide(hand(["K", "Q"], "6"), replace(base, running_count=4)).action == P


def test_zaehlen_wirkungslos_nur_basic_strategy():
    e = engine()
    s = count_state(5, ineffective=True)
    d = e.decide(hand(["K", "Q"], "6"), s)
    assert (d.action, d.source) == (S, "basic")
    assert not e.take_insurance(s)


def test_ohne_count_nur_basic_strategy():
    assert engine().decide(hand(["10", "2"], "3"), None).action == H


# ----------------------------------------------------------------------
# Einsatz
# ----------------------------------------------------------------------


@pytest.mark.parametrize("tc,units", [(-3, 1), (0, 1), (1, 1), (1.9, 1), (2, 2), (3.5, 4),
                                      (4, 6), (5, 8), (9, 8)])
def test_einsatz_staffelung(tc, units):
    ramp = BetRamp(unit=10)
    advice = ramp.advise(count_state(tc))
    assert advice.units == units and advice.amount == units * 10


def test_einsatz_staffelung_aus_profil():
    from blackjack_assistant.profiles import Profile

    p = Profile(name="x", betting={"unit": 5, "ramp": [[1, 3], [3, 12]]})
    ramp = BetRamp.from_profile(p)
    assert ramp.advise(count_state(1)).amount == 15
    assert ramp.advise(count_state(3)).amount == 60


def test_einsatz_bei_wirkungslosem_zaehlen_minimal():
    advice = BetRamp().advise(count_state(6, ineffective=True))
    assert advice.units == 1 and "mischt" in advice.note


def test_einsatz_ko_ueber_running_count():
    base = Counter("ko", decks=6).state()
    ramp = BetRamp(decks=6)
    assert ramp.advise(replace(base, running_count=-10, betting_count=-10)).units == 1
    assert ramp.advise(replace(base, running_count=4, betting_count=4)).units == 6
