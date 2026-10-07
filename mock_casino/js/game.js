// Spielablauf einer Blackjack-Runde. Kennt kein DOM: Die Oberfläche wird über
// "hooks" informiert. Dadurch lässt sich die Logik auch ohne Bildschirm testen.

import {
  DEFAULT_RULES,
  canDouble,
  canHit,
  canSplit,
  canSurrender,
  dealerShouldHit,
  handTotal,
  isBlackjack,
  rankValue,
  settleHand,
} from './rules.js';
import { Shoe, createRng } from './shoe.js';

// Phasen einer Runde
export const PHASE = Object.freeze({
  BETTING: 'betting',       // Einsatz wählen, "Austeilen" möglich
  DEALING: 'dealing',       // Karten werden ausgeteilt
  INSURANCE: 'insurance',   // Dealer zeigt Ass, Versicherung anbieten
  PLAYER: 'player',         // Spieler entscheidet
  DEALER: 'dealer',         // Dealer spielt
  SETTLED: 'settled',       // Runde abgerechnet, Karten liegen noch auf dem Tisch
});

const NOOP_HOOKS = {
  update() {},               // Zustand hat sich geändert → neu zeichnen
  cardRevealed() {},         // (card, info) eine Karte wurde offen sichtbar
  roundStarted() {},         // (round)
  roundEnded() {},           // (summary)
  tableCleared() {},         // Tisch ist leer
  shuffled() {},             // (info) Schuh wurde neu gemischt
  cardUnseen() {},           // (card, info) Karte wurde verdeckt abgeräumt (nie sichtbar)
};

export class Game {
  /**
   * @param {object} options
   * @param {object} options.rules    Regeln (siehe DEFAULT_RULES)
   * @param {number|null} options.seed Seed für reproduzierbares Mischen
   * @param {object} options.hooks    Rückruffunktionen für die Oberfläche
   * @param {object} options.timing   Verzögerungen in ms (0 = keine Animationen, für Tests)
   */
  constructor({ rules = {}, seed = null, hooks = {}, timing = {}, bankroll = 1000 } = {}) {
    this.rules = { ...DEFAULT_RULES, ...rules };
    this.hooks = { ...NOOP_HOOKS, ...hooks };
    this.timing = {
      dealCard: 450,     // Pause zwischen zwei ausgeteilten Karten
      dealerCard: 650,   // Pause zwischen Dealer-Karten
      clearTable: 2500,  // Wartezeit nach der Abrechnung, bevor der Tisch geräumt wird
      ...timing,
    };
    this.shoe = new Shoe(this.rules.decks, this.rules.penetration, createRng(seed));
    this.bankroll = bankroll;
    this.phase = PHASE.BETTING;
    this.round = 0;
    this.shoeNumber = 1;           // wie oft der Schuh schon gemischt wurde (+1)
    this.roundsSinceShuffle = 0;
    this.history = [];             // alle seit dem letzten Mischen aufgedeckten Karten
    this.hands = [];
    this.activeHand = 0;
    this.dealer = { cards: [], holeHidden: false };
    this.insuranceBet = 0;
    this.lastSummary = null;
    this.busy = false;             // läuft gerade eine Animation / Aktion?
    this.shufflePending = false;   // nach dieser Runde wird gemischt
    this.unseenCount = 0;          // verdeckt abgeräumte Karten seit dem letzten Mischen
  }

  // ------------------------------------------------------------------
  // Hilfsfunktionen
  // ------------------------------------------------------------------

