# Projektplan

Gearbeitet wird in Phasen. Nach jeder Phase gibt es eine kurze Zusammenfassung für die
Projektdokumentation, danach wird auf das OK gewartet.

Legende: **Ergebnis** = was am Ende der Phase vorliegt, **Abnahme** = wie man prüft, dass es funktioniert.

---

## Phase 0 – Planung (diese Phase)

- README mit Architektur und Ordnerstruktur
- Phasenplan (dieses Dokument)
- `.gitignore` (inkl. `.env`, `.venv`, `logs/`)

---

## Phase 1 – Mock-Casino

**Aufgaben**
1. `server.py`: Python `http.server`, liefert `mock_casino/` aus. Zusätzlicher
   POST-Endpunkt `/api/log`, weil JavaScript im Browser selbst keine Dateien schreiben
   kann. Mit `--debug` schreibt der Server jede aufgedeckte Karte als JSON-Zeile nach
   `logs/ground_truth.jsonl` (Zeitstempel, Rang, Farbe, Position Spieler/Dealer, Rundennummer,
   Mischereignisse).
2. Spiellogik in JS: 6-Deck-Schuh, Fisher-Yates-Mischen, Schnittkarte bei 75 %,
   Dealer steht auf Soft 17, Blackjack 3:2, Double (auf zwei Karten, auch nach Split),
   Split (bis 4 Hände, Asse nur eine Karte), Late Surrender.
   Die Hole Card des Dealers wird erst am Ende aufgedeckt (wichtig fürs Zählen).
3. SVG-Karten: grosse, klare Ecke (Rang + Farbsymbol), dunkelgrüner Tisch.
   Rangzeichen werden als Pfade gezeichnet (nicht als Text), damit sie in jedem
   Browser gleich aussehen und Templates exakt dazu passen.
4. Verlaufs-Panel: alle seit dem letzten Mischen aufgedeckten Karten, in Reihenfolge.
5. Mischanzeige: Fortschrittsbalken bis zur Schnittkarte, Meldung "Wird nach dieser
   Runde neu gemischt".
6. Optional per Schalter: "Mischen nach jeder Runde" (für Phase 3 / 6).

**Abnahme**: Spiel im Browser durchspielbar, alle Aktionen funktionieren,
`ground_truth.jsonl` entsteht im Debug-Modus.

---

## Phase 2 – Bildschirmaufnahme und Kartenerkennung

**Aufgaben**
1. `capture`: Aufnahme mit `mss`, Bereichsauswahl per Maus (halbtransparentes
   tkinter-Vollbild zum Aufziehen eines Rechtecks).
2. Stabilitätsprüfung: Auswertung erst, wenn sich das Bild 300 ms nicht verändert hat
   (Differenz zweier verkleinerter Graustufenbilder unter einer Schwelle).
3. Kartenerkennung: Kartenumrisse finden (heller Bereich auf dem Tisch), Ecke
   ausschneiden, `cv2.matchTemplate` gegen alle Rang-Templates, bester Treffer + Konfidenz.
   Mehrere Skalierungen, damit Browser-Zoom/Bildschirm-DPI keine Rolle spielen.
4. Tisch-Modus: Karten pro Runde anhand ihrer Position verfolgen (gleiche Position
   = gleiche Karte → nur einmal zählen). Tisch leer → Rundenende.
5. Verlaufs-Modus: Panel als Liste lesen, mit der vorherigen Liste vergleichen,
   nur neue Einträge zählen. Panel leer → Neu-Mischen.
6. Konfidenz: Schwelle pro Profil; unsichere Treffer werden nicht gezählt, sondern als
   Warnung (gelb) ans Overlay gemeldet.
7. Kalibrierung: Für jeden Rang (2–10, B, D, K, A) eine Karte per Maus markieren,
   Ecke als Template speichern. Profile mit Templates, Bereichen und Lesemodus.
8. `tools/generate_templates.py`: Templates aus den Mock-Casino-SVGs erzeugen.
9. `tools/measure_accuracy.py`: Erkennungs-Log mit Ground Truth vergleichen, Genauigkeit
   in % (gesamt und pro Rang), Liste der Fehler.
10. Erkennungs-Log mit Mini-Screenshot pro Karte (`logs/recognition/<datum>/`) plus
    einfache HTML-Übersicht zur Handprüfung.

