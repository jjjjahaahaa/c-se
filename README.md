# Blackjack-Assistent (Schulprojekt Applikationsentwicklung)

Ein lokal laufender Assistent, der per Bildschirmaufnahme Blackjack-Karten erkennt,
nach dem **Hi-Lo-System** zählt und Spielzüge sowie Einsätze empfiehlt.
Er funktioniert mit einem eigenen **Mock-Casino** (Entwicklungs- und Testumgebung)
und mit dem **Demo-Modus (Spielgeld)** von Online-Casinos.

> **Hinweis zum Einsatzzweck**
> Das Projekt ist ein Lern- und Analyseprojekt. Es ist ausschliesslich für das eigene
> Mock-Casino und für Demo-Modi **ohne Echtgeld** gedacht. Die meisten Online-Casinos
> verbieten Hilfsprogramme in ihren AGB, und viele Online-Spiele mischen nach jeder
> Runde – genau das soll die Auswertung (Phase 6) messbar zeigen.

---

## Funktionsübersicht

| Bereich | Inhalt |
|---|---|
| Mock-Casino | Blackjack im Browser (HTML/JS), 6 Decks, 75 % Penetration, S17, 3:2, Double, Split, Late Surrender, Verlaufs-Panel, Debug-Log (Ground Truth) |
| Erkennung | Bildschirmaufnahme (mss), Template Matching auf der Kartenecke (OpenCV), Tisch-Modus und Verlaufs-Modus, Kalibrierung für fremde Spiele, Profile |
| Zählen | Hi-Lo, KO, Hi-Opt II, Omega II, Zen, Wong Halves (konfigurierbar), Running Count, verbleibende Decks, True Count, Misch-Erkennung |
| Strategie | Basic Strategy (Tabellen), Illustrious 18, Einsatzstaffelung |
| Overlay | tkinter-Fenster, immer im Vordergrund, Hotkeys |
| Jev (optional) | Entscheidung über die TypeSafe-Jev-API, Fallback auf lokale Strategie |
| Simulation | 10'000 Hände ohne Bildschirm, Vergleich der Strategien und Zählsysteme gegen eine exakte Strategie, Grafiken, Markdown-Bericht |

---

## Architektur

Die Anwendung ist als **Pipeline** aufgebaut. Jedes Modul hat genau eine Aufgabe und
kennt nur die Schnittstelle des nächsten Moduls. Dadurch lassen sich Teile einzeln
testen (z. B. Zählung und Strategie komplett ohne Bildschirm).

```
 ┌──────────────┐   Frames    ┌───────────────┐   Karten-     ┌──────────────┐
 │   capture    │ ──────────▶ │  recognition  │ ───────────▶  │   counting   │
 │ mss, Bereich │  (stabil    │ Template-     │  ereignisse   │ Hi-Lo, RC,   │
 │ Stabilität   │   300 ms)   │ Matching,     │  (neue Karte, │ TC, Decks,   │
 └──────────────┘             │ Tisch-/Ver-   │  Runde fertig,│ Mischen      │
                              │ laufs-Modus   │  gemischt)    └──────┬───────┘
                              └───────┬───────┘                      │ Zählstand
                                      │ Handzustand                  ▼
                                      │ (Spieler, Dealer)     ┌──────────────┐
                                      └─────────────────────▶ │   strategy   │
                                                              │ Basic, I18,  │
                                                              │ Einsatz, Jev │
                                                              └──────┬───────┘
                                                                     │ Empfehlung
                                                                     ▼
                                                              ┌──────────────┐
                                                              │   overlay    │
                                                              │ tkinter,     │
                                                              │ Hotkeys      │
                                                              └──────────────┘

 simulation: nutzt counting + strategy direkt mit einem virtuellen Schuh (ohne Bildschirm)
 mock_casino: eigenständige Webseite, liefert Ground Truth für die Genauigkeitsmessung
```

### Zentrale Datenobjekte

