"""Tests der exakten, zusammensetzungsabhängigen Strategie (simulation/exact.py).

Standardregeln (Rules()): 6 Decks, S17, DAS, Late Surrender, Peek, 3:2.
Konvention: Der übergebene Schuh enthält nur die für den Spieler unbekannten Karten,
die Spielerkarten und die Dealer-Upcard sind also bereits entfernt.
Die ganze Datei läuft in ca. 15 s (der grösste Teil sind die Effects of Removal).
"""

from __future__ import annotations

import random
import statistics
import time
from functools import lru_cache

import pytest

from blackjack_assistant.models import VALUE_RANKS, Action, HandState, Rules
from blackjack_assistant.simulation.exact import (
    ExactCalculator,
    full_shoe,
    rank_index,
    remove_cards,
)

VOLL = full_shoe(6)


def rest(*karten: str, schuh: tuple[int, ...] = VOLL) -> tuple[int, ...]:
    """Schuh ohne die angegebenen (sichtbaren) Karten."""
    return remove_cards(schuh, karten)


def zufaelliger_schuh(seed: int, entfernt: int, decks: int = 6) -> tuple[int, ...]:
    """Schuh, aus dem ``entfernt`` zufällige Karten gespielt wurden."""
    karten = [r for r, n in zip(VALUE_RANKS, full_shoe(decks)) for _ in range(n)]
    random.Random(seed).shuffle(karten)
    return remove_cards(full_shoe(decks), karten[:entfernt])


@pytest.fixture(scope="module")
def rechner() -> ExactCalculator:
    """Ein Rechner für die ganze Datei, damit sich die Zwischenspeicher lohnen."""
    return ExactCalculator(Rules())


# ----------------------------------------------------------------------
# Dealer
# ----------------------------------------------------------------------


@pytest.mark.parametrize("regeln", [
    Rules(), Rules(hit_soft_17=True), Rules(dealer_peek=False), Rules(decks=1),
], ids=["S17", "H17", "ohne_peek", "ein_deck"])
@pytest.mark.parametrize("upcard", VALUE_RANKS)
def test_dealer_wahrscheinlichkeiten_summieren_zu_eins(regeln, upcard):
    rechner = ExactCalculator(regeln)
    p = rechner.dealer_probabilities(rest(upcard, schuh=full_shoe(regeln.decks)), upcard)
    assert sum(p.values()) == pytest.approx(1.0, abs=1e-12)
    assert all(v >= 0 for v in p.values())
    erwartete = {"17", "18", "19", "20", "21", "bust"}
    if not regeln.dealer_peek and upcard in ("10", "A"):
        erwartete.add("blackjack")
    assert set(p) == erwartete


def test_dealer_bust_wahrscheinlichkeiten_bekannte_werte(rechner):
    # Bekannte Werte 6 Decks S17: Bust bei Upcard 2 ≈ 35.4 %, bei 6 ≈ 42.3 %
    assert rechner.dealer_probabilities(rest("2"), "2")["bust"] == pytest.approx(0.354, abs=0.003)
    assert rechner.dealer_probabilities(rest("6"), "6")["bust"] == pytest.approx(0.423, abs=0.003)


@pytest.mark.parametrize("upcard", ["6", "A"])
def test_dealer_s17_und_h17_unterscheiden_sich(upcard):
    s17 = ExactCalculator(Rules(hit_soft_17=False)).dealer_probabilities(rest(upcard), upcard)
    h17 = ExactCalculator(Rules(hit_soft_17=True)).dealer_probabilities(rest(upcard), upcard)
    # H17: Soft 17 wird weitergezogen → weniger 17, mehr Bust und mehr 18–21
    assert h17["17"] < s17["17"] - 0.03
    assert h17["bust"] > s17["bust"]
    for total in ("18", "19", "20", "21"):
        assert h17[total] > s17[total]