**Abnahme**: Mit dem Mock-Casino eine Genauigkeit von mindestens 99 % im Verlaufs-Modus
und mindestens 97 % im Tisch-Modus.

---

## Phase 3 – Zählen und Strategie

**Aufgaben**
1. Zählsystem konfigurierbar (pro Profil und in der Simulation). Die Kartenwerte stehen
   als Tabelle in `config/counting_systems.toml`, nicht im Code:

   | Rang | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10/B/D/K | A | Typ |
   |---|---|---|---|---|---|---|---|---|---|---|---|
   | Hi-Lo | +1 | +1 | +1 | +1 | +1 | 0 | 0 | 0 | −1 | −1 | ausgeglichen |
   | KO | +1 | +1 | +1 | +1 | +1 | +1 | 0 | 0 | −1 | −1 | unausgeglichen |
   | Hi-Opt II | +1 | +1 | +2 | +2 | +1 | +1 | 0 | 0 | −2 | 0 | ausgeglichen, Ass-Nebenzähler |
   | Omega II | +1 | +1 | +2 | +2 | +2 | +1 | 0 | −1 | −2 | 0 | ausgeglichen, Ass-Nebenzähler |
   | Zen Count | +1 | +1 | +2 | +2 | +2 | +1 | 0 | 0 | −2 | −1 | ausgeglichen |
   | Wong Halves | +0.5 | +1 | +1 | +1.5 | +1 | +0.5 | 0 | −0.5 | −1 | −1 | ausgeglichen |

   - Ausgeglichene Systeme: Running Count → True Count (RC / verbleibende Decks).
   - Unausgeglichen (KO): Start-Count (IRC = 4 − 4 × Decks), Entscheidungen über feste
     Schwellen (Key Count, Pivot), kein True Count.
   - Hi-Opt II und Omega II: separater Ass-Nebenzähler. Für Einsatz und Insurance wird
     der Count um den Ass-Überschuss bzw. -Mangel korrigiert (Faktor pro System in der Konfiguration).
   - Verbleibende Decks: `Decks im Profil − gesehene Karten / 52`, auf halbe Decks gerundet.
2. Misch-Erkennung setzt den Count zurück. Option "Spiel mischt jede Runde":
   Count nach jeder Runde auf 0, Warnung "Zählen hier wirkungslos".
3. Statistik im Log: Anzahl Runden zwischen zwei Mischvorgängen.
4. Basic Strategy als Tabellen (hart, soft, Paare, Surrender) für 6 Decks, S17, DAS,
   Late Surrender. Regeln pro Profil anpassbar (z. B. H17, kein DAS, kein Surrender).
5. Illustrious 18 (und Fab 4 für Surrender) abhängig vom True Count, inkl. Insurance.
   Die Indizes sind systemspezifisch und stehen ebenfalls in der Konfiguration.
   Mitgeliefert werden die veröffentlichten Hi-Lo-Indizes; für die anderen Systeme
   werden sie über den Level des Systems umgerechnet (Näherung, wird im Bericht
   vermerkt). Für KO gelten feste Schwellen statt True-Count-Indizes.
6. Einsatzempfehlung: 1 Einheit bis TC +1, danach steigend; Staffelung im Profil.
7. Unit Tests für Zählung, True Count, Strategie und Abweichungen.

**Abnahme**: `pytest` grün, Stichproben aus der Basic-Strategy-Tabelle stimmen.

---

## Phase 4 – Overlay

**Aufgaben**
1. tkinter-Fenster, klein, immer im Vordergrund (`-topmost`), optional halbtransparent.
2. Anzeige: Running Count, True Count, verbleibende Decks, Einsatz, Spielzug,
   aktives Profil, Warnungen (unsicher erkannt = gelb, Zählen wirkungslos = rot).
3. Hotkeys (global über `pynput`): Pause, Count zurücksetzen, Profil wechseln.
4. Erkennung läuft in einem eigenen Thread, das Overlay wird über eine Queue aktualisiert
   (tkinter darf nur aus dem Hauptthread verändert werden).

**Abnahme**: Mock-Casino spielen, Overlay zeigt laufend korrekte Werte.

---

## Phase 5 – Jev (optional)

