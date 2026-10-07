"""Blackjack-Simulation ohne Bildschirm.

Spielt Runden nach denselben Regeln wie das Mock-Casino (Rules): Schuh mit Schnittkarte oder
Mischen nach jeder Runde, Dealer-Peek, Versicherung, Blackjack 3:2, Double (auch nach Split),
Split bis max_hands (gesplittete Asse eine Karte), Late Surrender, S17/H17, Seven-Card Charlie.

Der Spieler (siehe players.py) sieht jede offene Karte, entscheidet über Einsatz, Versicherung
und Spielzüge. Ergebnisse in Einheiten (1 = Mindesteinsatz).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from ..models import Action, HandState, Rules, hand_total, is_blackjack

# Schuh nur mit Punktwert-Klassen: J/Q/K sind für das Spiel identisch mit 10
DECK = ["2", "3", "4", "5", "6", "7", "8", "9", "A"] * 4 + ["10"] * 16


class Player(Protocol):
    name: str

    def on_shuffle(self) -> None: ...
    def observe(self, rank: str) -> None: ...
    def bet(self) -> int: ...
    def insurance(self) -> bool: ...
    def decide(self, hand: HandState) -> Action: ...
    def on_round_end(self) -> None: ...


class Shoe:
    def __init__(self, rules: Rules, rng: random.Random):
        self.rules = rules
        self.rng = rng
        self.cards: list[str] = []
        self.pos = 0
        self.cut = int(rules.decks * 52 * rules.penetration)
        self.shuffles = 0

    def shuffle(self) -> None:
        self.cards = DECK * self.rules.decks
        self.rng.shuffle(self.cards)
        self.pos = 0
        self.shuffles += 1

    @property
    def needs_shuffle(self) -> bool:
        return not self.cards or self.pos >= self.cut

    def draw(self) -> str:
        if self.pos >= len(self.cards):  # nur bei extremen Einstellungen
            self.shuffle()
        card = self.cards[self.pos]
        self.pos += 1
        return card


@dataclass
class _Hand:
    cards: list[str]
    bet: int
    from_split: bool = False
    split_aces: bool = False
    done: bool = False
    surrendered: bool = False


@dataclass
class RoundResult:
    bet: int            # Starteinsatz
    net: float          # Gewinn/Verlust der Runde in Einheiten (inkl. Versicherung)
    wagered: float      # insgesamt eingesetzt (inkl. Double/Split/Versicherung)
    hands: int = 1


class Simulator:
    def __init__(self, rules: Rules, player: Player, seed: int = 1):
        self.rules = rules
        self.player = player
        self.shoe = Shoe(rules, random.Random(seed))

    def _draw(self, visible: bool = True) -> str:
        card = self.shoe.draw()
        if visible:
            self.player.observe(card)
        return card

    def play_round(self) -> RoundResult:
        r, p = self.rules, self.player
        if self.shoe.needs_shuffle or r.shuffle_every_round:
            self.shoe.shuffle()
            p.on_shuffle()

        bet = max(1, int(p.bet()))
        player = [self._draw()]
        up = self._draw()
        player.append(self._draw())
        hole = self._draw(visible=False)
        dealer = [up, hole]
        dealer_bj = is_blackjack(dealer)
        net = 0.0
        wagered = float(bet)

        # Versicherung
        insurance = 0.0
        if up == "A" and r.insurance and p.insurance():
            insurance = bet / 2
            wagered += insurance
            net += 2 * insurance if dealer_bj else -insurance

        player_bj = is_blackjack(player)
        peeks = r.dealer_peek and up in ("A", "10")
        if (peeks and dealer_bj) or player_bj:
            p.observe(hole)
            if player_bj and dealer_bj:
                pass
            elif player_bj:
                net += bet * r.blackjack_pays
            else:
                net -= bet
            p.on_round_end()
            return RoundResult(bet, net, wagered)

        hands = [_Hand(player, bet)]
        i = 0
        while i < len(hands):
            h = hands[i]
            if len(h.cards) == 1:  # zweite Karte nach einem Split
                h.cards.append(self._draw())
                if h.split_aces and not r.hit_split_aces:
                    h.done = True
            while not h.done:
                total, _ = hand_total(h.cards)
                if total >= 21 or (r.seven_card_charlie and len(h.cards) >= 7):
                    break
                n = len(hands)
                pair = len(h.cards) == 2 and h.cards[0] == h.cards[1]
                state = HandState(
                    player=list(h.cards), dealer_up=up,
                    can_double=len(h.cards) == 2 and (not h.from_split or r.double_after_split)
                    and (r.double_any_two or 9 <= total <= 11),
                    can_split=pair and n < r.max_hands and (not h.split_aces or r.resplit_aces),
                    can_surrender=r.late_surrender and n == 1 and len(h.cards) == 2 and not h.from_split,
                    from_split=h.from_split, hand_count=n,
                )
                action = p.decide(state)
                if action == Action.SURRENDER and state.can_surrender:
                    h.surrendered = h.done = True
                elif action == Action.DOUBLE and state.can_double:
                    wagered += h.bet
                    h.bet *= 2
                    h.cards.append(self._draw())
                    h.done = True
                elif action == Action.SPLIT and state.can_split:
                    wagered += h.bet
                    aces = h.cards[0] == "A"
                    second = h.cards.pop()
                    h.from_split = True
                    h.split_aces = aces
                    hands.insert(i + 1, _Hand([second], h.bet, True, aces))
                    h.cards.append(self._draw())
                    if aces and not r.hit_split_aces:
                        h.done = True
                elif action == Action.STAND:
                    h.done = True
                else:  # HIT (oder nicht erlaubte Aktion → ziehen)
                    h.cards.append(self._draw())
            i += 1

        # Dealer spielt
        p.observe(hole)
        alive = [h for h in hands if not h.surrendered and hand_total(h.cards)[0] <= 21]
        charlie = r.seven_card_charlie
        needs_dealer = [h for h in alive if not (charlie and len(h.cards) >= 7)]
        if needs_dealer and not dealer_bj:
            while True:
                total, soft = hand_total(dealer)
                if total < 17 or (total == 17 and soft and r.hit_soft_17):
                    dealer.append(self._draw())
                else:
                    break
        dealer_total = hand_total(dealer)[0]

        for h in hands:
            total = hand_total(h.cards)[0]
            if h.surrendered:
                net -= h.bet / 2
            elif total > 21:
                net -= h.bet
            elif dealer_bj:            # nur ohne Peek möglich: alle Einsätze verloren
                net -= h.bet
            elif charlie and len(h.cards) >= 7:
                net += h.bet
            elif dealer_total > 21 or total > dealer_total:
                net += h.bet
            elif total < dealer_total:
                net -= h.bet
        p.on_round_end()
        return RoundResult(bet, net, wagered, len(hands))


@dataclass
class SimulationResult:
    name: str
    mode: str                         # "shoe" (75 %) oder "every_round"
    bets: np.ndarray                  # Starteinsatz pro Runde
    nets: np.ndarray                  # Ergebnis pro Runde (Einheiten)
    wagered: np.ndarray
    shuffles: int
    info: dict = field(default_factory=dict)
    shoe_ids: np.ndarray | None = None  # Nummer des Schuhs pro Runde (für das Intervall)

    @property
    def rounds(self) -> int:
        return len(self.nets)

    @property
    def net(self) -> float:
        return float(self.nets.sum())

    @property
    def ev_per_round(self) -> float:
        return float(self.nets.mean())

    @property
    def sd_per_round(self) -> float:
        return float(self.nets.std(ddof=1))

    @property
    def ci95(self) -> float:
        """Halbe Breite des 95-%-Vertrauensintervalls für den Gewinn pro Runde.

        Runden aus demselben Schuh sind nicht unabhängig (der Count koppelt die Einsätze).
        Deshalb wird – wenn die Schuhnummern bekannt sind – auf Schuh-Ebene gerechnet
        (Cluster-Standardfehler). Sonst wie bei unabhängigen Runden."""
        if self.shoe_ids is None:
            return 1.96 * self.sd_per_round / np.sqrt(self.rounds)
        return shoe_ci95(*per_shoe(self.shoe_ids, self.nets))

    @property
    def ev_per_unit_bet(self) -> float:
        """Gewinn pro eingesetzter Starteinheit (Spielervorteil in %)."""
        return float(self.nets.sum() / self.bets.sum())

    @property
    def mean_bet(self) -> float:
        return float(self.bets.mean())

    @property
    def max_drawdown(self) -> float:
        curve = np.cumsum(self.nets)
        peak = np.maximum.accumulate(np.concatenate([[0.0], curve]))[1:]
        return float((peak - curve).max())

    def summary(self) -> dict:
        return {
            "name": self.name, "mode": self.mode, "rounds": self.rounds,
            "net": round(self.net, 2), "ev_per_round": round(self.ev_per_round, 5),
            "ci95": round(self.ci95, 5), "ev_per_unit_bet": round(self.ev_per_unit_bet, 5),
            "sd_per_round": round(self.sd_per_round, 4), "mean_bet": round(self.mean_bet, 3),
            "max_drawdown": round(self.max_drawdown, 2), "shuffles": self.shuffles,
            **self.info,
        }


def per_shoe(shoe_ids: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Summe der Werte und Anzahl Runden pro Schuh."""
    _, idx = np.unique(shoe_ids, return_inverse=True)
    sums = np.bincount(idx, weights=values)
    counts = np.bincount(idx).astype(float)
    return sums, counts


