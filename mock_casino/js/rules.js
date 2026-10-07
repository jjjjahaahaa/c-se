// Blackjack-Regeln: Handwerte, Dealer-Logik, erlaubte Aktionen, Auszahlungen.
// Reine Funktionen ohne DOM, damit sie sich einzeln testen lassen.

export const RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A'];
export const SUITS = ['S', 'H', 'D', 'C']; // Pik, Herz, Karo, Kreuz

// Standardregeln laut Projektauftrag
export const DEFAULT_RULES = Object.freeze({
  decks: 6,
  penetration: 0.75,       // Schnittkarte nach 75 % des Schuhs
  hitSoft17: false,        // Dealer steht auf Soft 17
  blackjackPays: 1.5,      // 3:2
  doubleAnyTwo: true,      // Double auf beliebige zwei Karten
  doubleAfterSplit: true,  // DAS
  maxHands: 4,             // bis zu 3 Splits
  resplitAces: false,
  hitSplitAces: false,     // gesplittete Asse bekommen genau eine Karte
  lateSurrender: true,
  dealerPeek: true,        // Dealer prüft bei A/10 auf Blackjack (US-Regel)
  insurance: true,
  shuffleEveryRound: false,
});

// Punktwert eines Rangs (Ass zunächst als 1)
export function rankValue(rank) {
  if (rank === 'A') return 1;
  if (rank === 'J' || rank === 'Q' || rank === 'K') return 10;
  return Number(rank);
}

// Handwert berechnen. soft = true, wenn ein Ass als 11 zählt.
export function handTotal(cards) {
  let total = 0;
  let aces = 0;
  for (const c of cards) {
    total += rankValue(c.rank);
    if (c.rank === 'A') aces += 1;
  }
  // Höchstens ein Ass kann als 11 zählen (zwei Asse als 11 wären 22)
  if (aces > 0 && total + 10 <= 21) {
    return { total: total + 10, soft: true };
  }
  return { total, soft: false };
}

// Blackjack = Ass + Zehnerwert mit den ersten zwei Karten, nicht nach einem Split
export function isBlackjack(cards, fromSplit = false) {
  return !fromSplit && cards.length === 2 && handTotal(cards).total === 21;
}

export function isBust(cards) {
  return handTotal(cards).total > 21;
}

// Muss der Dealer noch ziehen? (S17: steht auf allen 17, H17: zieht auf Soft 17)
export function dealerShouldHit(cards, rules = DEFAULT_RULES) {
  const { total, soft } = handTotal(cards);
  if (total < 17) return true;
  if (total === 17 && soft && rules.hitSoft17) return true;
  return false;
}

// Zwei Karten mit gleichem Punktwert dürfen gesplittet werden (also auch K + 10)
export function canSplit(hand, handCount, bankroll, rules = DEFAULT_RULES) {
  if (hand.done || hand.cards.length !== 2) return false;
  if (handCount >= rules.maxHands) return false;
  if (bankroll < hand.bet) return false;
  if (rankValue(hand.cards[0].rank) !== rankValue(hand.cards[1].rank)) return false;
  if (hand.splitAces && !rules.resplitAces) return false;
  return true;
}

export function canDouble(hand, bankroll, rules = DEFAULT_RULES) {
  if (hand.done || hand.cards.length !== 2) return false;
  if (bankroll < hand.bet) return false;
  if (hand.splitAces && !rules.hitSplitAces) return false;
  if (hand.fromSplit && !rules.doubleAfterSplit) return false;
  if (!rules.doubleAnyTwo) {
    const t = handTotal(hand.cards).total;
    if (t < 9 || t > 11) return false;
  }
  return true;
}

// Late Surrender: nur als erste Entscheidung mit den ersten zwei Karten, nicht nach Split
export function canSurrender(hand, handCount, rules = DEFAULT_RULES) {
  return (
    rules.lateSurrender &&
    !hand.done &&
    handCount === 1 &&
    !hand.fromSplit &&
    hand.cards.length === 2
  );
}

export function canHit(hand, rules = DEFAULT_RULES) {
  if (hand.done) return false;
  if (hand.splitAces && !rules.hitSplitAces) return false;
  return handTotal(hand.cards).total < 21;
}

// Ergebnis einer Hand gegen den Dealer.
// Rückgabe: { outcome, payout } – payout = Betrag, der an den Spieler zurückgeht
// (inklusive Einsatz). Der Einsatz wurde beim Setzen bereits abgezogen.
export function settleHand(hand, dealerCards, handCount, rules = DEFAULT_RULES) {
  const bet = hand.bet;
  if (hand.surrendered) return { outcome: 'surrender', payout: bet / 2 };

  const player = handTotal(hand.cards).total;
  if (player > 21) return { outcome: 'bust', payout: 0 };

  const playerBJ = handCount === 1 && isBlackjack(hand.cards, hand.fromSplit);
  const dealerBJ = isBlackjack(dealerCards);

  if (playerBJ && dealerBJ) return { outcome: 'push', payout: bet };
  if (playerBJ) return { outcome: 'blackjack', payout: bet + bet * rules.blackjackPays };
  if (dealerBJ) return { outcome: 'lose', payout: 0 };

  const dealer = handTotal(dealerCards).total;
  if (dealer > 21) return { outcome: 'win', payout: bet * 2 };
  if (player > dealer) return { outcome: 'win', payout: bet * 2 };
  if (player < dealer) return { outcome: 'lose', payout: 0 };
  return { outcome: 'push', payout: bet };
}
