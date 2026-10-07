"""Exakte, zusammensetzungsabhängige Blackjack-Strategie (Phase 6).

Die Strategie kennt die genaue Zusammensetzung der für den Spieler unbekannten
Restkarten und berechnet für jede Entscheidung den Erwartungswert (EV) aller
erlaubten Aktionen. In der Auswertung dient sie als theoretisches Maximum, an dem die
Zählsysteme gemessen werden. Das Modul braucht nur die Standardbibliothek und numpy.

Darstellung des Schuhs
----------------------
Ein Schuh ist ein Tupel aus 10 Ganzzahlen in der Reihenfolge von ``VALUE_RANKS``
("2" … "9", "10", "A"). Index 8 zählt alle Zehnerwerte (10/J/Q/K), Index 9 die Asse.
Voller 6-Deck-Schuh: ``(24, 24, 24, 24, 24, 24, 24, 24, 96, 24)``.

Konvention: Übergeben wird immer die Zusammensetzung der für den Spieler *unbekannten*
Karten. Sichtbare Karten (Spielerkarten, Dealer-Upcard, gespielte Karten) sind bereits
entfernt, die Hole Card des Dealers steckt noch darin.

Methode
-------
* **Dealer**: Für jede Upcard werden einmalig alle Ziehfolgen des Dealers aufgezählt und
  nach (Multimenge der gezogenen Karten, Endergebnis) zusammengefasst. Die
  Wahrscheinlichkeit einer Folge ohne Zurücklegen hängt nur von der Multimenge ab:
  ``Π_r n_r·(n_r-1)·…/(N·(N-1)·…)``. Damit ist die Dealer-Verteilung für eine beliebige
  Zusammensetzung eine einzige numpy-Rechnung (exakt, ca. 25–125 µs je nach Upcard).
  Bei Peek-Regel und Upcard A/10 wird auf "kein Dealer-Blackjack" bedingt.
* **Spieler**: Hit/Stand werden rekursiv über alle gezogenen Karten mit der jeweils
  exakten Restzusammensetzung berechnet (Memoization pro Zusammensetzung und Hand).
  Bei Peek wird auch die Ziehwahrscheinlichkeit des Spielers exakt auf "Hole Card ist
  keine Blackjack-Karte" bedingt.
* **Dealer-Nachführung** (Parameter ``dealer_mode``):

  - ``"exact"``: Die Dealer-Verteilung wird für jede Spielerhand aus der genauen
    Restzusammensetzung neu berechnet (Referenz, langsamer).
  - ``"linear"`` (Standard): Exakt für die Entscheidungs-Zusammensetzung und für jede
    Zusammensetzung mit genau einer weiteren entfernten Karte (also Stand, Double und
    die erste Hit-Karte exakt). Tiefere Knoten werden linear fortgesetzt:
    ``P(Schuh − Karten) ≈ P(Wurzel) + Σ (P(Wurzel − Karte) − P(Wurzel))``.
    Gemessene Abweichung zu ``"exact"`` (1000 zufällige Startsituationen, 6 Decks,
    0–75 % gespielt): |ΔEV| pro Aktion im Mittel 1.3e-6, max. 2.1e-4, keine einzige
    andere Entscheidung.
  - ``"fixed"``: Klassische Vereinfachung, eine Dealer-Verteilung pro Entscheidung
    (nur zum Vergleich: |ΔEV| im Mittel 6e-4, max. 1.3e-2, 1 von 1000 Entscheidungen
    anders).

* **Split** (übliche Näherung): EV(Split) = 2 × EV einer Hand, die mit einer Karte des
  Paares beginnt und ihre zweite Karte aus derselben Zusammensetzung zieht (die zweite
  Split-Hand wird also wie die erste bewertet). Danach optimales Spiel inklusive DAS.
  Re-Split: höchstens eine weitere Teilungsstufe pro Hand (genau richtig für die
  Standardregel ``max_hands=4``), mit ``X1 = A + q·max(B, 2·X0)``; A = Anteil ohne
  weitere Paarkarte, q = Wahrscheinlichkeit einer weiteren Paarkarte, B = Wert des
  nicht geteilten Paares, X0 = EV einer Split-Hand ohne Re-Split. Die Zusammensetzung
  wird für die neuen Hände nicht weiter angepasst. Gesplittete Asse bekommen genau eine
  Karte (ausser ``hit_split_aces``), 21 nach Split ist kein Blackjack.
* **Seven-Card Charlie**: Eine Hand mit 7 Karten ohne Überkaufen gewinnt sofort
  (ohne Peek verliert sie nur gegen einen Dealer-Blackjack).
* **Ohne Peek** (europäisch, wie im Mock-Casino): Ein Dealer-Blackjack schlägt jede
  Hand ausser Spieler-Blackjack und kostet den vollen (auch verdoppelten/gesplitteten)
  Einsatz. Surrender gibt wie im Mock-Casino immer die Hälfte zurück, wirkt ohne Peek
  also wie Early Surrender (deshalb ist "ohne Peek + Surrender" sogar besser als mit
  Peek: +0.12 % statt −0.34 %; ohne Surrender −0.52 %).
* Eine Hand mit 21 steht automatisch (wie im Mock-Casino), 21 wird nicht weiter gezogen.

Erwartungswert vor dem Austeilen und Effects of Removal
-------------------------------------------------------
``predeal_ev`` summiert über alle Upcards und Spieler-Startkarten (550 Situationen) mit
optimalem Spiel, Peek, 3:2-Blackjack, Surrender und Versicherung (nur wenn sie positiv
ist). Pro Upcard dient der Schuh ohne Upcard als Wurzel, alle Spielerhände teilen sich
so die Zwischenergebnisse. Laufzeit voller 6-Deck-Schuh: ca. 0.5 s (``"linear"``) bzw.
ca. 6 s (``"exact"``); beide Ergebnisse unterscheiden sich um 2e-6. Voller 6-Deck-Schuh
mit den Standardregeln: EV = −0.337 %. ``effects_of_removal`` braucht 11 solche
Rechnungen (ca. 5 s, danach gecacht). ``predeal_ev_linear`` ist die schnelle Näherung
für die Einsatzhöhe (ca. 10 µs pro Aufruf):

    EV ≈ EV_voll + (N_voll − 1) / N_rest · Σ_r m_r · EOR_r

(m_r = Anzahl entfernter Karten vom Rang r, N_rest = verbleibende Karten). Die Formel
ist die lineare Näherung in den Kartendichten: Werden m Karten entfernt, ändert sich die
Dichte genau um ``(N_voll − 1)/N_rest`` mal die Summe der Einzeleffekte, deshalb wächst
der Effekt einer entfernten Karte mit 1/Restkarten. Gemessene Abweichung zu
``predeal_ev`` (zufällige 6-Deck-Schuhe): bis 2 Decks gespielt höchstens ca. 0.002,
bei 75 % Penetration und extremen Zählständen bis ca. 0.01.

Laufzeit ``action_evs`` (``"linear"``, 1000 zufällige Startsituationen mit zufällig
abgereicherten 6-Deck-Schuhen): Mittel 1.6 ms, Median 1.1 ms, 95 % unter 4.4 ms,
Maximum ca. 15 ms (Paare kleiner Karten). ``"exact"``: Mittel 15 ms, Maximum 215 ms.

Hinweis: Die Rechnung ist wirklich zusammensetzungsabhängig. Beispiel: 10,2 gegen 4
im vollen 6-Deck-Schuh → Ziehen (EV −0.2104 statt −0.2111 beim Stehen), 9,3 oder 7,5
gegen 4 → Stehen. Das wurde mit einer unabhängigen Brute-Force-Rechnung bestätigt.
"""

