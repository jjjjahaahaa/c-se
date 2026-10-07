"""Hauptprogramm: verbindet Aufnahme → Erkennung → Zählung → Strategie → Overlay.

Aufbau:
- `Assistant`: die ganze Logik ohne GUI. Bekommt Bilder, liefert einen `OverlayState`.
  Ohne Bildschirm testbar (mit gespeicherten Screenshots oder dem Headless-Browser).
- `AssistantWorker`: Thread, der laufend Bilder holt und den Assistant füttert. Ergebnisse
  gehen über eine Queue an das Overlay (tkinter darf nur aus dem Hauptthread bedient werden).
- `run_app`: startet Worker, Overlay (oder Konsolenausgabe) und globale Hotkeys.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .counting.counter import Counter, CountState
from .models import Action, Decision, HandState, hand_total, is_blackjack, value_rank
from .profiles import Profile, ProfileManager
from .recognition.pipeline import RecognitionResult, Recognizer
from .recognition.recognition_log import RecognitionLogger
from .strategy.betting import BetAdvice, BetRamp
from .strategy.engine import DecisionEngine, create_engine

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"


@dataclass
class OverlayState:
    """Alles, was das Overlay anzeigt (reine Daten, keine GUI)."""

    profile: str = ""
    read_mode: str = ""
    system: str = ""
    engine: str = ""
    running_count: float = 0.0
    true_count: float | None = 0.0
    decks_remaining: float = 0.0
    cards_seen: int = 0
    cards_unseen: int = 0
    bet: BetAdvice | None = None
    decision: Decision | None = None
    insurance: bool | None = None          # None = keine Versicherungsfrage
    dealer: list[str] = field(default_factory=list)
    player_hands: list[list[str]] = field(default_factory=list)
    active_hand: int = 0
    uncertain: bool = False
    ineffective: bool = False
    paused: bool = False
    message: str = ""
    last_event: str = ""


class Assistant:
    """Logik des Assistenten für ein Profil (ohne Bildschirm und GUI)."""

    def __init__(self, profile: Profile, engine: str | None = None, log: bool = True,
                 log_dir: Path | None = None):
        self.profile = profile
        log_dir = log_dir or LOG_DIR
        self.log_dir = log_dir
        self.logger = RecognitionLogger(log_dir / "recognition" / time.strftime("%Y%m%d_%H%M%S"),
                                        mode=profile.read_mode) if log else None
        self.recognizer = Recognizer(profile, logger=self.logger)
        self.counter = Counter.from_profile(profile, stats_file=log_dir / "shuffle_stats.jsonl")
        self.ramp = BetRamp.from_profile(profile)
        self.engine: DecisionEngine = create_engine(engine or profile.decision_engine,
                                                    profile.rules, self.counter.system.key,
                                                    blocking=False)
        self.paused = False
        self.last: RecognitionResult = RecognitionResult()
        self.last_event = ""
        self.message = ""
        self._decision_cache: tuple | None = None

    # ------------------------------------------------------------------

    def process(self, image: np.ndarray, timestamp: float,
                origin: tuple[int, int] = (0, 0)) -> OverlayState:
        """Ein Bildschirmbild verarbeiten und den neuen Anzeigezustand liefern."""
        if self.paused:
            return self.state()
        result = self.recognizer.process_frame(image, timestamp, origin)
        for event in result.events:
            self.counter.apply(event)
            self.last_event = event.describe()
        if result.evaluated:
            self.last = result
        return self.state()

    def toggle_pause(self) -> bool:
        self.paused = not self.paused
        self.counter.paused = self.paused
        self.message = "Pausiert" if self.paused else "Läuft"
        return self.paused

    def reset_count(self) -> None:
        """Hotkey "Count zurücksetzen": z. B. wenn man ein Mischen von Hand bemerkt."""
        self.counter.shuffle("manual")
        self.recognizer.reset()
        self.last = RecognitionResult()
        self.message = "Count zurückgesetzt"

    def close(self) -> Path | None:
        return self.logger.close() if self.logger else None

    # ------------------------------------------------------------------

    def current_hand(self) -> HandState | None:
        """Handzustand für die Empfehlung, falls gerade eine Entscheidung ansteht."""
        dealer, hands = self.last.dealer, self.last.player_hands
        if len(dealer) != 1 or not hands:
            return None  # keine Runde oder Dealer spielt schon (mehr als eine Karte offen)
        index = min(self.last.active_hand, len(hands) - 1)
        player = hands[index]
        if len(player) < 2 or hand_total(player)[0] >= 21:
            return None
        n = len(hands)
        rules = self.profile.rules
        is_pair = len(player) == 2 and value_rank(player[0]) == value_rank(player[1])
        return HandState(
            player=player,
            dealer_up=dealer[0],
            can_double=len(player) == 2 and (n == 1 or rules.double_after_split),
            can_split=is_pair and n < rules.max_hands,
            can_surrender=rules.late_surrender and n == 1 and len(player) == 2,
            from_split=n > 1,
            hand_count=n,
        )

    def decision(self, count: CountState) -> tuple[Decision | None, bool | None]:
        hand = self.current_hand()
        if hand is None:
            return None, None
        insurance = None
        if (value_rank(hand.dealer_up) == "A" and self.profile.rules.insurance
                and hand.hand_count == 1 and len(hand.player) == 2
                and not is_blackjack(hand.player)):
            insurance = self.engine.take_insurance(count)
        # Gleiche Situation → Ergebnis wiederverwenden (wichtig für Jev: keine Anfrage pro Bild)
        key = (tuple(hand.player), hand.dealer_up, hand.hand_count, round(count.running_count, 2),
               round(count.decks_remaining, 2))
        if self._decision_cache and self._decision_cache[0] == key:
            return self._decision_cache[1], insurance
        decision = self.engine.decide(hand, count)
        if decision.source != "pending":  # Zwischenergebnis (Jev rechnet noch) nicht merken
            self._decision_cache = (key, decision)
        return decision, insurance

    def state(self) -> OverlayState:
        count = self.counter.state()
        decision, insurance = self.decision(count)
        return OverlayState(
            profile=self.profile.display_name or self.profile.name,
            read_mode=self.profile.read_mode,
            system=count.system_name,
            engine=getattr(self.engine, "active_name", self.engine.name),
            running_count=count.running_count,
            true_count=count.true_count,
            decks_remaining=count.decks_remaining,
            cards_seen=count.cards_seen,
            cards_unseen=count.cards_unseen,
            bet=self.ramp.advise(count),
            decision=decision,
            insurance=insurance,
            dealer=list(self.last.dealer),
            player_hands=[list(h) for h in self.last.player_hands],
            active_hand=self.last.active_hand,
            uncertain=self.last.uncertain,
            ineffective=count.ineffective,
            paused=self.paused,
            message=self.message or getattr(self.engine, "status", ""),
            last_event=self.last_event,
        )


# ----------------------------------------------------------------------
# Anzeige-Texte (ohne GUI, damit testbar)
# ----------------------------------------------------------------------


def format_state(s: OverlayState) -> dict[str, str]:
    """Wandelt den Zustand in die Texte des Overlays um."""
    tc = "–" if s.true_count is None else f"{s.true_count:+.1f}"
    lines = {
        "profile": f"{s.profile}  ·  {s.system}  ·  {s.engine}",
        "rc": f"{s.running_count:+g}",
        "tc": tc,
        "decks": f"{s.decks_remaining:g}",
        "bet": "–" if s.bet is None else f"{s.bet.amount:g} ({s.bet.units} E.)",
        "action": "–",
        "detail": "",
        "insurance": "",
        "probabilities": "",
        "hand": "",
    }
    if s.decision is not None:
        lines["action"] = s.decision.action.german.upper()
        source = {"basic": "Basic Strategy", "deviation": "Abweichung", "jev": "Jev",
                  "pending": "Lokale Strategie"}.get(
            s.decision.source, s.decision.source)
        lines["detail"] = f"{source}: {s.decision.note}" if s.decision.note else source
        if s.decision.probabilities:
            probs = sorted(s.decision.probabilities.items(), key=lambda kv: -kv[1])
            lines["probabilities"] = "  ".join(
                f"{Action(k).german if k in Action._value2member_map_ else k} {v:.0%}"
                for k, v in probs)
    if s.insurance is not None:
        lines["insurance"] = "Versicherung: JA" if s.insurance else "Versicherung: nein"
    if s.player_hands:
        hand = s.player_hands[min(s.active_hand, len(s.player_hands) - 1)]
        dealer = s.dealer[0] if s.dealer else "?"
        lines["hand"] = f"{' '.join(hand)}  gegen  {dealer}"
    return lines


def warnings(s: OverlayState) -> list[tuple[str, str]]:
    """Warnungen als (Stufe, Text). Stufe: "yellow" oder "red"."""
    out = []
    if s.paused:
        out.append(("yellow", "PAUSE – es wird nicht gezählt"))
    if s.ineffective:
        out.append(("red", "Spiel mischt jede Runde – Zählen hier wirkungslos"))
    if s.uncertain:
        out.append(("yellow", "Unsichere Erkennung – Karte nicht gezählt"))
    return out


def console_line(s: OverlayState) -> str:
    t = format_state(s)
    warn = " | ".join(text for _, text in warnings(s))
    return (f"RC {t['rc']:>4}  TC {t['tc']:>5}  Decks {t['decks']:>3}  Einsatz {t['bet']:>10}  "
            f"Zug {t['action']:<10} {t['hand']:<16} {warn}")


# ----------------------------------------------------------------------
# Hintergrund-Thread
# ----------------------------------------------------------------------


class AssistantWorker(threading.Thread):
    """Holt laufend Bilder und schickt neue Zustände an eine Queue."""

    def __init__(self, assistant: Assistant, source, origin=(0, 0), interval: float = 0.08):
        super().__init__(daemon=True)
        self.assistant = assistant
        self.source = source
        self.origin = origin
        self.interval = interval
        self.states: queue.Queue[OverlayState] = queue.Queue(maxsize=5)
        self.commands: queue.Queue[tuple] = queue.Queue()
        self.stop_event = threading.Event()
        self.error: Exception | None = None

    def command(self, name: str, *args) -> None:
        """Befehl aus dem GUI-Thread (Hotkey) an den Worker: pause, reset, switch."""
        self.commands.put((name, *args))

    def _handle_commands(self) -> None:
        while True:
            try:
                name, *args = self.commands.get_nowait()
            except queue.Empty:
                return
            if name == "pause":
                self.assistant.toggle_pause()
            elif name == "reset":
                self.assistant.reset_count()
            elif name == "switch":
                self.assistant, self.origin, self.source = args[0]
            self._publish(self.assistant.state())

    def _publish(self, state: OverlayState) -> None:
        try:
            self.states.put_nowait(state)
        except queue.Full:
            try:
                self.states.get_nowait()  # ältesten Zustand verwerfen
            except queue.Empty:
                pass
            self.states.put_nowait(state)

    def run(self) -> None:
        try:
            while not self.stop_event.is_set():
                self._handle_commands()
                frame = self.source.grab()
                if frame is None:
                    break
                self._publish(self.assistant.process(frame.image, frame.timestamp, self.origin))
                time.sleep(self.interval)
        except Exception as err:  # noqa: BLE001 – Fehler an die GUI weitergeben
            self.error = err

    def stop(self) -> None:
        self.stop_event.set()


# ----------------------------------------------------------------------
# Start
# ----------------------------------------------------------------------


def _screen_source(profile: Profile):
    from .capture.screen import ScreenSource, bounding_region

    regions = [r for r in profile.regions.values() if r]
    if not regions:
        raise SystemExit(
            f"Profil '{profile.name}' hat keine Bildschirmbereiche. Zuerst:\n"
            f"  python -m blackjack_assistant select-region --profile {profile.name} --region table")
    source = ScreenSource(bounding_region(regions))
    return source, source.origin


def build(profile: Profile, engine: str | None):
    """Assistant + Bildquelle für ein Profil (wird auch beim Profilwechsel benutzt)."""
    assistant = Assistant(profile, engine)
    source, origin = _screen_source(profile)
    return assistant, origin, source


def run_app(profile_name: str | None = None, engine: str | None = None,
            no_overlay: bool = False, profiles_root: Path | None = None,
            duration: float | None = None) -> int:
    """Startet den Assistenten. duration = nach so vielen Sekunden beenden (für Tests)."""
    from .capture.region_select import make_dpi_aware
    from .profiles import PROFILES_DIR

    make_dpi_aware()
    manager = ProfileManager(root=profiles_root or PROFILES_DIR, active=profile_name)
    assistant, origin, source = build(manager.active, engine)
    worker = AssistantWorker(assistant, source, origin)

    def switch_profile():
        profile = manager.next()
        try:
            worker.command("switch", build(profile, engine))
        except SystemExit as err:
            print(err)

    actions = {"pause": lambda: worker.command("pause"),
               "reset": lambda: worker.command("reset"),
               "switch": switch_profile}

    from .overlay.hotkeys import HotkeyListener

    hotkeys = HotkeyListener(actions)
    hotkeys.start()
    worker.start()
    print(f"Profil: {manager.active.name}  –  {hotkeys.describe()}  –  Beenden mit Ctrl+C")
    if hotkeys.error:
        print(hotkeys.error)
    deadline = None if duration is None else time.time() + duration
    try:
        if no_overlay:
            last = ""
            while worker.is_alive() and (deadline is None or time.time() < deadline):
                try:
                    state = worker.states.get(timeout=0.5)
                except queue.Empty:
                    continue
                line = console_line(state)
                if line != last:
                    print(line)
                    last = line
        else:
            from .overlay.window import OverlayWindow

            window = OverlayWindow(worker, actions, hotkeys.describe())
            if deadline is not None:
                window.root.after(int(duration * 1000), window.root.destroy)
            window.run()
    except KeyboardInterrupt:
        pass
    finally:
        worker.stop()
        hotkeys.stop()
        log = worker.assistant.close()
        if log:
            print(f"Erkennungs-Log: {log}")
        stats = worker.assistant.counter.shuffle_statistics()
        if stats.get("shoes"):
            print(f"Mischstatistik: {stats}")
    if worker.error:
        raise worker.error
    return 0

