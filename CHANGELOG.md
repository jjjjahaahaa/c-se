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

---

## Phase 3 – Zählen und Strategie

**Zählen (`counting`)**
- Sechs Zählsysteme, Kartenwerte als Tabelle in `config/counting_systems.toml` (nicht im Code):
  Hi-Lo, KO, Hi-Opt II, Omega II, Zen Count, Wong Halves. Beim Laden wird geprüft, ob ein als
  ausgeglichen markiertes System pro Deck wirklich die Summe 0 hat.
- `Counter`: Running Count, verbleibende Decks (gesehene + ungesehene Karten, Deckanzahl aus dem
  Profil, auf halbe Decks gerundet), True Count. KO ohne True Count, mit Start-Count (IRC).
  Ass-Nebenzähler für Hi-Opt II und Omega II.
- Verarbeitet direkt die Ereignisse der Erkennung: neue Karte, Korrektur, ungesehen
  (zählt nicht, verringert aber die Restdecks), Rundenende, Mischen.
- Misch-Erkennung setzt den Count zurück. Option „mischt jede Runde“: Count nach jeder Runde
  auf 0, Kennzeichen „Zählen wirkungslos“ (Einsatz immer 1 Einheit, nur Basic Strategy).
- Mischstatistik: pro Schuh Anzahl Runden und Penetration in `logs/shuffle_stats.jsonl`.

**Strategie (`strategy`)**
- Basic Strategy als Tabelle (`config/basic_strategy.toml`: 6 Decks, S17, DAS, Late Surrender).
  Regeln pro Profil: H17 (eigene Ausnahmeliste), ohne DAS, ohne Surrender, Verdoppeln/Teilen
  nicht möglich (z. B. drei Karten) werden im Code umgesetzt.
- Abweichungen: Illustrious 18 + Fab 4 (`config/deviations.toml`). Reihenfolge: zuerst
  Surrender-Indizes, dann Spiel-Indizes; Versicherung separat.
- Einsatz: 1 Einheit bis TC +1, danach Staffelung aus dem Profil.
- Gemeinsame Schnittstelle `DecisionEngine` (für Phase 5).
- Zusätzlich (parallel von einem Subagenten erstellt, für Phase 6 gebraucht): **exakte
  Erwartungswert-Berechnung** aus der Restzusammensetzung (`simulation/exact.py`). Damit wird die
  Basic-Strategy-Tabelle unabhängig geprüft: Von allen 550 Zwei-Karten-Situationen (voller
  6-Deck-Schuh) stimmen 548 mit der exakten Berechnung überein. Die 2 Abweichungen sind bekannte
  zusammensetzungsabhängige Ausnahmen mit winzigem Unterschied: 10,2 gegen 4 (Ziehen statt Stehen,
  0,075 % des Einsatzes) und 8,7 gegen 10 (Ziehen statt Aufgeben, 0,024 %).

**Gefundene und behobene Fehler**
- A,A ohne Teilmöglichkeit wurde als „hart 12“ gespielt (gegen 4–6 stehen). Ergänzt: Zeile Soft 12.
- 16 gegen 10 mit erlaubtem Surrender: Der I18-Index „ab TC 0 stehen“ hat das Aufgeben
  überschrieben. Spiel-Indizes gelten jetzt nur, wenn nicht aufgegeben wird.

**Tests**: Kartenwerte aller Systeme, ausgeglichen/unausgeglichen, ganzer Schuh ergibt 0 (bzw.
+4 bei KO), Running/True Count, Restdecks inkl. ungesehener Karten, Korrekturen, Mischen,
„mischt jede Runde“, Statistik, Ass-Nebenzähler; Basic Strategy (40 Stichproben + Vergleich mit
exakter Berechnung), H17/kein DAS/kein Surrender, alle Illustrious 18 und Fab 4, Umrechnung für
Level-2-Systeme, KO-Schwellen, Einsatzstaffelung.