def shoe_ci95(shoe_net: np.ndarray, shoe_rounds: np.ndarray) -> float:
    """95-%-Intervall (halbe Breite) für Gewinn/Runde mit dem Schuh als unabhängiger Einheit
    (Verhältnisschätzer: Summe Gewinn / Summe Runden, Standardfehler nach der Delta-Methode)."""
    n = len(shoe_net)
    if n < 2:
        return float("nan")
    ev = shoe_net.sum() / shoe_rounds.sum()
    resid = (shoe_net - ev * shoe_rounds) / shoe_rounds.mean()
    return float(1.96 * resid.std(ddof=1) / np.sqrt(n))


def simulate(player: Player, rules: Rules, rounds: int = 10_000, seed: int = 1,
             mode: str = "shoe") -> SimulationResult:
    """Spielt `rounds` Runden. Gleicher Seed → gleiche Kartenfolge pro Schuh."""
    sim = Simulator(rules, player, seed)
    bets = np.empty(rounds)
    nets = np.empty(rounds)
    wagered = np.empty(rounds)
    shoes = np.empty(rounds, dtype=np.int64)
    for k in range(rounds):
        res = sim.play_round()
        bets[k], nets[k], wagered[k] = res.bet, res.net, res.wagered
        shoes[k] = sim.shoe.shuffles
    return SimulationResult(player.name, mode, bets, nets, wagered, sim.shoe.shuffles,
                            shoe_ids=shoes)


