// Oberfläche: verbindet Game (Logik) mit dem DOM, Buttons, Tastatur und Logger.

import { Game, PHASE } from './game.js';
import { handTotal } from './rules.js';
import { createCardElement, createHistoryTile, setCardFace, cardLabel } from './cards.js';
import { GroundTruthLogger } from './logger.js';

const $ = (id) => document.getElementById(id);

const OUTCOME_TEXT = {
  win: 'Gewonnen',
  blackjack: 'Blackjack!',
  lose: 'Verloren',
  bust: 'Überkauft',
  push: 'Unentschieden',
  surrender: 'Aufgegeben',
};

const BASE_TIMING = { dealCard: 450, dealerCard: 650 };

// ----------------------------------------------------------------------
// Konfiguration laden: Server-Einstellungen, überschreibbar per URL-Parameter
// z. B. index.html?seed=42&speed=0&clear=500
// ----------------------------------------------------------------------

async function loadConfig() {
  let server = {};
  try {
    const res = await fetch('/api/config');
    if (res.ok) server = await res.json();
  } catch {
    // Seite wurde ohne server.py geöffnet → Standardwerte
  }
  const params = new URLSearchParams(window.location.search);
  const num = (key, fallback) => (params.has(key) ? Number(params.get(key)) : fallback);
  return {
    debug: Boolean(server.debug),
    decks: num('decks', server.decks ?? 6),
    penetration: num('penetration', server.penetration ?? 0.75),
    seed: params.has('seed') ? Number(params.get('seed')) : server.seed ?? null,
    shuffleEveryRound: params.has('every')
      ? params.get('every') === '1'
      : Boolean(server.shuffleEveryRound),
    hideHoleCard: params.has('hide') ? params.get('hide') === '1' : Boolean(server.hideHoleCard),
    speed: num('speed', 1),
    clear: num('clear', 2500),
  };
}

// ----------------------------------------------------------------------
// Darstellung
// ----------------------------------------------------------------------

class TableView {
  constructor(game) {
    this.game = game;
    this.cardElements = new Map(); // Karten-ID → <img>, damit Animationen nicht neu starten
    this.bet = 10;
  }

  // Karte im richtigen Container anzeigen (neue Karten werden animiert)
  placeCard(container, card, hidden) {
    let el = this.cardElements.get(card.id);
    if (!el) {
      el = createCardElement(card, hidden);
      el.dataset.cardId = String(card.id);
      el.classList.add('dealt');
      this.cardElements.set(card.id, el);
    } else if ((el.dataset.hidden === '1') !== hidden) {
      // Hole Card wird umgedreht
      setCardFace(el, card, hidden);
      el.classList.remove('dealt');
      el.classList.add('flip');
    }
    if (el.parentElement !== container) container.appendChild(el);
  }

  render() {
    const g = this.game;
    $('bankroll').textContent = formatMoney(g.bankroll);
    $('round').textContent = g.round;
    $('shoe-number').textContent = g.shoeNumber;
    $('bet-value').textContent = this.bet;

    this.renderDealer();
    this.renderHands();
    this.renderShoe();
    this.renderButtons();
  }

  renderDealer() {
    const g = this.game;
    const box = $('dealer-cards');
    const ids = new Set();
    g.dealer.cards.forEach((card, i) => {
      ids.add(card.id);
      this.placeCard(box, card, i === 1 && g.dealer.holeHidden);
    });
    removeStale(box, ids, this.cardElements);
    const visible = g.dealer.holeHidden ? g.dealer.cards.slice(0, 1) : g.dealer.cards;
    $('dealer-total').textContent = visible.length ? formatTotal(visible) : '';
  }