| Objekt | Beschreibung |
|---|---|
| `Card` | Rang (`2`–`10`, `J`, `Q`, `K`, `A`), optional Position und Konfidenz |
| `CardEvent` | Ereignis aus der Erkennung: `NEW_CARD`, `ROUND_END`, `SHUFFLE`, `UNCERTAIN` |
| `CountState` | Running Count, gesehene Karten, verbleibende Decks, True Count |
| `HandState` | Spielerkarten, Dealer-Upcard, erlaubte Aktionen |
| `Decision` | Empfohlene Aktion, Quelle (Basic / Deviation / Jev), optional Wahrscheinlichkeiten |
| `Profile` | Einstellungen pro Spiel: Bildschirmbereiche, Lesemodus, Templates, Regeln, Deckanzahl |

### Entscheidungs-Engine austauschbar

`strategy` definiert eine gemeinsame Schnittstelle `DecisionEngine.decide(hand, count) -> Decision`.
Es gibt zwei Implementierungen:

- `StrategyEngine` – Basic Strategy + Illustrious 18 (läuft immer offline)
- `JevEngine` – fragt die Jev-API ab; ohne API-Key oder bei Fehlern automatischer
  Rückfall auf `StrategyEngine`

---

## Ordnerstruktur (Zielzustand)

```
c-se/
├── README.md                  Dieses Dokument
├── PLAN.md                    Phasenplan mit Aufgaben und Abnahmekriterien
├── requirements.txt           Python-Abhängigkeiten
├── pyproject.toml             Projekt- und pytest-Konfiguration
├── .gitignore                 u. a. .env, venv, logs
├── .env.example               Vorlage für JEV_API_KEY (ohne echten Key)
│
├── config/
│   └── counting_systems.toml  Kartenwerte und Indizes aller Zählsysteme
│
├── mock_casino/               PHASE 1 – lokale Blackjack-Webseite
│   ├── server.py              http.server + Endpunkt für das Ground-Truth-Log
│   ├── index.html
│   ├── css/style.css
│   ├── js/
│   │   ├── shoe.js            Schuh, Mischen, Penetration
│   │   ├── rules.js           Handwerte, Dealer-Logik, Auszahlungen
│   │   ├── game.js            Spielablauf (Deal, Hit, Stand, Double, Split, Surrender)
│   │   ├── cards.js           Zuordnung Karte → SVG, Verlaufs-Kacheln
│   │   ├── logger.js          Ereignisse an den Server senden (Ground Truth)
│   │   └── ui.js              Tisch, Verlaufs-Panel, Mischanzeige, Tastatur
│   └── assets/cards/          Karten-SVGs (erzeugt von tools/generate_card_svgs.py)
│
├── blackjack_assistant/       Python-Paket
│   ├── __main__.py            Startpunkt: python -m blackjack_assistant
│   ├── models.py              Card, CardEvent, HandState, Decision …
│   ├── profiles.py            Profile laden/speichern/umschalten
│   ├── capture/               PHASE 2 – Bildschirmaufnahme
│   │   ├── screen.py          mss-Aufnahme eines Bereichs
│   │   ├── region_select.py   Bereich per Maus aufziehen
│   │   └── stability.py       "Bild 300 ms unverändert"-Prüfung
│   ├── recognition/           PHASE 2 – Kartenerkennung
│   │   ├── matcher.py         Template Matching auf der Kartenecke
│   │   ├── templates.py       Templates laden, aus SVG erzeugen
│   │   ├── table_mode.py      Tisch-Modus: Positions-Tracking, Rundenende
│   │   ├── history_mode.py    Verlaufs-Modus: Listenvergleich, Panel leer = Mischen
│   │   ├── calibration.py     Kalibrierung für externe Spiele
│   │   └── recognition_log.py Log mit Mini-Screenshot pro Karte
│   ├── counting/              PHASE 3
│   │   ├── systems.py         Zählsysteme aus der Konfiguration laden
│   │   └── counter.py         Running/True Count, Ass-Nebenzähler, Decks, Misch-Statistik
│   ├── strategy/              PHASE 3 + 5
│   │   ├── engine.py          Schnittstelle DecisionEngine
│   │   ├── basic.py           Basic-Strategy-Tabellen
│   │   ├── deviations.py      Illustrious 18
│   │   ├── betting.py         Einsatzstaffelung
│   │   └── jev.py             Jev-Anbindung (optional)
│   ├── overlay/               PHASE 4
│   │   ├── window.py          tkinter-Fenster
│   │   └── hotkeys.py         Pause, Reset, Profilwechsel
│   └── simulation/            PHASE 6
│       ├── simulator.py       Blackjack-Simulation mit Seed
│       ├── players.py         Spielertypen (Basic, Zählsysteme, Jev, exakt)
│       ├── exact.py           Composition-dependent Erwartungswerte
│       └── report.py          Grafiken + Markdown-Zusammenfassung
│
├── profiles/                  Ein Ordner pro Spiel
│   └── mock_casino/
│       ├── profile.json       Bereiche, Lesemodus, Regeln, Decks, Konfidenz
│       └── templates/         Rang-Templates (PNG)
│
├── tools/
│   ├── generate_card_svgs.py  Karten-SVGs für das Mock-Casino erzeugen
│   ├── generate_templates.py  Templates aus den Mock-Casino-SVGs erzeugen
│   └── measure_accuracy.py    Erkennung vs. Ground Truth → Genauigkeit in %
│
├── tests/                     pytest Unit Tests
├── logs/                      Laufzeit-Logs (nicht im Git)
└── docs/
    └── results.md             Ergebnisse der Auswertung (Phase 6)
```