def test_dealer_ohne_peek_blackjack_wahrscheinlichkeit():
    rechner = ExactCalculator(Rules(dealer_peek=False))
    schuh = rest("A")
    p = rechner.dealer_probabilities(schuh, "A")
    assert p["blackjack"] == pytest.approx(96 / 311)
    # Mit Peek ist die Verteilung genau die auf "kein Blackjack" bedingte
    mit_peek = ExactCalculator(Rules()).dealer_probabilities(schuh, "A")
    for k in mit_peek:
        assert mit_peek[k] == pytest.approx(p[k] / (1 - p["blackjack"]))


# ----------------------------------------------------------------------
# Entscheidungen im vollen Schuh (6D, S17, DAS, LS, Peek, 3:2)
# ----------------------------------------------------------------------

BEKANNTE_ENTSCHEIDUNGEN = [
    (["10", "6"], "10", Action.SURRENDER),
    (["10", "5"], "10", Action.SURRENDER),
    (["6", "5"], "6", Action.DOUBLE),
    (["9", "3"], "4", Action.STAND),
    (["10", "2"], "3", Action.HIT),
    (["A", "7"], "9", Action.HIT),
    (["A", "7"], "2", Action.STAND),
    (["A", "7"], "3", Action.DOUBLE),
    (["8", "8"], "10", Action.SPLIT),
    (["9", "9"], "7", Action.STAND),
    (["A", "A"], "6", Action.SPLIT),
    (["10", "10"], "6", Action.STAND),
    (["5", "4"], "2", Action.HIT),
    (["6", "4"], "9", Action.DOUBLE),
    (["6", "5"], "A", Action.HIT),
    (["7", "4"], "A", Action.HIT),
    (["K", "Q"], "5", Action.STAND),
    (["2", "2"], "4", Action.SPLIT),
]


@pytest.mark.parametrize("spieler,upcard,erwartet", BEKANNTE_ENTSCHEIDUNGEN,
                         ids=[f"{'+'.join(s)}_gegen_{u}" for s, u, _ in BEKANNTE_ENTSCHEIDUNGEN])
def test_bekannte_entscheidungen_voller_schuh(rechner, spieler, upcard, erwartet):
    hand = HandState(player=spieler, dealer_up=upcard)
    aktion, evs = rechner.best_action(rest(*spieler, upcard), hand)
    assert aktion == erwartet, evs


def test_zusammensetzung_zaehlt_zwoelf_gegen_vier(rechner):
    """10,2 gegen 4 ist eine echte Composition-Ausnahme (Ziehen), 9,3 und 7,5 stehen."""
    zehn_zwei = rechner.action_evs(rest("10", "2", "4"), ["10", "2"], "4")
    assert zehn_zwei[Action.HIT] > zehn_zwei[Action.STAND]
    for hand in (["9", "3"], ["7", "5"]):
        evs = rechner.action_evs(rest(*hand, "4"), hand, "4")
        assert evs[Action.STAND] > evs[Action.HIT]


def test_ev_werte_sechzehn_gegen_zehn(rechner):
    evs = rechner.action_evs(rest("10", "6", "10"), ["10", "6"], "10")
    assert evs[Action.STAND] == pytest.approx(-0.54, abs=0.01)
    assert evs[Action.HIT] == pytest.approx(-0.54, abs=0.01)
    assert evs[Action.SURRENDER] == -0.5
    # Verdoppeln auf 16 setzt den doppelten Einsatz aufs Spiel: klar schlechter als Ziehen
    assert -2.0 <= evs[Action.DOUBLE] < evs[Action.HIT] - 0.3


def test_double_ist_zwei_mal_ev_mit_einer_karte(rechner):
    """Double-EV nachrechnen: 2 × Σ P(Karte) × Stand-EV der Hand mit dieser Karte."""
    schuh = rest("6", "5", "7")
    n = sum(schuh)
    summe = 0.0
    for i, rang in enumerate(VALUE_RANKS):
        if schuh[i]:
            stand = rechner.action_evs(remove_cards(schuh, [rang]), ["6", "5", rang], "7")
            summe += schuh[i] / n * stand[Action.STAND]
    evs = rechner.action_evs(schuh, ["6", "5"], "7")
    assert evs[Action.DOUBLE] == pytest.approx(2 * summe, abs=1e-12)