@dataclass
class ShoeTotals:
    """Ergebnis eines langen Laufs, zusammengefasst pro Schuh (spart Speicher).

    Alle Varianten mit gleichem Seed spielen exakt dieselben Schuhe (gleiche Mischfolge).
    Dadurch lassen sich zwei Varianten Schuh für Schuh vergleichen (gepaarter Vergleich)."""

    net: np.ndarray        # Gewinn pro Schuh
    rounds: np.ndarray     # Runden pro Schuh
    bets: np.ndarray       # Summe der Starteinsätze pro Schuh
    sum_sq: float          # Summe der quadrierten Rundenergebnisse (für die Streuung)

    @staticmethod
    def concat(parts: list["ShoeTotals"]) -> "ShoeTotals":
        return ShoeTotals(np.concatenate([p.net for p in parts]),
                          np.concatenate([p.rounds for p in parts]),
                          np.concatenate([p.bets for p in parts]),
                          float(sum(p.sum_sq for p in parts)))

    @property
    def total_rounds(self) -> int:
        return int(self.rounds.sum())

    @property
    def ev_per_round(self) -> float:
        return float(self.net.sum() / self.rounds.sum())

    @property
    def ci95(self) -> float:
        return shoe_ci95(self.net, self.rounds)

    @property
    def ev_per_unit_bet(self) -> float:
        return float(self.net.sum() / self.bets.sum())

    @property
    def mean_bet(self) -> float:
        return float(self.bets.sum() / self.rounds.sum())

    @property
    def sd_per_round(self) -> float:
        n = self.rounds.sum()
        return float(np.sqrt(self.sum_sq / n - (self.net.sum() / n) ** 2))


def simulate_shoes(player: Player, rules: Rules, shoes: int, seed: int = 1) -> ShoeTotals:
    """Spielt genau `shoes` Schuhe (bis zur Schnittkarte) und fasst pro Schuh zusammen."""
    sim = Simulator(rules, player, seed)
    net = np.zeros(shoes)
    rounds = np.zeros(shoes)
    bets = np.zeros(shoes)
    sum_sq = 0.0
    while True:
        # Vor der Runde mischen, falls nötig – danach gehört die Runde zu diesem Schuh
        if sim.shoe.needs_shuffle and sim.shoe.shuffles >= shoes:
            break
        res = sim.play_round()
        k = sim.shoe.shuffles - 1
        net[k] += res.net
        rounds[k] += 1
        bets[k] += res.bet
        sum_sq += res.net * res.net
    return ShoeTotals(net, rounds, bets, sum_sq)
