"""Langer Simulationslauf mit gepaartem Vergleich (Phase 6).

Idee: Alle Varianten spielen **genau dieselben Schuhe** (gleiche Mischfolge pro Schuh).
Ein Schuh ist die unabhängige Einheit: Innerhalb eines Schuhs hängen die Runden über den
Count zusammen, verschiedene Schuhe sind unabhängig. Daraus folgt:

- Vertrauensintervall pro Variante: Standardfehler über die Schuhe (Cluster), nicht über
  die einzelnen Runden.
- Unterschied zweier Varianten: Schuh für Schuh vergleichen (gepaarter Vergleich). Weil
  beide Varianten dieselben Karten sehen, heben sich viele Zufallsschwankungen auf – die
  Unterschiede lassen sich viel genauer messen als mit zwei unabhängigen Läufen.

Parallelisierung: Die Schuhe werden in Blöcke aufgeteilt. Block i hat für alle Varianten
denselben Seed → identische Schuhe, egal auf welchem Prozessorkern er läuft.
"""

from __future__ import annotations

import math
import multiprocessing
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass

import numpy as np

from ..models import Rules
from .players import ExactPlayer, StrategyPlayer
from .simulator import ShoeTotals, simulate_shoes

# z-Wert für 95 %; Bonferroni-Korrektur wird bei Bedarf separat berechnet
Z95 = 1.959964


@dataclass(frozen=True)
class Variant:
    """Eine Spielweise im Langlauf."""

    key: str            # z. B. "hi_lo", "hi_lo:flat", "hi_lo:spread_only", "exact", "basic"

    @property
    def base(self) -> str:
        return self.key.split(":")[0]

    @property
    def option(self) -> str:
        return self.key.split(":")[1] if ":" in self.key else ""

    def make_player(self, rules: Rules):
        if self.base == "basic":
            return StrategyPlayer(rules)
        if self.base == "exact":
            return ExactPlayer(rules, flat_bet=self.option == "flat")
        if self.option == "flat":          # zählen + Abweichungen, Einsatz immer 1
            return StrategyPlayer(rules, self.base, flat_bet=True)
        if self.option == "spread_only":   # zählen + Einsatzstaffelung, keine Abweichungen
            return StrategyPlayer(rules, self.base, deviations=False)
        return StrategyPlayer(rules, self.base)


def _run_block(args) -> tuple[str, int, ShoeTotals, float]:
    key, block, shoes, seed = args
    t0 = time.time()
    rules = Rules()
    totals = simulate_shoes(Variant(key).make_player(rules), rules, shoes, seed)
    return key, block, totals, time.time() - t0


def block_seed(seed: int, block: int) -> int:
    """Gleicher Seed pro Block für alle Varianten → identische Schuhe."""
    return seed * 100_003 + block


def run_longrun(plan: dict[str, int], seed: int, jobs: int = 4, block_shoes: int = 2000,
                log=print) -> dict[str, ShoeTotals]:
    """plan: Variante → Anzahl Schuhe. Alle Blöcke laufen gemeinsam in einem Prozess-Pool;
    die teuersten Varianten (exakt) werden zuerst gestartet."""
    tasks = []
    for key, shoes in plan.items():
        blocks = math.ceil(shoes / block_shoes)
        for b in range(blocks):
            n = min(block_shoes, shoes - b * block_shoes)
            tasks.append((key, b, n, block_seed(seed, b)))
    tasks.sort(key=lambda t: (not t[0].startswith("exact"), t[1]))
    parts: dict[str, dict[int, ShoeTotals]] = {k: {} for k in plan}
    t0 = time.time()
    done = 0
    # "spawn" statt "fork": sicher auch aus Programmen mit mehreren Threads und gleich wie
    # unter Windows (dort gibt es nur spawn)
    with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = [pool.submit(_run_block, t) for t in tasks]
        for fut in as_completed(futures):
            key, block, totals, dt = fut.result()
            parts[key][block] = totals
            done += 1
            if done % 10 == 0 or done == len(tasks):
                elapsed = time.time() - t0
                eta = elapsed / done * (len(tasks) - done)
                log(f"  Langlauf: {done}/{len(tasks)} Blöcke fertig, {elapsed / 60:.1f} min, "
                    f"noch ca. {eta / 60:.0f} min")
                sys.stdout.flush()
    return {k: ShoeTotals.concat([v[b] for b in sorted(v)]) for k, v in parts.items()}


# ----------------------------------------------------------------------
# Statistik
# ----------------------------------------------------------------------


def summarize(t: ShoeTotals) -> dict:
    return {
        "rounds": t.total_rounds,
        "shoes": len(t.net),
        "ev_per_round": t.ev_per_round,
        "ci95": t.ci95,
        "ev_per_unit_bet": t.ev_per_unit_bet,
        "mean_bet": t.mean_bet,
        "sd_per_round": t.sd_per_round,
        "rounds_per_shoe": t.total_rounds / len(t.net),
    }


def paired_difference(a: ShoeTotals, b: ShoeTotals) -> dict:
    """Unterschied Gewinn/Runde (a − b) auf den gemeinsamen Schuhen, mit 95-%-Intervall.

    Schätzer: Gewinn/Runde jeder Variante als Verhältnis Summe Gewinn / Summe Runden.
    Standardfehler nach der Delta-Methode mit den gepaarten Schuh-Residuen.
    """
    n = min(len(a.net), len(b.net))
    an, ar = a.net[:n], a.rounds[:n]
    bn, br = b.net[:n], b.rounds[:n]
    ev_a, ev_b = an.sum() / ar.sum(), bn.sum() / br.sum()
    resid = (an - ev_a * ar) / ar.mean() - (bn - ev_b * br) / br.mean()
    se = resid.std(ddof=1) / math.sqrt(n)
    diff = ev_a - ev_b
    z = diff / se if se > 0 else float("inf")
    corr = float(np.corrcoef(an, bn)[0, 1]) if n > 2 else float("nan")
    return {"diff": float(diff), "ci95": float(Z95 * se), "z": float(z), "shoes": n,
            "corr": corr}


def z_bonferroni(comparisons: int, alpha: float = 0.05) -> float:
    """Kritischer z-Wert bei Bonferroni-Korrektur (zweiseitig)."""
    from statistics import NormalDist

    return NormalDist().inv_cdf(1 - alpha / (2 * comparisons))