from __future__ import annotations

import functools
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from operator import add

import numpy as np

from blackjack_assistant.models import (
    VALUE_RANKS,
    Action,
    HandState,
    Rules,
    hand_total,
    value_rank,
)

# ----------------------------------------------------------------------
# Konstanten und Hilfsfunktionen
# ----------------------------------------------------------------------

#: Index der Zehnerwerte bzw. Asse im Schuh-Tupel
TEN = 8
ACE = 9

#: Punktwert pro Index (Ass hart = 1, die Soft-Logik steckt in der Rekursion)
POINTS: tuple[int, ...] = (2, 3, 4, 5, 6, 7, 8, 9, 10, 1)

#: Ergebnisse der Dealer-Verteilung in dieser Reihenfolge
DEALER_OUTCOMES: tuple[str, ...] = ("17", "18", "19", "20", "21", "bust", "blackjack")
_BUST = 5
_BJ = 6

#: Position im "Stand-Vektor": [≤16, 17, 18, 19, 20, 21, Charlie]
_CHARLIE = 6

_ACTION_ORDER: tuple[Action, ...] = (
    Action.STAND, Action.HIT, Action.DOUBLE, Action.SPLIT, Action.SURRENDER,
)

DEALER_MODES = ("exact", "linear", "fixed")


def rank_index(rank: str) -> int:
    """Rang (z. B. "K", "10", "A") → Index im Schuh-Tupel."""
    return VALUE_RANKS.index(value_rank(rank))


def full_shoe(decks: int) -> tuple[int, ...]:
    """Zusammensetzung eines vollen Schuhs mit ``decks`` Decks."""
    return (4 * decks,) * 8 + (16 * decks, 4 * decks)