# ----------------------------------------------------------------------
# Unabhängige Brute-Force-Kontrolle (1 Deck, damit es schnell geht)
# ----------------------------------------------------------------------

_PUNKTE = (2, 3, 4, 5, 6, 7, 8, 9, 10, 1)


@lru_cache(maxsize=None)
def _dealer_brute(schuh, hart, ass, karten):
    """Dealer-Verteilung durch direkte Rekursion über jede einzelne Karte (S17)."""
    total = hart + 10 if ass and hart <= 11 else hart
    if karten >= 2 and (hart > 21 or total >= 17):
        return {"bust" if hart > 21 else total: 1.0}
    n = sum(schuh)
    ergebnis: dict = {}
    for i in range(10):
        if schuh[i]:
            neu = schuh[:i] + (schuh[i] - 1,) + schuh[i + 1:]
            for k, v in _dealer_brute(neu, hart + _PUNKTE[i], ass or i == 9, karten + 1).items():
                ergebnis[k] = ergebnis.get(k, 0.0) + schuh[i] / n * v
    return ergebnis


def _stand_brute(schuh, up, total):
    ev = 0.0
    for k, v in _dealer_brute(schuh, _PUNKTE[up], up == 9, 1).items():
        if k == "bust" or total > k:
            ev += v
        elif total < k:
            ev -= v
    return ev


@lru_cache(maxsize=None)
def _best_brute(schuh, up, hart, ass):
    total = hart + 10 if ass and hart <= 11 else hart
    stand = _stand_brute(schuh, up, total)
    return stand if total >= 21 else max(stand, _hit_brute(schuh, up, hart, ass))


def _hit_brute(schuh, up, hart, ass):
    n = sum(schuh)
    ev = 0.0
    for i in range(10):
        if schuh[i]:
            p = schuh[i] / n
            if hart + _PUNKTE[i] > 21:
                ev -= p
            else:
                neu = schuh[:i] + (schuh[i] - 1,) + schuh[i + 1:]
                ev += p * _best_brute(neu, up, hart + _PUNKTE[i], ass or i == 9)
    return ev


@pytest.mark.parametrize("modus", ["exact", "linear"])
@pytest.mark.parametrize("spieler,upcard", [(["10", "2"], "4"), (["7", "5"], "6"), (["A", "6"], "3")])
def test_brute_force_vergleich_ein_deck(modus, spieler, upcard):
    rechner = ExactCalculator(Rules(decks=1), dealer_mode=modus)
    schuh = rest(*spieler, upcard, schuh=full_shoe(1))
    evs = rechner.action_evs(schuh, spieler, upcard)
    up = rank_index(upcard)
    hart = sum(_PUNKTE[rank_index(k)] for k in spieler)
    ass = "A" in spieler
    total = hart + 10 if ass and hart <= 11 else hart
    toleranz = 1e-12 if modus == "exact" else 2e-3
    assert evs[Action.STAND] == pytest.approx(_stand_brute(schuh, up, total), abs=1e-12)
    assert evs[Action.HIT] == pytest.approx(_hit_brute(schuh, up, hart, ass), abs=toleranz)


