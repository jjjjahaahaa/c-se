"""Phase 4 ohne Bildschirm: Assistant (Erkennung → Zählung → Strategie), Worker-Thread mit
Befehlen (Pause/Reset/Profil) und die Texte des Overlays."""

import time

import numpy as np
import pytest

from blackjack_assistant.app import (Assistant, AssistantWorker, OverlayState, console_line,
                                     format_state, warnings)
from blackjack_assistant.capture.sources import Frame
from blackjack_assistant.models import Action, Decision
from blackjack_assistant.profiles import load_profile
from blackjack_assistant.strategy.betting import BetAdvice
from tests.helpers import fixture_image


class ListSource:
    """Bildquelle aus einer Liste (Zeitstempel in 0.1-s-Schritten)."""

    def __init__(self, images):
        self.images = list(images)
        self.t = 0.0

    def grab(self):
        if not self.images:
            return None
        self.t += 0.1
        return Frame(self.images.pop(0), self.t)


def table_profile():
    p = load_profile("mock_casino")
    p.read_mode = "table"
    img = fixture_image("table_player_turn")
    p.regions = {"table": [0, 0, img.shape[1], img.shape[0]], "history": None}
    return p


def empty_table(like):
    img = np.empty_like(like)
    img[:] = (34, 77, 11)
    return img


@pytest.fixture
def assistant(tmp_path):
    return Assistant(table_profile(), engine="strategy", log_dir=tmp_path)


def feed(assistant, images, t0=0.0):
    state = None
    for i, img in enumerate(images):
        state = assistant.process(img, t0 + i * 0.1)
    return state


def test_empfehlung_waehrend_der_spielerentscheidung(assistant):
    state = feed(assistant, [fixture_image("table_player_turn")] * 5)
    # Spieler 3+6 = 9 gegen Dealer 6 → Verdoppeln
    assert state.dealer == ["6"] and state.player_hands == [["3", "6"]]
    assert state.decision.action == Action.DOUBLE
    assert state.running_count == 3          # 3, 6, 6 → +3 (Hole Card verdeckt)
    assert state.bet.units == 1
    assert format_state(state)["action"] == "VERDOPPELN"


def test_ganze_runde_zaehlen_und_rundenende(assistant):
    turn, settled = fixture_image("table_player_turn"), fixture_image("table_settled")
    feed(assistant, [turn] * 5 + [settled] * 5 + [empty_table(turn)] * 5)
    c = assistant.counter
    assert c.cards_seen == 6
    assert c.running_count == 3              # 3 6 6 9 Q 6 → +1 +1 +1 0 −1 +1
    assert c.rounds_since_shuffle == 1
    state = assistant.state()
    assert state.decision is None            # keine Runde auf dem Tisch


def test_dealer_spielt_keine_empfehlung(assistant):
    state = feed(assistant, [fixture_image("table_settled")] * 5)
    assert len(state.dealer) == 3 and state.decision is None


def test_split_haende_aktive_hand(assistant):
    state = feed(assistant, [fixture_image("table_split")] * 5)
    assert state.player_hands == [["8", "Q"], ["8", "10", "A"]]
    # zweite Hand (8,10,A = 19) hat zuletzt eine Karte bekommen → Stehen
    assert state.active_hand == 1
    assert state.decision.action == Action.STAND


def test_pause_und_reset(assistant):
    turn = fixture_image("table_player_turn")
    assistant.toggle_pause()
    feed(assistant, [turn] * 5)
    assert assistant.counter.cards_seen == 0
    assert assistant.state().paused
    assistant.toggle_pause()
    feed(assistant, [turn] * 5, t0=1.0)
    assert assistant.counter.cards_seen == 3
    assistant.reset_count()
    assert assistant.counter.cards_seen == 0 and assistant.counter.running_count == 0


def test_mischt_jede_runde_warnung(tmp_path):
    p = table_profile()
    p.rules.shuffle_every_round = True
    a = Assistant(p, log_dir=tmp_path)
    turn = fixture_image("table_player_turn")
    state = feed(a, [turn] * 5 + [empty_table(turn)] * 5)
    assert state.ineffective
    assert state.running_count == 0          # nach der Runde zurückgesetzt
    assert ("red", "Spiel mischt jede Runde – Zählen hier wirkungslos") in warnings(state)
    assert state.bet.units == 1


def test_worker_thread_mit_befehlen(tmp_path):
    turn = fixture_image("table_player_turn")
    a = Assistant(table_profile(), log_dir=tmp_path)
    worker = AssistantWorker(a, ListSource([turn] * 8), interval=0.0)
    worker.start()
    worker.join(timeout=10)
    assert worker.error is None
    states = []
    while not worker.states.empty():
        states.append(worker.states.get())
    assert states[-1].running_count == 3
    # Befehle werden im Worker ausgeführt
    worker2 = AssistantWorker(a, ListSource([turn] * 3), interval=0.0)
    worker2.command("reset")
    worker2.command("pause")
    worker2.start()
    worker2.join(timeout=10)
    assert a.counter.cards_seen == 0 and a.paused


def test_texte_und_warnungen_des_overlays():
    state = OverlayState(profile="Mock", system="Hi-Lo", engine="strategy", running_count=5,
                         true_count=1.66, decks_remaining=3, bet=BetAdvice(2, 20, 2.1),
                         decision=Decision(Action.STAND, "deviation", "16 gegen 10 stehen"),
                         insurance=True, dealer=["10"], player_hands=[["10", "6"]],
                         uncertain=True, paused=True)
    t = format_state(state)
    assert t["rc"] == "+5" and t["tc"] == "+1.7" and t["decks"] == "3"
    assert t["bet"] == "20 (2 E.)"
    assert t["action"] == "STEHEN"
    assert t["detail"] == "Abweichung: 16 gegen 10 stehen"
    assert t["insurance"] == "Versicherung: JA"
    assert t["hand"] == "10 6  gegen  10"
    w = warnings(state)
    assert ("yellow", "Unsichere Erkennung – Karte nicht gezählt") in w
    assert any("PAUSE" in text for _, text in w)
    assert "STEHEN" in console_line(state)


def test_ko_zeigt_keinen_true_count():
    t = format_state(OverlayState(true_count=None, running_count=-12))
    assert t["tc"] == "–" and t["rc"] == "-12"


def test_wahrscheinlichkeiten_werden_angezeigt():
    d = Decision(Action.HIT, "jev", probabilities={"hit": 0.7, "stand": 0.25, "double": 0.05})
    t = format_state(OverlayState(decision=d))
    assert t["probabilities"].startswith("Ziehen 70%")
    assert t["detail"] == "Jev"


def test_erkennungs_log_wird_geschrieben(tmp_path):
    a = Assistant(table_profile(), log_dir=tmp_path)
    feed(a, [fixture_image("table_player_turn")] * 5)
    index = a.close()
    assert index.exists()
    assert len(list((tmp_path / "recognition").glob("*/crops/*.png"))) == 3


def test_profilwechsel_ueber_worker(tmp_path):
    a = Assistant(table_profile(), log_dir=tmp_path)
    b = Assistant(table_profile(), log_dir=tmp_path)
    worker = AssistantWorker(a, ListSource([]), interval=0.0)
    worker.command("switch", (b, (0, 0), ListSource([fixture_image("table_player_turn")] * 5)))
    worker.start()
    worker.join(timeout=10)
    assert worker.assistant is b
    assert b.counter.cards_seen == 3
    time.sleep(0)