def remove_cards(shoe: Iterable[int], cards: Iterable[str]) -> tuple[int, ...]:
    """Entfernt Karten (Ränge) aus einer Zusammensetzung. Fehlt eine Karte → ValueError."""
    counts = list(shoe)
    for card in cards:
        i = rank_index(card)
        if counts[i] <= 0:
            raise ValueError(f"Karte {card!r} ist im Schuh nicht mehr vorhanden")
        counts[i] -= 1
    return tuple(counts)


def _minus(shoe: tuple[int, ...], i: int) -> tuple[int, ...]:
    """Schuh ohne eine Karte mit Index ``i`` (ohne Prüfung, intern)."""
    return shoe[:i] + (shoe[i] - 1,) + shoe[i + 1:]


def _soft_total(hard: int, ace: bool) -> int:
    """Bester Handwert aus hartem Wert und Ass-Flag."""
    return hard + 10 if ace and hard <= 11 else hard


def _stand_index(total: int) -> int:
    """Position des Handwerts im Stand-Vektor (alles ≤ 16 teilt sich Position 0)."""
    return total - 16 if total > 16 else 0


# ----------------------------------------------------------------------
# Dealer: Ziehfolgen einmal aufzählen, danach pro Zusammensetzung mit numpy auswerten
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class _DealerTable:
    """Alle Endzustände des Dealers für eine Upcard, als Multimengen zusammengefasst."""

    gather: np.ndarray      # (D, 10) Indizes in die abgeflachte Tabelle der fallenden Fakultäten
    n_cards: np.ndarray     # (D,) Anzahl gezogener Karten (inkl. Hole Card)
    weights: np.ndarray     # (D,) Anzahl gültiger Reihenfolgen der Multimenge
    outcome: np.ndarray     # (D,) Index in DEALER_OUTCOMES
    max_per_rank: int       # grösste Anzahl eines Rangs in einer Multimenge
    max_cards: int          # grösste Anzahl gezogener Karten


@functools.lru_cache(maxsize=None)
def _dealer_table(up: int, hit_soft_17: bool) -> _DealerTable:
    """Zählt alle Ziehfolgen des Dealers ab der Upcard ``up`` auf (unabhängig vom Schuh).

    Die erste gezogene Karte ist die Hole Card. Zwei Karten mit 21 sind ein Blackjack.
    Folgen mit derselben Multimenge und demselben Ergebnis werden zusammengefasst, weil
    ihre Wahrscheinlichkeit ohne Zurücklegen nur von der Multimenge abhängt.
    """
    found: dict[tuple[tuple[int, ...], int], int] = {}
    counts = [0] * 10

    def visit(hard: int, ace: bool, drawn: int) -> None:
        if drawn >= 1:
            total = _soft_total(hard, ace)
            soft = ace and hard <= 11
            result = None
            if hard > 21:
                result = _BUST
            elif drawn == 1 and total == 21:
                result = _BJ
            elif total > 17 or (total == 17 and not (soft and hit_soft_17)):
                result = total - 17
            if result is not None:
                key = (tuple(counts), result)
                found[key] = found.get(key, 0) + 1
                return
        for i in range(10):
            counts[i] += 1
            visit(hard + POINTS[i], ace or i == ACE, drawn + 1)
            counts[i] -= 1

    visit(POINTS[up], up == ACE, 0)

    multisets = np.array([key[0] for key in found], dtype=np.int64)
    max_per_rank = int(multisets.max())
    gather = multisets + np.arange(10, dtype=np.int64) * (max_per_rank + 1)
    n_cards = multisets.sum(axis=1)
    return _DealerTable(
        gather=gather,
        n_cards=n_cards,
        weights=np.array(list(found.values()), dtype=float),
        outcome=np.array([key[1] for key in found], dtype=np.int64),
        max_per_rank=max_per_rank,
        max_cards=int(n_cards.max()),
    )


def _dealer_distribution(table: _DealerTable, shoe: tuple[int, ...]) -> np.ndarray:
    """Exakte Verteilung des Dealer-Ergebnisses (7 Werte, siehe DEALER_OUTCOMES).

    Wahrscheinlichkeit einer Multimenge m: Anzahl Reihenfolgen · Π_r fall(n_r, m_r) /
    fall(N, |m|) mit der fallenden Fakultät fall(n, k) = n·(n−1)·…·(n−k+1).
    """
    counts = np.asarray(shoe, dtype=float)
    k = table.max_per_rank
    falling = np.ones((10, k + 1))
    falling[:, 1:] = np.cumprod(counts[:, None] - np.arange(k), axis=1)
    numerators = falling.ravel()[table.gather].prod(axis=1)
    n = counts.sum()
    denominators = np.ones(table.max_cards + 1)
    denominators[1:] = np.cumprod(n - np.arange(table.max_cards))
    probs = table.weights * numerators / denominators[table.n_cards]
    dist = np.bincount(table.outcome, weights=probs, minlength=7)
    total = dist.sum()
    # Sehr kleine Schuhe: Folgen, für die Karten fehlen, haben Wahrscheinlichkeit 0
    if 0.0 < total < 1.0 - 1e-12:
        dist /= total
    return dist