  renderHands() {
    const g = this.game;
    const wrap = $('player-hands');
    // Anzahl Hand-Container an die Anzahl Hände anpassen
    while (wrap.children.length < g.hands.length) {
      const hand = document.createElement('div');
      hand.className = 'hand';
      hand.innerHTML = '<div class="cards"></div><div class="hand-info"></div>';
      wrap.appendChild(hand);
    }
    while (wrap.children.length > g.hands.length) wrap.lastChild.remove();

    g.hands.forEach((hand, i) => {
      const box = wrap.children[i];
      const cardsBox = box.querySelector('.cards');
      const ids = new Set();
      hand.cards.forEach((card) => {
        ids.add(card.id);
        this.placeCard(cardsBox, card, false);
      });
      removeStale(cardsBox, ids, this.cardElements);
      box.classList.toggle('active', g.phase === PHASE.PLAYER && i === g.activeHand);

      let info = `Einsatz ${formatMoney(hand.bet)}`;
      if (hand.cards.length) info += ` · ${formatTotal(hand.cards)}`;
      if (hand.outcome) {
        info += ` <span class="outcome ${hand.outcome}">${OUTCOME_TEXT[hand.outcome]}</span>`;
      }
      box.querySelector('.hand-info').innerHTML = info;
    });
  }

  renderShoe() {
    const shoe = this.game.shoe;
    $('shoe-fill').style.width = `${(100 * shoe.dealt) / shoe.total}%`;
    $('cut-marker').style.left = `${100 * shoe.penetration}%`;
    const untilCut = Math.max(0, shoe.cutCardPosition - shoe.dealt);
    $('shoe-text').textContent =
      `${shoe.dealt} von ${shoe.total} Karten gespielt · ` +
      (this.game.unseenCount ? `${this.game.unseenCount} ungesehen · ` : '') +
      (this.game.rules.shuffleEveryRound
        ? 'Mischen nach jeder Runde'
        : `noch ${untilCut} Karten bis zur Schnittkarte`);
    $('shuffle-warning').hidden = !this.game.shufflePending;
    $('history-count').textContent = this.game.history.length;
  }

  renderButtons() {
    const a = this.game.availableActions();
    $('btn-deal').disabled = !a.deal || this.bet > this.game.bankroll || this.bet <= 0;
    $('btn-hit').disabled = !a.hit;
    $('btn-stand').disabled = !a.stand;
    $('btn-double').disabled = !a.double;
    $('btn-split').disabled = !a.split;
    $('btn-surrender').disabled = !a.surrender;
    $('insurance-row').hidden = !a.insurance && this.game.phase !== PHASE.INSURANCE;
    $('btn-insure-yes').disabled = !a.insurance;
    $('btn-insure-no').disabled = !a.insurance;
    for (const chip of document.querySelectorAll('.chip')) chip.disabled = !a.deal;
    $('btn-clear-bet').disabled = !a.deal;
    $('btn-shuffle-now').disabled = !a.deal;
  }

  addHistoryTile(card) {
    $('history').appendChild(createHistoryTile(card));
  }

  clearHistory() {
    $('history').replaceChildren();
  }

  setMessage(text) {
    $('message').textContent = text;
  }
}

function removeStale(container, keepIds, cardElements) {
  for (const el of [...container.children]) {
    const id = Number(el.dataset.cardId);
    if (!keepIds.has(id)) {
      el.remove();
      cardElements.delete(id);
    }
  }
}

function formatTotal(cards) {
  const { total, soft } = handTotal(cards);
  if (total > 21) return `${total}`;
  return soft && total !== 21 ? `Soft ${total}` : `${total}`;
}

function formatMoney(x) {
  return Number.isInteger(x) ? String(x) : x.toFixed(1);
}

// ----------------------------------------------------------------------
// Start
// ----------------------------------------------------------------------

