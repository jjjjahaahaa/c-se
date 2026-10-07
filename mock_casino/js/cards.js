// Zuordnung Karte → SVG-Datei. Die SVGs werden mit tools/generate_card_svgs.py erzeugt.

const CARD_DIR = 'assets/cards';

export const SUIT_NAMES = { S: 'Pik', H: 'Herz', D: 'Karo', C: 'Kreuz' };
export const RANK_NAMES = { J: 'Bube', Q: 'Dame', K: 'König', A: 'Ass' };

export function cardUrl(card) {
  return `${CARD_DIR}/${card.rank}${card.suit}.svg`;
}

export function backUrl() {
  return `${CARD_DIR}/back.svg`;
}

// Lesbarer Name, z. B. "Herz Dame"
export function cardLabel(card) {
  return `${SUIT_NAMES[card.suit]} ${RANK_NAMES[card.rank] ?? card.rank}`;
}

// Karte auf dem Tisch als <img>
export function createCardElement(card, hidden = false) {
  const img = document.createElement('img');
  img.className = 'card';
  img.draggable = false;
  setCardFace(img, card, hidden);
  return img;
}

export function setCardFace(img, card, hidden) {
  img.src = hidden ? backUrl() : cardUrl(card);
  img.alt = hidden ? 'verdeckte Karte' : cardLabel(card);
  img.dataset.rank = hidden ? '' : card.rank;
  img.dataset.hidden = hidden ? '1' : '0';
}

// Kachel im Verlaufs-Panel: zeigt nur die linke obere Ecke der Karte (Rang + Farbe).
// Es ist dieselbe Ecke wie auf dem Tisch, nur in anderer Grösse → gleiche Templates.
export function createHistoryTile(card) {
  const tile = document.createElement('div');
  tile.className = 'history-tile';
  tile.title = cardLabel(card);
  tile.dataset.rank = card.rank;
  const img = document.createElement('img');
  img.src = cardUrl(card);
  img.alt = cardLabel(card);
  img.draggable = false;
  tile.appendChild(img);
  return tile;
}