def test_peek_bedingung_wie_physikalisches_modell():
    """Double 11 gegen Ass (1 Deck, Peek): Hole Card zuerst ziehen (kein Zehner), dann
    die Spielerkarte – muss genau die bedingten Wahrscheinlichkeiten der Rekursion geben."""
    rechner = ExactCalculator(Rules(decks=1), dealer_mode="exact")
    schuh = rest("6", "5", "A", schuh=full_shoe(1))
    n = sum(schuh)
    ev = 0.0
    for h in range(10):                              # Hole Card ≠ Zehner (Index 8)
        if not schuh[h] or h == 8:
            continue
        p_h = schuh[h] / (n - schuh[8])
        ohne_h = schuh[:h] + (schuh[h] - 1,) + schuh[h + 1:]
        for c in range(10):
            if ohne_h[c]:
                p_c = ohne_h[c] / (n - 1)
                total = 11 + _PUNKTE[c] if c != 9 else 12
                ohne_hc = ohne_h[:c] + (ohne_h[c] - 1,) + ohne_h[c + 1:]
                dealer = _dealer_brute(ohne_hc, 1 + _PUNKTE[h], True, 2)
                for k, v in dealer.items():
                    ev += p_h * p_c * v * (1 if k == "bust" or total > k else -1 if total < k else 0)
    assert rechner.action_evs(schuh, ["6", "5"], "A")[Action.DOUBLE] == pytest.approx(2 * ev, abs=1e-12)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_lineare_dealer_nachfuehrung_nahe_exakt(seed):
    linear = ExactCalculator(Rules(), dealer_mode="linear")
    exakt = ExactCalculator(Rules(), dealer_mode="exact")
    schuh = zufaelliger_schuh(seed, 150)
    for spieler, upcard in [(["10", "3"], "2"), (["9", "2"], "10"), (["A", "6"], "5")]:
        try:
            s = remove_cards(schuh, [*spieler, upcard])
        except ValueError:
            continue
        a = linear.action_evs(s, spieler, upcard)
        b = exakt.action_evs(s, spieler, upcard)
        for aktion in b:
            assert a[aktion] == pytest.approx(b[aktion], abs=1e-3)
        assert max(a, key=a.get) == max(b, key=b.get)


# ----------------------------------------------------------------------
# Regeln und erlaubte Aktionen
# ----------------------------------------------------------------------


def test_erlaubte_aktionen_nach_regeln():
    standard = ExactCalculator(Rules())
    # Kein Surrender nach Split und nicht mit mehr als zwei Karten
    evs = standard.action_evs(rest("10", "6", "10"), ["10", "6"], "10", from_split=True, hand_count=2)
    assert Action.SURRENDER not in evs
    evs = standard.action_evs(rest("10", "3", "3", "10"), ["10", "3", "3"], "10")
    assert set(evs) == {Action.STAND, Action.HIT}
    # Split-Grenze erreicht
    evs = standard.action_evs(rest("8", "8", "10"), ["8", "8"], "10", from_split=True, hand_count=4)
    assert Action.SPLIT not in evs
    # Gesplittete Asse: nur stehen (kein Re-Split ohne resplit_aces)
    evs = standard.action_evs(rest("A", "A", "6"), ["A", "A"], "6", from_split=True, hand_count=2)
    assert set(evs) == {Action.STAND}
    # Mit resplit_aces darf weiter geteilt werden
    rsa = ExactCalculator(Rules(resplit_aces=True))
    evs = rsa.action_evs(rest("A", "A", "6"), ["A", "A"], "6", from_split=True, hand_count=2)
    assert set(evs) == {Action.STAND, Action.SPLIT}
    # Double nur auf 9–11, wenn double_any_two aus ist
    nur_9_11 = ExactCalculator(Rules(double_any_two=False))
    assert Action.DOUBLE not in nur_9_11.action_evs(rest("A", "7", "3"), ["A", "7"], "3")
    assert Action.DOUBLE in nur_9_11.action_evs(rest("6", "4", "3"), ["6", "4"], "3")
    # Ohne DAS kein Double nach Split
    ohne_das = ExactCalculator(Rules(double_after_split=False))
    assert Action.DOUBLE not in ohne_das.action_evs(rest("6", "5", "6"), ["6", "5"], "6",
                                                     from_split=True, hand_count=2)
    # Flags des Aufrufers werden respektiert
    evs = standard.action_evs(rest("6", "5", "6"), ["6", "5"], "6", can_double=False,
                              can_surrender=False)
    assert set(evs) == {Action.STAND, Action.HIT}