async function main() {
  const config = await loadConfig();
  const logger = new GroundTruthLogger(config.debug);
  $('debug-badge').hidden = !config.debug;
  $('opt-shuffle-every-round').checked = config.shuffleEveryRound;
  $('opt-hide-hole').checked = config.hideHoleCard;
  $('opt-speed').value = String(config.speed);
  $('opt-clear').value = String(config.clear);

  let view = null;
  let bannerTimer = null;

  const hooks = {
    update: () => view?.render(),

    cardRevealed: (card, info) => {
      view?.addHistoryTile(card);
      logger.log('card', {
        rank: card.rank,
        suit: card.suit,
        target: info.target,    // 'player' oder 'dealer'
        hand: info.hand,        // Index der Spielerhand (nach Split > 0)
        hole: info.hole,        // true = Hole Card des Dealers
        round: info.round,
        shoe: info.shoe,
        seq: info.seq,          // Position im Verlauf seit dem letzten Mischen
      });
    },

    // Karte wurde verdeckt abgeräumt: nicht im Verlauf, aber in der Ground Truth als "unseen"
    cardUnseen: (card, info) => {
      logger.log('unseen', {
        rank: card.rank, suit: card.suit, target: info.target, hand: info.hand,
        hole: info.hole, round: info.round, shoe: info.shoe,
      });
    },

    roundStarted: (round) => {
      view?.setMessage('');
      logger.log('round_start', { round, shoe: game.shoeNumber });
    },

    roundEnded: (summary) => {
      const net = summary.net;
      const text = net > 0 ? `+${formatMoney(net)}` : net < 0 ? `${formatMoney(net)}` : '±0';
      view?.setMessage(`Runde ${summary.round}: ${text}`);
      logger.log('round_end', summary);
    },

    tableCleared: () => {
      view?.setMessage('Einsatz wählen und austeilen');
    },

    shuffled: (info) => {
      view?.clearHistory();
      logger.log('shuffle', info);
      // Kurze Einblendung, damit man das Mischen auch auf dem Bildschirm sieht
      const banner = $('shuffle-banner');
      banner.hidden = false;
      clearTimeout(bannerTimer);
      bannerTimer = setTimeout(() => { banner.hidden = true; }, 1500);
    },
  };

  const game = new Game({
    rules: {
      decks: config.decks,
      penetration: config.penetration,
      shuffleEveryRound: config.shuffleEveryRound,
      hideUnneededHoleCard: config.hideHoleCard,
    },
    seed: config.seed,
    hooks,
    timing: timingFor(config.speed, config.clear),
  });
  view = new TableView(game);

  $('rules-text').textContent =
    `${game.rules.decks} Decks · ${Math.round(game.rules.penetration * 100)} % Penetration · ` +
    'S17 · BJ 3:2 · DAS · Late Surrender';

  logger.log('session_start', {
    decks: game.rules.decks,
    penetration: game.rules.penetration,
    seed: config.seed,
    shuffleEveryRound: game.rules.shuffleEveryRound,
    hideHoleCard: game.rules.hideUnneededHoleCard,
  });

  // Fehler aus Spielaktionen nur anzeigen, nicht abstürzen
  const act = (fn) => () => {
    Promise.resolve()
      .then(fn)
      .catch((err) => view.setMessage(err.message));
  };

  // --- Buttons ---------------------------------------------------------
  for (const chip of document.querySelectorAll('.chip')) {
    chip.addEventListener('click', () => {
      view.bet = Math.min(view.bet + Number(chip.dataset.chip), game.bankroll);
      view.render();
    });
  }
  $('btn-clear-bet').addEventListener('click', () => { view.bet = 0; view.render(); });
  $('btn-deal').addEventListener('click', act(() => game.deal(view.bet)));
  $('btn-hit').addEventListener('click', act(() => game.hit()));
  $('btn-stand').addEventListener('click', act(() => game.stand()));
  $('btn-double').addEventListener('click', act(() => game.double()));
  $('btn-split').addEventListener('click', act(() => game.split()));
  $('btn-surrender').addEventListener('click', act(() => game.surrender()));
  $('btn-insure-yes').addEventListener('click', act(() => game.insurance(true)));
  $('btn-insure-no').addEventListener('click', act(() => game.insurance(false)));
  $('btn-shuffle-now').addEventListener('click', () => game.shuffleNow());
  $('btn-reset-bankroll').addEventListener('click', () => {
    if (game.phase === PHASE.BETTING && !game.busy) {
      game.bankroll = 1000;
      view.render();
    }
  });

  // --- Einstellungen ---------------------------------------------------
  $('opt-shuffle-every-round').addEventListener('change', (e) => {
    game.rules.shuffleEveryRound = e.target.checked;
    view.render();
  });
  $('opt-hide-hole').addEventListener('change', (e) => {
    game.rules.hideUnneededHoleCard = e.target.checked;
  });
  const applyTiming = () => {
    Object.assign(game.timing, timingFor(Number($('opt-speed').value), Number($('opt-clear').value)));
  };
  $('opt-speed').addEventListener('change', applyTiming);
  $('opt-clear').addEventListener('change', applyTiming);

  // --- Tastatur --------------------------------------------------------
  const keys = {
    Enter: 'btn-deal', h: 'btn-hit', s: 'btn-stand', d: 'btn-double',
    p: 'btn-split', r: 'btn-surrender', y: 'btn-insure-yes', n: 'btn-insure-no',
  };
  document.addEventListener('keydown', (e) => {
    if (e.target instanceof HTMLSelectElement || e.repeat) return;
    const id = keys[e.key] ?? keys[e.key.toLowerCase()];
    if (id && !$(id).disabled) {
      e.preventDefault();
      $(id).click();
    }
  });

  view.render();

  // Zugriff für automatisierte Tests und die Browser-Konsole
  window.casino = { game, logger, view, cardLabel, autoplay: (rounds, pauseMs) => autoplay(game, view, rounds, pauseMs) };
  document.body.dataset.ready = '1';
}

