"""Entscheidungs-Engines mit gemeinsamer Schnittstelle.

- StrategyEngine: Basic Strategy + Abweichungen (läuft immer offline)
- JevEngine (strategy/jev.py): TypeSafe-Jev-API, fällt ohne Key auf StrategyEngine zurück

Beide liefern ein `Decision` (Aktion, Quelle, Hinweis, optional Wahrscheinlichkeiten).
"""

from __future__ import annotations

from typing import Protocol

from ..counting.counter import CountState
from ..models import Action, Decision, HandState, Rules
from .basic import basic_action
from .deviations import DeviationSet


class DecisionEngine(Protocol):
    name: str

    def decide(self, hand: HandState, count: CountState) -> Decision: ...

    def take_insurance(self, count: CountState) -> bool: ...


class StrategyEngine:
    """Basic Strategy, optional mit Index-Abweichungen (Illustrious 18 + Fab 4)."""

    name = "strategy"

    def __init__(self, rules: Rules, system: str = "hi_lo", use_deviations: bool = True):
        self.rules = rules
        self.system = system
        self.use_deviations = use_deviations
        self.deviations = DeviationSet(system, rules.decks)

    def _counting_useful(self, count: CountState | None) -> bool:
        return self.use_deviations and count is not None and not count.ineffective

    def take_insurance(self, count: CountState | None) -> bool:
        if not self.rules.insurance or not self._counting_useful(count):
            return False  # Basic Strategy: nie versichern
        take, _ = self.deviations.insurance(count)
        return take

    def decide(self, hand: HandState, count: CountState | None = None) -> Decision:
        basic = basic_action(hand, self.rules)
        if not self._counting_useful(count):
            return Decision(basic, source="basic")

        # 1) Surrender-Indizes (nur, wenn Aufgeben gerade erlaubt ist)
        can_surrender = (hand.can_surrender and self.rules.late_surrender and len(hand.player) == 2
                         and not hand.from_split and hand.hand_count == 1)
        if can_surrender:
            surrender, dev = self.deviations.surrender(hand, count)
            if surrender is True:
                src = "deviation" if basic != Action.SURRENDER else "basic"
                return Decision(Action.SURRENDER, source=src, note=dev.name)
            if surrender is False and basic == Action.SURRENDER:
                # Count zu tief zum Aufgeben → so spielen, als gäbe es kein Surrender
                no_sur = HandState(hand.player, hand.dealer_up, hand.can_double, hand.can_split,
                                   False, hand.from_split, hand.hand_count)
                basic = basic_action(no_sur, self.rules)
                hand = no_sur
            elif basic == Action.SURRENDER:
                # Aufgeben laut Basic Strategy und erlaubt: Spiel-Indizes wie "16 gegen 10
                # stehen" gelten nur, wenn man NICHT aufgeben kann.
                return Decision(Action.SURRENDER, source="basic")

        # 2) Spiel-Indizes (Stehen/Ziehen/Verdoppeln/Teilen)
        action, dev = self.deviations.play(hand, count)
        if action is not None and self._allowed(action, hand):
            if action != basic:
                return Decision(action, source="deviation", note=dev.name)
        return Decision(basic, source="basic")

    def _allowed(self, action: Action, hand: HandState) -> bool:
        if action == Action.DOUBLE:
            return hand.can_double and len(hand.player) == 2 and (
                not hand.from_split or self.rules.double_after_split)
        if action == Action.SPLIT:
            return hand.can_split and hand.is_pair and hand.hand_count < self.rules.max_hands
        return True


def create_engine(name: str, rules: Rules, system: str = "hi_lo",
                  blocking: bool = True) -> DecisionEngine:
    """Engine nach Namen erzeugen. "jev" fällt ohne API-Key automatisch auf "strategy" zurück.
    blocking=False: Jev-Anfragen laufen im Hintergrund (für das Overlay)."""
    if name == "jev":
        from .jev import JevEngine

        return JevEngine(rules, system, blocking=blocking)
    if name != "strategy":
        raise ValueError(f"Unbekannte Engine '{name}' (strategy oder jev)")
    return StrategyEngine(rules, system)
