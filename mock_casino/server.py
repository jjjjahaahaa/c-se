"""Lokaler Webserver für das Mock-Casino.

Liefert die Dateien aus dem Ordner mock_casino/ aus und bietet zwei kleine API-Endpunkte:

  GET  /api/config  Einstellungen für das Spiel (Debug-Modus, Decks, Penetration, Seed)
  POST /api/log     Ein Ereignis (aufgedeckte/ungesehene Karte, Mischen, Rundenende) als JSON.
                    Nur im Debug-Modus wird es als Zeile in die Ground-Truth-Datei geschrieben.

Der Browser kann selbst keine Dateien schreiben, deshalb übernimmt der Server das Log.
Der Server lauscht nur auf 127.0.0.1 und ist damit von aussen nicht erreichbar.

Aufruf:
  python mock_casino/server.py                 # http://localhost:8000
  python mock_casino/server.py --debug         # zusätzlich Ground Truth in logs/
  python mock_casino/server.py --seed 42       # reproduzierbares Mischen
"""

from __future__ import annotations

import argparse
import json
import threading
from datetime import datetime
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = STATIC_DIR.parent
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"

# Schutz gegen versehentlich riesige Anfragen
MAX_BODY_BYTES = 64 * 1024

# Erlaubte Ereignistypen im Ground-Truth-Log
ALLOWED_EVENTS = {"card", "unseen", "shuffle", "round_start", "round_end", "session_start"}


class GroundTruthLog:
    """Schreibt Ereignisse threadsicher als JSON Lines (eine JSON-Zeile pro Ereignis)."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, event: dict) -> None:
        # Serverzeit ergänzen, damit sich das Log später mit der Erkennung abgleichen lässt
        event = {"server_time": datetime.now().isoformat(timespec="milliseconds"), **event}
        line = json.dumps(event, ensure_ascii=False)
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


class CasinoConfig:
    """Einstellungen, die der Browser über /api/config abfragt."""

    def __init__(
        self,
        debug: bool = False,
        decks: int = 6,
        penetration: float = 0.75,
        seed: int | None = None,
        shuffle_every_round: bool = False,
        hide_hole_card: bool = False,
        log: GroundTruthLog | None = None,
    ):
        self.debug = debug
        self.decks = decks
        self.penetration = penetration
        self.seed = seed
        self.shuffle_every_round = shuffle_every_round
        self.hide_hole_card = hide_hole_card
        self.log = log

    def as_json(self) -> dict:
        return {
            "debug": self.debug,
            "decks": self.decks,
            "penetration": self.penetration,
            "seed": self.seed,
            "shuffleEveryRound": self.shuffle_every_round,
            "hideHoleCard": self.hide_hole_card,
        }


class CasinoRequestHandler(SimpleHTTPRequestHandler):
    """Statische Dateien + die beiden API-Endpunkte."""

    # .js-Dateien als JavaScript ausliefern (wichtig für ES-Module unter Windows,
    # wo die Registry manchmal einen falschen Typ liefert)
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".svg": "image/svg+xml",
        ".css": "text/css",
    }

    def __init__(self, *args, config: CasinoConfig, **kwargs):
        self.config = config
        super().__init__(*args, **kwargs)

    # --- Hilfsfunktionen -------------------------------------------------

    def _send_json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self) -> None:
        # Kein Caching, damit Änderungen an JS/CSS beim Entwickeln sofort sichtbar sind
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002 (Name von der Basisklasse)
        # Nur Fehler ausgeben, nicht jede erfolgreiche Anfrage (das wären hunderte Zeilen)
        if len(args) >= 2 and str(args[1]).startswith(("2", "3")):
            return
        super().log_message(format, *args)

    # --- Endpunkte ------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 (Name von der Basisklasse vorgegeben)
        if self.path == "/api/config":
            self._send_json(HTTPStatus.OK, self.config.as_json())
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/log":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "unbekannter Endpunkt"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "ungültige Länge"})
            return

        try:
            event = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "kein gültiges JSON"})
            return

        if not isinstance(event, dict) or event.get("type") not in ALLOWED_EVENTS:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "unbekannter Ereignistyp"})
            return

        if self.config.debug and self.config.log is not None:
            self.config.log.write(event)
            self._send_json(HTTPStatus.OK, {"logged": True})
        else:
            # Ohne Debug-Modus wird nichts geschrieben
            self._send_json(HTTPStatus.OK, {"logged": False})


def create_server(config: CasinoConfig, host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    """Erzeugt den Server (wird auch von den Tests verwendet)."""
    handler = partial(CasinoRequestHandler, directory=str(STATIC_DIR), config=config)
    return ThreadingHTTPServer((host, port), handler)


class BackgroundServer:
    """Startet den Server auf einem freien Port in einem Hintergrund-Thread
    (für Tests und Tools wie tools/record_mock_session.py)."""

    def __init__(self, config: CasinoConfig, port: int = 0):
        self.config = config
        self.httpd = create_server(config, port=port)  # Port 0 = Betriebssystem wählt frei
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "BackgroundServer":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def default_log_path(log_dir: Path = DEFAULT_LOG_DIR) -> Path:
    """Pro Serverstart eine eigene Datei, z. B. logs/ground_truth_20261007_142501.jsonl."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return log_dir / f"ground_truth_{stamp}.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock-Casino (Blackjack) lokal starten")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--debug", action="store_true", help="Ground-Truth-Log schreiben")
    parser.add_argument("--log-file", type=Path, help="Pfad der Ground-Truth-Datei")
    parser.add_argument("--decks", type=int, default=6)
    parser.add_argument("--penetration", type=float, default=0.75)
    parser.add_argument("--seed", type=int, help="Seed für reproduzierbares Mischen")
    parser.add_argument(
        "--shuffle-every-round", action="store_true", help="nach jeder Runde neu mischen"
    )
    parser.add_argument(
        "--hide-hole-card",
        action="store_true",
        help="Hole Card nur aufdecken, wenn der Dealer spielen muss",
    )
    args = parser.parse_args()

    if not 1 <= args.decks <= 8:
        parser.error("--decks muss zwischen 1 und 8 liegen")
    if not 0.1 <= args.penetration <= 0.95:
        parser.error("--penetration muss zwischen 0.1 und 0.95 liegen")

    log = None
    if args.debug:
        log = GroundTruthLog(args.log_file or default_log_path())

    config = CasinoConfig(
        debug=args.debug,
        decks=args.decks,
        penetration=args.penetration,
        seed=args.seed,
        shuffle_every_round=args.shuffle_every_round,
        hide_hole_card=args.hide_hole_card,
        log=log,
    )
    server = create_server(config, port=args.port)
    print(f"Mock-Casino läuft auf http://localhost:{args.port}  (Beenden mit Ctrl+C)")
    if log:
        print(f"Debug-Modus: Ground Truth wird geschrieben nach {log.path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer beendet.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