**Offene Entscheidungen**
- Die Illustrious-18-Indizes sind für Hi-Lo veröffentlicht. Für Hi-Opt II, Omega II, Zen und
  Wong Halves werden sie mit einem Faktor umgerechnet (Regression der Kartenwerte gegenüber Hi-Lo:
  1.5 / 1.6 / 1.7 / 1.0). Das ist eine Näherung; echte Indizes können in
  `config/deviations.toml` unter `[overrides.<system>]` eingetragen werden.
- KO: Die Hi-Lo-Indizes werden in feste Running-Count-Schwellen umgerechnet, bezogen auf eine
  Referenztiefe von 37,5 % des Schuhs (Mitte des gespielten Teils bei 75 % Penetration).
  Bei TC +4 ergibt das genau den Pivot (+4). Versicherung: fest ab RC +3.
- Ass-Korrektur (Hi-Opt II, Omega II): 2 Punkte pro überzähligem Ass, nur für den Einsatz,
  nicht für Spielentscheidungen.
- True Count wird nicht abgerundet (z. B. TC 1.9 zählt nicht als 2). Restdecks auf halbe Decks
  gerundet (einstellbar: `counting.deck_rounding`).
- Seven-Card Charlie (Playtech-Profil) ist in der Basic-Strategy-Tabelle nicht berücksichtigt
  (betrifft nur Hände mit 6 Karten); die exakte Berechnung kennt die Regel.

---

## Phase 4 – Overlay

- `Assistant` (`app.py`): verbindet Erkennung → Zählung → Strategie → Einsatz und liefert einen
  reinen Datenzustand (`OverlayState`). Keine GUI darin, deshalb ohne Bildschirm testbar.
  - Empfehlung nur, wenn eine Entscheidung ansteht: genau eine offene Dealerkarte, Spielerhand mit
    mindestens zwei Karten unter 21. Bei Split wird die Hand bewertet, die zuletzt eine Karte bekam.
  - Erlaubte Aktionen werden aus dem Tisch abgeleitet (Verdoppeln nur mit zwei Karten, Teilen bis
    zur Höchstzahl Hände, Aufgeben nur als erste Entscheidung ohne Split).
  - Versicherungsempfehlung, wenn der Dealer ein Ass zeigt.
- `AssistantWorker`: Thread für Aufnahme und Auswertung, Zustände über eine Queue ans Overlay,
  Befehle (Pause, Reset, Profilwechsel) über eine zweite Queue zurück.
- Overlay (`overlay/window.py`, tkinter): klein, immer im Vordergrund, halbtransparent,
  verschiebbar. Zeigt Running Count, True Count, Decks übrig, Einsatz, Spielzug (farbig) mit
  Quelle, Hand gegen Dealerkarte, Versicherung, Wahrscheinlichkeiten (für Jev), aktives Profil,
  Warnungen (gelb: unsichere Erkennung, Pause; rot: Zählen wirkungslos).
- Hotkeys (`overlay/hotkeys.py`, pynput): F8 Pause, F9 Count zurücksetzen, F10 Profil wechseln.
  Global; falls das System das nicht erlaubt, funktionieren dieselben Tasten im Overlay.
- Befehl `python -m blackjack_assistant run [--profile …] [--engine …] [--no-overlay]`.
  Beim Beenden werden Erkennungs-Log und Mischstatistik ausgegeben.

**Tests**
- Ohne Display: Assistant mit Test-Screenshots (Empfehlung, Zählung über eine ganze Runde,
  Split, Pause/Reset, „mischt jede Runde“), Worker-Thread mit Befehlen und Profilwechsel,
  Overlay-Texte und Warnungen.
- Mit virtuellem Bildschirm (Xvfb, Python 3.12 mit tkinter): Overlay-Fenster und Tasten,
  Bereichsauswahl per Maus (auch Abbruch mit Esc), Kalibrierfenster, Bildschirmaufnahme mit mss,
  globale Hotkeys, `run` mit und ohne Overlay, **Gesamtablauf**: Mock-Casino im sichtbaren
  Browser, Aufnahme mit mss, Worker und Overlay – der angezeigte Running Count stimmt mit der
  Ground Truth überein.