---

## Installation

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux/macOS:  source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium   # für Browser-Tests und Headless-Erkennungstests
pytest
```

Ohne Playwright werden die Browser-Tests übersprungen, alle anderen Tests laufen trotzdem.

## Mock-Casino (Phase 1)

```bash
python mock_casino/server.py            # http://localhost:8000
python mock_casino/server.py --debug    # zusätzlich Ground-Truth-Log in logs/
```

| Option | Bedeutung |
|---|---|
| `--debug` | Jede aufgedeckte Karte wird nach `logs/ground_truth_<Datum>_<Zeit>.jsonl` geschrieben |
| `--log-file PFAD` | Eigener Pfad für das Ground-Truth-Log |
| `--seed N` | Reproduzierbares Mischen (gleicher Seed = gleiche Kartenfolge) |
| `--decks N`, `--penetration X` | Standard: 6 Decks, 0.75 |
| `--shuffle-every-round` | Nach jeder Runde neu mischen (wie viele Online-Spiele) |
| `--port N` | Standard: 8000 |

URL-Parameter überschreiben die Einstellungen im Browser, z. B.
`http://localhost:8000/?seed=42&speed=0&clear=1000&every=1`
(`speed`: Animationstempo 0 / 0.5 / 1 / 2, `clear`: ms bis der Tisch geräumt wird).

**Regeln:** 6 Decks, Schnittkarte bei 75 %, Dealer steht auf Soft 17, Blackjack 3:2,
Double auf zwei beliebige Karten (auch nach Split), Split bis 4 Hände (gesplittete Asse
erhalten genau eine Karte), Late Surrender, Dealer-Peek bei Ass/Zehn, Versicherung 2:1.

**Tastatur:** Enter = Austeilen, H = Ziehen, S = Stehen, D = Verdoppeln, P = Teilen,
R = Aufgeben, Y/N = Versicherung.

**Ablauf einer Runde (wichtig für die Erkennung):**
1. Karten werden einzeln mit Animation ausgeteilt (Hole Card verdeckt).
2. Nach der Abrechnung bleiben die Karten 2.5 s liegen, dann wird der Tisch geräumt
   → leerer Tisch = Rundenende (Tisch-Modus).
3. Ist die Schnittkarte erreicht, wird danach gemischt: Das Verlaufs-Panel wird leer
   → leeres Panel = Neu-Mischen (Verlaufs-Modus).

**Ground-Truth-Format** (eine JSON-Zeile pro Ereignis):

```json
{"server_time": "2026-10-07T14:25:01.123", "type": "card", "rank": "K", "suit": "H",
 "target": "dealer", "hand": 0, "hole": true, "round": 12, "shoe": 2, "seq": 47}
```

Weitere Typen: `session_start`, `round_start`, `round_end` (mit Ergebnis), `shuffle`
(mit Grund `cut_card` / `every_round` / `manual` und Anzahl Runden seit dem letzten Mischen).
`seq` ist die Position der Karte im Verlaufs-Panel.

