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
    # Intervall auf Schuh-Ebene; ohne Schuhnummern wie bei unabhängigen Runden
    iid = 1.96 * res.sd_per_round / np.sqrt(1000)
    assert 0.5 * iid < res.ci95 < 2 * iid
    res.shoe_ids = None
    assert res.ci95 == pytest.approx(iid)


def test_betting_correlation_der_systeme():
    from blackjack_assistant.simulation.exact import ExactCalculator

    bc = betting_correlations(ExactCalculator(RULES).effects_of_removal())
    assert 0.95 < bc["hi_lo"]["bc"] < 0.99
    assert bc["wong_halves"]["bc"] > bc["hi_lo"]["bc"]
    # Ass-Korrektur verbessert die Betting Correlation von Hi-Opt II und Omega II
    for key in ("hi_opt_2", "omega_2"):
        assert bc[key]["bc_ace_adjusted"] > bc[key]["bc"]


def test_bericht_wird_erzeugt(tmp_path):
    assert report_main(["--hands", "200", "--big-rounds", "0", "--out", str(tmp_path)]) == 0
    md = (tmp_path / "results.md").read_text(encoding="utf-8")
    assert "Kurzfassung" in md and "Betting Correlation" in md and "Jev" in md
    for name in ("bankroll_10k", "gewinn_pro_runde_10k", "ergebnisse_verteilung", "streuung",
                 "betting_correlation"):
        assert (tmp_path / "img" / f"{name}.png").stat().st_size > 10_000


# ----------------------------------------------------------------------
# Langlauf mit gleichen Schuhen (gepaarter Vergleich)
# ----------------------------------------------------------------------


def test_alle_varianten_spielen_dieselben_schuhe():
    """Der Schuh wird nur beim Mischen vom Zufallsgenerator berührt → Schuh k ist für alle
    Spieler gleich, egal wie sie spielen."""
    from blackjack_assistant.simulation.simulator import Simulator

    firsts = []
    for player in (StrategyPlayer(RULES), StrategyPlayer(RULES, "zen"), ExactPlayer(RULES)):
        sim = Simulator(RULES, player, seed=42)
        orders = []
        while sim.shoe.shuffles < 3:
            sim.play_round()
            if sim.shoe.pos <= 12:
                orders.append(tuple(sim.shoe.cards[:20]))
        firsts.append(sorted(set(orders)))
    assert firsts[0] == firsts[1] == firsts[2]


def test_simulation_ueber_schuhe():
    from blackjack_assistant.simulation.simulator import simulate_shoes

    t = simulate_shoes(StrategyPlayer(RULES, "hi_lo"), RULES, 30, seed=3)
    assert len(t.net) == 30 and t.rounds.min() > 30
    assert t.total_rounds == int(t.rounds.sum())
    assert t.mean_bet > 1 and t.sd_per_round > 1 and t.ci95 > 0


def test_flacher_einsatz_zaehlt_aber_setzt_immer_eins():
    res = simulate(StrategyPlayer(RULES, "hi_lo", flat_bet=True), RULES, 3000, seed=2)
    assert res.mean_bet == 1
    exact = simulate(ExactPlayer(RULES, flat_bet=True), RULES, 200, seed=2)
    assert exact.mean_bet == 1


def test_gepaarter_vergleich():
    from blackjack_assistant.simulation.longrun import paired_difference
    from blackjack_assistant.simulation.simulator import ShoeTotals

    rng = np.random.default_rng(0)
    rounds = np.full(4000, 40.0)
    common = rng.normal(0, 10, 4000)                    # gemeinsamer Schuh-Zufall
    a = ShoeTotals(common + 0.4, rounds, rounds, 1.0)   # 0.4 / 40 = +1 % pro Runde besser
    b = ShoeTotals(common + rng.normal(0, 1, 4000), rounds, rounds, 1.0)
    c = paired_difference(a, b)
    assert c["diff"] == pytest.approx(0.01, abs=0.002)
    assert c["ci95"] < 0.002 and c["z"] > 5 and c["corr"] > 0.9
    # Ohne Paarung (unabhängige Schuhe) wäre der Unterschied nicht messbar
    assert a.ci95 > 5 * c["ci95"]


def test_langlauf_parallel_und_auswertung(tmp_path):
    from blackjack_assistant.simulation.longrun import run_longrun
    from blackjack_assistant.simulation.report import analyse_longrun, write_report

    plan = {"basic": 40, "hi_lo": 40, "hi_lo:flat": 40, "hi_lo:spread_only": 40, "zen": 40,
            "zen:flat": 40, "exact": 6, "exact:flat": 6}
    big = run_longrun(plan, seed=5, jobs=2, block_shoes=20, log=lambda m: None)
    assert {k: len(t.net) for k, t in big.items()} == plan
    # gleiche Schuhe: Basic und Hi-Lo flach unterscheiden sich nur bei Abweichungen → stark korreliert
    lr = analyse_longrun(big)
    corr = [c for c in lr["decomposition"] if c["a"] == "hi_lo:flat" and c["b"] == "basic"][0]["corr"]
    assert corr > 0.8
    assert len(lr["pairwise"]) == 1 and lr["z_bonferroni"] == pytest.approx(1.96, abs=0.01)
    assert set(lr["shares"]) == {"hi_lo", "zen"}
    # Bericht mit Langlauf-Abschnitten
    from blackjack_assistant.simulation import report

    s = {"created": "x", "seed": 1, "runtime_s": 60,
         "settings": {"block_shoes": 20, "jobs": 2, "hands": 100},
         "ramp_table": report.ramp_table(), "index_table": report.index_table(),
         "runs_10k": [{"key": k, "mode": m, "name": k, "net": 0, "ev_per_round": 0, "ci95": 0.01,
                       "ev_per_unit_bet": 0, "sd_per_round": 1, "mean_bet": 1, "max_drawdown": 0,
                       "rounds": 100, "shuffles": 3 if m == "shoe" else 100}
                      for k in ("basic", "hi_lo") for m in ("shoe", "every_round")],
         "jev_note": None, "longrun": lr, "eor": {"2": 0.0007}, "base_ev": -0.0034,
         "betting_correlation": {"hi_lo": {"bc": 0.96}}}
    write_report(s, tmp_path / "r.md")
    md = (tmp_path / "r.md").read_text(encoding="utf-8")
    for heading in ("Einsatzstaffelung", "Abweichungen (Indizes)", "Statistische Signifikanz",
                    "Woher kommt der Vorteil", "95-%-Vertrauensintervall", "Näherung"):
        assert heading in md, heading


def test_index_und_staffelungstabelle():
    from blackjack_assistant.simulation.report import index_table, ramp_table

    ramps = ramp_table()
    assert ramps["hi_lo"] == [2, 3, 4, 5]
    assert ramps["zen"] == pytest.approx([3.4, 5.1, 6.8, 8.5])
    assert ramps["ko"][2] == pytest.approx(4)                # TC 4 = Pivot +4
    rows = {r["name"]: r for r in index_table()}
    ins = rows["Versicherung"]
    assert ins["hilo"] == 3 and ins["systems"]["ko"] == 3     # KO fest ab +3
    assert rows["16 gegen 10 stehen"]["systems"]["zen"] == pytest.approx(0)
    assert rows["10,10 gegen 6 teilen"]["systems"]["hi_opt_2"] == pytest.approx(6.0)
