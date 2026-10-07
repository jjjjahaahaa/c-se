"""Auswertung (Phase 6): Simulationen, Grafiken (matplotlib) und Markdown-Bericht.

Aufruf:
  python -m blackjack_assistant simulate                       # 10'000 Hände + Langlauf
  python -m blackjack_assistant simulate -- --hands 10000 --big 0   # nur die 10'000 Hände
  python -m blackjack_assistant.simulation.report --help

Ergebnis: docs/results.md, docs/results.json, docs/img/*.png
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np

from ..counting.systems import CARDS_PER_DECK, load_systems
from ..models import VALUE_RANKS, Rules
from .players import ExactPlayer, JevPlayer, StrategyPlayer
from .simulator import SimulationResult, simulate

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS = PROJECT_ROOT / "docs"

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


def _run_chunk(args) -> dict:
    key, mode, rounds, seed = args
    rules = rules_for(mode)
    res = simulate(make_player(key, rules), rules, rounds, seed, mode)
    return {"nets": res.nets, "bets": res.bets, "wagered": res.wagered, "shuffles": res.shuffles}


def run_variant(key: str, mode: str, rounds: int, seed: int, jobs: int = 1,
                chunk: int = 50_000) -> SimulationResult:
    """Simuliert eine Variante; grosse Läufe werden in Blöcke mit eigenem Seed aufgeteilt."""
    if rounds <= chunk or jobs <= 1:
        rules = rules_for(mode)
        res = simulate(make_player(key, rules), rules, rounds, seed, mode)
        res.name = player_label(key)
        return res
    tasks = []
    left, i = rounds, 0
    while left > 0:
        n = min(chunk, left)
        tasks.append((key, mode, n, seed * 1000 + i))
        left -= n
        i += 1
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        parts = list(pool.map(_run_chunk, tasks))
    return SimulationResult(
        player_label(key), mode,
        np.concatenate([p["bets"] for p in parts]),
        np.concatenate([p["nets"] for p in parts]),
        np.concatenate([p["wagered"] for p in parts]),
        sum(p["shuffles"] for p in parts),
    )


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


def plot_ev_ci(rows: list[tuple[str, dict[str, SimulationResult]]], path: Path, title: str,
               modes: list[str]) -> None:
    """Gewinn pro Runde mit 95-%-Vertrauensintervall, je Variante (Zeilen) und Modus (Farbe)."""
    colors = {"shoe": BLUE, "every_round": ORANGE}
    fig, ax = _figure(10, 0.45 * len(rows) + 1.6)
    _style(ax, title)
    ys = np.arange(len(rows))[::-1]
    offsets = {m: (0.12 if i == 0 else -0.12) if len(modes) > 1 else 0 for i, m in enumerate(modes)}
    for mode in modes:
        for y, (label, by_mode) in zip(ys, rows):
            res = by_mode.get(mode)
            if res is None:
                continue
            ax.errorbar(res.ev_per_round * 100, y + offsets[mode], xerr=res.ci95 * 100, fmt="o",
                        color=colors[mode], markersize=6, elinewidth=2, capsize=0)
        ax.plot([], [], "o", color=colors[mode], label=MODES[mode])
    ax.axvline(0, color=MUTED, linewidth=1)
    ax.set_yticks(ys)
    ax.set_yticklabels([r[0] for r in rows], color=TEXT, fontsize=9)
    ax.set_xlabel("Gewinn pro Runde in % einer Einheit (Punkt = Mittelwert, Strich = 95-%-Intervall)",
                  color=MUTED, fontsize=9)
    if len(modes) > 1:
        ax.legend(frameon=False, fontsize=9, loc="lower right", labelcolor=TEXT)
    fig.tight_layout()
    fig.savefig(path, dpi=130)


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
# Bericht
# ----------------------------------------------------------------------


def pct(x: float, digits: int = 2) -> str:
    return f"{x * 100:+.{digits}f} %"


def write_report(summary: dict, path: Path) -> None:
    s = summary
    lines = [
        "# Ergebnisse der Auswertung (Phase 6)",
        "",
        f"Erzeugt mit `python -m blackjack_assistant simulate` am {s['created']} "
        f"(Seed {s['seed']}, Laufzeit {s['runtime_s']:.0f} s). Alle Beträge in **Einheiten** "
        "(1 Einheit = Mindesteinsatz).",
        "",
        "**Regeln:** 6 Decks, Dealer steht auf Soft 17, Blackjack 3:2, Double auf zwei Karten "
        "(auch nach Split), Split bis 4 Hände, Late Surrender, Dealer-Peek, Versicherung.",
        "**Einsatz der zählenden Spieler:** 1 Einheit bis TC +1, ab +2: 2, ab +3: 4, ab +4: 6, ab +5: 8 "
        "(Spread 1–8). Basic Strategy setzt immer 1 Einheit.",
        "",
        "## Kurzfassung",
        "",
    ]
    lines += [f"- {t}" for t in s["findings"]]
    lines += ["", "## 1. Die geforderten 10'000 Hände", ""]
    lines += [
        "| Variante | Modus | Gewinn gesamt | pro Runde | ± 95 % | Vorteil pro Einsatz | "
        "Streuung pro Runde | Ø Einsatz | max. Rückgang |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in s["runs_10k"]:
        lines.append(
            f"| {r['name']} | {MODES[r['mode']]} | {r['net']:+.1f} | {pct(r['ev_per_round'])} | "
            f"{r['ci95'] * 100:.2f} % | {pct(r['ev_per_unit_bet'])} | {r['sd_per_round']:.2f} | "
            f"{r['mean_bet']:.2f} | {r['max_drawdown']:.0f} |")
    if s.get("jev_note"):
        lines += ["", f"**Jev:** {s['jev_note']}"]
    lines += [
        "",
        "![Guthabenverlauf](img/bankroll_10k.png)",
        "",
        "![Gewinn pro Runde mit Vertrauensintervall](img/gewinn_pro_runde_10k.png)",
        "",
        "![Verteilung der Rundenergebnisse](img/ergebnisse_verteilung.png)",
        "",
        "![Streuung pro Runde](img/streuung.png)",
        "",
        f"**Wichtig zur Einordnung:** Bei 10'000 Runden ist das 95-%-Vertrauensintervall des Gewinns "
        f"pro Runde ±{min(r['ci95'] for r in s['runs_10k']) * 100:.1f} bis "
        f"±{max(r['ci95'] for r in s['runs_10k']) * 100:.1f} % einer Einheit breit – grösser als der "
        "Unterschied zwischen den Zählsystemen und ungefähr so gross wie der Vorteil, den Zählen "
        "überhaupt bringt. Ein einzelner Lauf mit 10'000 Händen kann deshalb nicht zuverlässig "
        "zeigen, welche Strategie besser ist; Glück überwiegt. Darum zusätzlich der Langlauf unten.",
        "",
    ]
    if s.get("runs_big"):
        n = s["runs_big"][0]["rounds"]
        lines += [f"## 2. Langlauf mit {n:,} Runden pro Variante (75 % Penetration)".replace(",", "'"), ""]
        lines += [
            "| Variante | Gewinn pro Runde | ± 95 % | Vorteil pro Einsatz | Ø Einsatz | "
            "Anteil am Maximum |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for r in s["runs_big"]:
            share = r.get("share_of_max")
            share_txt = "–" if share is None else f"{share * 100:.0f} %"
            lines.append(f"| {r['name']} | {pct(r['ev_per_round'], 3)} | {r['ci95'] * 100:.2f} % | "
                         f"{pct(r['ev_per_unit_bet'])} | {r['mean_bet']:.2f} | {share_txt} |")
        lines += [
            "",
            "*Anteil am Maximum* = (Gewinn pro Runde des Systems − Basic Strategy) / "
            "(Exakt − Basic Strategy). Die exakte Strategie ist das theoretische Maximum für "
            "Spielzüge, die nur die gesehenen Karten kennen.",
            "",
            "![Langlauf](img/langlauf.png)",
            "",
            "![Anteil am Maximum](img/anteil_maximum.png)",
            "",
        ]
    lines += ["## 3. Zählsysteme ohne Zufall: Betting Correlation", ""]
    lines += [
        "Die *Betting Correlation* misst, wie gut die Kartenwerte eines Systems die tatsächliche "
        "Wirkung jeder Karte auf den Spielervorteil abbilden (Effects of Removal, exakt berechnet). "
        "1.00 wäre perfekt. Sie hängt nicht vom Glück ab.",
        "",
        "| System | Betting Correlation | mit Ass-Korrektur |",
        "|---|---:|---:|",
    ]
    for key, entry in s["betting_correlation"].items():
        adj = entry.get("bc_ace_adjusted")
        lines.append(f"| {load_systems()[key].name} | {entry['bc']:.3f} | "
                     f"{'–' if adj is None else f'{adj:.3f}'} |")
    lines += [
        "",
        "![Betting Correlation](img/betting_correlation.png)",
        "",
        "Effects of Removal (Änderung des Spielervorteils in %, wenn eine Karte entfernt wird): "
        + ", ".join(f"{r}: {v * 100:+.3f}" for r, v in s["eor"].items())
        + f". Theoretischer Erwartungswert der Basic Strategy mit vollem Schuh: "
        f"{pct(s['base_ev'], 3)} pro Einheit.",
        "",
        "## 4. Tiefer Schuh gegen Mischen nach jeder Runde",
        "",
    ]
    lines += [f"- {t}" for t in s["shoe_vs_every"]]
    lines += [
        "",
        "## Methode",
        "",
        "- Simulator mit denselben Regeln wie das Mock-Casino; der Spieler sieht jede offene Karte "
        "(Hole Card wird am Rundenende aufgedeckt).",
        "- Gleicher Seed für alle Varianten: Jeder Schuh wird gleich gemischt. Weil die Spieler "
        "verschieden spielen, laufen die Kartenfolgen danach trotzdem auseinander.",
        "- Zählsysteme: Running Count → True Count (Restdecks auf halbe Decks gerundet), "
        "Illustrious 18 + Fab 4 (für andere Systeme umgerechnet), Einsatzstaffelung wie oben. "
        "KO mit festen Schwellen.",
        "- Exakt: Jede Entscheidung aus der genauen Restzusammensetzung (alle gesehenen Karten "
        "entfernt). Einsatz nach dem linear geschätzten Vorteil, umgerechnet in einen "
        "Hi-Lo-äquivalenten True Count (0,5 % Vorteil ≈ 1 TC) und dieselbe Staffelung.",
        "- Bei „Mischen nach jeder Runde“ wissen die Zähler, dass das Zählen wirkungslos ist, und "
        "spielen Basic Strategy mit 1 Einheit.",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simulate", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hands", type=int, default=10_000, help="Runden pro Variante")
    parser.add_argument("--big", type=int, default=500_000,
                        help="Runden im Langlauf (75 %%), 0 = kein Langlauf")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--jobs", type=int, default=4, help="Prozesse für den Langlauf")
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
    (out / "img").mkdir(parents=True, exist_ok=True)
    keys = ["basic", *SYSTEMS, "exact"]

    # 1) 10'000 Hände, beide Modi
    results: dict[tuple[str, str], SimulationResult] = {}
    for mode in MODES:
        for key in keys:
            results[(key, mode)] = run_variant(key, mode, args.hands, args.seed)
            print(f"{MODES[mode]:28s} {player_label(key):32s} "
                  f"{results[(key, mode)].ev_per_round:+.4f} pro Runde")

    jev_note = None
    probe = JevPlayer(Rules())
    if probe.available:
        for mode in MODES:
            results[("jev", mode)] = run_variant("jev", mode, args.hands, args.seed)
        jev_note = f"mit der Jev-API gespielt ({probe.jev.requests} Anfragen)."
    else:
        jev_note = ("nicht simuliert – kein API-Key vorhanden (" + probe.jev.status + "). "
                    "Mit Key: `python -m blackjack_assistant simulate` erneut ausführen; "
                    "die Variante „Jev + Hi-Lo“ erscheint dann automatisch.")

    # 2) Langlauf
    big: dict[str, SimulationResult] = {}
    if args.big:
        for key in keys:
            big[key] = run_variant(key, "shoe", args.big, args.seed + 1, jobs=args.jobs)
            print(f"Langlauf {player_label(key):32s} {big[key].ev_per_round:+.4f} ± "
                  f"{big[key].ci95:.4f}")

    # 3) Ohne Zufall: EOR und Betting Correlation
    from .exact import ExactCalculator, full_shoe

    calc = ExactCalculator(Rules())
    eor = calc.effects_of_removal()
    base_ev = calc.predeal_ev(full_shoe(6))
    bc = betting_correlations(eor)

    # Grafiken
    img = out / "img"
    plot_bankroll(results, img / "bankroll_10k.png")
    rows = [(player_label(k), {m: results[(k, m)] for m in MODES if (k, m) in results})
            for k in keys + (["jev"] if ("jev", "shoe") in results else [])]
    plot_ev_ci(rows, img / "gewinn_pro_runde_10k.png",
               "Gewinn pro Runde nach 10'000 Runden – mit Zufallsspielraum", list(MODES))
    plot_outcomes(results, img / "ergebnisse_verteilung.png")
    labels = [player_label(k) for k in keys]
    plot_hbar(labels, [results[(k, "shoe")].sd_per_round for k in keys], img / "streuung.png",
              "Streuung (Standardabweichung) des Ergebnisses pro Runde – 75 % Penetration",
              "Standardabweichung in Einheiten (höher = grössere Schwankungen)")
    plot_hbar([load_systems()[k].name for k in bc],
              [v.get("bc_ace_adjusted", v["bc"]) for v in bc.values()],
              img / "betting_correlation.png",
              "Betting Correlation der Zählsysteme (mit Ass-Korrektur, falls vorhanden)",
              "Korrelation mit den exakten Effects of Removal (1 = perfekt)", "{:.3f}")

    big_rows = []
    shares: dict[str, float] = {}
    if big:
        rows_big = [(player_label(k), {"shoe": big[k]}) for k in keys]
        plot_ev_ci(rows_big, img / "langlauf.png",
                   f"Gewinn pro Runde im Langlauf ({args.big:,} Runden pro Variante)".replace(",", "'"),
                   ["shoe"])
        gain_max = big["exact"].ev_per_round - big["basic"].ev_per_round
        for k in keys:
            entry = big[k].summary()
            if k not in ("basic", "exact") and gain_max > 0:
                shares[k] = (big[k].ev_per_round - big["basic"].ev_per_round) / gain_max
                entry["share_of_max"] = round(shares[k], 4)
            big_rows.append(entry)
        if shares:
            plot_hbar([player_label(k) for k in shares], [v * 100 for v in shares.values()],
                      img / "anteil_maximum.png",
                      "Anteil am maximal möglichen Zusatzgewinn (Exakt = 100 %)",
                      "% des Zusatzgewinns der exakten Strategie gegenüber Basic Strategy",
                      "{:.0f} %")

    # Kernaussagen
    def r10(k, m="shoe"):
        return results[(k, m)]

    findings = [
        f"Basic Strategy ohne Zählen verliert langfristig: theoretisch {pct(base_ev, 2)} pro "
        "Einheit (exakt berechnet)" + (f", im Langlauf {pct(big['basic'].ev_per_round)} "
                                       f"± {big['basic'].ci95 * 100:.2f} % pro Runde." if big else "."),
    ]
    if big and shares:
        best = max(SYSTEMS, key=lambda k: big[k].ev_per_round)
        findings += [
            f"Mit Hi-Lo, Abweichungen und Spread 1–8 dreht der Vorteil ins Plus: "
            f"{pct(big['hi_lo'].ev_per_round)} pro Runde (± {big['hi_lo'].ci95 * 100:.2f} %), "
            f"{pct(big['hi_lo'].ev_per_unit_bet)} pro eingesetzter Einheit.",
            f"Die exakte Strategie (theoretisches Maximum) erreicht {pct(big['exact'].ev_per_round)} "
            f"pro Runde ({pct(big['exact'].ev_per_unit_bet)} pro eingesetzter Einheit). Die "
            f"Zählsysteme holen davon {min(shares.values()) * 100:.0f}–{max(shares.values()) * 100:.0f} % "
            f"des möglichen Zusatzgewinns; am meisten {player_label(best)} "
            f"({pct(big[best].ev_per_round)}). Die Unterschiede zwischen den Systemen liegen "
            "innerhalb des Zufallsspielraums.",
        ]
    findings += [
        f"In den geforderten 10'000 Händen ist das Ergebnis vom Zufall geprägt: Hi-Lo "
        f"{r10('hi_lo').net:+.0f} Einheiten, Basic {r10('basic').net:+.0f}, Exakt "
        f"{r10('exact').net:+.0f} (95-%-Spielraum pro Runde ca. ± "
        f"{r10('hi_lo').ci95 * 100:.1f} %).",
        f"Zählen erhöht die Schwankungen deutlich: Streuung pro Runde {r10('hi_lo').sd_per_round:.2f} "
        f"Einheiten statt {r10('basic').sd_per_round:.2f} (Basic), weil bei hohem Count mehr gesetzt "
        "wird.",
        "Wenn nach jeder Runde gemischt wird, bringt Zählen nichts: Alle Zählsysteme spielen "
        "dann Basic Strategy mit 1 Einheit; auch die exakte Strategie kann nur noch die Karten "
        "der laufenden Runde nutzen.",
    ]
    rounds_per_shoe = r10("basic").rounds / max(1, r10("basic").shuffles)
    shoe_vs_every = [
        f"Tiefer Schuh (75 %): im Schnitt {rounds_per_shoe:.1f} Runden pro Schuh, der Count "
        "kann sich aufbauen, Einsatz und Spielzüge passen sich an.",
        f"Mischen nach jeder Runde: {r10('basic', 'every_round').rounds} Mischvorgänge in "
        f"{r10('basic', 'every_round').rounds} Runden. Hi-Lo setzt dann immer 1 Einheit "
        f"(Ø Einsatz {r10('hi_lo', 'every_round').mean_bet:.2f}) und hat denselben Nachteil wie "
        "Basic Strategy.",
        "Viele Online-Casinos (auch im Demo-Modus) mischen nach jeder Runde oder nutzen einen "
        "Zufallsgenerator pro Karte – genau dieser Fall. Das Overlay warnt dann mit "
        "„Zählen hier wirkungslos“.",
    ]

    summary = {
        "created": time.strftime("%Y-%m-%d %H:%M"),
        "seed": args.seed,
        "runtime_s": time.time() - t0,
        "runs_10k": [results[(k, m)].summary() for m in MODES for k in keys]
                    + ([results[("jev", m)].summary() for m in MODES] if ("jev", "shoe") in results else []),
        "runs_big": big_rows,
        "eor": {r: round(v, 6) for r, v in eor.items()},
        "base_ev": base_ev,
        "betting_correlation": {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in bc.items()},
        "jev_note": jev_note,
        "findings": findings,
        "shoe_vs_every": shoe_vs_every,
    }
    (out / "results.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=float)
                                      + "\n", encoding="utf-8")
    write_report(summary, out / "results.md")
    print(f"Bericht: {out / 'results.md'}  ({time.time() - t0:.0f} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
