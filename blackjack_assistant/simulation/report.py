"""Auswertung (Phase 6): Simulationen, Grafiken (matplotlib) und Markdown-Bericht.

Aufruf:
  python -m blackjack_assistant simulate                                # alles (ca. 80 min)
  python -m blackjack_assistant simulate -- --big-rounds 0              # nur die 10'000 Hände
  python -m blackjack_assistant simulate -- --big-rounds 1000000 --exact-rounds 100000
  python -m blackjack_assistant simulate -- --report-only               # nur results.md neu

Ergebnis: docs/results.md, docs/results.json, docs/img/*.png
(Rohdaten des Langlaufs pro Schuh: results/longrun.npz, nicht im Git)
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from ..counting.systems import CARDS_PER_DECK, load_systems
from ..models import VALUE_RANKS, Rules
from ..strategy.deviations import load_deviations
from .longrun import Z95, paired_difference, run_longrun, summarize, z_bonferroni
from .players import DEFAULT_RAMP, ExactPlayer, JevPlayer, StrategyPlayer
from .simulator import ShoeTotals, SimulationResult, simulate

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS = PROJECT_ROOT / "docs"
RAW = PROJECT_ROOT / "results"

SYSTEMS = ["hi_lo", "ko", "hi_opt_2", "omega_2", "zen", "wong_halves"]
MODES = {"shoe": "75 % Penetration", "every_round": "Mischen nach jeder Runde"}

# Farben (validierte Kategorienpalette, feste Reihenfolge) und Text
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
TEXT, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


# ----------------------------------------------------------------------
# Spieler
# ----------------------------------------------------------------------


def make_player(key: str, rules: Rules):
    if key == "basic":
        return StrategyPlayer(rules)
    if key == "exact":
        return ExactPlayer(rules)
    if key == "jev":
        return JevPlayer(rules)
    return StrategyPlayer(rules, key)


def player_label(key: str) -> str:
    if key == "basic":
        return "Basic Strategy (ohne Zählen)"
    if key == "exact":
        return "Exakt (Restzusammensetzung)"
    if key == "jev":
        return "Jev + Hi-Lo"
    return load_systems()[key].name


def rules_for(mode: str, base: Rules | None = None) -> Rules:
    base = base or Rules()
    return replace(base, shuffle_every_round=(mode == "every_round"))


def run_variant(key: str, mode: str, rounds: int, seed: int) -> SimulationResult:
    """Simuliert eine Variante über `rounds` Runden (für den Teil mit 10'000 Händen)."""
    rules = rules_for(mode)
    res = simulate(make_player(key, rules), rules, rounds, seed, mode)
    res.name = player_label(key)
    return res


def longrun_label(key: str) -> str:
    base, _, option = key.partition(":")
    name = {"basic": "Basic Strategy", "exact": "Exakt"}.get(base) or load_systems()[base].name
    return name + {"": "", "flat": " – flacher Einsatz",
                   "spread_only": " – nur Einsatzstaffelung"}[option]


# ----------------------------------------------------------------------
# Kennzahlen ohne Simulation
# ----------------------------------------------------------------------


def betting_correlations(eor: dict[str, float]) -> dict[str, dict[str, float]]:
    """Betting Correlation: Korrelation der Kartenwerte eines Systems mit den Effects of
    Removal (wie stark der Count den tatsächlichen Vorteil abbildet). Gewichtet mit der
    Häufigkeit der Ränge. Für Systeme mit Ass-Nebenzähler zusätzlich mit Ass-Korrektur."""
    n = np.array([CARDS_PER_DECK[r] for r in VALUE_RANKS], float)
    # EOR: Entfernen einer Karte; ein positiver Zählwert bedeutet "Karte gut für den Spieler,
    # wenn sie weg ist" → gleiches Vorzeichen wie EOR
    e = np.array([eor[r] for r in VALUE_RANKS])

    def corr(v):
        v = np.asarray(v, float)
        vm, em = np.average(v, weights=n), np.average(e, weights=n)
        cov = np.sum(n * (v - vm) * (e - em))
        return float(cov / np.sqrt(np.sum(n * (v - vm) ** 2) * np.sum(n * (e - em) ** 2)))

    out = {}
    for key, system in load_systems().items():
        values = [system.values[r] for r in VALUE_RANKS]
        entry = {"bc": corr(values)}
        if system.ace_side_count:
            adjusted = list(values)
            adjusted[VALUE_RANKS.index("A")] = -system.ace_adjust
            entry["bc_ace_adjusted"] = corr(adjusted)
        out[key] = entry
    return out


# ----------------------------------------------------------------------
# Grafiken
# ----------------------------------------------------------------------


def _style(ax, title: str | None = None):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, color=TEXT, fontsize=11, loc="left")


def _figure(w=10, h=4.6, ncols=1, sharey=False):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, ncols, figsize=(w, h), sharey=sharey, facecolor=SURFACE)
    return fig, axes


def plot_bankroll(results: dict, path: Path) -> None:
    """Guthabenverlauf (kumulierter Gewinn) für Basic, Hi-Lo und Exakt in beiden Schuh-Modi."""
    series = [("basic", BLUE), ("hi_lo", ORANGE), ("exact", AQUA)]
    short = {"basic": "Basic", "hi_lo": "Hi-Lo", "exact": "Exakt"}
    fig, axes = _figure(11.5, 4.6, ncols=2, sharey=True)
    panels = []
    rounds = 0
    for ax, mode in zip(axes, MODES):
        _style(ax, MODES[mode])
        ends = []
        for key, color in series:
            res = results.get((key, mode))
            if res is None:
                continue
            curve = np.cumsum(res.nets)
            x = np.arange(1, len(curve) + 1)
            ax.plot(x, curve, color=color, linewidth=2, label=player_label(key))
            ends.append([curve[-1], curve[-1], x[-1], short[key]])
            rounds = len(curve)
        ax.axhline(0, color=MUTED, linewidth=1)
        ax.set_xlabel("Runde", color=MUTED, fontsize=9)
        panels.append((ax, ends))
    # Endwerte mit Kurznamen beschriften, ohne dass sich die Texte überdecken
    for ax, ends in panels:
        lo, hi = ax.get_ylim()
        gap = (hi - lo) * 0.065
        ends.sort(key=lambda e: e[0])
        for i in range(1, len(ends)):
            ends[i][1] = max(ends[i][1], ends[i - 1][1] + gap)
        for value, y, x_end, name in ends:
            ax.annotate(f"{name} {value:+.0f}", xy=(x_end, value), xytext=(x_end * 1.03, y),
                        color=TEXT, fontsize=8, va="center", annotation_clip=False,
                        arrowprops={"arrowstyle": "-", "color": MUTED, "linewidth": 0.6})
    axes[0].set_ylabel("Gewinn in Einheiten", color=MUTED, fontsize=9)
    axes[0].legend(frameon=False, fontsize=9, loc="upper left", labelcolor=TEXT)
    fig.suptitle(f"Guthabenverlauf über {rounds:,} Runden (gleicher Seed)".replace(",", "'"),
                 color=TEXT, x=0.01, ha="left", fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=130)


