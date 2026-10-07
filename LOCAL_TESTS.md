# Lokale Tests (mit Bildschirm)

Alles, was in der Entwicklungsumgebung ohne Bildschirm nicht geprüft werden konnte.
Jeder Test hat einen Befehl und ein erwartetes Ergebnis. Bitte Ergebnis und Datum eintragen.

**Vorbereitung (einmalig)**

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
python -m playwright install chromium
pytest                            # alles grün, Browser-Tests laufen mit
```

Erwartet: alle Tests grün (siehe Testübersicht in CHANGELOG.md). Unter Windows/macOS
ohne Chromium werden die Browser-Tests übersprungen – das ist in Ordnung.

---

## A. Mock-Casino (Phase 1)

| # | Befehl / Aktion | Erwartetes Ergebnis | OK? |
|---|---|---|---|
| A1 | `python mock_casino/server.py --debug`, Browser auf http://localhost:8000 | Dunkelgrüner Tisch, rotes DEBUG-Badge oben rechts | |
| A2 | Einige Runden spielen (Enter, H, S, D, P, R) | Alle Aktionen funktionieren, Verlaufs-Panel füllt sich, Balken zeigt Fortschritt bis zur Schnittkarte | |
| A3 | Datei `logs/ground_truth_*.jsonl` öffnen | Pro aufgedeckter Karte eine Zeile `"type": "card"` | |
| A4 | Server mit `--hide-hole-card` starten, absichtlich überkaufen | Hole Card bleibt verdeckt, im Log steht `"type": "unseen"`, Panel zeigt sie nicht | |
| A5 | Einstellungen → „Nach jeder Runde neu mischen“ | Nach jeder Runde „Neu gemischt“, Panel leer | |

---

## B. Bildschirmaufnahme und Erkennung (Phase 2)

Browserfenster mit dem Mock-Casino geöffnet lassen, Zoom 100 %.

| # | Befehl / Aktion | Erwartetes Ergebnis | OK? |
|---|---|---|---|
| B1 | `python -m blackjack_assistant select-region --profile mock_casino --region table` | Halbtransparentes Fenster über allen Monitoren; Rechteck um den grünen Tisch ziehen → „Bereich 'table' gespeichert: [x, y, b, h]“ | |
| B2 | Dasselbe mit `--region history` um das Verlaufs-Panel (inkl. Platz nach unten) | Bereich gespeichert | |
| B3 | Esc während der Auswahl | „Abgebrochen.“, Profil unverändert | |
| B4 | Mehrere Monitore / Windows-Skalierung 125 % (falls vorhanden): B1 wiederholen | Gespeicherte Koordinaten passen zum Tisch (siehe B6) | |
| B5 | Einige Karten aufdecken, dann `python -m blackjack_assistant scale --profile mock_casino` | `table: Skalierung ≈1.00` (bei 125 % Windows-Skalierung ≈1.25) und `history: ≈0.95`, Übereinstimmung > 0.9 | |
| B6 | `python -m blackjack_assistant run --profile mock_casino --no-overlay` und 20 Runden spielen, dann Ctrl+C | Konsole zeigt laufend RC/TC/Decks/Einsatz/Zug; nach Ctrl+C Pfad des Erkennungs-Logs | |
| B7 | `python tools/measure_accuracy.py` (nimmt automatisch die neuesten Logs) | Genauigkeit ≥ 99 % (Verlauf) bzw. ≥ 97 % (Tisch, Profil auf `"read_mode": "table"` stellen) | |
| B8 | `logs/recognition/<Zeit>/index.html` im Browser öffnen | Mini-Screenshot jeder erkannten Karte, unsichere gelb | |
| B9 | Browser-Zoom auf 125 % stellen, B5 + B6 wiederholen | Skalierung ≈1.25 erkannt, Karten weiterhin korrekt | |

### Externes Spiel (Demo-Modus, kein Echtgeld)

| # | Befehl / Aktion | Erwartetes Ergebnis | OK? |
|---|---|---|---|
| B10 | Profil kopieren: Ordner `profiles/playtech_blackjack_surrender` als Vorlage nutzen oder direkt verwenden | `python -m blackjack_assistant profiles` listet es (Templates 0) | |
| B11 | `select-region --profile playtech_blackjack_surrender --region table` | Bereich gespeichert | |
| B12 | Dealer-/Spielerbereich prüfen: in `profile.json` unter `areas` die Anteile so setzen, dass Dealerkarten im oberen und Spielerkarten im unteren Teil liegen | – | |
| B13 | Einige Runden spielen, bis viele Ränge sichtbar waren, dann `python -m blackjack_assistant calibrate --profile playtech_blackjack_surrender` | Fenster mit Screenshot; pro Rang Rechteck um das Rangzeichen, Enter. Eingabe von B/D/K oder J/Q/K wird akzeptiert. Fehlende Ränge mit neuem Screenshot nachholen | |
| B14 | `python -m blackjack_assistant profiles` | Templates=13 (keine fehlen) | |
| B15 | `run --profile playtech_blackjack_surrender --no-overlay`, 20 Runden spielen | Karten werden gezählt; Overlay/Konsole meldet „Zählen hier wirkungslos“ (mischt jede Runde) | |
| B16 | `logs/recognition/<Zeit>/index.html` von Hand mit den gespielten Karten vergleichen | Anteil richtig erkannter Karten notieren (Ziel ≥ 97 %) | |

---

## C. Overlay und Hotkeys (Phase 4)

Voraussetzung: Bereiche für `mock_casino` festgelegt (B1, B2), Mock-Casino im Browser offen.

| # | Befehl / Aktion | Erwartetes Ergebnis | OK? |
|---|---|---|---|
| C1 | `python -m blackjack_assistant run --profile mock_casino` | Kleines dunkles Fenster: Profil, Running Count, True Count, Decks übrig, Einsatz, Hotkey-Leiste | |
| C2 | Auf das Browserfenster klicken | Overlay bleibt **im Vordergrund** (konnte auf dem virtuellen Bildschirm nicht geprüft werden, da dort kein Fenstermanager läuft) | |
| C3 | Overlay mit der Maus verschieben | Fenster folgt der Maus | |
| C4 | Runde austeilen und auf die Entscheidung warten | Nach ca. 0,3 s erscheint der Spielzug (z. B. „STEHEN“, farbig) und darunter „Basic Strategy“ bzw. „Abweichung: …“ | |
| C5 | Running Count mit eigener Zählung vergleichen (Hi-Lo: 2–6 = +1, 10–A = −1) | Gleicher Wert; Decks übrig sinkt; True Count = RC / Decks | |
| C6 | Dealer zeigt Ass | Zusätzlich „Versicherung: nein“ (oder „JA“ ab TC +3) | |
| C7 | **F8** drücken, während das Casino-Fenster den Fokus hat | Gelbe Warnung „PAUSE – es wird nicht gezählt“; neue Karten ändern den Count nicht. Nochmals F8 → weiter | |
| C8 | **F9** drücken | Count auf 0, Decks wieder 6 | |
| C9 | **F10** drücken | Profil wechselt (Profilzeile oben), z. B. zu `playtech_blackjack_surrender` | |
| C10 | Falls globale Hotkeys nicht gehen (macOS: Bedienungshilfen-Berechtigung fehlt; Linux: Wayland) | Meldung in der Konsole; F8/F9/F10 funktionieren dann, wenn das Overlay den Fokus hat | |
| C11 | Einstellungen im Mock-Casino → „Nach jeder Runde neu mischen“, Profil-Regel `shuffle_every_round` auf `true` setzen, neu starten | Rote Warnung „Spiel mischt jede Runde – Zählen hier wirkungslos“, Einsatz immer 1 Einheit | |
| C12 | Browser-Zoom ändern, bis Karten undeutlich werden (z. B. 50 %) | Gelbe Warnung „Unsichere Erkennung“, unsichere Karten werden nicht gezählt | |
| C13 | Escape im Overlay oder Ctrl+C in der Konsole | Programm endet, Pfad des Erkennungs-Logs und ggf. Mischstatistik werden ausgegeben | |
| C14 | Optional: `pytest -m display` | GUI-Tests laufen auf dem echten Bildschirm (Fenster blitzen kurz auf) | |

Automatischer Gesamtablauf (öffnet einen sichtbaren Browser, spielt 5 Runden, zeigt das Overlay):
`python tools/screen_demo.py --rounds 5 --shot logs/overlay_demo.png` → Ausgabe vergleicht den
angezeigten Running Count mit der Ground Truth (müssen gleich sein).

---

## D. Jev (Phase 5, optional, braucht Internet und einen API-Key)

In der Entwicklungsumgebung gab es keinen API-Key; getestet wurde mit einer nachgebildeten API.

| # | Befehl / Aktion | Erwartetes Ergebnis | OK? |
|---|---|---|---|
| D1 | Ohne Key: `python -m blackjack_assistant jev-check` | „Jev: kein API-Key → lokale Strategie (offline)“, Exit-Code 1 | |
| D2 | Key holen (https://console.typesafe.ai/keys), `cp .env.example .env`, Key eintragen | `git status` zeigt `.env` **nicht** an (ist ignoriert) | |
| D3 | `python -m blackjack_assistant jev-check` | „16 gegen 10, TC 0 → …“ mit Quelle `jev` und Wahrscheinlichkeiten (Summe ≈ 100 %) | |
| D4 | `pytest tests/test_jev.py` | Auch `test_echte_jev_anfrage` läuft jetzt (statt übersprungen) und ist grün | |
| D5 | `run --profile mock_casino --engine jev`, Runde spielen | Kurz „Lokale Strategie: Jev rechnet …“, danach Spielzug mit „Jev: Konfidenz …“ und Wahrscheinlichkeiten | |
| D6 | Falschen Key eintragen, D5 wiederholen | Meldung „Jev lehnt den API-Key ab“, Empfehlungen kommen von der lokalen Strategie | |
| D7 | Internet trennen, D5 wiederholen | „Jev nicht erreichbar … → lokale Strategie“, Programm läuft weiter | |

---

## E. Auswertung (Phase 6, kein Bildschirm nötig)

| # | Befehl / Aktion | Erwartetes Ergebnis | OK? |
|---|---|---|---|
| E1 | `python -m blackjack_assistant simulate -- --big-rounds 0 --out logs/sim_test` | Läuft ca. 1 Minute, schreibt `logs/sim_test/results.md` und Grafiken (Teil „10'000 Hände“ identisch mit `docs/results.md`) | |
| E2 | `python -m blackjack_assistant simulate` (mit Langlauf) | Ca. 80 Minuten auf 4 Kernen (mit `--jobs` anpassen); Zahlen identisch mit dem eingecheckten `docs/results.md` (gleicher Seed, gleiche Blöcke) | |
| E3 | Optional mit Jev-API-Key: E1 wiederholen | Zusätzliche Variante „Jev + Hi-Lo“ in Tabelle und Grafiken (dauert lange, kostet laut Preisliste weniger als 1 USD) | |

## F. Alle Tests

| # | Befehl | Erwartetes Ergebnis | OK? |
|---|---|---|---|
| F1 | `pytest` | Alles grün; übersprungen nur `test_echte_jev_anfrage` (ohne Key) | |
| F2 | `pytest -m display` | GUI-Tests auf dem echten Bildschirm grün (Fenster erscheinen kurz) | |