**Offene Entscheidungen**
- „Immer im Vordergrund“ konnte auf dem virtuellen Bildschirm nicht geprüft werden (ohne
  Fenstermanager wirkt `-topmost` nicht) → LOCAL_TESTS C2.
- Hotkeys sind fest F8/F9/F10 (in `overlay/hotkeys.py` änderbar), weil diese Tasten in Browsern
  kaum belegt sind (F11 = Vollbild, F12 = Entwicklertools werden bewusst vermieden).
- Der Worker wertet ca. 12 Bilder pro Sekunde aus. Gezählt wird trotzdem nur, wenn das Bild
  300 ms ruhig war.

---

## Phase 5 – Jev (optional)

**Recherche** (Oktober 2026, Subagent mit Webzugriff): Jev ist das „System One“-Modell von
TypeSafe AI. API: `POST https://api.typesafe.ai/v1/systemone`, Authentifizierung
`Authorization: Bearer <Key>`, offizielle Umgebungsvariable `TYPESAFE_API_KEY`. Fragetyp
„Choice“: Optionen als Schlüssel von `criteria`, Antwort mit `choice`, `probabilities` und
`confidence`. Das Projekt patrickhaahr/jevjack (TypeScript) nutzt das JS-SDK und stellt eine
Choice über alle fünf Aktionen. Die API war erreichbar (ohne Key: HTTP 403).

**Umsetzung** (`strategy/jev.py`)
- `JevEngine` mit derselben Schnittstelle wie die lokale Strategie (`decide`, `take_insurance`),
  wählbar per Profil (`decision_engine`) oder `run --engine jev`.
- Zustand an Jev: Spielerkarten, Summe, soft, Dealer-Karte, True Count, Restdecks, erlaubte
  Aktionen, Anzahl Hände. Auswahl: nur die gerade erlaubten Aktionen.
- Wahrscheinlichkeiten und Konfidenz werden im Overlay angezeigt.
- API-Key nur aus der Umgebung (`TYPESAFE_API_KEY` oder `JEV_API_KEY`, optional `.env`).
  Der Key erscheint nie in Fehlermeldungen oder Ausgaben. `.env` in `.gitignore`, Vorlage
  `.env.example`.
- Rückfall auf die lokale Strategie: ohne Key, bei ungültigem Key (danach keine weiteren
  Versuche), Netzwerkfehler, Serverfehler oder unerwarteter Antwort.
- Overlay: Anfrage im Hintergrund (das Bild friert nicht ein), Ergebnis wird pro Situation
  zwischengespeichert. Simulation: blockierend.
- Befehl `python -m blackjack_assistant jev-check` für eine Testanfrage.

**Tests**: mit nachgebildeter API (keine echten Aufrufe): Request-Format, nur erlaubte Aktionen,
Auswertung inkl. Wahrscheinlichkeiten, Zwischenspeicher, kein Key, ungültiger Key (403),
Netzwerkfehler, kaputte Antwort, HTTP 529, Key nicht in Meldungen, Hintergrundmodus,
`.env` ignoriert. Zusätzlich einmalig geprüft: Unser Request und das erwartete Antwortformat
sind gültig nach der offiziellen OpenAPI-Spezifikation (api.typesafe.ai/openapi.json).
Ein echter Test (`test_echte_jev_anfrage`) läuft automatisch, sobald ein Key gesetzt ist.

**Offene Entscheidungen**
- **Kein API-Key in der Entwicklungsumgebung** → Phase 5 ist mit nachgebildeter API fertig
  gestellt; die echte Verbindung bitte lokal prüfen (LOCAL_TESTS D).
- Direkte HTTP-Anfragen mit `requests` statt offiziellem Python-SDK (`typesafe-sdk`): weniger
  Abhängigkeiten (das SDK braucht pydantic, httpx2, tenacity) und leicht testbar. Das Format
  entspricht der Doku.