def plot_ci_rows(rows: list[tuple[str, dict[str, tuple[float, float]]]], series: dict[str, str],
                 path: Path, title: str, xlabel: str) -> None:
    """Punkt + 95-%-Intervall pro Zeile. rows: (Beschriftung, {Serie: (Wert, ±)}),
    series: Serie → Farbe (feste Reihenfolge). Werte in Prozent."""
    fig, ax = _figure(10, 0.45 * len(rows) + 1.7)
    _style(ax, title)
    ys = np.arange(len(rows))[::-1]
    names = list(series)
    step = 0.24 if len(names) > 1 else 0
    for i, name in enumerate(names):
        offset = (len(names) - 1) / 2 * step - i * step
        for y, (_, values) in zip(ys, rows):
            if name not in values:
                continue
            v, ci = values[name]
            ax.errorbar(v * 100, y + offset, xerr=ci * 100, fmt="o", color=series[name],
                        markersize=6, elinewidth=2, capsize=0)
        ax.plot([], [], "o", color=series[name], label=name)
    ax.axvline(0, color=MUTED, linewidth=1)
    ax.set_yticks(ys)
    ax.set_yticklabels([r[0] for r in rows], color=TEXT, fontsize=9)
    ax.set_xlabel(xlabel, color=MUTED, fontsize=9)
    if len(names) > 1:
        ax.legend(frameon=False, fontsize=9, loc="lower right", labelcolor=TEXT)
    fig.tight_layout()
    fig.savefig(path, dpi=130)


CI_XLABEL = "Gewinn pro Runde in % einer Einheit (Punkt = Mittelwert, Strich = 95-%-Vertrauensintervall)"


def plot_outcomes(results: dict, path: Path) -> None:
    """Verteilung der Rundenergebnisse (Gewinn pro Hand) für Basic und Hi-Lo."""
    fig, ax = _figure(10, 4.2)
    _style(ax, "Gewinn pro Runde – Häufigkeit der Ergebnisse (75 % Penetration)")
    width = 0.4
    data = {}
    for key in ("basic", "hi_lo"):
        res = results.get((key, "shoe"))
        if res is not None:
            values, counts = np.unique(np.round(res.nets * 2) / 2, return_counts=True)
            data[key] = dict(zip(values.tolist(), (counts / res.rounds * 100).tolist()))
    # Kategoriale Achse: nur Ergebnisse, die in mindestens 0,2 % der Runden vorkommen
    cats = sorted({v for d in data.values() for v, p in d.items() if p >= 0.2})
    xs = np.arange(len(cats))
    for i, (key, color) in enumerate([("basic", BLUE), ("hi_lo", ORANGE)]):
        if key not in data:
            continue
        ax.bar(xs + (i - 0.5) * width, [data[key].get(c, 0) for c in cats], width=width * 0.92,
               color=color, label=player_label(key))
    ax.set_xticks(xs)
    ax.set_xticklabels([f"{c:+g}" for c in cats], fontsize=8)
    ax.set_xlabel("Ergebnis der Runde in Einheiten (−0,5 = aufgegeben, +1,5 = Blackjack)",
                  color=MUTED, fontsize=9)
    ax.set_ylabel("Anteil der Runden in %", color=MUTED, fontsize=9)
    ax.legend(frameon=False, fontsize=9, labelcolor=TEXT)
    fig.tight_layout()
    fig.savefig(path, dpi=130)


def plot_hbar(labels: list[str], values: list[float], path: Path, title: str, xlabel: str,
              fmt: str = "{:.2f}") -> None:
    """Einfacher horizontaler Balken (eine Serie → eine Farbe), Werte direkt beschriftet."""
    fig, ax = _figure(10, 0.42 * len(labels) + 1.4)
    _style(ax, title)
    ys = np.arange(len(labels))[::-1]
    ax.barh(ys, values, color=BLUE, height=0.6)
    for y, v in zip(ys, values):
        ax.annotate(fmt.format(v), (v, y), xytext=(4 if v >= 0 else -4, 0),
                    textcoords="offset points", va="center", ha="left" if v >= 0 else "right",
                    color=TEXT, fontsize=8)
    ax.set_yticks(ys)
    ax.set_yticklabels(labels, color=TEXT, fontsize=9)
    ax.set_xlabel(xlabel, color=MUTED, fontsize=9)
    ax.axvline(0, color=MUTED, linewidth=1)
    fig.tight_layout()
    fig.savefig(path, dpi=130)


# ----------------------------------------------------------------------
# Einstellungen dokumentieren (Staffelung und umgerechnete Indizes)
# ----------------------------------------------------------------------


def ramp_table(decks: int = 6) -> dict[str, list[float]]:
    """Schwellen der Einsatzstaffelung im Massstab jedes Systems (zu den Hi-Lo-TC 2/3/4/5)."""
    out = {}
    for key, system in load_systems().items():
        if system.balanced:
            out[key] = [t * system.index_factor for t, _ in DEFAULT_RAMP]
        else:
            out[key] = [system.ko_threshold(t, decks) for t, _ in DEFAULT_RAMP]
    return out


def index_table(decks: int = 6) -> list[dict]:
    """Alle Index-Abweichungen mit dem Hi-Lo-Index und dem umgerechneten Wert je System."""
    from ..counting.counter import Counter

    states = {k: Counter(k, decks).state() for k in SYSTEMS}
    rows = []
    for dev in load_deviations():
        rows.append({
            "name": dev.name, "group": dev.group, "when": dev.when, "hilo": dev.index,
            "systems": {k: dev.threshold(states[k], decks) for k in SYSTEMS},
        })
    return rows


# ----------------------------------------------------------------------
# Langlauf auswerten
# ----------------------------------------------------------------------


