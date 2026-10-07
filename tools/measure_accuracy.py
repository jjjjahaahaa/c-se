"""Vergleicht erkannte Karten mit der Ground Truth des Mock-Casinos und gibt die
Genauigkeit in % aus.

Eingaben:
  --truth       logs/ground_truth_<…>.jsonl   (Mock-Casino mit --debug)
  --recognized  logs/recognition/<…>/events.jsonl

Methode: Jede erkannte Karte wird über ihren Zeitstempel einer Runde der Ground Truth
zugeordnet (die Uhrzeiten stammen vom selben Rechner). Pro Runde werden die Ränge als
Multimenge verglichen; Reste werden mit den Nachbarrunden abgeglichen (die Erkennung ist
wegen der 300-ms-Wartezeit etwas später). Was dann noch übrig ist, zählt als Fehler:
  - verpasst:   in der Ground Truth, aber nicht erkannt
  - zusätzlich: erkannt, aber nicht in der Ground Truth (z. B. doppelt gezählt)
  - verwechselt: in derselben Runde ein verpasster und ein zusätzlicher Rang

Aufruf:  python tools/measure_accuracy.py --truth … --recognized …
"""

from __future__ import annotations

import argparse
import bisect
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def _t(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


@dataclass
class AccuracyReport:
    truth_cards: int = 0
    recognized_cards: int = 0
    correct: int = 0
    missed: int = 0
    extra: int = 0
    confusions: Counter = field(default_factory=Counter)        # (wahr, erkannt) → Anzahl
    missed_by_rank: Counter = field(default_factory=Counter)
    extra_by_rank: Counter = field(default_factory=Counter)
    truth_by_rank: Counter = field(default_factory=Counter)
    truth_unseen: int = 0
    recognized_unseen: int = 0
    uncertain_final: int = 0
    rounds: int = 0
    truth_shuffles: int = 0
    recognized_shuffles: int = 0
    recognized_round_ends: int = 0

    @property
    def accuracy(self) -> float:
        """Korrekt gezählte Karten / (Karten der Ground Truth + zusätzlich gezählte) in %."""
        denom = self.truth_cards + self.extra
        return 100.0 * self.correct / denom if denom else 100.0

    @property
    def recall(self) -> float:
        return 100.0 * self.correct / self.truth_cards if self.truth_cards else 100.0

    @property
    def precision(self) -> float:
        return 100.0 * self.correct / self.recognized_cards if self.recognized_cards else 100.0

    def as_dict(self) -> dict:
        return {
            "accuracy": round(self.accuracy, 2),
            "recall": round(self.recall, 2),
            "precision": round(self.precision, 2),
            "truth_cards": self.truth_cards,
            "recognized_cards": self.recognized_cards,
            "correct": self.correct,
            "missed": self.missed,
            "extra": self.extra,
            "confusions": {f"{a}->{b}": n for (a, b), n in self.confusions.items()},
            "truth_unseen": self.truth_unseen,
            "recognized_unseen": self.recognized_unseen,
            "uncertain_final": self.uncertain_final,
            "rounds": self.rounds,
            "truth_shuffles": self.truth_shuffles,
            "recognized_shuffles": self.recognized_shuffles,
            "recognized_round_ends": self.recognized_round_ends,
        }

    def format(self) -> str:
        lines = [
            f"Runden ausgewertet:     {self.rounds}",
            f"Karten (Ground Truth):  {self.truth_cards}",
            f"Karten erkannt/gezählt: {self.recognized_cards}",
            f"  korrekt:              {self.correct}",
            f"  verpasst:             {self.missed}",
            f"  zusätzlich:           {self.extra}",
            f"GENAUIGKEIT:            {self.accuracy:.2f} %"
            f"   (Trefferquote {self.recall:.2f} %, Präzision {self.precision:.2f} %)",
            f"Ungesehene Karten:      Ground Truth {self.truth_unseen}, erkannt {self.recognized_unseen}"
            f" (davon endgültig unsicher: {self.uncertain_final})",
            f"Mischen:                Ground Truth {self.truth_shuffles}, erkannt {self.recognized_shuffles}",
        ]
        if self.confusions:
            conf = ", ".join(f"{a}→{b} ×{n}" for (a, b), n in self.confusions.most_common())
            lines.append(f"Verwechslungen:         {conf}")
        if self.missed_by_rank:
            lines.append("Verpasst pro Rang:      " + ", ".join(
                f"{r}: {n}" for r, n in sorted(self.missed_by_rank.items())))
        if self.extra_by_rank:
            lines.append("Zusätzlich pro Rang:    " + ", ".join(
                f"{r}: {n}" for r, n in sorted(self.extra_by_rank.items())))
        return "\n".join(lines)


def measure(truth_path: Path, recognized_path: Path) -> AccuracyReport:
    truth = _load(truth_path)
    rec = _load(recognized_path)
    report = AccuracyReport()

    # Zeitraum der Erkennung (nur vollständig beobachtete Runden auswerten)
    rec_times = [_t(e["time"]) for e in rec]
    if not rec_times:
        return report
    t_start, t_end = min(rec_times), max(rec_times)
    for e in rec:
        if e["type"] == "session_start":
            t_start = _t(e["time"])
        if e["type"] == "session_end":
            t_end = _t(e["time"])

    # Runden der Ground Truth: (Startzeit, Liste der Ränge)
    starts: list[float] = []
    cards: list[list[str]] = []
    for e in truth:
        t = _t(e["server_time"])
        if e["type"] == "round_start":
            starts.append(t)
            cards.append([])
        elif e["type"] == "card" and cards:
            cards[-1].append(e["rank"])
        elif e["type"] == "unseen" and starts and t_start <= starts[-1]:
            report.truth_unseen += 1
        elif e["type"] == "shuffle" and t_start <= t <= t_end:
            report.truth_shuffles += 1
    # Runde zählt, wenn sie nach Beginn der Aufnahme startet und die nächste Runde
    # (bzw. das Ende) noch innerhalb der Aufnahme liegt
    valid = []
    for i, s in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else None
        if s >= t_start and (end is None or end <= t_end + 5.0):
            valid.append(i)
    if not valid:
        return report
    report.rounds = len(valid)
    first, last = valid[0], valid[-1]

    truth_rounds: dict[int, Counter] = {i: Counter(cards[i]) for i in valid}
    rec_rounds: dict[int, Counter] = {i: Counter() for i in valid}
    for i in valid:
        report.truth_by_rank.update(cards[i])
    report.truth_cards = sum(len(cards[i]) for i in valid)

    for e in rec:
        t = _t(e["time"])
        if e["type"] == "shuffle" and e.get("counted", True):
            report.recognized_shuffles += 1
        if e["type"] == "round_end" and e.get("counted", True):
            report.recognized_round_ends += 1
        if not e.get("counted", True):
            continue
        idx = bisect.bisect_right(starts, t) - 1
        if idx < first or idx > last:
            continue
        if e["type"] == "new_card":
            rec_rounds[idx][e["rank"]] += 1
            report.recognized_cards += 1
        elif e["type"] == "correction":
            # Alte Lesung dort abziehen, wo sie gezählt wurde (diese oder eine frühere Runde)
            for j in range(idx, first - 1, -1):
                if rec_rounds[j][e["old_rank"]] > 0:
                    rec_rounds[j][e["old_rank"]] -= 1
                    rec_rounds[idx][e["rank"]] += 1
                    break
        elif e["type"] == "unseen":
            report.recognized_unseen += e.get("count", 1)
        elif e["type"] == "uncertain" and e.get("final"):
            report.uncertain_final += 1

    # Pass 1: gleiche Runde
    missing: dict[int, Counter] = {}
    extra: dict[int, Counter] = {}
    for i in valid:
        common = truth_rounds[i] & rec_rounds[i]
        report.correct += sum(common.values())
        missing[i] = truth_rounds[i] - common
        extra[i] = rec_rounds[i] - common
    # Pass 2: Nachbarrunden (Erkennung kommt etwas später als das Austeilen)
    for i in valid:
        for j in (i - 1, i + 1):
            if j in missing and extra[i]:
                common = missing[j] & extra[i]
                report.correct += sum(common.values())
                missing[j] -= common
                extra[i] -= common
    # Rest: Fehler; in derselben Runde als Verwechslung paaren
    for i in valid:
        m = list(missing[i].elements())
        x = list(extra[i].elements())
        for a, b in zip(m, x):
            report.confusions[(a, b)] += 1
        report.missed += len(m)
        report.extra += len(x)
        report.missed_by_rank.update(m)
        report.extra_by_rank.update(x)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--truth", type=Path, help="Ground-Truth-Datei (Standard: neueste in logs/)")
    parser.add_argument("--recognized", type=Path,
                        help="events.jsonl der Erkennung (Standard: neuester Ordner in logs/recognition/)")
    parser.add_argument("--json", action="store_true", help="Ergebnis als JSON ausgeben")
    args = parser.parse_args()
    truth = args.truth or max((PROJECT_ROOT / "logs").glob("ground_truth_*.jsonl"),
                              key=lambda p: p.stat().st_mtime)
    recognized = args.recognized or max((PROJECT_ROOT / "logs" / "recognition").glob("*/events.jsonl"),
                                        key=lambda p: p.stat().st_mtime)
    report = measure(truth, recognized)
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"Ground Truth: {truth}\nErkennung:    {recognized}\n")
        print(report.format())


if __name__ == "__main__":
    main()
