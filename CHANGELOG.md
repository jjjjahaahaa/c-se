# Changelog

Kurze Zusammenfassung pro Phase für die Projektdokumentation. Am Ende jeder Phase steht,
welche Entscheidungen ich selbst getroffen habe ("Offene Entscheidungen") – diese können
bei Bedarf noch geändert werden.

---

## Phase 0 – Planung

- README mit Architektur (Pipeline capture → recognition → counting → strategy → overlay),
  Datenobjekten und Ordnerstruktur.
- PLAN.md mit allen Phasen, Abnahmekriterien und Risiken.
- `.gitignore` schliesst `.env`, `.venv/` und `logs/` aus.
- Ergänzt: konfigurierbare Zählsysteme, exakte Strategie als Vergleich, Testbarkeit ohne Display.

---

## Phase 1 – Mock-Casino

- Blackjack im Browser (HTML/JS), lokal über `python mock_casino/server.py`.
- Spiellogik getrennt von der Oberfläche: `rules.js` (Regeln), `shoe.js` (6-Deck-Schuh,
  Fisher-Yates, Schnittkarte bei 75 %, optionaler Seed), `game.js` (Rundenablauf), `ui.js` (Darstellung).
- Regeln: S17, Blackjack 3:2, Double (auch nach Split), Split bis 4 Hände, gesplittete Asse
  nur eine Karte, Late Surrender, Dealer-Peek, Versicherung.
- Karten als SVG; Ränge als Pfade (nicht Text), damit sie überall gleich aussehen.
- Verlaufs-Panel (alle Karten seit dem Mischen), Mischanzeige mit Schnittkarte.
- Debug-Modus: Der Browser schickt jedes Ereignis an den Server, der es als Ground Truth
  in `logs/ground_truth_<Zeit>.jsonl` schreibt.
- Tests: Server, SVGs, 15 Regelsituationen, Dauerlauf über 400 Runden, End-to-End über die Oberfläche.

**Offene Entscheidungen**
- Auf den Karten stehen J/Q/K (wie in fast allen Online-Casinos), die Oberfläche ist deutsch.
- Versicherung wurde zusätzlich eingebaut (wird für die Illustrious 18 gebraucht).

---

## Phase 2 – Bildschirmaufnahme und Kartenerkennung

**Mock-Casino ergänzt**
- Schalter „Hole Card nur aufdecken, wenn der Dealer spielt“ (`--hide-hole-card` bzw. `?hide=1`):
  Muss der Dealer nicht spielen (alle Hände überkauft/aufgegeben, Spieler-Blackjack), bleibt
  die Hole Card verdeckt. Die Ground Truth meldet sie als `unseen`.
- Autoplay mit echten Animationen (für Aufnahmen im Headless-Browser).

**Aufnahme (`capture`)**
- `ScreenSource`: Bildschirmaufnahme mit mss. `select_region`: Bereich per Maus aufziehen
  (halbtransparentes Fenster über alle Monitore, DPI-Korrektur für Windows).
- Alle Bildquellen haben dieselbe Schnittstelle (`grab()`): echter Bildschirm,
  gespeicherte Screenshots (`ImageSequenceSource`) oder Headless-Browser (`PlaywrightPageSource`).
  Dadurch ist die ganze Erkennung ohne Bildschirm testbar.
- `StabilityGate`: Ein Bild wird erst ausgewertet, wenn es 300 ms unverändert war. Gemessen
  wird die Anzahl geänderter Pixel (nicht der Mittelwert), damit auch eine kleine neue Karte
  in einem grossen Bereich auffällt.

**Erkennung (`recognition`)**
- Template Matching (OpenCV, normierte Kreuzkorrelation) auf dem Rangzeichen der Kartenecke.
  Gesucht wird nur in hellen Flächen (Karten) → ca. 30 ms statt 400 ms pro Bild.
- Non-Maximum-Suppression; der zweitbeste Rang an derselben Stelle wird gemerkt. Liegen beide
  zu nah beieinander (z. B. 6/8), gilt der Treffer als unsicher.
- Orientierungsprüfung: Die Ecke unten rechts ist gedreht (6 sieht aus wie 9, 7 wie L). Unter
  einem echten Rang liegt ein kompaktes Farbsymbol, unter einer gedrehten Ecke der Tisch →
  wird aussortiert.
- Automatische Skalierungssuche (Browser-Zoom, Windows-Skalierung 125 %).
- **Tisch-Modus** (`TableTracker`): Karten pro Runde nach Rang und Position verfolgen,
  jede Karte nur einmal zählen. Leerer Tisch = Rundenende. Sonderfälle: Split (Karte wandert
  in neue Hand), Korrektur einer Fehllesung, neue Runde ohne sichtbaren leeren Tisch,
  unsichere Karten erst zählen, wenn sie sicher sind.
- **Verlaufs-Modus** (`HistoryReader`): Panel zeilenweise lesen, mit der bisherigen Liste
  vergleichen, nur neue Einträge zählen. Leeres Panel = Neu-Mischen. Funktioniert auch,
  wenn das Panel nur die letzten N Karten zeigt (Überlappung suchen).
- **Ungesehene Karten**: Hat der Dealer am Rundenende nur eine sichtbare Karte, wird die
  Hole Card als „ungesehen“ gemeldet (zählt nicht, aber für die Restdeck-Schätzung).
  Auch Karten, die bis zum Rundenende unsicher bleiben, gelten als ungesehen.