  wait(ms) {
    if (!ms) return Promise.resolve();
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  get currentHand() {
    return this.hands[this.activeHand];
  }

  // Karte ziehen. Ist der Schuh (nur bei extremen Einstellungen) leer, wird notfalls gemischt.
  drawCard() {
    if (this.shoe.remaining === 0) {
      this.doShuffle('empty');
    }
    const card = this.shoe.draw();
    if (this.shoe.cutCardReached) this.shufflePending = true;
    return card;
  }

  // Karte offen zeigen: in den Verlauf aufnehmen und die Oberfläche/den Logger informieren
  reveal(card, info) {
    this.history.push(card);
    this.hooks.cardRevealed(card, {
      ...info,
      round: this.round,
      shoe: this.shoeNumber,
      seq: this.history.length, // Position im Verlauf seit dem letzten Mischen
    });
  }

  // Welche Aktionen sind gerade erlaubt? (für die Buttons)
  availableActions() {
    const none = {
      deal: false, hit: false, stand: false, double: false, split: false,
      surrender: false, insurance: false,
    };
    if (this.busy) return none;
    if (this.phase === PHASE.BETTING) return { ...none, deal: true };
    if (this.phase === PHASE.INSURANCE) return { ...none, insurance: true };
    if (this.phase !== PHASE.PLAYER) return none;
    const hand = this.currentHand;
    return {
      ...none,
      hit: canHit(hand, this.rules),
      stand: true,
      double: canDouble(hand, this.bankroll, this.rules),
      split: canSplit(hand, this.hands.length, this.bankroll, this.rules),
      surrender: canSurrender(hand, this.hands.length, this.rules),
    };
  }

  // Schützt vor Doppelklicks während einer laufenden Aktion
  async runExclusive(fn) {
    if (this.busy) return false;
    this.busy = true;
    this.hooks.update();
    try {
      await fn();
      return true;
    } finally {
      this.busy = false;
      this.hooks.update();
    }
  }

  // ------------------------------------------------------------------
  // Runde starten
  // ------------------------------------------------------------------

  async deal(bet) {
    if (this.phase !== PHASE.BETTING) throw new Error('Austeilen nur in der Einsatzphase');
    if (!(bet > 0) || bet > this.bankroll) throw new Error('Ungültiger Einsatz');

    return this.runExclusive(async () => {
      this.round += 1;
      this.roundsSinceShuffle += 1;
      this.bankroll -= bet;
      this.insuranceBet = 0;
      this.lastSummary = null;
      this.hands = [newHand(bet)];
      this.activeHand = 0;
      this.dealer = { cards: [], holeHidden: true };
      this.phase = PHASE.DEALING;
      this.hooks.roundStarted(this.round);
      this.hooks.update();

      // Reihenfolge wie am echten Tisch: Spieler, Dealer offen, Spieler, Dealer verdeckt
      await this.dealTo('player');
      await this.dealTo('dealer');
      await this.dealTo('player');
      await this.dealTo('dealer', { hole: true });

      const up = this.dealer.cards[0];
      if (up.rank === 'A' && this.rules.insurance) {
        this.phase = PHASE.INSURANCE;
        return; // weiter mit insurance()
      }
      await this.afterInitialDeal();
    });
  }

  async dealTo(target, { hole = false } = {}) {
    const card = this.drawCard();
    if (target === 'player') {
      this.currentHand.cards.push(card);
      this.reveal(card, { target: 'player', hand: this.activeHand, hole: false });
    } else {
      this.dealer.cards.push(card);
      if (!hole) this.reveal(card, { target: 'dealer', hand: 0, hole: false });
    }
    this.hooks.update();
    await this.wait(target === 'dealer' && this.phase === PHASE.DEALER
      ? this.timing.dealerCard
      : this.timing.dealCard);
    return card;
  }

  async insurance(take) {
    if (this.phase !== PHASE.INSURANCE) throw new Error('Keine Versicherung möglich');
    return this.runExclusive(async () => {
      if (take) {
        const cost = this.hands[0].bet / 2;
        if (cost <= this.bankroll) {
          this.bankroll -= cost;
          this.insuranceBet = cost;
        }
      }
      await this.afterInitialDeal();
    });
  }

  // Dealer-Peek und Blackjack-Prüfung nach dem Austeilen
  async afterInitialDeal() {
    const up = this.dealer.cards[0];
    const dealerBJ = isBlackjack(this.dealer.cards);
    const peeks = this.rules.dealerPeek && (up.rank === 'A' || rankValue(up.rank) === 10);
    const playerBJ = isBlackjack(this.hands[0].cards);

    if ((peeks && dealerBJ) || playerBJ) {
      // Runde ist sofort zu Ende
      this.hands[0].done = true;
      await this.finishRound({ dealerPlays: false });
      return;
    }
    this.phase = PHASE.PLAYER;
    this.hooks.update();
  }

  // ------------------------------------------------------------------
  // Spieleraktionen
  // ------------------------------------------------------------------

  assertPlayerTurn() {
    if (this.phase !== PHASE.PLAYER) throw new Error('Spieler ist nicht am Zug');
  }

  async hit() {
    this.assertPlayerTurn();
    if (!canHit(this.currentHand, this.rules)) throw new Error('Ziehen nicht erlaubt');
    return this.runExclusive(async () => {
      await this.dealTo('player');
      const total = handTotal(this.currentHand.cards).total;
      if (total >= 21) {
        // Überkauft oder 21 → Hand ist automatisch fertig
        this.currentHand.done = true;
        await this.nextHand();
      }
    });
  }

  async stand() {
    this.assertPlayerTurn();
    return this.runExclusive(async () => {
      this.currentHand.done = true;
      await this.nextHand();
    });
  }

  async double() {
    this.assertPlayerTurn();
    const hand = this.currentHand;
    if (!canDouble(hand, this.bankroll, this.rules)) throw new Error('Verdoppeln nicht erlaubt');
    return this.runExclusive(async () => {
      this.bankroll -= hand.bet;
      hand.bet *= 2;
      hand.doubled = true;
      await this.dealTo('player');
      hand.done = true;
      await this.nextHand();
    });
  }

  async split() {
    this.assertPlayerTurn();
    const hand = this.currentHand;
    if (!canSplit(hand, this.hands.length, this.bankroll, this.rules)) {
      throw new Error('Teilen nicht erlaubt');
    }
    return this.runExclusive(async () => {
      this.bankroll -= hand.bet;
      const aces = hand.cards[0].rank === 'A';
      const second = hand.cards.pop();
      hand.fromSplit = true;
      hand.splitAces = aces;
      const other = newHand(hand.bet);
      other.cards.push(second);
      other.fromSplit = true;
      other.splitAces = aces;
      this.hands.splice(this.activeHand + 1, 0, other);
      this.hooks.update();
      await this.wait(this.timing.dealCard);

      // Die aktuelle Hand bekommt ihre zweite Karte
      await this.dealTo('player');
      await this.checkHandAfterSecondCard();
    });
  }

  async surrender() {
    this.assertPlayerTurn();
    if (!canSurrender(this.currentHand, this.hands.length, this.rules)) {
      throw new Error('Aufgeben nicht erlaubt');
    }
    return this.runExclusive(async () => {
      this.currentHand.surrendered = true;
      this.currentHand.done = true;
      await this.nextHand();
    });
  }

  // Nach der zweiten Karte einer Split-Hand: Asse und 21 sind automatisch fertig
  async checkHandAfterSecondCard() {
    const hand = this.currentHand;
    const total = handTotal(hand.cards).total;
    const canResplitAce =
      hand.splitAces && this.rules.resplitAces &&
      canSplit(hand, this.hands.length, this.bankroll, this.rules);
    if ((hand.splitAces && !this.rules.hitSplitAces && !canResplitAce) || total === 21) {
      hand.done = true;
      await this.nextHand();
    }
  }

  // Zur nächsten offenen Hand wechseln oder den Dealer spielen lassen
  async nextHand() {
    while (this.activeHand < this.hands.length && this.currentHand.done) {
      this.activeHand += 1;
    }
    if (this.activeHand < this.hands.length) {
      this.hooks.update();
      if (this.currentHand.cards.length === 1) {
        await this.dealTo('player');
        await this.checkHandAfterSecondCard();
      }
      return;
    }
    this.activeHand = this.hands.length - 1;
    const anyAlive = this.hands.some(
      (h) => !h.surrendered && handTotal(h.cards).total <= 21,
    );
    await this.finishRound({ dealerPlays: anyAlive });
  }

  // ------------------------------------------------------------------
  // Dealer und Abrechnung
  // ------------------------------------------------------------------

  async finishRound({ dealerPlays }) {
    this.phase = PHASE.DEALER;

    // Hole Card wird normalerweise immer aufgedeckt (wie im Casino) – wichtig für das Zählen.
    // Mit hideUnneededHoleCard bleibt sie verdeckt, wenn der Dealer nicht spielen muss
    // (alle Hände überkauft/aufgegeben oder Spieler-Blackjack). Sie gilt dann als "ungesehen".
    const dealerBlackjack = isBlackjack(this.dealer.cards);
    if (this.dealer.holeHidden && this.rules.hideUnneededHoleCard && !dealerPlays && !dealerBlackjack) {
      this.unseenCount += 1;
      this.hooks.cardUnseen(this.dealer.cards[1], {
        target: 'dealer', hand: 0, hole: true, round: this.round, shoe: this.shoeNumber,
      });
    } else if (this.dealer.holeHidden) {
      this.dealer.holeHidden = false;
      this.reveal(this.dealer.cards[1], { target: 'dealer', hand: 0, hole: true });
      this.hooks.update();
      await this.wait(this.timing.dealerCard);
    }

    if (dealerPlays) {
      while (dealerShouldHit(this.dealer.cards, this.rules)) {
        await this.dealTo('dealer');
      }
    }

    // Abrechnung
    const dealerBJ = isBlackjack(this.dealer.cards);
    let returned = 0;
    for (const hand of this.hands) {
      const { outcome, payout } = settleHand(hand, this.dealer.cards, this.hands.length, this.rules);
      hand.outcome = outcome;
      hand.payout = payout;
      returned += payout;
    }
    let insurancePayout = 0;
    if (this.insuranceBet > 0 && dealerBJ) insurancePayout = this.insuranceBet * 3; // 2:1 + Einsatz
    this.bankroll += returned + insurancePayout;

    const staked = this.hands.reduce((s, h) => s + h.bet, 0) + this.insuranceBet;
    this.lastSummary = {
      round: this.round,
      shoe: this.shoeNumber,
      hands: this.hands.map((h) => ({
        cards: h.cards.map((c) => c.rank),
        total: handTotal(h.cards).total,
        bet: h.bet,
        outcome: h.outcome,
        payout: h.payout,
      })),
      dealer: { cards: this.dealer.cards.map((c) => c.rank), total: handTotal(this.dealer.cards).total },
      insurance: this.insuranceBet,
      net: returned + insurancePayout - staked,
      bankroll: this.bankroll,
      cardsDealt: this.shoe.dealt,
      shufflePending: this.shufflePending || this.rules.shuffleEveryRound,
    };
    this.phase = PHASE.SETTLED;
    this.hooks.roundEnded(this.lastSummary);
    this.hooks.update();

    // Karten bleiben kurz liegen, dann wird der Tisch geräumt (wichtig für den Tisch-Modus)
    await this.wait(this.timing.clearTable);
    this.clearTable();

    if (this.shufflePending || this.rules.shuffleEveryRound) {
      this.doShuffle(this.shufflePending ? 'cut_card' : 'every_round');
    }
    this.phase = PHASE.BETTING;
  }

  clearTable() {
    this.hands = [];
    this.activeHand = 0;
    this.dealer = { cards: [], holeHidden: false };
    this.hooks.tableCleared();
    this.hooks.update();
  }

  doShuffle(reason) {
    const info = {
      reason,                                  // 'cut_card', 'every_round', 'empty', 'manual'
      roundsSinceShuffle: this.roundsSinceShuffle,
      cardsDealt: this.shoe.dealt,
      shoe: this.shoeNumber + 1,
    };
    this.shoe.shuffle();
    this.shoeNumber += 1;
    this.roundsSinceShuffle = 0;
    this.history = [];
    this.unseenCount = 0;
    this.shufflePending = false;
    this.hooks.shuffled(info);
    this.hooks.update();
  }

  // Manuelles Mischen (Button), nur zwischen den Runden
  shuffleNow() {
    if (this.phase !== PHASE.BETTING || this.busy) return false;
    this.doShuffle('manual');
    return true;
  }
}

function newHand(bet) {
  return {
    cards: [],
    bet,
    doubled: false,
    done: false,
    surrendered: false,
    fromSplit: false,
    splitAces: false,
    outcome: null,
    payout: 0,
  };
}