def analyse_longrun(big: dict[str, ShoeTotals]) -> dict:
    """Kennzahlen pro Variante und gepaarte Vergleiche (gleiche Schuhe)."""
    out = {"variants": {}, "vs_basic": [], "spread_vs_flat": [], "pairwise": [],
           "exact_vs": [], "decomposition": [], "vs_hilo": []}
    for key, t in big.items():
        out["variants"][key] = {"label": longrun_label(key), **summarize(t)}

    def cmp(a: str, b: str) -> dict:
        return {"a": a, "b": b, "a_label": longrun_label(a), "b_label": longrun_label(b),
                **paired_difference(big[a], big[b])}

    for k in SYSTEMS:
        if k in big:
            out["vs_basic"].append(cmp(k, "basic"))
        if k in big and f"{k}:flat" in big:
            out["spread_vs_flat"].append(cmp(k, f"{k}:flat"))
        if k in big and k != "hi_lo" and "hi_lo" in big:
            out["vs_hilo"].append(cmp(k, "hi_lo"))
    present = [k for k in SYSTEMS if k in big]
    for i, a in enumerate(present):
        for b in present[i + 1:]:
            out["pairwise"].append(cmp(a, b))
    if "exact" in big:
        out["vs_hilo"].append(cmp("exact", "hi_lo"))
        for k in ["basic", *present, "exact:flat"]:
            if k in big:
                out["exact_vs"].append(cmp("exact", k))
    # Zerlegung für Hi-Lo: Spielzüge (Abweichungen) gegen Einsatzvariation
    for a, b in [("hi_lo:flat", "basic"), ("hi_lo:spread_only", "basic"), ("hi_lo", "basic"),
                 ("hi_lo", "hi_lo:spread_only"), ("hi_lo", "hi_lo:flat")]:
        if a in big and b in big:
            out["decomposition"].append(cmp(a, b))
    out["z_bonferroni"] = z_bonferroni(max(1, len(out["pairwise"])))
    if "exact" in big and "basic" in big:
        gain = big["exact"].ev_per_round - big["basic"].ev_per_round
        out["shares"] = {k: (big[k].ev_per_round - big["basic"].ev_per_round) / gain
                         for k in present} if gain > 0 else {}
    return out


# ----------------------------------------------------------------------
# Bericht
# ----------------------------------------------------------------------


def pct(x: float, digits: int = 2) -> str:
    return f"{x * 100:+.{digits}f} %"


def pm(ci: float, digits: int = 2) -> str:
    return f"± {ci * 100:.{digits}f} %"


def fmt_n(n: float) -> str:
    return f"{n:,.0f}".replace(",", "'")


def verdict(c: dict, z_crit: float = Z95) -> str:
    return "**gesichert**" if abs(c["z"]) >= z_crit else "nicht gesichert"


def _cmp(lr: dict, group: str, a: str, b: str) -> dict | None:
    return next((c for c in lr[group] if c["a"] == a and c["b"] == b), None)


def decomposition(lr: dict) -> dict | None:
    """Mehrgewinn von Hi-Lo gegenüber Basic, aufgeteilt in Abweichungen und Staffelung."""
    total = _cmp(lr, "decomposition", "hi_lo", "basic")
    spread = _cmp(lr, "decomposition", "hi_lo", "hi_lo:flat")
    dev = _cmp(lr, "decomposition", "hi_lo:flat", "basic")
    if not (total and spread and dev) or total["diff"] <= 0:
        return None
    return {"total": total, "spread": spread, "dev": dev,
            "share_spread": spread["diff"] / total["diff"]}


def share_intervals(lr: dict) -> dict[str, float]:
    """Näherungsweises 95-%-Intervall (± Prozentpunkte) für den Anteil am Maximum
    (Fehlerfortpflanzung aus den gepaarten Intervallen von Zähler und Nenner)."""
    den = _cmp(lr, "exact_vs", "exact", "basic")
    out = {}
    if not den or den["diff"] <= 0:
        return out
    for k, share in lr.get("shares", {}).items():
        num = _cmp(lr, "vs_basic", k, "basic")
        if num and num["diff"] > 0:
            rel = ((num["ci95"] / num["diff"]) ** 2 + (den["ci95"] / den["diff"]) ** 2) ** 0.5
            out[k] = abs(share) * rel
    return out


