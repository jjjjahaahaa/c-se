"""Spielertypen für die Simulation.

- StrategyPlayer: Basic Strategy (flacher Einsatz) oder Zählsystem + Abweichungen + Staffelung
- ExactPlayer:    merkt sich alle gesehenen Karten und berechnet jede Entscheidung exakt aus der
                  Restzusammensetzung (theoretisches Maximum); Einsatz nach berechnetem Vorteil
- JevPlayer:      Spielzüge von Jev (API), Einsatz und Versicherung über Hi-Lo
"""

from __future__ import annotations

from ..counting.counter import Counter
from ..models import Action, HandState, Rules
from ..strategy.betting import BetRamp
from ..strategy.engine import StrategyEngine
from .exact import ExactCalculator, full_shoe, rank_index

DEFAULT_RAMP = [[2, 2], [3, 4], [4, 6], [5, 8]]


class StrategyPlayer:
    """Basic Strategy ohne Zählen (system=None) oder mit Zählsystem."""

    def __init__(self, rules: Rules, system: str | None = None, deviations: bool = True,
                 ramp: list | None = None, name: str | None = None):
        self.rules = rules
        self.counting = system is not None
        key = system or "hi_lo"
        self.counter = Counter(key, rules.decks, shuffle_every_round=rules.shuffle_every_round)
        self.engine = StrategyEngine(rules, key, use_deviations=self.counting and deviations)
        self.ramp = BetRamp(ramp or DEFAULT_RAMP, unit=1, decks=rules.decks)
        self.name = name or (self.counter.system.name if self.counting else "Basic Strategy")

    def on_shuffle(self) -> None:
        self.counter.shuffle("simulation")

    def observe(self, rank: str) -> None:
        self.counter.add(rank)

    def on_round_end(self) -> None:
        self.counter.round_end()

    def bet(self) -> int:
        if not self.counting:
            return 1
        return self.ramp.advise(self.counter.state()).units

    def insurance(self) -> bool:
        return self.counting and self.engine.take_insurance(self.counter.state())

    def decide(self, hand: HandState) -> Action:
        count = self.counter.state() if self.counting else None
        return self.engine.decide(hand, count).action


class ExactPlayer:
    """Composition-dependent: exakte Erwartungswerte aus der Restzusammensetzung.

    Einsatz: Der Vorteil vor dem Austeilen wird linear aus den Effects of Removal geschätzt
    (exakte Pre-deal-Berechnung pro Runde wäre zu langsam) und in einen "Hi-Lo-äquivalenten"
    True Count umgerechnet: TC ≈ (Vorteil − Vorteil voller Schuh) / 0,5 %. Damit nutzt der
    Spieler dieselbe Einsatzstaffelung wie die Zählsysteme – der Vergleich ist fair.
    """

    TC_PER_ADVANTAGE = 1 / 0.005

    def __init__(self, rules: Rules, ramp: list | None = None, name: str = "Exakt (Restzusammensetzung)"):
        self.rules = rules
        self.calc = ExactCalculator(rules)
        self.full = full_shoe(rules.decks)
        self.base_ev = self.calc.predeal_ev_linear(self.full)
        self.ramp = sorted((float(t), int(u)) for t, u in (ramp or DEFAULT_RAMP))
        self.name = name
        self.on_shuffle()

    def on_shuffle(self) -> None:
        self.shoe = list(self.full)

    def observe(self, rank: str) -> None:
        self.shoe[rank_index(rank)] -= 1

    def on_round_end(self) -> None:
        if self.rules.shuffle_every_round:
            self.on_shuffle()

    def advantage(self) -> float:
        return self.calc.predeal_ev_linear(tuple(self.shoe))

    def bet(self) -> int:
        tc_equivalent = (self.advantage() - self.base_ev) * self.TC_PER_ADVANTAGE
        units = 1
        for threshold, u in self.ramp:
            if tc_equivalent >= threshold:
                units = u
        return units

    def insurance(self) -> bool:
        return self.calc.insurance_ev(tuple(self.shoe)) > 0

    def decide(self, hand: HandState) -> Action:
        action, _ = self.calc.best_action(tuple(self.shoe), hand)
        return action


class JevPlayer(StrategyPlayer):
    """Spielzüge von Jev, Einsatz/Versicherung mit Hi-Lo. Ohne API-Key nicht verfügbar."""

    def __init__(self, rules: Rules, ramp: list | None = None, engine=None):
        super().__init__(rules, "hi_lo", True, ramp, name="Jev + Hi-Lo")
        from ..strategy.jev import JevEngine

        self.jev = engine or JevEngine(rules, "hi_lo", blocking=True)

    @property
    def available(self) -> bool:
        return self.jev.available

    def decide(self, hand: HandState) -> Action:
        return self.jev.decide(hand, self.counter.state()).action
