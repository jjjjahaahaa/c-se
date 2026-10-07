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
| B6 | `python -m blackjack_assistant run --profile mock_casino --no-overlay` (ab Phase 4) und 20 Runden spielen, dann Ctrl+C | Konsole zeigt jede Karte genau einmal, „Rundenende“ nach dem Abräumen | |
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