// Automatisches Spielen mit echten Animationen – für Aufnahmen im Headless-Browser
// (Erkennungstests ohne Bildschirm). Einfache Regeln, damit auch Double/Split/Surrender vorkommen.
async function autoplay(game, view, rounds, pauseMs = 800) {
  const waitIdle = async () => {
    while (game.busy) await new Promise((r) => setTimeout(r, 20));
  };
  for (let i = 0; i < rounds; i++) {
    await waitIdle();
    if (game.phase !== PHASE.BETTING) break;
    // Wie ein Mensch: kurz warten, bevor neu gesetzt wird (der Tisch ist dann leer)
    if (i > 0 && pauseMs) await new Promise((r) => setTimeout(r, pauseMs));
    if (game.bankroll < view.bet) game.bankroll = 1000;
    await game.deal(view.bet);
    if (game.phase === PHASE.INSURANCE) await game.insurance(false);
    while (game.phase === PHASE.PLAYER) {
      const a = game.availableActions();
      const hand = game.currentHand;
      const { total, soft } = handTotal(hand.cards);
      const up = handTotal([game.dealer.cards[0]]).total;
      const pair = hand.cards.length === 2 && hand.cards[0].rank === hand.cards[1].rank;
      if (a.split && pair && ['A', '8'].includes(hand.cards[0].rank)) await game.split();
      else if (a.surrender && total === 16 && up >= 10) await game.surrender();
      else if (a.double && !soft && (total === 11 || (total === 10 && up <= 9))) await game.double();
      else if (a.hit && (total < 12 || (total < 17 && up >= 7))) await game.hit();
      else await game.stand();
    }
  }
  await waitIdle();
}

// Animationstempo: 0 = keine Pausen (z. B. für Tests), 2 = doppelt so langsam
function timingFor(speed, clear) {
  document.documentElement.style.setProperty('--deal-ms', `${Math.round(300 * speed)}ms`);
  return {
    dealCard: BASE_TIMING.dealCard * speed,
    dealerCard: BASE_TIMING.dealerCard * speed,
    clearTable: clear,
  };
}

main();