- **Kalibrierung** für externe Spiele: pro Rang ein Rechteck um das Rangzeichen ziehen,
  Rang eintippen. J/Q/K und B/D/K (auch „Bube“, „Dame“, „König“) werden akzeptiert und auf
  dieselben Ränge abgebildet.
- **Profile** (`profiles/<name>/profile.json`): Bereiche, Lesemodus, Templates, Regeln,
  Erkennungseinstellungen, umschaltbar. Beispielprofile `mock_casino` und
  `playtech_blackjack_surrender` (6 Decks, S17, Peek, DAS, Late Surrender, kein Re-Split,
  Seven-Card Charlie, „mischt jede Runde“ aktiv).
- Templates für das Mock-Casino werden automatisch aus den SVGs erzeugt
  (`tools/generate_templates.py`, rendert im Headless-Browser in Originalgrösse).
- **Erkennungs-Log** mit Mini-Screenshot jeder Karte und `index.html` zum Durchsehen
  (unsichere Treffer gelb).
- **Genauigkeitsmessung** `tools/measure_accuracy.py`: vergleicht Erkennung und Ground Truth
  rundenweise und gibt Genauigkeit, verpasste/zusätzliche Karten und Verwechslungen aus.
- `tools/record_mock_session.py`: Mock-Casino spielt im Headless-Browser, die komplette
  Pipeline liest laufend Screenshots (ca. 10 Bilder/s) – Tisch- und Verlaufs-Modus gleichzeitig.

**Messergebnisse (Headless, ohne Bildschirm)**

| Lauf | Karten | Tisch-Modus | Verlaufs-Modus |
|---|---|---|---|
| 40 Runden, Hole Card teils verdeckt | 205 (+10 ungesehen) | 100 %, 10/10 ungesehene erkannt | 100 %, 10/10 ungesehene erkannt |
| 25 Runden, sofort neu austeilen (kein leerer Tisch sichtbar) | 128 | 100 % | 100 % |
| 12 Runden, Mischen nach jeder Runde | 70 | 100 % | 100 %, 12/12 Mischvorgänge erkannt |
| 6 Runden, **sichtbarer Browser + Aufnahme mit mss** (virtueller Bildschirm Xvfb) | 33 | 100 % | 100 % |

Abnahmekriterium (Verlauf ≥ 99 %, Tisch ≥ 97 %) erfüllt. Der letzte Lauf nutzt dieselbe
Bildschirmaufnahme wie im echten Betrieb, aber auf einem virtuellen Bildschirm. Auf dem echten
Bildschirm (andere Schriftglättung, DPI, mehrere Monitore) muss das noch lokal bestätigt
werden (LOCAL_TESTS.md).

**Probleme, die beim Testen gefunden und behoben wurden**
- Stabilitätsprüfung reagierte nicht auf neue Kacheln im grossen Verlaufs-Panel (Mittelwert →
  Anzahl geänderter Pixel).
- Gedrehte Ecken unten rechts wurden als 6/9/7 gelesen (Orientierungsprüfung).
- Zu langsame Auswertung (Suche auf Kartenflächen beschränkt, schnellere Screenshots).
- Runden verschmolzen, wenn sofort neu ausgeteilt wird (Regel „mehrere widersprüchliche Ränge = neue Runde“).
- Split zählte die verschobene Karte doppelt (Verschiebung vor Korrektur prüfen).
- Gedrehte 7 unten rechts (sieht aus wie „L“) wurde knapp unter der Sicherheitsschwelle
  erkannt und als „ungesehen“ gemeldet → zusätzlich prüfen, dass ÜBER dem Rang kein Farbsymbol
  liegt, und Kandidatenschwelle auf 0.75 angehoben.

**Offene Entscheidungen**
- Ein Template pro Rang genügt im Mock-Casino (rote und schwarze Zeichen haben dieselbe Form;
  die Korrelation ist kontrastunabhängig).
- Im Tisch-Modus gibt es kein sichtbares Mischsignal. Gemischt wird dort per Option
  „mischt jede Runde“, per Hotkey (Count zurücksetzen) oder über das Verlaufs-Panel.
- Im Verlaufs-Modus wird der Tischbereich trotzdem gelesen – nicht zum Zählen, sondern für
  den Handzustand (Empfehlung), das Rundenende und die nicht gezeigte Hole Card.
- Ein Split wird erkannt, wenn eine gezählte Karte verschwindet und derselbe Rang in derselben
  Rolle woanders auftaucht. Sehr selten könnte dadurch eine echte neue Karte gleichen Rangs
  übersehen werden.
- Dealer- und Spielerbereich sind relative Anteile des Tischbereichs; beim Playtech-Profil
  sind sie geschätzt und müssen lokal angepasst werden.
- Skalierung des Verlaufs-Panels im Mock-Casino: gemessen 0.95 statt rechnerisch 0.90
  (Kantenglättung bei kleinen Zeichen), aus `estimate_scale` übernommen.
- Schwellen: Treffer unter 0.75 werden ignoriert, 0.75–0.80 gelten als unsicher (gelb),
  ab 0.80 wird gezählt. Alles im Profil einstellbar.
- Die Orientierungsprüfung setzt voraus, dass Karten nebeneinander liegen (Rang oben links,
  Farbsymbol darunter). Bei Spielen mit senkrecht gestapelten Karten kann sie im Profil
  abgeschaltet werden (`orientation_check: false`).
