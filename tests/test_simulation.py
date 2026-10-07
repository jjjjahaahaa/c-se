"""Simulation (Phase 6): Regeln des Simulators mit vorgegebenen Karten, Reproduzierbarkeit,
Spielertypen, Kennzahlen und Bericht."""

from dataclasses import replace

import numpy as np
import pytest

from blackjack_assistant.models import Action, Rules
from blackjack_assistant.simulation.players import ExactPlayer, StrategyPlayer
from blackjack_assistant.simulation.report import betting_correlations, main as report_main
from blackjack_assistant.simulation.simulator import Simulator, simulate

RULES = Rules()


class ScriptedPlayer:
    """Spieler mit festen Entscheidungen (für Regeltests)."""

    name = "Test"

    def __init__(self, actions=(), insurance=False, bet=1):
        self.actions = list(actions)
        self.take_insurance = insurance
        self.units = bet
        self.seen = []
        self.shuffles = 0

    def on_shuffle(self):
        self.shuffles += 1

    def observe(self, rank):
        self.seen.append(rank)

    def bet(self):
        return self.units

    def insurance(self):
        return self.take_insurance

    def decide(self, hand):
        return self.actions.pop(0) if self.actions else Action.STAND

    def on_round_end(self):
        pass


def rigged(cards, player, rules=RULES):
    """Simulator, dessen Schuh mit den angegebenen Karten beginnt.
    Reihenfolge: Spieler, Dealer offen, Spieler, Dealer verdeckt, dann weitere Karten."""
    sim = Simulator(rules, player, seed=1)
    sim.shoe.shuffle()
    sim.shoe.cards = list(cards) + sim.shoe.cards
    sim.shoe.cut = 10_000
    return sim


@pytest.mark.parametrize("cards,actions,net", [
    (["A", "9", "10", "7"], [], 1.5),                        # Blackjack 3:2
    (["9", "10", "7", "A"], [], -1),                         # Dealer-Blackjack (Peek)
    (["10", "10", "6", "7"], [Action.SURRENDER], -0.5),      # Late Surrender
    (["5", "6", "6", "10", "10", "10"], [Action.DOUBLE], 2),  # Double gewinnt
    (["10", "10", "7", "8"], [Action.STAND], -1),            # 17 gegen 18
    (["10", "10", "8", "8"], [Action.STAND], 0),             # Push
    (["10", "6", "6", "10", "10"], [Action.HIT], -1),        # Überkauft
])
def test_regeln_des_simulators(cards, actions, net):
    sim = rigged(cards, ScriptedPlayer(actions))
    assert sim.play_round().net == pytest.approx(net)


def test_dealer_steht_auf_soft_17_und_zieht_bei_h17():
    cards = ["10", "A", "8", "6", "2"]
    assert rigged(cards, ScriptedPlayer([Action.STAND])).play_round().net == 1
    h17 = replace(RULES, hit_soft_17=True)
    assert rigged(cards, ScriptedPlayer([Action.STAND]), h17).play_round().net == -1


def test_split_asse_eine_karte_und_kein_blackjack():
    sim = rigged(["A", "6", "A", "10", "9", "10", "10"],
                 ScriptedPlayer([Action.SPLIT]))
    res = sim.play_round()
    assert res.hands == 2 and res.net == 2 and res.wagered == 2


def test_versicherung_zahlt_2_zu_1():
    res = rigged(["9", "A", "7", "10"], ScriptedPlayer(insurance=True, bet=2)).play_round()
    assert res.net == pytest.approx(-2 + 2)   # Hand verloren, Versicherung (1) gewinnt 2


def test_seven_card_charlie():
    rules = replace(RULES, seven_card_charlie=True)
    cards = ["2", "10", "2", "9", "2", "2", "3", "2", "3"]   # 7 Karten = 16
    res = rigged(cards, ScriptedPlayer([Action.HIT] * 5), rules).play_round()
    assert res.net == 1