def _stand_vector(dist: list[float]) -> tuple[float, ...]:
    """EV beim Stehen für Spielerwerte ≤16, 17, …, 21 sowie den EV eines Charlie."""
    p17, p18, p19, p20, p21, bust, bj = dist
    made = (p17, p18, p19, p20, p21)
    values = [bust - sum(made) - bj]                     # ≤ 16: nur Dealer-Bust gewinnt
    for t in range(5):                                   # Spieler 17 … 21
        win = bust + sum(made[:t])
        lose = sum(made[t + 1:]) + bj
        values.append(win - lose)
    values.append(1.0 - 2.0 * bj)                        # Charlie verliert nur gegen BJ
    return tuple(values)


# ----------------------------------------------------------------------
# Rechenkontext pro Wurzel-Zusammensetzung
# ----------------------------------------------------------------------


class _Context:
    """Rekursion für eine Wurzel-Zusammensetzung und eine Dealer-Upcard.

    Knotenwerte werden pro (Zusammensetzung, harter Wert, Ass, Kartenzahl) gespeichert.
    Der "Stand-Vektor" eines Knotens enthält die Stand-EVs für alle Spielerwerte und
    wird je nach ``dealer_mode`` exakt, linear fortgesetzt oder fest übernommen.
    """

    def __init__(self, calc: ExactCalculator, root: tuple[int, ...], up: int):
        self.calc = calc
        self.rules = calc.rules
        self.up = up
        self.mode = calc.dealer_mode
        self.charlie = calc.rules.seven_card_charlie
        bj_idx = TEN if up == ACE else ACE if up == TEN else None
        # Bei Peek ist "Hole Card = Blackjack-Karte" ausgeschlossen
        self.peek_idx = bj_idx if calc.rules.dealer_peek else None
        self.root_svec = calc._svec(root, up)
        self.deltas: list[tuple[float, ...]] = []
        if self.mode == "linear":
            zero = (0.0,) * 7
            for i in range(10):
                if root[i] > 0:
                    svec = calc._svec(_minus(root, i), up)
                    self.deltas.append(tuple(a - b for a, b in zip(svec, self.root_svec)))
                else:
                    self.deltas.append(zero)
        # Im exakten Modus sind Knotenwerte unabhängig von der Wurzel → global teilen
        self.cache = calc._exact_nodes(up) if self.mode == "exact" else {}

    # --- Grundbausteine ------------------------------------------------

    def child_svec(self, svec: tuple[float, ...], child: tuple[int, ...], i: int) -> tuple[float, ...]:
        """Stand-Vektor nach dem Entfernen einer Karte mit Index ``i``."""
        if self.mode == "linear":
            return tuple(map(add, svec, self.deltas[i]))
        if self.mode == "exact":
            return self.calc._svec(child, self.up)
        return svec

    def draw_probs(self, shoe: tuple[int, ...], n: int) -> list[float]:
        """Wahrscheinlichkeit der nächsten Spielerkarte pro Index.

        Mit Peek und Upcard A/10 weiss der Spieler, dass die Hole Card keine
        Blackjack-Karte b ist: P(c) = n_c/N · P(kein BJ | Schuh − c) / P(kein BJ | Schuh).
        """
        b = self.peek_idx
        if b is not None and n >= 2:
            nb = shoe[b]
            rest = n - nb
            if rest > 0:
                f = (rest - 1) / ((n - 1) * rest)
                probs = [c * f for c in shoe]
                probs[b] = nb / (n - 1)
                return probs
        inv = 1.0 / n
        return [c * inv for c in shoe]

    # --- Rekursion ------------------------------------------------------

    def value(self, shoe: tuple[int, ...], n: int, hard: int, ace: bool, cards: int,
              svec: tuple[float, ...]) -> float:
        """Optimaler EV einer Hand, die nur noch ziehen oder stehen darf."""
        key = (shoe, hard, ace, cards if self.charlie else 0)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        total = _soft_total(hard, ace)
        stand = svec[_stand_index(total)]
        result = stand
        if total < 21:
            hit = self.hit_ev(shoe, n, hard, ace, cards, svec)
            if hit > stand:
                result = hit
        self.cache[key] = result
        return result

    def hit_ev(self, shoe: tuple[int, ...], n: int, hard: int, ace: bool, cards: int,
               svec: tuple[float, ...]) -> float:
        """EV beim Ziehen einer Karte, danach optimal weiter."""
        probs = self.draw_probs(shoe, n)
        cache = self.cache
        charlie_next = self.charlie and cards + 1 >= 7
        nc_key = cards + 1 if self.charlie else 0
        ev = 0.0
        for i in range(10):
            p = probs[i]
            if p <= 0.0:
                continue
            new_hard = hard + POINTS[i]
            if new_hard > 21:
                ev -= p
                continue
            new_ace = ace or i == ACE
            child = shoe[:i] + (shoe[i] - 1,) + shoe[i + 1:]
            if charlie_next:
                ev += p * self.child_svec(svec, child, i)[_CHARLIE]
                continue
            cached = cache.get((child, new_hard, new_ace, nc_key))
            if cached is None:
                cached = self.value(child, n - 1, new_hard, new_ace, cards + 1,
                                    self.child_svec(svec, child, i))
            ev += p * cached
        return ev

    def double_ev(self, shoe: tuple[int, ...], n: int, hard: int, ace: bool,
                  svec: tuple[float, ...]) -> float:
        """EV beim Verdoppeln (genau eine Karte, doppelter Einsatz)."""
        probs = self.draw_probs(shoe, n)
        ev = 0.0
        for i in range(10):
            p = probs[i]
            if p <= 0.0:
                continue
            new_hard = hard + POINTS[i]
            if new_hard > 21:
                ev -= p
                continue
            child = shoe[:i] + (shoe[i] - 1,) + shoe[i + 1:]
            child_svec = self.child_svec(svec, child, i)
            ev += p * child_svec[_stand_index(_soft_total(new_hard, ace or i == ACE))]
        return 2.0 * ev

    def split_ev(self, shoe: tuple[int, ...], n: int, pair: int, svec: tuple[float, ...],
                 resplit: bool) -> float:
        """Split-EV mit der üblichen Näherung (2 × EV einer Split-Hand, siehe Moduldoku)."""
        rules = self.rules
        aces = pair == ACE
        one_card_only = aces and not rules.hit_split_aces
        probs = self.draw_probs(shoe, n)
        other = 0.0          # A: Beitrag aller zweiten Karten ≠ Paarkarte
        same_value = 0.0     # B: Wert, wenn das neue Paar nicht geteilt wird
        q = probs[pair]
        for i in range(10):
            p = probs[i]
            if p <= 0.0:
                continue
            child = shoe[:i] + (shoe[i] - 1,) + shoe[i + 1:]
            child_svec = self.child_svec(svec, child, i)
            hard = POINTS[pair] + POINTS[i]
            ace = aces or i == ACE
            total = _soft_total(hard, ace)
            v = child_svec[_stand_index(total)]
            if not one_card_only and total < 21:
                v = self.value(child, n - 1, hard, ace, 2, child_svec)
                if rules.double_after_split and (rules.double_any_two or 9 <= total <= 11):
                    v = max(v, self.double_ev(child, n - 1, hard, ace, child_svec))
            if i == pair:
                same_value = v
            else:
                other += p * v
        hand = other + q * same_value                # X0: ohne Re-Split
        if resplit:
            hand = other + q * max(same_value, 2.0 * hand)
        return 2.0 * hand

    def decision(self, shoe: tuple[int, ...], n: int, hard: int, ace: bool, cards: int,
                 svec: tuple[float, ...], *, can_hit: bool, can_double: bool,
                 split_pair: int | None, resplit: bool, can_surrender: bool) -> dict[Action, float]:
        """EV aller erlaubten Aktionen für eine Hand an einem Knoten."""
        total = _soft_total(hard, ace)
        if self.charlie and cards >= 7:
            return {Action.STAND: svec[_CHARLIE]}
        evs: dict[Action, float] = {Action.STAND: svec[_stand_index(total)]}
        if can_hit and total < 21:
            evs[Action.HIT] = self.hit_ev(shoe, n, hard, ace, cards, svec)
        if can_double and total < 21:
            evs[Action.DOUBLE] = self.double_ev(shoe, n, hard, ace, svec)
        if split_pair is not None:
            evs[Action.SPLIT] = self.split_ev(shoe, n, split_pair, svec, resplit)
        if can_surrender:
            evs[Action.SURRENDER] = -0.5
        return evs