**Aufgaben**
1. Aktuelle Jev-API recherchieren (Orientierung: GitHub `patrickhaahr/jevjack`).
2. `JevEngine` nach der Schnittstelle `DecisionEngine`: Zustand = Spielerhand,
   Dealer-Karte, True Count; Aktionen = hit/stand/double/split/surrender.
3. Wahrscheinlichkeiten der Aktionen im Overlay anzeigen.
4. API-Key nur aus `JEV_API_KEY`; ohne Key oder bei Netzwerkfehler automatisch
   `StrategyEngine`. Tests mit gemockter API (keine echten Aufrufe in Tests).

**Abnahme**: Ohne Key läuft alles offline; mit Key erscheinen Jev-Empfehlungen.

---

## Phase 6 – Auswertung

**Aufgaben**
1. Simulator ohne Bildschirm, gleicher Seed für alle Varianten, 10'000 Hände:
   (a) Basic Strategy ohne Zählen, (b) Basic Strategy + Hi-Lo (Deviations + Einsatz),
   (c) Jev mit Count (ohne Key: übersprungen bzw. markiert),
   (d) jedes konfigurierte Zählsystem (Hi-Lo, KO, Hi-Opt II, Omega II, Zen, Wong Halves),
   (e) **exakte Strategie** (composition-dependent): merkt sich alle gespielten Karten
       und berechnet für jede Entscheidung den Erwartungswert aus der genauen
       Restzusammensetzung des Schuhs (Dealer-Wahrscheinlichkeiten rekursiv, Hit/Stand/
       Double/Surrender exakt, Split mit der üblichen Näherung). Einsatz nach dem
       berechneten Vorteil vor dem Austeilen. Rechenintensiv: Zwischenergebnisse werden
       pro Restzusammensetzung zwischengespeichert.
2. Vergleich aller Zählsysteme gegen die exakte Strategie als theoretisches Maximum
   (Anteil des maximal erreichbaren Vorteils, der mit dem System erreicht wird).
3. Vergleich tiefer Schuh (75 % Penetration) vs. Mischen nach jeder Runde.
4. Grafiken (matplotlib): Guthabenverlauf, Gewinn pro Hand, Varianz/Streuung.
5. `docs/results.md`: kurze Zusammenfassung mit Tabellen und Grafiken.

**Abnahme**: Ein Befehl erzeugt alle Grafiken und den Bericht reproduzierbar.

---

## Testbarkeit ohne Bildschirm

Phase 1, 3 und 6 laufen und testen vollständig ohne Display (z. B. in CI):

- Kein Modul aus `counting`, `strategy` oder `simulation` importiert `tkinter`, `mss`
  oder `pynput`. Diese Bibliotheken werden nur in `capture` und `overlay` importiert.
- Die Spiellogik des Mock-Casinos ist vom DOM getrennt (`rules.js`, `shoe.js`, `game.js`)
  und wird in den Tests in einem Headless-Browser (Playwright) ausgeführt. Ist Playwright
  nicht installiert, werden diese Tests übersprungen, alle anderen laufen trotzdem.
- Phase 2 und 4 werden lokal mit Bildschirm getestet. Die reinen Logikteile davon
  (Positions-Tracking, Listenvergleich, Stabilitätsprüfung) arbeiten auf Bildern bzw.
  Listen und sind ebenfalls ohne Display testbar.

---

## Risiken und Annahmen

| Risiko | Massnahme |
|---|---|
| Browser-Zoom / DPI verändert Kartengrösse | Multi-Scale-Matching, Skalierung pro Profil speichern |
| Animationen erzeugen Fehlerkennungen | Stabilitätsprüfung (300 ms), Positions-Tracking |
| Externe Spiele mischen jede Runde | Option im Profil, Warnung im Overlay, Nachweis in Phase 6 |
| Globale Hotkeys brauchen unter macOS Berechtigungen | Hinweis in der README, Fallback auf Tasten im Overlay-Fenster |
| Jev-API ändert sich oder ist nicht erreichbar | Austauschbare Engine, automatischer Fallback |
| Exakte Strategie ist langsam | Caching pro Restzusammensetzung, Anzahl Hände per Parameter |
| Deviation-Indizes für andere Systeme sind nur Näherungen | Im Bericht kennzeichnen, Indizes in der Konfiguration überschreibbar |
| 10'000 Hände sind statistisch wenig | Varianz/Standardabweichung mit ausweisen, optional mehr Hände per Parameter |
