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
| Zählen | Hi-Lo, Running Count, verbleibende Decks, True Count, Misch-Erkennung |
| Strategie | Basic Strategy (Tabellen), Illustrious 18, Einsatzstaffelung |
| Overlay | tkinter-Fenster, immer im Vordergrund, Hotkeys |
| Jev (optional) | Entscheidung über die TypeSafe-Jev-API, Fallback auf lokale Strategie |
| Simulation | 10'000 Hände ohne Bildschirm, Vergleich der Strategien, Grafiken, Markdown-Bericht |

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
├── mock_casino/               PHASE 1 – lokale Blackjack-Webseite
│   ├── server.py              http.server + Endpunkt für das Ground-Truth-Log
│   ├── index.html
│   ├── css/style.css
│   ├── js/
│   │   ├── shoe.js            Schuh, Mischen, Penetration
│   │   ├── rules.js           Handwerte, Dealer-Logik, Auszahlungen
│   │   ├── game.js            Spielablauf (Deal, Hit, Stand, Double, Split, Surrender)
│   │   ├── cards.js           SVG-Kartenerzeugung
│   │   └── ui.js              Tisch, Verlaufs-Panel, Mischanzeige, Debug-Schalter
│   └── assets/cards/          Karten-SVGs
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
│   │   └── hilo.py            Running Count, True Count, Decks, Misch-Statistik
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
│       ├── players.py         Spielertypen (Basic, Hi-Lo, Jev)
│       └── report.py          Grafiken + Markdown-Zusammenfassung
│
├── profiles/                  Ein Ordner pro Spiel
│   └── mock_casino/
│       ├── profile.json       Bereiche, Lesemodus, Regeln, Decks, Konfidenz
│       └── templates/         Rang-Templates (PNG)
│
├── tools/
│   ├── generate_templates.py  Templates aus den Mock-Casino-SVGs erzeugen
│   └── measure_accuracy.py    Erkennung vs. Ground Truth → Genauigkeit in %
│
├── tests/                     pytest Unit Tests
├── logs/                      Laufzeit-Logs (nicht im Git)
└── docs/
    └── results.md             Ergebnisse der Auswertung (Phase 6)
```

---

## Installation (Entwurf, wird pro Phase ergänzt)

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux/macOS:  source .venv/bin/activate
pip install -r requirements.txt
pytest
```

Mock-Casino starten (ab Phase 1):

```bash
python mock_casino/server.py            # http://localhost:8000
python mock_casino/server.py --debug    # zusätzlich Ground-Truth-Log in logs/
```

## Konfiguration und Geheimnisse

- Der Jev-API-Key wird **nur** aus der Umgebungsvariable `JEV_API_KEY` gelesen
  (optional über eine lokale `.env`-Datei).
- `.env` steht in `.gitignore` und wird nie committet. `.env.example` dient als Vorlage.
- Ohne Key läuft alles offline mit der lokalen Strategie.
