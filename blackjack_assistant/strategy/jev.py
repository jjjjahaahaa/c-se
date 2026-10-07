"""Entscheidungs-Engine "jev": TypeSafe Jev über die API (optional).

Jev ist ein "System One"-Modell von TypeSafe AI: Es bekommt einen Zustand (JSON) und eine
Frage mit Auswahlmöglichkeiten und liefert die gewählte Option plus Wahrscheinlichkeiten.
Doku: https://docs.typesafe.ai  ·  Orientierung: github.com/patrickhaahr/jevjack

API (Stand Oktober 2026):
  POST https://api.typesafe.ai/v1/systemone
  Header  Authorization: Bearer <API-Key>
  Body    {"state": {...}, "model": "jev-latest",
           "questions": {"action": {"type": "choice", "instructions": ..., "criteria": {...}}}}
  Antwort {"answers": {"action": {"choice": "stand", "probabilities": {...}, "confidence": 0.8}}}

Sicherheit / Offline-Betrieb:
- Der API-Key wird NUR aus einer Umgebungsvariable gelesen: TYPESAFE_API_KEY (offizieller Name)
  oder JEV_API_KEY. Optional lädt python-dotenv eine lokale .env-Datei (steht in .gitignore).
- Ohne Key, bei ungültigem Key oder Netzwerkfehlern wird automatisch die lokale Strategie
  (Basic Strategy + Abweichungen) verwendet. Alles läuft dann offline weiter.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass

from ..counting.counter import CountState
from ..models import Action, Decision, HandState, Rules, hand_total
from .basic import basic_action
from .engine import StrategyEngine

API_URL = "https://api.typesafe.ai"
ENV_KEYS = ("TYPESAFE_API_KEY", "JEV_API_KEY")
DEFAULT_MODEL = "jev-latest"

ACTION_CRITERIA = {
    "hit": "Take another card. Chosen when the current total is too weak to stand against "
           "`dealerUpcard`.",
    "stand": "Keep the current total and end the hand. Chosen when drawing risks busting more "
             "than it helps.",
    "double": "Double the bet, take exactly one card, and stand. A strong two-card draw against "
              "a weak dealer upcard.",
    "split": "Split a pair into two hands. Two cards of the same value that play better apart "
             "than together.",
    "surrender": "Forfeit half the bet and end the hand. A weak hand against a strong dealer "
                 "upcard, when losing half is better than the likely outcome.",
}

INSTRUCTIONS = {
    "question": "Which action should the player take right now?",
    "goal": "Play this blackjack hand to maximize the expected return of the bet.",
    "rules": (
        "Cards: 2-9 count face value, 10/J/Q/K count 10, an ace counts 1 or 11. "
        "`playerTotal` and `playerSoft` are already computed. The dealer "
        + "{dealer_rule}. "
        "`trueCount` is the Hi-Lo true count of the remaining shoe: positive means many tens "
        "and aces remain (good for the player), negative means many small cards remain. "
        "Only the options listed are legal."
    ),
}


class JevError(Exception):
    """Fehler bei der Anfrage an Jev (Netzwerk, Server, Antwortformat)."""


class JevAuthError(JevError):
    """API-Key fehlt oder ist ungültig (401/403)."""


def read_api_key(load_env_file: bool = True) -> str | None:
    """API-Key aus der Umgebung (optional vorher .env laden). Nie aus Code oder Profil."""
    if load_env_file:
        try:
            from dotenv import load_dotenv

            load_dotenv(override=False)
        except ImportError:
            pass
    for name in ENV_KEYS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def legal_actions(hand: HandState, rules: Rules) -> list[str]:
    actions = ["hit", "stand"]
    if hand.can_double and len(hand.player) == 2 and (
            not hand.from_split or rules.double_after_split):
        actions.append("double")
    if hand.can_split and hand.is_pair and hand.hand_count < rules.max_hands:
        actions.append("split")
    if (hand.can_surrender and rules.late_surrender and len(hand.player) == 2
            and hand.hand_count == 1 and not hand.from_split):
        actions.append("surrender")
    return actions


def build_request(hand: HandState, count: CountState | None, rules: Rules,
                  model: str = DEFAULT_MODEL, advice: Action | None = None) -> dict:
    """Request-Body für POST /v1/systemone. Nur die gerade erlaubten Aktionen werden als
    Auswahl angeboten → Jev kann keine unmögliche Aktion wählen."""
    total, soft = hand_total(hand.player)
    legal = legal_actions(hand, rules)
    tc = None
    if count is not None:
        tc = count.true_count if count.true_count is not None else count.betting_count
    state = {
        "playerCards": list(hand.player),
        "playerTotal": total,
        "playerSoft": soft,
        "dealerUpcard": hand.dealer_up,
        "trueCount": None if tc is None else round(float(tc), 1),
        "decksRemaining": None if count is None else round(float(count.decks_remaining), 1),
        "legalActions": legal,
        "handsInPlay": hand.hand_count,
    }
    if advice is not None:
        state["basicStrategy"] = advice.value
    instructions = dict(INSTRUCTIONS)
    instructions["rules"] = INSTRUCTIONS["rules"].format(
        dealer_rule="hits soft 17" if rules.hit_soft_17 else "stands on all 17s")
    return {
        "state": state,
        "model": model,
        "questions": {
            "action": {
                "type": "choice",
                "instructions": instructions,
                "criteria": {a: ACTION_CRITERIA[a] for a in legal},
            }
        },
    }


@dataclass
class JevAnswer:
    action: Action
    probabilities: dict[str, float]
    confidence: float
    model: str = ""


class JevClient:
    """Minimaler HTTP-Client für die Jev-API (requests)."""

    def __init__(self, api_key: str, model: str | None = None, base_url: str | None = None,
                 timeout: float = 10.0, session=None):
        if not api_key:
            raise JevAuthError("Kein API-Key")
        self._api_key = api_key
        self.model = model or os.environ.get("TYPESAFE_DEFAULT_MODEL", DEFAULT_MODEL)
        self.base_url = (base_url or os.environ.get("TYPESAFE_BASE_URL") or API_URL).rstrip("/")
        self.timeout = timeout
        if session is None:
            import requests

            session = requests.Session()
        self.session = session

    def __repr__(self) -> str:  # Key nie ausgeben
        return f"JevClient(model={self.model!r}, base_url={self.base_url!r})"

    def ask(self, body: dict) -> JevAnswer:
        try:
            response = self.session.post(
                f"{self.base_url}/v1/systemone",
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self.timeout,
            )
        except Exception as err:  # noqa: BLE001 – Netzwerkfehler aller Art
            raise JevError(f"Jev nicht erreichbar: {type(err).__name__}") from None
        if response.status_code in (401, 403):
            raise JevAuthError(f"Jev lehnt den API-Key ab (HTTP {response.status_code})")
        if response.status_code != 200:
            raise JevError(f"Jev-Fehler HTTP {response.status_code}")
        try:
            data = response.json()
            answer = data["answers"]["action"]
            choice = answer["choice"]
            probs = {str(k): float(v) for k, v in answer.get("probabilities", {}).items()}
            return JevAnswer(Action(choice), probs, float(answer.get("confidence", 0.0)),
                             data.get("model", ""))
        except (KeyError, TypeError, ValueError) as err:
            raise JevError(f"Unerwartete Antwort von Jev: {err}") from None


class JevEngine:
    """Engine "jev" mit automatischem Rückfall auf die lokale Strategie.

    blocking=True  (Simulation): wartet auf die Antwort.
    blocking=False (Overlay):    fragt im Hintergrund; bis die Antwort da ist, wird die lokale
                                 Strategie angezeigt (Hinweis "Jev rechnet …").
    """

    name = "jev"

    def __init__(self, rules: Rules, system: str = "hi_lo", client: JevClient | None = None,
                 api_key: str | None = None, blocking: bool = True, advice: bool = False):
        self.rules = rules
        self.fallback = StrategyEngine(rules, system)
        self.blocking = blocking
        self.advice = advice
        self.status = ""
        self.requests = 0
        self.failures = 0
        self._cache: dict[tuple, Decision] = {}
        self._pending: set[tuple] = set()
        self._lock = threading.Lock()
        if client is None:
            key = api_key if api_key is not None else read_api_key()
            if key:
                client = JevClient(key)
        self.client = client
        if self.client is None:
            self.status = "Jev: kein API-Key → lokale Strategie (offline)"

    @property
    def available(self) -> bool:
        return self.client is not None

    @property
    def active_name(self) -> str:
        return "jev" if self.available else "strategy (Jev aus)"

    def take_insurance(self, count: CountState | None) -> bool:
        return self.fallback.take_insurance(count)

    def _key(self, hand: HandState, count: CountState | None) -> tuple:
        tc = None if count is None or count.true_count is None else round(count.true_count, 1)
        return (tuple(hand.player), hand.dealer_up, hand.hand_count, hand.can_double,
                hand.can_split, hand.can_surrender, tc)

    def _ask(self, key: tuple, hand: HandState, count: CountState | None) -> Decision:
        advice = basic_action(hand, self.rules) if self.advice else None
        body = build_request(hand, count, self.rules, self.client.model, advice)
        self.requests += 1
        answer = self.client.ask(body)
        decision = Decision(answer.action, source="jev",
                            note=f"Konfidenz {answer.confidence:.0%}",
                            probabilities=answer.probabilities)
        with self._lock:
            self._cache[key] = decision
        return decision

    def _ask_safely(self, key, hand, count) -> Decision | None:
        try:
            return self._ask(key, hand, count)
        except JevAuthError as err:
            self.status = f"{err} → lokale Strategie"
            self.client = None          # nicht bei jeder Hand erneut versuchen
        except JevError as err:
            self.failures += 1
            self.status = f"{err} → lokale Strategie"
        finally:
            with self._lock:
                self._pending.discard(key)
        return None

    def decide(self, hand: HandState, count: CountState | None = None) -> Decision:
        if not self.available:
            return self.fallback.decide(hand, count)
        key = self._key(hand, count)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        if self.blocking:
            return self._ask_safely(key, hand, count) or self.fallback.decide(hand, count)
        with self._lock:
            start = key not in self._pending
            self._pending.add(key)
        if start:
            threading.Thread(target=self._ask_safely, args=(key, hand, count), daemon=True).start()
        interim = self.fallback.decide(hand, count)
        return Decision(interim.action, source="pending", note="Jev rechnet … (lokale Strategie)")
