"""Tests der Spiellogik des Mock-Casinos (rules.js, shoe.js, game.js).

Die JavaScript-Module laufen in einem Headless-Browser, es wird kein Bildschirm gebraucht.
Für gezielte Situationen wird der Schuh "präpariert": Die ersten Karten werden vorgegeben.
Austeilreihenfolge: Spieler, Dealer offen, Spieler, Dealer verdeckt, danach weitere Karten.
"""

import pytest

pytestmark = pytest.mark.browser

# JavaScript-Hilfsfunktion: Spiel ohne Pausen mit vorgegebenen ersten Karten
RIGGED = """
async ([seq, rules]) => {
  const { Game } = await import('/js/game.js');
  const g = new Game({ rules, seed: 7, timing: { dealCard: 0, dealerCard: 0, clearTable: 0 } });
  const top = seq.map((rank) => ({ rank, suit: 'S' }));
  g.shoe.cards = top.concat(g.shoe.cards.slice(top.length));
  window.g = g;
  return true;
}
"""


def rig(page, seq, rules=None):
    page.evaluate(RIGGED, [seq, rules or {}])


def js(page, code):
    return page.evaluate(f"async () => {{ const g = window.g; {code} }}")


# ----------------------------------------------------------------------
# rules.js
# ----------------------------------------------------------------------


def test_handwerte_und_soft(casino_page):
    result = casino_page.evaluate("""async () => {
      const r = await import('/js/rules.js');
      const h = (...ranks) => r.handTotal(ranks.map((rank) => ({ rank })));
      return [h('A', '6'), h('A', '6', '10'), h('A', 'A'), h('K', 'Q', '5'), h('A', 'A', 'A', '8')];
    }""")
    assert result == [
        {"total": 17, "soft": True},
        {"total": 17, "soft": False},
        {"total": 12, "soft": True},
        {"total": 25, "soft": False},
        {"total": 21, "soft": True},
    ]


def test_dealer_steht_auf_soft_17(casino_page):
    result = casino_page.evaluate("""async () => {
      const r = await import('/js/rules.js');
      const c = (...ranks) => ranks.map((rank) => ({ rank }));
      return [
        r.dealerShouldHit(c('A', '6')),
        r.dealerShouldHit(c('A', '6'), { ...r.DEFAULT_RULES, hitSoft17: true }),
        r.dealerShouldHit(c('10', '6')),
        r.dealerShouldHit(c('10', '7')),
      ];
    }""")
    assert result == [False, True, True, False]


def test_schuh_hat_6_decks_und_schnittkarte_bei_75_prozent(casino_page):
    result = casino_page.evaluate("""async () => {
      const { Shoe, createRng } = await import('/js/shoe.js');
      const s = new Shoe(6, 0.75, createRng(5));
      const counts = {};
      for (const c of s.cards) counts[c.rank + c.suit] = (counts[c.rank + c.suit] ?? 0) + 1;
      const same = new Shoe(6, 0.75, createRng(5)).cards.map((c) => c.rank + c.suit).join();
      return { total: s.cards.length, cut: s.cutCardPosition, distinct: Object.keys(counts).length,
               allSix: Object.values(counts).every((n) => n === 6),
               reproducible: same === s.cards.map((c) => c.rank + c.suit).join() };
    }""")
    assert result == {"total": 312, "cut": 234, "distinct": 52, "allSix": True, "reproducible": True}


# ----------------------------------------------------------------------
# game.js – einzelne Situationen
# ----------------------------------------------------------------------


def test_blackjack_zahlt_3_zu_2_und_hole_card_wird_aufgedeckt(casino_page):
    rig(casino_page, ["A", "9", "K", "7"])
    r = js(casino_page, "await g.deal(10); return [g.bankroll, g.lastSummary.hands[0].outcome, g.history.length];")
    assert r == [1015, "blackjack", 4]


def test_dealer_blackjack_mit_zehn_offen_beendet_runde_sofort(casino_page):
    rig(casino_page, ["9", "K", "7", "A"])
    r = js(casino_page, "await g.deal(10); return [g.bankroll, g.lastSummary.hands[0].outcome, g.phase, g.history.length];")
    assert r == [990, "lose", "betting", 4]


def test_versicherung_zahlt_2_zu_1(casino_page):
    rig(casino_page, ["9", "A", "7", "K"])
    phase = js(casino_page, "await g.deal(10); return g.phase;")
    assert phase == "insurance"
    r = js(casino_page, "await g.insurance(true); return [g.bankroll, g.lastSummary.net];")
    assert r == [1000, 0]


def test_dealer_soft_17_steht_bei_s17(casino_page):
    rig(casino_page, ["10", "A", "8", "6"])
    r = js(casino_page, """
      await g.deal(10); await g.insurance(false); await g.stand();
      return [g.lastSummary.dealer.cards.length, g.lastSummary.hands[0].outcome];""")
    assert r == [2, "win"]