- Anders als jevjack wird Jev keine fertige Basic-Strategy-Empfehlung mitgegeben (Auftrag:
  Zustand = Hand, Dealer-Karte, True Count). Mit `JevEngine(advice=True)` lässt sich das einschalten.
- Modell `jev-latest` (änderbar über `TYPESAFE_DEFAULT_MODEL`, für reproduzierbare Vergleiche
  z. B. `jev-1.13.0`).

---

## Phase 6 – Auswertung

- **Simulator** (`simulation/simulator.py`) ohne Bildschirm, mit denselben Regeln wie das
  Mock-Casino (Peek, Versicherung, 3:2, Double/DAS, Split bis 4 Hände, Late Surrender,
  S17/H17, Seven-Card Charlie) und festem Seed. Geprüft: Basic Strategy über 2 Mio. Runden
  −0,32 % ± 0,16 % – passt zum exakt berechneten Hausvorteil von −0,337 %.
- **Spieler** (`simulation/players.py`): Basic Strategy ohne Zählen (flach), jedes Zählsystem
  mit Abweichungen und Spread 1–8, exakte Strategie (Restzusammensetzung, Einsatz nach
  berechnetem Vorteil), Jev + Hi-Lo (nur mit API-Key).
- **Bericht** (`simulation/report.py`, Befehl `simulate`): 10'000 Hände pro Variante in beiden
  Modi (75 % Penetration / Mischen nach jeder Runde), Langlauf mit 500'000 Runden pro Variante
  (parallel auf 4 Prozessen), Betting Correlation aller Systeme aus den exakten Effects of
  Removal, 7 Grafiken (matplotlib) und `docs/results.md` + `docs/results.json`.
  Laufzeit ca. 9 Minuten; Ergebnisse sind reproduzierbar (zweimal gerechnet, identisch).

**Ergebnisse** (Details in [docs/results.md](docs/results.md))

| Variante (75 % Penetration) | 10'000 Hände | Langlauf 500'000: pro Runde | Anteil am Maximum |
|---|---:|---:|---:|
| Basic Strategy (ohne Zählen) | −211 Einheiten | −0,17 % ± 0,32 % | – |
| Hi-Lo | +262 | +1,37 % ± 0,66 % | 55 % |
| KO | +199 | +1,41 % ± 0,67 % | 56 % |
| Hi-Opt II | +320 | +1,56 % ± 0,73 % | 62 % |
| Omega II | +239 | +1,56 % ± 0,73 % | 62 % |
| Zen Count | +189 | +1,43 % ± 0,67 % | 57 % |
| Wong Halves | +213 | +1,26 % ± 0,68 % | 51 % |
| Exakt (theoretisches Maximum) | +266 | +2,63 % ± 0,88 % | 100 % |
| Jev + Hi-Lo | nicht simuliert (kein API-Key) | | |

- Mischen nach jeder Runde: alle Zählsysteme identisch mit Basic Strategy (1 Einheit, gleiche
  Ergebnisse), Zählen ist wirkungslos.
- 10'000 Hände sind zu wenig für eine Rangliste: Der Zufallsspielraum (±2,2 bis ±6,2 % pro
  Runde) ist grösser als die Unterschiede. Deshalb zusätzlich der Langlauf.
- Ohne Zufall (Betting Correlation): Wong Halves 0,993, Omega II mit Ass-Korrektur 0,981,
  Hi-Opt II mit Ass-Korrektur 0,973, Hi-Lo 0,961, Zen 0,959, KO 0,958.

**Tests**: Regeln des Simulators mit vorgegebenen Karten (Blackjack, Dealer-Blackjack,
Surrender, Double, Push, Überkaufen, S17/H17, gesplittete Asse, Versicherung, Seven-Card
Charlie), gleicher Seed = gleiches Ergebnis, Schnittkarte/Mischen jede Runde, Zähler spielt
Basic Strategy bei jeder Runde gemischt, Hausvorteil über 200'000 Runden, exakter Spieler,
Kennzahlen, Betting Correlation, Bericht mit allen Grafiken.