# ----------------------------------------------------------------------
# Öffentliche Schnittstelle
# ----------------------------------------------------------------------


class ExactCalculator:
    """Composition-dependent Erwartungswerte für Blackjack-Entscheidungen.

    ``dealer_mode`` steuert, wie genau die Dealer-Verteilung in der Hit-Rekursion
    nachgeführt wird (siehe Moduldoku): ``"linear"`` (Standard, schnell und praktisch
    exakt), ``"exact"`` (Referenz) oder ``"fixed"`` (klassische Vereinfachung).
    """

    #: Grenzen für die Zwischenspeicher (werden bei Überschreitung geleert)
    MAX_CACHE_ENTRIES = 300_000
    MAX_CONTEXTS = 64

    def __init__(self, rules: Rules, *, dealer_mode: str = "linear"):
        if dealer_mode not in DEALER_MODES:
            raise ValueError(f"Unbekannter dealer_mode {dealer_mode!r}, erlaubt: {DEALER_MODES}")
        self.rules = rules
        self.dealer_mode = dealer_mode
        self._svec_cache: dict[tuple[int, tuple[int, ...]], tuple[float, ...]] = {}
        self._node_caches: dict[int, dict] = {}
        self._contexts: OrderedDict[tuple[tuple[int, ...], int], _Context] = OrderedDict()
        self._predeal_cache: dict[tuple[int, ...], float] = {}
        self._eor_cache: dict[tuple[int, ...], dict[str, float]] = {}
        self._linear_model: tuple[tuple[int, ...], float, tuple[float, ...]] | None = None

    # --- Dealer -----------------------------------------------------------

    def _dist(self, shoe: tuple[int, ...], up: int) -> list[float]:
        """Dealer-Verteilung (7 Werte), bei Peek bedingt auf "kein Blackjack"."""
        dist = _dealer_distribution(_dealer_table(up, self.rules.hit_soft_17), shoe).tolist()
        bj = dist[_BJ]
        if self.rules.dealer_peek and bj > 0.0:
            if bj < 1.0:
                scale = 1.0 / (1.0 - bj)
                dist = [p * scale for p in dist[:_BJ]] + [0.0]
            # bj == 1: Situation unmöglich (Dealer hätte sicher BJ) → unbedingt lassen
        return dist

    def _svec(self, shoe: tuple[int, ...], up: int) -> tuple[float, ...]:
        """Stand-Vektor (gecacht) für eine Zusammensetzung."""
        key = (up, shoe)
        svec = self._svec_cache.get(key)
        if svec is None:
            svec = _stand_vector(self._dist(shoe, up))
            self._svec_cache[key] = svec
        return svec

    def dealer_probabilities(self, shoe: tuple[int, ...], upcard: str) -> dict[str, float]:
        """Wahrscheinlichkeiten der Dealer-Endergebnisse.

        Schlüssel "17" … "21" und "bust"; "blackjack" nur, wenn ein Dealer-Blackjack
        möglich und nicht durch den Peek ausgeschlossen ist (Upcard A/10 ohne Peek).
        ``shoe`` enthält die Hole Card (sichtbare Karten sind entfernt).
        """
        shoe = self._check_shoe(shoe)
        up = rank_index(upcard)
        dist = self._dist(shoe, up)
        result = {name: dist[i] for i, name in enumerate(DEALER_OUTCOMES[:_BJ])}
        if up in (TEN, ACE) and not self.rules.dealer_peek:
            result["blackjack"] = dist[_BJ]
        return result

    # --- Entscheidungen ---------------------------------------------------

    def action_evs(self, shoe: tuple[int, ...], player: list[str], dealer_up: str, *,
                   can_double: bool = True, can_split: bool = True, can_surrender: bool = True,
                   from_split: bool = False, hand_count: int = 1) -> dict[Action, float]:
        """EV aller erlaubten Aktionen pro Einheit des ursprünglichen Einsatzes der Hand.

        Double enthält den verdoppelten Einsatz, Split die Summe beider Hände,
        Surrender ist −0.5. Bei Peek ist ein Dealer-Blackjack bereits ausgeschlossen
        (die Entscheidung fällt nach dem Peek). Die Flags des Aufrufers werden mit den
        Tischregeln kombiniert; nur erlaubte Aktionen erscheinen im Ergebnis.
        Gesplittete Asse erkennt die Methode an ``from_split`` und Ass als erster Karte.
        """
        shoe = self._check_shoe(shoe)
        if len(player) < 2:
            raise ValueError("Die Spielerhand braucht mindestens zwei Karten")
        rules = self.rules
        up = rank_index(dealer_up)
        indices = [rank_index(c) for c in player]
        hard = sum(POINTS[i] for i in indices)
        ace = ACE in indices
        total, _ = hand_total(player)
        if total > 21:
            raise ValueError(f"Hand {player} ist überkauft")
        two_cards = len(indices) == 2

        split_aces = from_split and indices[0] == ACE and not rules.hit_split_aces
        allow_double = (
            can_double and two_cards and not split_aces
            and (rules.double_any_two or 9 <= total <= 11)
            and (not from_split or rules.double_after_split)
        )
        split_pair = None
        resplit = False
        if (can_split and two_cards and indices[0] == indices[1]
                and hand_count < rules.max_hands
                and not (indices[0] == ACE and from_split and not rules.resplit_aces)):
            split_pair = indices[0]
            resplit = hand_count + 1 < rules.max_hands and (
                indices[0] != ACE or rules.resplit_aces)
        allow_surrender = (can_surrender and rules.late_surrender and two_cards
                           and hand_count == 1 and not from_split)

        ctx = self._context(shoe, up)
        evs = ctx.decision(
            shoe, sum(shoe), hard, ace, len(indices), ctx.root_svec,
            can_hit=not split_aces, can_double=allow_double, split_pair=split_pair,
            resplit=resplit, can_surrender=allow_surrender,
        )
        return {a: evs[a] for a in _ACTION_ORDER if a in evs}

    def best_action(self, shoe: tuple[int, ...], hand: HandState) -> tuple[Action, dict[Action, float]]:
        """Beste Aktion (höchster EV) und die EVs aller erlaubten Aktionen."""
        evs = self.action_evs(
            shoe, hand.player, hand.dealer_up,
            can_double=hand.can_double, can_split=hand.can_split,
            can_surrender=hand.can_surrender, from_split=hand.from_split,
            hand_count=hand.hand_count,
        )
        best = max(evs, key=evs.__getitem__)   # bei Gleichstand gewinnt die frühere Aktion
        return best, evs

    def insurance_ev(self, shoe: tuple[int, ...]) -> float:
        """EV der Versicherung pro Einheit Versicherungseinsatz (zahlt 2:1).

        Der Dealer zeigt ein Ass, ``shoe`` enthält die unbekannten Karten inkl. Hole Card:
        EV = 2·P(Zehner) − (1 − P(Zehner)) = 3·n_10/N − 1.
        """
        shoe = self._check_shoe(shoe)
        return 3.0 * shoe[TEN] / sum(shoe) - 1.0

    # --- Erwartungswert vor dem Austeilen ---------------------------------

    def predeal_ev(self, shoe: tuple[int, ...]) -> float:
        """EV einer ganzen Runde vor dem Austeilen pro Einheit Einsatz (optimales Spiel).

        Summiert über Upcard und beide Spielerkarten (Reihenfolge egal). Enthalten sind
        Blackjack-Auszahlung, Peek, Surrender, Split-Näherung und die Versicherung, falls
        sie positiv ist. Laufzeit voller 6-Deck-Schuh ca. 1 s (``"linear"``), gecacht.
        """
        shoe = self._check_shoe(shoe)
        cached = self._predeal_cache.get(shoe)
        if cached is not None:
            return cached
        self._trim_caches()
        n = sum(shoe)
        if n < 4:
            raise ValueError("Zu wenige Karten für eine Runde")
        ev = 0.0
        for up in range(10):
            if shoe[up] == 0:
                continue
            root = _minus(shoe, up)
            ctx = _Context(self, root, up)
            n1 = n - 1
            pair_norm = 1.0 / (n1 * (n1 - 1))
            round_ev = 0.0
            for i in range(10):
                if root[i] == 0:
                    continue
                after_i = _minus(root, i)
                svec_i = ctx.child_svec(ctx.root_svec, after_i, i)
                for j in range(i, 10):
                    if after_i[j] == 0:
                        continue
                    weight = root[i] * after_i[j] * pair_norm * (1 if i == j else 2)
                    after_ij = _minus(after_i, j)
                    svec_ij = ctx.child_svec(svec_i, after_ij, j)
                    round_ev += weight * self._round_ev(ctx, after_ij, svec_ij, i, j)
            ev += shoe[up] / n * round_ev
        self._predeal_cache[shoe] = ev
        return ev

    def _round_ev(self, ctx: _Context, shoe: tuple[int, ...], svec: tuple[float, ...],
                  i: int, j: int) -> float:
        """EV einer Runde mit bekannten Startkarten (Indizes i, j) und Upcard."""
        rules = self.rules
        n = sum(shoe)
        up = ctx.up
        bj_idx = TEN if up == ACE else ACE if up == TEN else None
        q = shoe[bj_idx] / n if bj_idx is not None else 0.0      # P(Dealer-Blackjack)
        insurance = 0.0
        if rules.insurance and up == ACE:
            ins_ev = 3.0 * shoe[TEN] / n - 1.0
            if ins_ev > 0.0:
                insurance = 0.5 * ins_ev                         # halber Einsatz
        if {i, j} == {TEN, ACE}:
            return (1.0 - q) * rules.blackjack_pays + insurance
        peek = rules.dealer_peek and bj_idx is not None
        if peek and q >= 1.0:
            return -1.0 + insurance
        hard = POINTS[i] + POINTS[j]
        ace = ACE in (i, j)
        total = _soft_total(hard, ace)
        split_pair = i if i == j and rules.max_hands > 1 else None
        evs = ctx.decision(
            shoe, n, hard, ace, 2, svec,
            can_hit=True,
            can_double=rules.double_any_two or 9 <= total <= 11,
            split_pair=split_pair,
            resplit=rules.max_hands > 2 and (i != ACE or rules.resplit_aces),
            can_surrender=rules.late_surrender,
        )
        best = max(evs.values())
        if peek:
            return -q + (1.0 - q) * best + insurance
        return best + insurance

    def effects_of_removal(self, shoe: tuple[int, ...] | None = None) -> dict[str, float]:
        """Effects of Removal: Änderung von ``predeal_ev``, wenn eine Karte entfernt wird.

        Ohne Argument für den vollen Schuh laut ``rules.decks``. Braucht 11 Aufrufe von
        ``predeal_ev`` (ca. 9 s bei 6 Decks), das Ergebnis wird gecacht.
        """
        shoe = full_shoe(self.rules.decks) if shoe is None else self._check_shoe(shoe)
        cached = self._eor_cache.get(shoe)
        if cached is not None:
            return dict(cached)
        base = self.predeal_ev(shoe)
        eors = {}
        for i, name in enumerate(VALUE_RANKS):
            eors[name] = self.predeal_ev(_minus(shoe, i)) - base if shoe[i] > 0 else 0.0
        self._eor_cache[shoe] = eors
        return dict(eors)

    def predeal_ev_linear(self, shoe: tuple[int, ...]) -> float:
        """Schnelle lineare Näherung von ``predeal_ev`` (wenige Mikrosekunden).

        EV ≈ EV_voll + (N_voll − 1)/N_rest · Σ_r m_r·EOR_r, m_r = entfernte Karten vom
        Rang r. Der erste Aufruf berechnet die EORs des vollen Schuhs (einige Sekunden).
        """
        if self._linear_model is None:
            full = full_shoe(self.rules.decks)
            eors = self.effects_of_removal(full)
            self._linear_model = (full, self.predeal_ev(full),
                                  tuple(eors[name] for name in VALUE_RANKS))
        full, base, eor = self._linear_model
        if len(shoe) != 10:
            raise ValueError("Der Schuh braucht 10 Einträge (Reihenfolge VALUE_RANKS)")
        n_full = sum(full)
        n_rest = sum(shoe)
        if n_rest <= 0:
            raise ValueError("Der Schuh ist leer")
        shift = 0.0
        for f, s, e in zip(full, shoe, eor):
            shift += (f - s) * e
        return base + (n_full - 1) / n_rest * shift

    # --- Interne Verwaltung -----------------------------------------------

    @staticmethod
    def _check_shoe(shoe: Iterable[int]) -> tuple[int, ...]:
        shoe = tuple(int(c) for c in shoe)
        if len(shoe) != 10:
            raise ValueError("Der Schuh braucht 10 Einträge (Reihenfolge VALUE_RANKS)")
        if min(shoe) < 0 or sum(shoe) < 2:
            raise ValueError(f"Ungültige Zusammensetzung: {shoe}")
        return shoe

    def _context(self, shoe: tuple[int, ...], up: int) -> _Context:
        """Rechenkontext für eine Wurzel holen oder anlegen (kleiner LRU-Speicher)."""
        key = (shoe, up)
        ctx = self._contexts.get(key)
        if ctx is not None:
            self._contexts.move_to_end(key)
            return ctx
        self._trim_caches()
        ctx = _Context(self, shoe, up)
        self._contexts[key] = ctx
        if len(self._contexts) > self.MAX_CONTEXTS:
            self._contexts.popitem(last=False)
        return ctx

    def _exact_nodes(self, up: int) -> dict:
        """Gemeinsamer Knotenspeicher pro Upcard für den exakten Modus."""
        return self._node_caches.setdefault(up, {})

    def _trim_caches(self) -> None:
        """Zwischenspeicher leeren, bevor sie zu viel Arbeitsspeicher belegen."""
        nodes = sum(len(c) for c in self._node_caches.values())
        if len(self._svec_cache) > self.MAX_CACHE_ENTRIES or nodes > self.MAX_CACHE_ENTRIES:
            self._svec_cache.clear()
            self._node_caches.clear()
            self._contexts.clear()
