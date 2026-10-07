// Kartenschuh mit mehreren Decks, Fisher-Yates-Mischen und Schnittkarte.

import { RANKS, SUITS } from './rules.js';

// Kleiner, reproduzierbarer Zufallsgenerator (mulberry32).
// Mit gleichem Seed entsteht immer dieselbe Kartenreihenfolge – wichtig für Tests.
export function createRng(seed) {
  if (seed === null || seed === undefined) return Math.random;
  let a = seed >>> 0;
  return function rng() {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export class Shoe {
  constructor(decks = 6, penetration = 0.75, rng = Math.random) {
    this.decks = decks;
    this.penetration = penetration;
    this.rng = rng;
    this.cards = [];
    this.position = 0;   // Index der nächsten Karte
    this.nextId = 1;     // fortlaufende Karten-ID (für die Darstellung)
    this.shuffle();
  }

  get total() {
    return this.decks * 52;
  }

  // Nach so vielen Karten liegt die Schnittkarte
  get cutCardPosition() {
    return Math.floor(this.total * this.penetration);
  }

  get dealt() {
    return this.position;
  }

  get remaining() {
    return this.total - this.position;
  }

  // Wurde die Schnittkarte erreicht? Dann wird nach der laufenden Runde gemischt.
  get cutCardReached() {
    return this.position >= this.cutCardPosition;
  }

  shuffle() {
    const cards = [];
    for (let d = 0; d < this.decks; d++) {
      for (const suit of SUITS) {
        for (const rank of RANKS) {
          cards.push({ rank, suit });
        }
      }
    }
    // Fisher-Yates: jede Reihenfolge ist gleich wahrscheinlich
    for (let i = cards.length - 1; i > 0; i--) {
      const j = Math.floor(this.rng() * (i + 1));
      [cards[i], cards[j]] = [cards[j], cards[i]];
    }
    this.cards = cards;
    this.position = 0;
  }

  draw() {
    if (this.position >= this.cards.length) {
      // Sollte bei 75 % Penetration nie passieren, aber sicher ist sicher
      throw new Error('Schuh ist leer');
    }
    const card = { ...this.cards[this.position], id: this.nextId++ };
    this.position += 1;
    return card;
  }
}
