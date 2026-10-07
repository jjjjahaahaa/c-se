"""Jev-Engine (Phase 5) – ohne echte API-Aufrufe. Die HTTP-Schicht wird durch eine
Fake-Session ersetzt; geprüft werden Request-Format, Auswertung und der Rückfall auf die
lokale Strategie."""

import os
import time
from dataclasses import replace
from pathlib import Path

import pytest

from blackjack_assistant.counting.counter import Counter
from blackjack_assistant.models import Action, HandState, Rules
from blackjack_assistant.strategy.engine import create_engine
from blackjack_assistant.strategy.jev import (JevClient, JevEngine, build_request, legal_actions,
                                              read_api_key)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RULES = Rules()


class FakeResponse:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


class FakeSession:
    """Ersetzt requests.Session: merkt sich Anfragen und liefert vorbereitete Antworten."""

    def __init__(self, *responses, delay=0.0):
        self.responses = list(responses)
        self.calls = []
        self.delay = delay

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if self.delay:
            time.sleep(self.delay)
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Exception):
            raise r
        return r


def answer(choice, probs, confidence=0.8):
    return FakeResponse(200, {"model": "jev-1.13.0", "answers": {"action": {
        "type": "choice", "choice": choice, "probabilities": probs, "confidence": confidence}},
        "usage": {"input_tokens": 400, "output_tokens": 5}})


def tc_state(tc):
    s = Counter("hi_lo").state()
    return replace(s, running_count=tc * 3, true_count=tc, decks_remaining=3.0)


def engine_with(session, **kw):
    client = JevClient("test-key-123", session=session)
    return JevEngine(RULES, client=client, **kw)


HAND = HandState(["10", "6"], "10")


def test_request_enthaelt_zustand_und_nur_erlaubte_aktionen():
    body = build_request(HAND, tc_state(1.5), RULES)
    assert body["model"] == "jev-latest"
    state = body["state"]
    assert state["playerCards"] == ["10", "6"] and state["playerTotal"] == 16
    assert state["dealerUpcard"] == "10" and state["trueCount"] == 1.5
    question = body["questions"]["action"]
    assert question["type"] == "choice"
    assert set(question["criteria"]) == {"hit", "stand", "double", "surrender"}  # kein Paar
    pair = build_request(HandState(["8", "8"], "6"), None, RULES)
    assert "split" in pair["questions"]["action"]["criteria"]
    three = HandState(["4", "2", "10"], "10")
    assert legal_actions(three, RULES) == ["hit", "stand"]


def test_jev_antwort_mit_wahrscheinlichkeiten():
    session = FakeSession(answer("stand", {"hit": 0.3, "stand": 0.6, "double": 0.0,
                                            "surrender": 0.1}))
    e = engine_with(session)
    d = e.decide(HAND, tc_state(1.0))
    assert d.action == Action.STAND and d.source == "jev"
    assert d.probabilities["stand"] == pytest.approx(0.6)
    assert "80%" in d.note
    call = session.calls[0]
    assert call["url"] == "https://api.typesafe.ai/v1/systemone"
    assert call["headers"]["Authorization"] == "Bearer test-key-123"
    # gleiche Situation → keine zweite Anfrage
    e.decide(HAND, tc_state(1.0))
    assert len(session.calls) == 1


def test_ohne_api_key_lokale_strategie(monkeypatch):
    for name in ("TYPESAFE_API_KEY", "JEV_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(PROJECT_ROOT / "tests")  # keine .env im Arbeitsverzeichnis
    e = create_engine("jev", RULES)
    assert not e.available
    assert "kein API-Key" in e.status
    d = e.decide(HAND, tc_state(0))
    assert d.action == Action.SURRENDER and d.source == "basic"


def test_api_key_nur_aus_umgebungsvariable(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("JEV_API_KEY", "  abc  ")
    assert read_api_key(load_env_file=False) == "abc"
    monkeypatch.setenv("TYPESAFE_API_KEY", "official")
    assert read_api_key(load_env_file=False) == "official"


def test_ungueltiger_key_schaltet_auf_strategie_um():
    session = FakeSession(FakeResponse(403, {"detail": "Must supply an API key"}))
    e = engine_with(session)
    d = e.decide(HAND, tc_state(0))
    assert d.source == "basic" and not e.available
    assert "API-Key" in e.status
    e.decide(HandState(["9", "2"], "6"), tc_state(0))
    assert len(session.calls) == 1        # keine weiteren Versuche


def test_netzwerkfehler_und_kaputte_antwort_fallen_zurueck():
    e = engine_with(FakeSession(ConnectionError("offline")))
    assert e.decide(HAND, tc_state(0)).source == "basic"
    assert e.available and e.failures == 1
    e = engine_with(FakeSession(FakeResponse(200, {"unexpected": True})))
    assert e.decide(HAND, tc_state(0)).source == "basic"
    e = engine_with(FakeSession(FakeResponse(529, None)))
    assert e.decide(HAND, tc_state(0)).source == "basic"
    assert "529" in e.status


def test_key_erscheint_nicht_in_fehlern_oder_repr():
    client = JevClient("geheim-999", session=FakeSession(ConnectionError("geheim-999?")))
    assert "geheim" not in repr(client)
    e = JevEngine(RULES, client=client)
    e.decide(HAND, tc_state(0))
    assert "geheim" not in e.status


def test_nicht_blockierend_fuer_das_overlay():
    session = FakeSession(answer("hit", {"hit": 0.9, "stand": 0.1}), delay=0.2)
    e = engine_with(session, blocking=False)
    first = e.decide(HandState(["10", "2"], "3"), tc_state(0))
    assert first.source == "pending" and first.action == Action.HIT
    for _ in range(50):
        time.sleep(0.02)
        d = e.decide(HandState(["10", "2"], "3"), tc_state(0))
        if d.source == "jev":
            break
    assert d.source == "jev" and d.probabilities["hit"] == pytest.approx(0.9)
    assert len(session.calls) == 1


def test_versicherung_kommt_von_der_lokalen_strategie():
    e = engine_with(FakeSession(answer("hit", {"hit": 1.0})))
    assert e.take_insurance(tc_state(3.5)) and not e.take_insurance(tc_state(1))


def test_env_datei_wird_nie_committet():
    ignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignore
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "TYPESAFE_API_KEY=\n" in example  # Vorlage ohne echten Key


@pytest.mark.skipif(not (os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY")),
                    reason="Kein Jev-API-Key gesetzt (echter API-Test nur lokal)")
def test_echte_jev_anfrage():
    e = create_engine("jev", RULES)
    d = e.decide(HandState(["10", "6"], "10"), tc_state(0))
    assert d.source == "jev", e.status
    assert sum(d.probabilities.values()) == pytest.approx(1.0, abs=0.05)