Die Karten-SVGs werden mit `python tools/generate_card_svgs.py` erzeugt. Ränge sind
Pfade statt Text, damit die Darstellung nicht von installierten Schriften abhängt.

## Kartenerkennung (Phase 2)

```bash
python -m blackjack_assistant profiles                                   # Profile anzeigen
python -m blackjack_assistant select-region --profile mock_casino --region table
python -m blackjack_assistant select-region --profile mock_casino --region history
python -m blackjack_assistant scale --profile mock_casino                 # Zoom/DPI ausmessen
python -m blackjack_assistant calibrate --profile mein_spiel             # externes Spiel
python -m blackjack_assistant replay --profile mock_casino --frames <Ordner>   # offline
python tools/measure_accuracy.py                                         # Genauigkeit in %
```

**Ohne Bildschirm testen:** `python tools/record_mock_session.py --rounds 30` startet das
Mock-Casino im Headless-Browser, lässt es mit echten Animationen spielen, schickt laufend
Screenshots durch die Erkennung (Tisch- und Verlaufs-Modus gleichzeitig) und vergleicht mit
der Ground Truth. Optionen: `--hide-hole`, `--every` (mischen jede Runde), `--pause 0`,
`--save-frames <Ordner>` (Screenshots für `replay` speichern).

**Ablauf der Erkennung**

1. Bildschirm aufnehmen (mss), Tisch- und Verlaufsbereich ausschneiden.
2. Warten, bis der Bereich 300 ms unverändert ist (Animationen).
3. Helle Kartenflächen suchen und darin das Rangzeichen per Template Matching finden.
   Gedrehte Ecken (unten rechts) werden aussortiert.
4. Tisch-Modus: Karten nach Position verfolgen, jede nur einmal zählen, leerer Tisch =
   Rundenende. Verlaufs-Modus: Liste mit der vorherigen vergleichen, leeres Panel = Mischen.
5. Unsichere Treffer werden nicht gezählt, sondern gemeldet (Overlay gelb). Nicht gezeigte
   Karten (z. B. Hole Card) gelten als „ungesehen“: kein Einfluss auf den Count, aber auf die
   Restdecks.

**Profil** (`profiles/<name>/profile.json`): `read_mode` (`table`/`history`), `regions`
(Bildschirmpixel), `areas` (Dealer-/Spielerbereich als Anteile des Tisches), `recognition`
(Mindest-Konfidenz, Skalierung, Stabilitätszeit …), `rules`, `counting`, `betting`.
Templates liegen in `profiles/<name>/templates/<Rang>_<n>.png`.

## Zählen und Strategie (Phase 3)

```bash
python -m blackjack_assistant systems      # Zählsysteme mit ihren Kartenwerten
```

| Datei | Inhalt |
|---|---|
| `config/counting_systems.toml` | Kartenwerte aller Zählsysteme (Hi-Lo, KO, Hi-Opt II, Omega II, Zen, Wong Halves), Typ, KO-Schwellen, Ass-Nebenzähler |
| `config/basic_strategy.toml` | Basic Strategy für 6 Decks, S17, DAS, Late Surrender (hart, soft, Paare) + H17-Anpassungen |
| `config/deviations.toml` | Illustrious 18 und Fab 4 (Hi-Lo-Indizes), optional eigene Indizes pro System |

Im Profil (`counting`, `betting`):

```json
"counting": {"system": "zen", "deck_rounding": 0.5},
"betting":  {"unit": 10, "ramp": [[2, 2], [3, 4], [4, 6], [5, 8]]}
```

- **Running Count** = Summe der Kartenwerte, **Restdecks** = Decks − (gesehene + ungesehene
  Karten) / 52, auf halbe Decks gerundet, **True Count** = Running Count / Restdecks.
- **KO** (unausgeglichen) startet bei IRC = 4 − 4 × Decks und arbeitet mit festen Schwellen
  auf dem Running Count (Key Count, Pivot, Versicherung ab +3).
- **Hi-Opt II, Omega II**: Asse werden separat gezählt; für den Einsatz wird der Count um
  2 Punkte pro überzähligem Ass korrigiert.