def test_split_regeln_veraendern_split_ev():
    schuh = rest("2", "2", "6")
    mit_das = ExactCalculator(Rules()).action_evs(schuh, ["2", "2"], "6")[Action.SPLIT]
    ohne_das = ExactCalculator(Rules(double_after_split=False)).action_evs(
        schuh, ["2", "2"], "6")[Action.SPLIT]
    assert mit_das > ohne_das
    schuh = rest("A", "A", "6")
    normal = ExactCalculator(Rules()).action_evs(schuh, ["A", "A"], "6")[Action.SPLIT]
    hit_asse = ExactCalculator(Rules(hit_split_aces=True)).action_evs(
        schuh, ["A", "A"], "6")[Action.SPLIT]
    assert hit_asse > normal
    schuh = rest("8", "8", "10")
    resplit = ExactCalculator(Rules(max_hands=4)).action_evs(schuh, ["8", "8"], "10")[Action.SPLIT]
    kein_resplit = ExactCalculator(Rules(max_hands=2)).action_evs(schuh, ["8", "8"], "10")[Action.SPLIT]
    assert resplit > kein_resplit


def test_seven_card_charlie_veraendert_hit_ev():
    hand = ["2", "2", "2", "3", "3", "A"]            # 6 Karten, hart 13
    schuh = rest(*hand, "10")
    ohne = ExactCalculator(Rules()).action_evs(schuh, hand, "10")
    mit = ExactCalculator(Rules(seven_card_charlie=True)).action_evs(schuh, hand, "10")
    assert mit[Action.STAND] == pytest.approx(ohne[Action.STAND])
    # Mit Charlie gewinnt jede siebte Karte ausser 9/10 sofort → Ziehen wird klar positiv
    assert ohne[Action.HIT] < 0 < mit[Action.HIT]
    assert mit[Action.HIT] > ohne[Action.HIT] + 0.3
    # Auch früher in der Rekursion wirkt Charlie (5 Karten, hart 12)
    hand5 = ["2", "2", "3", "3", "2"]
    schuh5 = rest(*hand5, "10")
    ohne5 = ExactCalculator(Rules()).action_evs(schuh5, hand5, "10")[Action.HIT]
    mit5 = ExactCalculator(Rules(seven_card_charlie=True)).action_evs(schuh5, hand5, "10")[Action.HIT]
    assert mit5 > ohne5 + 0.01


# ----------------------------------------------------------------------
# Versicherung
# ----------------------------------------------------------------------


def test_versicherung_voller_schuh_negativ(rechner):
    # 3 · 96/312 − 1 = −0.0769 (Toleranz 0.001)
    assert rechner.insurance_ev(VOLL) == pytest.approx(-0.0769, abs=0.001)
    assert rechner.insurance_ev(rest("A", "9", "7")) < 0


def test_versicherung_positiv_bei_vielen_zehnern(rechner):
    zehnerreich = rest(*(["2", "3", "4", "5", "6"] * 8))
    assert rechner.insurance_ev(remove_cards(zehnerreich, ["A", "9", "7"])) > 0.03


# ----------------------------------------------------------------------
# Erwartungswert vor dem Austeilen, EOR und lineare Näherung
# ----------------------------------------------------------------------


def test_predeal_voller_schuh_im_erwarteten_bereich(rechner):
    ev = rechner.predeal_ev(VOLL)
    # Hausvorteil 6D S17 DAS LS ≈ 0.3–0.4 % (Ergebnis: −0.337 %)
    assert -0.006 <= ev <= -0.002


@pytest.mark.parametrize("regeln,differenz", [
    (Rules(hit_soft_17=True), -0.0019),            # H17 kostet ca. 0.2 %
    (Rules(blackjack_pays=1.2), -0.0136),          # 6:5 kostet ca. 1.4 %
    (Rules(late_surrender=False), -0.0007),        # Late Surrender bringt ca. 0.07 %
], ids=["H17", "6zu5", "ohne_surrender"])
def test_predeal_regelvarianten(rechner, regeln, differenz):
    ev = ExactCalculator(regeln).predeal_ev(VOLL)
    assert ev - rechner.predeal_ev(VOLL) == pytest.approx(differenz, abs=0.0005)


