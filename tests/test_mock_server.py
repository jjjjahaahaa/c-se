"""Tests für den Mock-Casino-Server (ohne Browser)."""

import json
import urllib.error
import urllib.request


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as res:
        return res.status, res.headers, res.read()


def _post(url, payload, raw=None):
    data = raw if raw is not None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def _lines(server):
    path = server.config.log.path
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_config_endpunkt(debug_server):
    status, _, body = _get(f"{debug_server.url}/api/config")
    config = json.loads(body)
    assert status == 200
    assert config["debug"] is True
    assert config["decks"] == 6
    assert config["penetration"] == 0.75


def test_statische_dateien_mit_richtigem_typ(plain_server):
    status, headers, body = _get(f"{plain_server.url}/index.html")
    assert status == 200 and b"Mock-Casino" in body
    _, headers, _ = _get(f"{plain_server.url}/js/game.js")
    assert headers["Content-Type"].startswith("text/javascript")
    _, headers, _ = _get(f"{plain_server.url}/assets/cards/AS.svg")
    assert headers["Content-Type"].startswith("image/svg+xml")


def test_debug_modus_schreibt_ground_truth(debug_server):
    event = {"type": "card", "rank": "K", "suit": "H", "target": "dealer", "seq": 1}
    status, body = _post(f"{debug_server.url}/api/log", event)
    assert status == 200 and body["logged"] is True
    lines = _lines(debug_server)
    assert len(lines) == 1
    assert lines[0]["rank"] == "K"
    assert "server_time" in lines[0]


def test_ohne_debug_wird_nichts_geschrieben(plain_server):
    status, body = _post(f"{plain_server.url}/api/log", {"type": "card", "rank": "2"})
    assert status == 200 and body["logged"] is False


def test_ungueltige_anfragen_werden_abgelehnt(debug_server):
    url = f"{debug_server.url}/api/log"
    assert _post(url, {"type": "hack"})[0] == 400
    assert _post(url, [1, 2, 3])[0] == 400
    assert _post(url, None, raw=b"{kein json")[0] == 400
    assert _post(f"{debug_server.url}/api/unbekannt", {"type": "card"})[0] == 404
    assert _lines(debug_server) == []