def test_dealer_zieht_auf_soft_17_bei_h17(casino_page):
    rig(casino_page, ["10", "A", "8", "6", "2"], {"hitSoft17": True})
    r = js(casino_page, """
      await g.deal(10); await g.insurance(false); await g.stand();
      return [g.lastSummary.dealer.total, g.lastSummary.hands[0].outcome];""")
    assert r == [19, "lose"]


def test_late_surrender_gibt_halben_einsatz_zurueck(casino_page):
    rig(casino_page, ["10", "10", "6", "7"])
    r = js(casino_page, """
      await g.deal(10);
      const allowed = g.availableActions().surrender;
      await g.surrender();
      return [allowed, g.bankroll, g.lastSummary.hands[0].outcome];""")
    assert r == [True, 995, "surrender"]


def test_verdoppeln(casino_page):
    rig(casino_page, ["5", "6", "6", "10", "10", "10"])
    r = js(casino_page, "await g.deal(10); await g.double(); return [g.bankroll, g.lastSummary.hands[0].bet];")
    assert r == [1020, 20]


def test_gesplittete_asse_bekommen_eine_karte_und_21_ist_kein_blackjack(casino_page):
    rig(casino_page, ["A", "6", "A", "10", "9", "K", "10"])
    r = js(casino_page, """
      await g.deal(10); await g.split();
      return [g.lastSummary.hands.map((h) => h.cards.join('+')),
              g.lastSummary.hands.map((h) => h.outcome), g.bankroll];""")
    assert r == [["A+9", "A+K"], ["win", "win"], 1020]


def test_split_mit_double_after_split_und_kein_surrender_nach_split(casino_page):
    rig(casino_page, ["8", "6", "8", "10", "3", "9", "K", "10"])
    r = js(casino_page, """
      await g.deal(10); await g.split();
      const a = g.availableActions();
      await g.double();   // Hand 1: 8+3 = 11, verdoppeln, bekommt 9
      await g.stand();    // Hand 2: 8+K = 18
      return [a.double, a.surrender, g.lastSummary.hands.map((h) => [h.bet, h.outcome]), g.bankroll];""")
    assert r == [True, False, [[20, "win"], [10, "win"]], 1030]


def test_kein_double_after_split_wenn_regel_aus(casino_page):
    rig(casino_page, ["8", "6", "8", "10", "3"], {"doubleAfterSplit": False})
    r = js(casino_page, "await g.deal(10); await g.split(); return g.availableActions().double;")
    assert r is False


def test_mischen_nach_jeder_runde(casino_page):
    rig(casino_page, ["10", "9", "10", "8"], {"shuffleEveryRound": True})
    r = js(casino_page, "await g.deal(10); await g.stand(); return [g.shoeNumber, g.history.length, g.shoe.dealt];")
    assert r == [2, 0, 0]


# ----------------------------------------------------------------------
# game.js – viele Runden
# ----------------------------------------------------------------------


def test_viele_runden_mischen_an_der_schnittkarte(casino_page):
    """Spielt 400 Runden mit einer einfachen Strategie und prüft dabei:
    - jede gezogene Karte wird genau einmal aufgedeckt (auch die Hole Card)
    - gemischt wird erst nach Erreichen der Schnittkarte (234 Karten)
    - das Guthaben stimmt mit der Summe der Rundenergebnisse überein
    """
    r = casino_page.evaluate("""async () => {
      const { Game } = await import('/js/game.js');
      const { handTotal } = await import('/js/rules.js');
      const shuffles = [];
      const problems = [];
      let netSum = 0;
      const g = new Game({
        seed: 11, bankroll: 1e9,
        timing: { dealCard: 0, dealerCard: 0, clearTable: 0 },
        hooks: {
          roundEnded: (s) => {
            netSum += s.net;
            if (g.history.length !== g.shoe.dealt) problems.push(['nicht alle Karten sichtbar', s.round]);
          },
          shuffled: (info) => shuffles.push(info),
        },
      });
      for (let i = 0; i < 400; i++) {
        await g.deal(10);
        if (g.phase === 'insurance') await g.insurance(false);
        while (g.phase === 'player') {
          const a = g.availableActions();
          const t = handTotal(g.currentHand.cards).total;
          if (a.split && i % 2 === 0) await g.split();
          else if (a.double && t === 11) await g.double();
          else if (a.surrender && t === 16 && i % 3 === 0) await g.surrender();
          else if (a.hit && t < 13) await g.hit();
          else await g.stand();
        }
      }
      return { shuffles, problems, netSum, bankroll: g.bankroll };
    }""")
    assert r["problems"] == []
    assert len(r["shuffles"]) >= 5
    for info in r["shuffles"]:
        assert info["reason"] == "cut_card"
        assert info["cardsDealt"] >= 234
        assert info["cardsDealt"] < 312
    assert r["bankroll"] == pytest.approx(1e9 + r["netSum"])