def test_zehnerreicher_schuh(rechner):
    zehnerreich = rest(*(["2", "3", "4", "5", "6"] * 6))     # 30 kleine Karten weg
    assert rechner.predeal_ev(zehnerreich) > rechner.predeal_ev(VOLL) + 0.02
    # 16 gegen 10: im vollen Schuh ziehen besser als stehen, hier umgekehrt
    voll = rechner.action_evs(rest("10", "6", "10"), ["10", "6"], "10")
    reich = rechner.action_evs(remove_cards(zehnerreich, ["10", "6", "10"]), ["10", "6"], "10")
    assert voll[Action.HIT] > voll[Action.STAND]
    assert reich[Action.STAND] > reich[Action.HIT]
    hand = HandState(player=["10", "6"], dealer_up="10", can_surrender=False)
    assert rechner.best_action(remove_cards(zehnerreich, ["10", "6", "10"]), hand)[0] == Action.STAND


def test_effects_of_removal_vorzeichen(rechner):
    eor = rechner.effects_of_removal()
    assert set(eor) == set(VALUE_RANKS)
    assert max(eor, key=eor.get) == "5"
    for klein in ("2", "3", "4", "5", "6"):
        assert eor[klein] > 0
    assert eor["10"] < 0 and eor["A"] < 0
    # Grössenordnung bei 6 Decks: 5 ≈ +0.14 %, Zehner ≈ −0.09 % pro Karte
    assert eor["5"] == pytest.approx(0.00145, abs=0.0003)
    assert eor["10"] == pytest.approx(-0.00092, abs=0.0003)
    # Gecacht: zweiter Aufruf liefert dieselben Werte
    assert rechner.effects_of_removal() == eor


@pytest.mark.parametrize("seed,entfernt", [(1, 52), (2, 52), (3, 104), (4, 104)])
def test_predeal_linear_nahe_exakt(rechner, seed, entfernt):
    schuh = zufaelliger_schuh(seed, entfernt)
    # Toleranz 0.003 für bis zu 2 gespielte Decks (gemessen: höchstens ca. 0.002)
    assert rechner.predeal_ev_linear(schuh) == pytest.approx(rechner.predeal_ev(schuh), abs=0.003)


def test_predeal_linear_voller_schuh_und_schnell(rechner):
    assert rechner.predeal_ev_linear(VOLL) == pytest.approx(rechner.predeal_ev(VOLL))
    schuhe = [zufaelliger_schuh(seed, 120) for seed in range(50)]
    start = time.perf_counter()
    for schuh in schuhe:
        rechner.predeal_ev_linear(schuh)
    mittel = (time.perf_counter() - start) / len(schuhe)
    assert mittel < 0.001


# ----------------------------------------------------------------------
# Laufzeit und Eingaben
# ----------------------------------------------------------------------


def _zufaellige_situationen(anzahl: int, seed: int = 7):
    rng = random.Random(seed)
    karten = [r for r, n in zip(VALUE_RANKS, VOLL) for _ in range(n)]
    situationen = []
    while len(situationen) < anzahl:
        rng.shuffle(karten)
        gespielt = rng.randint(0, 234)
        p1, up, p2 = karten[gespielt:gespielt + 3]
        if {p1, p2} == {"10", "A"}:
            continue
        schuh = remove_cards(VOLL, karten[:gespielt] + [p1, up, p2])
        situationen.append((schuh, [p1, p2], up))
    return situationen


def test_performance_action_evs():
    """200 zufällige Situationen; Ziel ≤ 30 ms im Mittel, getestet grosszügig mit 100 ms."""
    rechner = ExactCalculator(Rules())
    situationen = _zufaellige_situationen(200)
    zeiten = []
    for schuh, spieler, upcard in situationen:
        start = time.perf_counter()
        rechner.action_evs(schuh, spieler, upcard)
        zeiten.append(time.perf_counter() - start)
    assert statistics.mean(zeiten) < 0.1


def test_ungueltige_eingaben(rechner):
    with pytest.raises(ValueError):
        rechner.action_evs((24,) * 9, ["10", "6"], "10")
    with pytest.raises(ValueError):
        rechner.action_evs(rest("10", "8", "6", "10"), ["10", "8", "6"], "10")
    with pytest.raises(ValueError):
        rechner.action_evs(VOLL, ["10"], "10")
    with pytest.raises(ValueError):
        ExactCalculator(Rules(), dealer_mode="ungefaehr")
    with pytest.raises(ValueError):
        remove_cards((0,) * 10, ["5"])