- **Mischen** setzt den Count zurück. Option „mischt jede Runde“ (`rules.shuffle_every_round`):
  Count nach jeder Runde auf 0, Hinweis „Zählen hier wirkungslos“.
- **Mischstatistik**: `logs/shuffle_stats.jsonl` (Runden und Penetration pro Schuh).
- **Strategie**: Basic Strategy aus der Tabelle, angepasst an die Profilregeln (H17, kein DAS,
  kein Surrender, Verdoppeln/Teilen nicht möglich). Abweichungen nach True Count; für andere
  Systeme werden die Hi-Lo-Indizes umgerechnet (Faktor = Regression der Kartenwerte auf Hi-Lo).
- **Einsatz**: 1 Einheit bis TC +1, danach laut Staffelung.

## Overlay (Phase 4)

```bash
python -m blackjack_assistant run --profile mock_casino          # mit Overlay
python -m blackjack_assistant run --profile mock_casino --no-overlay   # nur Konsole
```

Das Overlay ist ein kleines tkinter-Fenster, immer im Vordergrund und verschiebbar. Es zeigt
Running Count, True Count, verbleibende Decks, empfohlenen Einsatz, empfohlenen Spielzug
(mit Quelle: Basic Strategy / Abweichung / Jev), aktives Profil und Warnungen
(gelb: unsichere Erkennung, Pause; rot: Zählen wirkungslos).

| Taste | Funktion |
|---|---|
| F8 | Pause (nichts zählen) |
| F9 | Count zurücksetzen |
| F10 | Profil wechseln |

Die Hotkeys sind global (pynput), funktionieren also auch, wenn das Casino-Fenster den Fokus
hat. Ohne Berechtigung (macOS) bzw. unter Wayland gelten sie nur im Overlay-Fenster.

**Aufbau:** Ein Worker-Thread nimmt laufend den Bildschirm auf und schickt den neuen Zustand
über eine Queue an das Overlay (tkinter darf nur im Hauptthread verändert werden). Hotkeys
schicken Befehle (Pause, Reset, Profilwechsel) über eine zweite Queue an den Worker.

**Tests ohne echten Bildschirm:** `xvfb-run -a python -m pytest -m display` startet Overlay,
Bereichsauswahl, Kalibrierfenster, Bildschirmaufnahme und Hotkeys auf einem virtuellen
Bildschirm. `tools/screen_demo.py` spielt das Mock-Casino in einem sichtbaren Browser und
prüft den im Overlay angezeigten Count gegen die Ground Truth.

## Jev (Phase 5, optional)

[Jev](https://docs.typesafe.ai) von TypeSafe AI ist ein Entscheidungsmodell: Es bekommt einen
Zustand und eine Auswahlfrage und liefert die gewählte Option mit Wahrscheinlichkeiten.

```bash
cp .env.example .env            # dann TYPESAFE_API_KEY=... eintragen (nie committen!)
python -m blackjack_assistant jev-check                  # eine Testanfrage
python -m blackjack_assistant run --profile mock_casino --engine jev
```

- Request: `POST https://api.typesafe.ai/v1/systemone` mit Zustand (Spielerkarten, Summe,
  soft, Dealer-Karte, True Count, Restdecks, erlaubte Aktionen) und einer Choice-Frage.
  Angeboten werden **nur die gerade erlaubten Aktionen**, Jev kann also nichts Unmögliches wählen.
- Antwort: gewählte Aktion + Wahrscheinlichkeit jeder Aktion (im Overlay angezeigt) + Konfidenz.
- Im Overlay läuft die Anfrage im Hintergrund; bis die Antwort da ist, steht die Empfehlung
  der lokalen Strategie da („Jev rechnet …“). Gleiche Situationen werden nur einmal angefragt.
- Versicherung entscheidet weiterhin die lokale Strategie.

## Konfiguration und Geheimnisse

- Der Jev-API-Key wird **nur** aus der Umgebungsvariable `TYPESAFE_API_KEY` (oder
  `JEV_API_KEY`) gelesen, optional über eine lokale `.env`-Datei.
- `.env` steht in `.gitignore` und wird nie committet. `.env.example` dient als Vorlage.
- Ohne Key, mit ungültigem Key oder ohne Internet wird automatisch die lokale Strategie
  verwendet – alles läuft offline.