def write_report(s: dict, path: Path) -> None:
    lr = s.get("longrun")
    lines = [
        "# Ergebnisse der Auswertung (Phase 6)",
        "",
        f"Erzeugt mit `python -m blackjack_assistant simulate` am {s['created']} (Seed {s['seed']}, "
        f"Laufzeit {s['runtime_s'] / 60:.0f} min). Alle Beträge in **Einheiten** "
        "(1 Einheit = Mindesteinsatz).",
        "",
        "## Lesehilfe",
        "",
        "- **„±“ ist immer ein 95-%-Vertrauensintervall** (halbe Breite): Der wahre Wert liegt mit "
        "95 % Wahrscheinlichkeit im Bereich Mittelwert ± Intervall. Berechnet mit dem **Schuh als "
        "unabhängiger Einheit**, weil die Runden innerhalb eines Schuhs über den Count zusammenhängen.",
        "- **Gewinn pro Runde** = Gesamtgewinn / Anzahl Runden, in % einer Einheit.",
        "  **Vorteil pro Einsatz** = Gesamtgewinn / Summe der Starteinsätze.",
        "- **Regeln:** 6 Decks, Schnittkarte bei 75 %, Dealer steht auf Soft 17, Blackjack 3:2, "
        "Double auf zwei Karten (auch nach Split), Split bis 4 Hände, Late Surrender, Dealer-Peek, "
        "Versicherung.",
        "",
    ]
    lines += _settings_section(s)
    lines += ["## Kurzfassung", ""] + [f"- {t}" for t in _findings(s)] + [""]
    lines += _section_10k(s)
    if lr:
        lines += _section_longrun(s)
        lines += _section_origin(s)
        lines += _section_significance(s)
    lines += _section_bc(s)
    lines += _section_shoe_vs_every(s)
    lines += [
        "## Methode",
        "",
        "- Simulator mit denselben Regeln wie das Mock-Casino; der Spieler sieht jede offene Karte "
        "(die Hole Card wird am Rundenende aufgedeckt). Perfekte Erkennung angenommen.",
        "- **10'000 Hände:** gleicher Seed für alle Varianten (jeder Schuh wird gleich gemischt).",
        "- **Langlauf:** Alle Varianten spielen **dieselben Schuhe** (Blöcke à "
        f"{fmt_n(s['settings']['block_shoes'])} Schuhe mit festem Seed, parallel auf "
        f"{s['settings']['jobs']} Prozessen). Unterschiede werden Schuh für Schuh verglichen "
        "(gepaarter Vergleich); das verkleinert den Zufallsspielraum stark, weil beide Varianten "
        "dieselben Karten bekommen.",
        "- Zählsysteme: Running Count → True Count (Restdecks auf halbe Decks gerundet), "
        "Abweichungen und Einsatzstaffelung wie oben. KO mit festen Running-Count-Schwellen.",
        "- Exakt: Jede Entscheidung aus der genauen Restzusammensetzung (alle gesehenen Karten "
        "entfernt). Einsatz nach dem linear geschätzten Vorteil, umgerechnet in einen "
        "Hi-Lo-äquivalenten True Count (0,5 % Vorteil ≈ 1 TC), dieselbe Staffelung.",
        "- Flacher Einsatz: gleiche Zählung und gleiche Spielzüge (inkl. Abweichungen), aber immer "
        "1 Einheit.",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _settings_section(s: dict) -> list[str]:
    names = {k: load_systems()[k].name for k in SYSTEMS}
    out = [
        "## Einstellungen",
        "",
        "### Einsatzstaffelung (alle zählenden Varianten)",
        "",
        "| Hi-Lo True Count | unter +2 | ab +2 | ab +3 | ab +4 | ab +5 |",
        "|---|---:|---:|---:|---:|---:|",
        "| **Einsatz** | 1 Einheit | 2 | 4 | 6 | 8 |",
        "",
        "Spread 1–8. Basic Strategy setzt immer 1 Einheit. Für die anderen Systeme werden die "
        "Schwellen umgerechnet (**Näherung**, siehe unten):",
        "",
        "| System | Count, ab dem 2 / 4 / 6 / 8 Einheiten gesetzt werden | Art |",
        "|---|---|---|",
    ]
    for k in SYSTEMS:
        thr = " / ".join(f"{t:+.1f}" for t in s["ramp_table"][k])
        system = load_systems()[k]
        kind = ("True Count (original Hi-Lo)" if k == "hi_lo" else
                "Running Count, feste Schwellen" if not system.balanced else
                f"True Count × {system.index_factor:.2f}"
                + (" inkl. Ass-Korrektur" if system.ace_side_count else ""))
        out.append(f"| {names[k]} | {thr} | {kind} |")
    out += [
        "| Exakt | Vorteil ab −0,34 % + 1,0 / 1,5 / 2,0 / 2,5 % | berechneter Vorteil |",
        "",
        "### Abweichungen (Indizes)",
        "",
        "Die Illustrious 18 und Fab 4 sind **für Hi-Lo veröffentlicht** (Schlesinger, *Blackjack "
        "Attack*). **Alle Werte der anderen Systeme sind umgerechnet (Näherung)**: Bei den "
        "ausgeglichenen Systemen wird der Hi-Lo-Index mit dem Faktor des Systems multipliziert "
        "(Regression der Kartenwerte auf Hi-Lo), bei KO in eine feste Running-Count-Schwelle "
        "(Referenztiefe 37,5 % des Schuhs; Versicherung fest ab +3). Eigene, genauere Indizes "
        "lassen sich in `config/deviations.toml` eintragen.",
        "",
        "| Abweichung | Hi-Lo (Original) | " + " | ".join(names[k] for k in SYSTEMS[1:]) + " |",
        "|---|---:|" + "---:|" * (len(SYSTEMS) - 1),
    ]
    for row in s["index_table"]:
        cond = "ab" if row["when"] == ">=" else "unter"
        cells = [f"{cond} {row['systems'][k]:+.1f}" for k in SYSTEMS[1:]]
        out.append(f"| {row['name']} ({row['group']}) | {cond} {row['hilo']:+g} | "
                   + " | ".join(cells) + " |")
    out += ["", "Bei KO sind die Werte Running Counts, sonst True Counts.", ""]
    return out


def _findings(s: dict) -> list[str]:
    lr = s.get("longrun")
    out = [f"Basic Strategy ohne Zählen hat theoretisch {pct(s['base_ev'], 2)} pro Einheit "
           "(exakt berechnet)."]
    if not lr:
        return out
    v = lr["variants"]
    hi = v["hi_lo"]
    out.append(
        f"Langlauf ({fmt_n(hi['rounds'])} Runden pro Zählsystem): Hi-Lo mit Abweichungen und Spread "
        f"1–8 gewinnt {pct(hi['ev_per_round'])} {pm(hi['ci95'])} pro Runde "
        f"({pct(hi['ev_per_unit_bet'])} pro eingesetzter Einheit); Basic Strategy "
        f"{pct(v['basic']['ev_per_round'])} {pm(v['basic']['ci95'])}.")
    d = decomposition(lr)
    if d:
        head = ("**Der Vorteil kommt vor allem aus der Einsatzvariation:** " if d["share_spread"] >= 0.7
                else "Herkunft des Vorteils: ")
        flat_ev = v["hi_lo:flat"]["ev_per_round"]
        out.append(
            head + f"Von {pct(d['total']['diff'], 2)} Mehrgewinn pro Runde gegenüber Basic Strategy "
            f"stammen {d['share_spread'] * 100:.0f} % aus der Einsatzstaffelung "
            f"({pct(d['spread']['diff'], 2)} {pm(d['spread']['ci95'])}). Mit denselben Spielzügen, aber "
            f"flachem Einsatz erreicht Hi-Lo nur {pct(flat_ev, 3)} {pm(v['hi_lo:flat']['ci95'], 3)} pro "
            "Runde – " + ("also weiterhin einen Verlust; " if flat_ev < 0 else "kaum mehr als null; ")
            + f"die Abweichungen allein bringen {pct(d['dev']['diff'], 3)} {pm(d['dev']['ci95'], 3)} "
            + ("(gesichert)." if abs(d["dev"]["z"]) >= Z95 else "(nicht gesichert)."))
    ranked = sorted((k for k in SYSTEMS if k in v), key=lambda k: -v[k]["ev_per_round"])
    sig = [c for c in lr["pairwise"] if abs(c["z"]) >= lr["z_bonferroni"]]
    out.append(
        "Rangliste im Langlauf: " + ", ".join(
            f"{load_systems()[k].name} {pct(v[k]['ev_per_round'])}" for k in ranked)
        + f". Von {len(lr['pairwise'])} Paarvergleichen sind {len(sig)} nach Bonferroni-Korrektur "
        "gesichert (Details: Abschnitt „Statistische Signifikanz“).")
    if "exact" in v:
        out.append(
            f"Die exakte Strategie (theoretisches Maximum, {fmt_n(v['exact']['rounds'])} Runden) "
            f"erreicht {pct(v['exact']['ev_per_round'])} {pm(v['exact']['ci95'])} pro Runde. "
            "Die Zählsysteme holen davon "
            f"{min(lr['shares'].values()) * 100:.0f}–{max(lr['shares'].values()) * 100:.0f} % des "
            "möglichen Zusatzgewinns gegenüber Basic Strategy"
            + (f" (je etwa ± {max(share_intervals(lr).values()) * 100:.0f} Prozentpunkte)."
               if share_intervals(lr) else "."))
    r10 = {(r["key"], r["mode"]): r for r in s["runs_10k"]}
    out.append(
        f"Die geforderten 10'000 Hände sind vom Zufall geprägt (Hi-Lo {r10[('hi_lo', 'shoe')]['net']:+.0f}, "
        f"Basic {r10[('basic', 'shoe')]['net']:+.0f} Einheiten; Spielraum pro Runde bis "
        f"{pm(max(r['ci95'] for r in s['runs_10k']), 1)}).")
    out.append("Wird nach jeder Runde gemischt, bringt Zählen nichts: Alle Zählsysteme spielen dann "
               "Basic Strategy mit 1 Einheit.")
    return out


def _section_10k(s: dict) -> list[str]:
    out = [
        f"## 1. Die geforderten {fmt_n(s['settings']['hands'])} Hände", "",
        "| Variante | Modus | Gewinn gesamt | pro Runde | 95-%-Intervall | Vorteil pro Einsatz | "
        "Streuung pro Runde | Ø Einsatz | max. Rückgang |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in s["runs_10k"]:
        out.append(
            f"| {r['name']} | {MODES[r['mode']]} | {r['net']:+.1f} | {pct(r['ev_per_round'])} | "
            f"{pm(r['ci95'])} | {pct(r['ev_per_unit_bet'])} | {r['sd_per_round']:.2f} | "
            f"{r['mean_bet']:.2f} | {r['max_drawdown']:.0f} |")
    if s.get("jev_note"):
        out += ["", f"**Jev:** {s['jev_note']}"]
    lo = min(r["ci95"] for r in s["runs_10k"])
    hi = max(r["ci95"] for r in s["runs_10k"])
    out += [
        "",
        "![Guthabenverlauf](img/bankroll_10k.png)",
        "",
        "![Gewinn pro Runde mit Vertrauensintervall](img/gewinn_pro_runde_10k.png)",
        "",
        "![Verteilung der Rundenergebnisse](img/ergebnisse_verteilung.png)",
        "",
        "![Streuung pro Runde](img/streuung.png)",
        "",
        f"Bei {fmt_n(s['settings']['hands'])} Runden ist das 95-%-Intervall des Gewinns pro Runde "
        f"{pm(lo, 1)} bis {pm(hi, 1)} "
        "breit – grösser als die Unterschiede zwischen den Zählsystemen. Diese Tabelle eignet sich "
        "deshalb nicht für eine Rangliste; dafür ist der Langlauf da.",
        "",
    ]
    return out


def _section_longrun(s: dict) -> list[str]:
    lr = s["longrun"]
    v = lr["variants"]
    out = [
        "## 2. Langlauf: gleiche Schuhe für alle Varianten", "",
        f"Zählsysteme und Basic Strategy: je **{fmt_n(v['hi_lo']['rounds'])} Runden** "
        f"({fmt_n(v['hi_lo']['shoes'])} Schuhe)"
        + (f"; exakte Strategie: **{fmt_n(v['exact']['rounds'])} Runden** "
           f"({fmt_n(v['exact']['shoes'])} Schuhe, die ersten Schuhe derselben Folge)."
           if "exact" in v else "."),
        "",
        "| Variante | Spread 1–8: pro Runde | 95-%-Intervall | Vorteil pro Einsatz | Ø Einsatz | "
        "flacher Einsatz: pro Runde | 95-%-Intervall | Anteil am Maximum |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    rows = ["basic", *[k for k in SYSTEMS if k in v], "exact"]
    for k in rows:
        if k not in v:
            continue
        r = v[k]
        f = v.get(f"{k}:flat")
        share = lr.get("shares", {}).get(k)
        if k == "basic":
            out.append(f"| {r['label']} | – | – | – | – | {pct(r['ev_per_round'], 3)} | "
                       f"{pm(r['ci95'], 3)} | – |")
            continue
        out.append(
            f"| {r['label']} | {pct(r['ev_per_round'], 3)} | {pm(r['ci95'], 3)} | "
            f"{pct(r['ev_per_unit_bet'])} | {r['mean_bet']:.2f} | "
            + (f"{pct(f['ev_per_round'], 3)} | {pm(f['ci95'], 3)}" if f else "– | –")
            + f" | {'–' if share is None else f'{share * 100:.0f} %'} |")
    out += [
        "",
        "*Anteil am Maximum* = (Gewinn pro Runde des Systems − Basic Strategy) / "
        "(Exakt − Basic Strategy). Die exakte Strategie ist das theoretische Maximum für Spielzüge, "
        "die nur die gesehenen Karten kennen. Weil sie weniger Runden hat, ist ihr Intervall breiter. "
        + ("95-%-Intervall des Anteils (Näherung): "
           + ", ".join(f"{load_systems()[k].name} ± {ci * 100:.0f} Prozentpunkte"
                       for k, ci in share_intervals(lr).items()) + "."
           if share_intervals(lr) else ""),
        "",
        "![Langlauf](img/langlauf.png)",
        "",
        "![Anteil am Maximum](img/anteil_maximum.png)",
        "",
    ]
    return out


def _section_origin(s: dict) -> list[str]:
    lr = s["longrun"]
    v = lr["variants"]
    if "hi_lo:flat" not in v:
        return []
    out = [
        "## 3. Woher kommt der Vorteil? Einsatz gegen Spielzüge", "",
        "Gleiche Schuhe, vier Varianten von Hi-Lo (gepaarter Vergleich gegen Basic Strategy):", "",
        "| Variante | pro Runde | 95-%-Intervall | Unterschied zu Basic | 95-%-Intervall | Bewertung |",
        "|---|---:|---:|---:|---:|---|",
    ]
    vs_basic = {c["a"]: c for c in lr["decomposition"] if c["b"] == "basic"}
    out.append(f"| Basic Strategy, flacher Einsatz | {pct(v['basic']['ev_per_round'], 3)} | "
               f"{pm(v['basic']['ci95'], 3)} | – | – | Ausgangslage |")
    for key, text in [("hi_lo:flat", "Hi-Lo: nur Abweichungen (flacher Einsatz)"),
                      ("hi_lo:spread_only", "Hi-Lo: nur Einsatzstaffelung (keine Abweichungen)"),
                      ("hi_lo", "Hi-Lo: Abweichungen + Einsatzstaffelung")]:
        if key in v and key in vs_basic:
            c = vs_basic[key]
            out.append(f"| {text} | {pct(v[key]['ev_per_round'], 3)} | {pm(v[key]['ci95'], 3)} | "
                       f"{pct(c['diff'], 3)} | {pm(c['ci95'], 3)} | {verdict(c)} |")
    out += ["", "Flacher Einsatz für alle Systeme (gleiche Spielzüge, immer 1 Einheit):", "",
            "| System | mit Spread 1–8 | flacher Einsatz | Gewinn durch die Staffelung | "
            "95-%-Intervall | flach: besser als Basic? |",
            "|---|---:|---:|---:|---:|---|"]
    for c in lr["spread_vs_flat"]:
        k = c["a"]
        fb = v[f"{k}:flat"]["ev_per_round"] - v["basic"]["ev_per_round"]
        out.append(f"| {load_systems()[k].name} | {pct(v[k]['ev_per_round'], 3)} | "
                   f"{pct(v[f'{k}:flat']['ev_per_round'], 3)} | {pct(c['diff'], 3)} | "
                   f"{pm(c['ci95'], 3)} | {pct(fb, 3)} |")
    if "exact:flat" in v:
        ex = [c for c in lr["exact_vs"] if c["b"] == "exact:flat"]
        if ex:
            c = ex[0]
            out.append(f"| Exakt | {pct(v['exact']['ev_per_round'], 3)} | "
                       f"{pct(v['exact:flat']['ev_per_round'], 3)} | {pct(c['diff'], 3)} | "
                       f"{pm(c['ci95'], 3)} | "
                       f"{pct(v['exact:flat']['ev_per_round'] - v['basic']['ev_per_round'], 3)} |")
    d = decomposition(lr)
    if d:
        flat_ev = v["hi_lo:flat"]["ev_per_round"]
        out += [
            "",
            f"**Ergebnis:** Die Abweichungen allein (flacher Einsatz) verbessern Basic Strategy um "
            f"{pct(d['dev']['diff'], 3)} {pm(d['dev']['ci95'], 3)} pro Runde "
            + ("(gesichert)" if abs(d["dev"]["z"]) >= Z95 else "(nicht gesichert)")
            + (" – das reicht nicht, um den Hausvorteil umzudrehen" if flat_ev < 0 else "")
            + f". Die Einsatzstaffelung bringt {pct(d['spread']['diff'], 3)} {pm(d['spread']['ci95'], 3)}, "
            f"das sind {d['share_spread'] * 100:.0f} % des gesamten Mehrgewinns. Der Gewinn entsteht "
            "also vor allem, weil bei hohem Count mehr gesetzt wird; wer immer gleich viel setzt, hat "
            "vom Zählen nur einen kleinen Teil des Nutzens.",
        ]
    out += ["", "![Woher kommt der Vorteil](img/vorteil_herkunft.png)", ""]
    return out


def _section_significance(s: dict) -> list[str]:
    lr = s["longrun"]
    zb = lr["z_bonferroni"]
    n = len(lr["pairwise"])
    out = [
        "## 4. Statistische Signifikanz", "",
        "**Wann ist ein Unterschied gesichert?** Wenn das 95-%-Vertrauensintervall des "
        "*Unterschieds* die Null nicht enthält (|z| ≥ 1,96). Der Unterschied wird gepaart gemessen: "
        "beide Varianten spielen dieselben Schuhe, verglichen wird Schuh für Schuh. Das ist viel "
        "genauer als zwei unabhängige Intervalle nebeneinander – zwei überlappende Intervalle "
        "in der Tabelle oben bedeuten deshalb **nicht** automatisch „kein Unterschied“.",
        "",
        f"**Mehrfachvergleiche:** Bei {n} Paarvergleichen zwischen den Zählsystemen würde man schon "
        "rein zufällig etwa einen „signifikanten“ Unterschied finden. Für die Rangliste gilt deshalb "
        f"die strengere Bonferroni-Grenze |z| ≥ {zb:.2f} (Gesamtirrtum höchstens 5 %).",
        "",
        "### Gegen Basic Strategy",
        "",
        "| Variante | Unterschied pro Runde | 95-%-Intervall | z | Bewertung |",
        "|---|---:|---:|---:|---|",
    ]
    for c in lr["vs_basic"]:
        out.append(f"| {c['a_label']} | {pct(c['diff'], 3)} | {pm(c['ci95'], 3)} | {c['z']:.1f} | "
                   f"{verdict(c)} |")
    out += ["", "### Zählsysteme untereinander", "",
            "| Vergleich | Unterschied pro Runde | 95-%-Intervall | z | 95 % | Bonferroni |",
            "|---|---:|---:|---:|---|---|"]
    for c in sorted(lr["pairwise"], key=lambda c: -abs(c["z"])):
        out.append(f"| {c['a_label']} − {c['b_label']} | {pct(c['diff'], 3)} | {pm(c['ci95'], 3)} | "
                   f"{c['z']:+.1f} | {verdict(c)} | {verdict(c, zb)} |")
    if lr["exact_vs"]:
        out += ["", "### Exakte Strategie gegen die anderen (auf den gemeinsamen Schuhen)", "",
                "| Vergleich | Unterschied pro Runde | 95-%-Intervall | z | Bewertung |",
                "|---|---:|---:|---:|---|"]
        for c in lr["exact_vs"]:
            out.append(f"| {c['a_label']} − {c['b_label']} | {pct(c['diff'], 3)} | "
                       f"{pm(c['ci95'], 3)} | {c['z']:+.1f} | {verdict(c)} |")
    out += ["", "![Unterschied zu Hi-Lo](img/unterschied_zu_hilo.png)", ""]
    # Zusammenfassung in Worten
    sig = [c for c in lr["pairwise"] if abs(c["z"]) >= zb]
    weak = [c for c in lr["pairwise"] if Z95 <= abs(c["z"]) < zb]
    out += ["**Was ist gesichert, was nicht?**", ""]
    out.append(f"- Gesichert: Jedes Zählsystem mit Spread schlägt Basic Strategy deutlich "
               f"(z zwischen {min(c['z'] for c in lr['vs_basic']):.0f} und "
               f"{max(c['z'] for c in lr['vs_basic']):.0f}).")
    if lr["exact_vs"]:
        vs_sys = [c for c in lr["exact_vs"] if c["b"] in SYSTEMS]
        worst = min(vs_sys, key=lambda c: c["z"], default=None)
        if worst and worst["z"] >= Z95:
            out.append(f"- Gesichert: Die exakte Strategie ist besser als jedes Zählsystem "
                       f"(kleinster Abstand: {worst['b_label']}, {pct(worst['diff'], 3)}, "
                       f"z = {worst['z']:.1f}).")
        elif worst:
            better = [c for c in vs_sys if c["z"] >= Z95]
            out.append("- Nicht gesichert: dass die exakte Strategie besser ist als "
                       + ("alle Zählsysteme" if not better else
                          "die Systeme " + ", ".join(c["b_label"] for c in vs_sys if c["z"] < Z95))
                       + f" (kleinster z = {worst['z']:.1f}); dafür reichen die "
                       f"{fmt_n(lr['variants']['exact']['rounds'])} Runden der exakten Strategie nicht."
                       + (" Gesichert besser ist sie als " + ", ".join(c["b_label"] for c in better) + "."
                          if better else ""))
    if sig:
        out.append("- Gesicherte Unterschiede zwischen Zählsystemen (Bonferroni): "
                   + "; ".join(f"{c['a_label']} vs. {c['b_label']} ({pct(c['diff'], 3)})" for c in sig)
                   + ".")
    if weak:
        out.append("- Nur auf 95-%-Niveau, aber nicht nach Bonferroni gesichert: "
                   + "; ".join(f"{c['a_label']} vs. {c['b_label']}" for c in weak) + ".")
    rest = len(lr["pairwise"]) - len(sig) - len(weak)
    if rest:
        out.append(f"- Bei den übrigen {rest} Paaren ist kein Unterschied nachweisbar – die Systeme "
                   "sind dort im Rahmen der Messgenauigkeit gleich gut.")
    out.append("- **Wichtig:** Gemessen wird die Kombination aus Kartenwerten, umgerechneten Indizes "
               "und umgerechneter Einsatzstaffelung. Ein Unterschied kann auch von der Näherung bei "
               "den Indizes/Schwellen kommen und nicht nur von der „Qualität“ des Systems.")
    out.append("")
    return out


def _section_bc(s: dict) -> list[str]:
    out = [
        "## 5. Zählsysteme ohne Zufall: Betting Correlation", "",
        "Die *Betting Correlation* misst, wie gut die Kartenwerte eines Systems die tatsächliche "
        "Wirkung jeder Karte auf den Spielervorteil abbilden (Effects of Removal, exakt berechnet). "
        "1.00 wäre perfekt. Sie hängt nicht vom Glück ab, sagt aber nichts über die Spielzüge.",
        "",
        "| System | Betting Correlation | mit Ass-Korrektur |",
        "|---|---:|---:|",
    ]
    for key, entry in s["betting_correlation"].items():
        adj = entry.get("bc_ace_adjusted")
        out.append(f"| {load_systems()[key].name} | {entry['bc']:.3f} | "
                   f"{'–' if adj is None else f'{adj:.3f}'} |")
    out += [
        "",
        "![Betting Correlation](img/betting_correlation.png)",
        "",
        "Effects of Removal (Änderung des Spielervorteils in %, wenn eine Karte entfernt wird): "
        + ", ".join(f"{r}: {val * 100:+.3f}" for r, val in s["eor"].items())
        + f". Theoretischer Erwartungswert der Basic Strategy mit vollem Schuh: "
        f"{pct(s['base_ev'], 3)} pro Einheit.",
        "",
    ]
    return out


def _section_shoe_vs_every(s: dict) -> list[str]:
    r10 = {(r["key"], r["mode"]): r for r in s["runs_10k"]}
    b, e = r10[("basic", "shoe")], r10[("basic", "every_round")]
    return [
        "## 6. Tiefer Schuh gegen Mischen nach jeder Runde", "",
        f"- Tiefer Schuh (75 %): im Schnitt {b['rounds'] / max(1, b['shuffles']):.1f} Runden pro "
        "Schuh; der Count kann sich aufbauen, Einsatz und Spielzüge passen sich an.",
        f"- Mischen nach jeder Runde: {fmt_n(e['shuffles'])} Mischvorgänge in {fmt_n(e['rounds'])} "
        f"Runden. Alle Zählsysteme setzen dann immer 1 Einheit (Ø Einsatz "
        f"{r10[('hi_lo', 'every_round')]['mean_bet']:.2f}) und spielen Basic Strategy – identische "
        "Ergebnisse wie ohne Zählen.",
        "- Viele Online-Casinos (auch im Demo-Modus) mischen nach jeder Runde oder ziehen jede Karte "
        "per Zufallsgenerator – genau dieser Fall. Das Overlay warnt dann mit „Zählen hier wirkungslos“.",
        "",
    ]


# ----------------------------------------------------------------------
# Hauptprogramm
# ----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simulate", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hands", type=int, default=10_000, help="Runden pro Variante (Teil 1)")
    parser.add_argument("--big-rounds", type=int, default=10_000_000,
                        help="Runden pro Zählsystem im Langlauf (0 = kein Langlauf)")
    parser.add_argument("--exact-rounds", type=int, default=1_000_000,
                        help="Runden der exakten Strategie im Langlauf (0 = ohne)")
    parser.add_argument("--block-shoes", type=int, default=2000, help="Schuhe pro Rechenblock")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--jobs", type=int, default=4, help="parallele Prozesse")
    parser.add_argument("--out", type=Path, default=DOCS)
    parser.add_argument("--report-only", action="store_true",
                        help="nur results.md aus vorhandenem results.json neu schreiben")
    args = parser.parse_args(argv)
    if args.report_only:
        summary = json.loads((args.out / "results.json").read_text(encoding="utf-8"))
        write_report(summary, args.out / "results.md")
        print(f"Bericht: {args.out / 'results.md'}")
        return 0
    if args.hands < 2:
        parser.error("--hands muss mindestens 2 sein")

    t0 = time.time()
    out = args.out
    img = out / "img"
    img.mkdir(parents=True, exist_ok=True)
    keys = ["basic", *SYSTEMS, "exact"]

    # 1) 10'000 Hände in beiden Modi
    results: dict[tuple[str, str], SimulationResult] = {}
    for mode in MODES:
        for key in keys:
            results[(key, mode)] = run_variant(key, mode, args.hands, args.seed)
            print(f"{MODES[mode]:28s} {player_label(key):32s} "
                  f"{results[(key, mode)].ev_per_round:+.4f} pro Runde", flush=True)
    probe = JevPlayer(Rules())
    if probe.available:
        for mode in MODES:
            results[("jev", mode)] = run_variant("jev", mode, args.hands, args.seed)
        jev_note = f"mit der Jev-API gespielt ({probe.jev.requests} Anfragen)."
    else:
        jev_note = ("nicht simuliert – kein API-Key vorhanden. Mit Key: "
                    "`python -m blackjack_assistant simulate` erneut ausführen; die Variante "
                    "„Jev + Hi-Lo“ erscheint dann automatisch.")

    # 2) Langlauf auf identischen Schuhen
    longrun = None
    if args.big_rounds:
        basic10 = results[("basic", "shoe")]
        rps = basic10.rounds / basic10.shuffles     # Runden pro Schuh (ca. 43)
        big_shoes = max(2, round(args.big_rounds / rps))
        plan = {"basic": big_shoes, "hi_lo:spread_only": big_shoes}
        for k in SYSTEMS:
            plan[k] = big_shoes
            plan[f"{k}:flat"] = big_shoes
        if args.exact_rounds:
            exact_shoes = max(2, round(args.exact_rounds / rps))
            plan["exact"] = plan["exact:flat"] = exact_shoes
        print(f"Langlauf: {len(plan)} Varianten, {fmt_n(big_shoes)} Schuhe "
              f"(≈ {fmt_n(big_shoes * rps)} Runden) pro Zählsystem", flush=True)
        big = run_longrun(plan, args.seed + 1, jobs=args.jobs, block_shoes=args.block_shoes,
                          log=lambda m: print(m, flush=True))
        RAW.mkdir(exist_ok=True)
        np.savez_compressed(RAW / "longrun.npz", **{
            f"{k}|{field}": getattr(t, field) for k, t in big.items()
            for field in ("net", "rounds", "bets")})
        longrun = analyse_longrun(big)

    # 3) Ohne Zufall
    from .exact import ExactCalculator, full_shoe

    calc = ExactCalculator(Rules())
    eor = calc.effects_of_removal()
    base_ev = calc.predeal_ev(full_shoe(6))
    bc = betting_correlations(eor)

    # Grafiken
    plot_bankroll(results, img / "bankroll_10k.png")
    rows10 = [(player_label(k), {MODES[m]: (results[(k, m)].ev_per_round, results[(k, m)].ci95)
                                 for m in MODES if (k, m) in results})
              for k in keys + (["jev"] if ("jev", "shoe") in results else [])]
    plot_ci_rows(rows10, {MODES["shoe"]: BLUE, MODES["every_round"]: ORANGE},
                 img / "gewinn_pro_runde_10k.png",
                 f"Gewinn pro Runde nach {fmt_n(args.hands)} Runden – mit Zufallsspielraum", CI_XLABEL)
    plot_outcomes(results, img / "ergebnisse_verteilung.png")
    plot_hbar([player_label(k) for k in keys], [results[(k, "shoe")].sd_per_round for k in keys],
              img / "streuung.png",
              "Streuung (Standardabweichung) des Ergebnisses pro Runde – 75 % Penetration",
              "Standardabweichung in Einheiten (höher = grössere Schwankungen)")
    plot_hbar([load_systems()[k].name for k in bc],
              [val.get("bc_ace_adjusted", val["bc"]) for val in bc.values()],
              img / "betting_correlation.png",
              "Betting Correlation der Zählsysteme (mit Ass-Korrektur, falls vorhanden)",
              "Korrelation mit den exakten Effects of Removal (1 = perfekt)", "{:.3f}")
    if longrun:
        v = longrun["variants"]
        rows = []
        for k in ["basic", *SYSTEMS, "exact"]:
            if k not in v:
                continue
            label = {"basic": "Basic Strategy", "exact": "Exakt"}.get(k) or load_systems()[k].name
            entry = {}
            if k != "basic":
                entry["Spread 1–8"] = (v[k]["ev_per_round"], v[k]["ci95"])
            flat_key = "basic" if k == "basic" else f"{k}:flat"
            if flat_key in v:
                entry["flacher Einsatz"] = (v[flat_key]["ev_per_round"], v[flat_key]["ci95"])
            rows.append((label, entry))
        plot_ci_rows(rows, {"Spread 1–8": BLUE, "flacher Einsatz": ORANGE}, img / "langlauf.png",
                     f"Langlauf: Gewinn pro Runde ({fmt_n(v['hi_lo']['rounds'])} Runden pro System)",
                     CI_XLABEL)
        deco = [("Basic Strategy", "basic"), ("nur Abweichungen (flach)", "hi_lo:flat"),
                ("nur Einsatzstaffelung", "hi_lo:spread_only"), ("Abweichungen + Staffelung", "hi_lo")]
        plot_ci_rows([(f"Hi-Lo: {t}" if k != "basic" else t,
                       {"Gewinn": (v[k]["ev_per_round"], v[k]["ci95"])}) for t, k in deco if k in v],
                     {"Gewinn": BLUE}, img / "vorteil_herkunft.png",
                     "Woher kommt der Vorteil? Hi-Lo zerlegt (gleiche Schuhe)", CI_XLABEL)
        diffs = [(c["a_label"], {"Unterschied": (c["diff"], c["ci95"])}) for c in longrun["vs_hilo"]]
        plot_ci_rows(diffs, {"Unterschied": BLUE}, img / "unterschied_zu_hilo.png",
                     "Unterschied zu Hi-Lo (gepaart, gleiche Schuhe) – Intervall ohne 0 = gesichert",
                     "Unterschied im Gewinn pro Runde in % einer Einheit (± 95-%-Intervall)")
        if longrun.get("shares"):
            plot_hbar([load_systems()[k].name for k in longrun["shares"]],
                      [x * 100 for x in longrun["shares"].values()], img / "anteil_maximum.png",
                      "Anteil am maximal möglichen Zusatzgewinn (Exakt = 100 %)",
                      "% des Zusatzgewinns der exakten Strategie gegenüber Basic Strategy", "{:.0f} %")

    runs_10k = []
    for (k, m), res in results.items():
        runs_10k.append({"key": k, **res.summary()})
    summary = {
        "created": time.strftime("%Y-%m-%d %H:%M"),
        "seed": args.seed,
        "runtime_s": time.time() - t0,
        "settings": {"hands": args.hands, "big_rounds": args.big_rounds,
                     "exact_rounds": args.exact_rounds, "block_shoes": args.block_shoes,
                     "jobs": args.jobs, "ramp": DEFAULT_RAMP},
        "ramp_table": ramp_table(),
        "index_table": index_table(),
        "runs_10k": runs_10k,
        "jev_note": jev_note,
        "longrun": longrun,
        "eor": {r: round(val, 6) for r, val in eor.items()},
        "base_ev": base_ev,
        "betting_correlation": {k: {kk: round(vv, 4) for kk, vv in val.items()}
                                for k, val in bc.items()},
    }
    (out / "results.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False,
                                                 default=float) + "\n", encoding="utf-8")
    write_report(summary, out / "results.md")
    print(f"Bericht: {out / 'results.md'}  ({(time.time() - t0) / 60:.1f} min)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