**Offene Entscheidungen**
- **Jev** wurde nicht simuliert (kein API-Key). Mit Key erscheint die Variante automatisch.
  Hinweis: 10'000 Hände bedeuten rund 15'000 API-Anfragen (Kosten laut Preisliste etwa
  0,40 USD, Dauer je nach Antwortzeit über eine Stunde).
- Die exakte Strategie setzt nach dem linear geschätzten Vorteil (Effects of Removal), weil eine
  vollständige Berechnung pro Runde zu langsam wäre (0,5 s statt 10 µs). Umrechnung:
  0,5 % Vorteil ≈ 1 Hi-Lo-True-Count, dieselbe Staffelung. Sie setzt damit im Mittel etwas mehr
  (Ø 1,90 statt 1,49 Einheiten); deshalb steht im Bericht auch der Vorteil pro eingesetzter Einheit
  (+1,39 % gegen +0,92 % bei Hi-Lo).
- „Anteil am Maximum“ ist ein Verhältnis aus zwei verrauschten Werten. Die Reihenfolge der
  Zählsysteme ist im Langlauf nicht sicher (überlappende Vertrauensintervalle); die Betting
  Correlation ist die zuverlässigere Rangfolge.
- Simuliert wird mit dem Ganzkarten-Schuh ohne Erkennungsfehler (perfekte Erkennung).

---

## Gesamtübersicht der Tests (Stand Phase 6)

354 Tests in 15 Dateien. Ausgeführt in der Entwicklungsumgebung (Linux, ohne echten Bildschirm):

| Umgebung | Ergebnis | Übersprungen (Grund) |
|---|---|---|
| Python 3.12 auf virtuellem Bildschirm (`xvfb-run`), alle Tests | **353 grün** | 1: echter Jev-Test (kein API-Key) |
| Python 3.13 ohne Display, alle Tests | **344 grün** | 2: GUI-Datei mit 9 Tests (kein Display), echter Jev-Test |
| Python 3.11 ohne Display, ohne Browser-Tests | **319 grün** | wie oben; 25 Browser-Tests abgewählt |

| Datei | Tests | Inhalt |
|---|---:|---|
| test_exact.py | 93 | exakte Erwartungswerte, Peek, Split, Charlie, EOR |
| test_strategy.py | 85 | Basic Strategy, Regelvarianten, I18/Fab 4, Einsatz, Abgleich mit exakter Berechnung |
| test_recognition_parts.py | 30 | Stabilität, Bereiche, Profile, Kalibrierung, Log, Genauigkeitsmessung, Pipeline |
| test_counting.py | 26 | sechs Zählsysteme, True Count, ungesehene Karten, Mischen, Statistik |
| test_tracking.py | 21 | Tisch-Modus (einmal zählen, Split, Korrektur, Rundenende) und Verlaufs-Modus |
| test_simulation.py | 21 | Simulator-Regeln, Seed, Spieler, Hausvorteil, Bericht |
| test_mock_casino_game.py | 20 | Spielregeln des Mock-Casinos im Headless-Browser |
| test_recognition_images.py | 12 | Erkennung auf Screenshots, gedrehte Ecken, 125 %-Zoom, Kalibrierung B/D/K |
| test_app.py | 12 | Assistant, Worker-Thread, Overlay-Texte |
| test_jev.py | 11 | Jev mit nachgebildeter API, Rückfall, Sicherheit des Keys |
| test_gui_display.py | 9 | Overlay, Bereichsauswahl, Kalibrierfenster, mss, Hotkeys, Gesamtablauf (Display nötig) |
| test_mock_server.py | 5 | Server und Ground-Truth-Log |
| test_card_svgs.py | 4 | Karten-SVGs |
| test_mock_casino_e2e.py | 3 | Mock-Casino über die Oberfläche gegen Ground Truth |
| test_recognition_e2e.py | 2 | ganze Erkennung im Headless-Browser gegen Ground Truth (≥ 99 % / ≥ 97 %) |

Was nur lokal geprüft werden kann, steht in [LOCAL_TESTS.md](LOCAL_TESTS.md).