def test_spieler_sieht_alle_offenen_karten_und_die_hole_card_am_ende():
    p = ScriptedPlayer([Action.STAND])
    rigged(["10", "9", "8", "8"], p).play_round()     # Dealer 9 + 8 = 17 steht
    assert p.seen == ["10", "9", "8", "8"]


def test_gleicher_seed_gleiches_ergebnis():
    a = simulate(StrategyPlayer(RULES, "hi_lo"), RULES, 2000, seed=5)
    b = simulate(StrategyPlayer(RULES, "hi_lo"), RULES, 2000, seed=5)
    c = simulate(StrategyPlayer(RULES, "hi_lo"), RULES, 2000, seed=6)
    assert np.array_equal(a.nets, b.nets)
    assert not np.array_equal(a.nets, c.nets)


def test_schnittkarte_und_mischen_jede_runde():
    shoe = simulate(StrategyPlayer(RULES), RULES, 3000, seed=1)
    assert 50 < shoe.shuffles < 90          # ca. 45 Runden pro Schuh bei 75 %
    every = replace(RULES, shuffle_every_round=True)
    res = simulate(StrategyPlayer(every), every, 300, seed=1, mode="every_round")
    assert res.shuffles == 300


def test_zaehler_spielt_basic_wenn_jede_runde_gemischt_wird():
    every = replace(RULES, shuffle_every_round=True)
    basic = simulate(StrategyPlayer(every), every, 3000, seed=3)
    hilo = simulate(StrategyPlayer(every, "hi_lo"), every, 3000, seed=3)
    assert np.array_equal(basic.nets, hilo.nets)
    assert hilo.mean_bet == 1


def test_zaehler_erhoeht_einsatz_bei_hohem_count():
    res = simulate(StrategyPlayer(RULES, "hi_lo"), RULES, 5000, seed=2)
    assert res.mean_bet > 1.2 and res.bets.max() == 8


def test_basic_strategy_entspricht_dem_theoretischen_hausvorteil():
    """200'000 Runden: Erwartungswert muss zum exakt berechneten Wert (−0,34 %) passen."""
    every = replace(RULES, shuffle_every_round=True)
    res = simulate(StrategyPlayer(every), every, 200_000, seed=11)
    assert abs(res.ev_per_round - (-0.00337)) < 2.5 * res.ci95 / 1.96


def test_exakter_spieler_spielt_und_setzt():
    p = ExactPlayer(RULES)
    res = simulate(p, RULES, 300, seed=4)
    assert res.rounds == 300 and res.mean_bet >= 1
    assert sum(p.shoe) < 312                   # merkt sich die gesehenen Karten


def test_kennzahlen():
    res = simulate(StrategyPlayer(RULES), RULES, 1000, seed=1)
    s = res.summary()
    assert s["rounds"] == 1000
    assert s["sd_per_round"] == pytest.approx(np.std(res.nets, ddof=1), abs=1e-4)
    assert res.max_drawdown >= 0
    assert res.ci95 == pytest.approx(1.96 * res.sd_per_round / np.sqrt(1000))


def test_betting_correlation_der_systeme():
    from blackjack_assistant.simulation.exact import ExactCalculator

    bc = betting_correlations(ExactCalculator(RULES).effects_of_removal())
    assert 0.95 < bc["hi_lo"]["bc"] < 0.99
    assert bc["wong_halves"]["bc"] > bc["hi_lo"]["bc"]
    # Ass-Korrektur verbessert die Betting Correlation von Hi-Opt II und Omega II
    for key in ("hi_opt_2", "omega_2"):
        assert bc[key]["bc_ace_adjusted"] > bc[key]["bc"]


def test_bericht_wird_erzeugt(tmp_path):
    assert report_main(["--hands", "200", "--big", "0", "--out", str(tmp_path)]) == 0
    md = (tmp_path / "results.md").read_text(encoding="utf-8")
    assert "Kurzfassung" in md and "Betting Correlation" in md and "Jev" in md
    for name in ("bankroll_10k", "gewinn_pro_runde_10k", "ergebnisse_verteilung", "streuung",
                 "betting_correlation"):
        assert (tmp_path / "img" / f"{name}.png").stat().st_size > 10_000
