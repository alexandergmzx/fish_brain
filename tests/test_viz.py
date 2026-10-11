"""The page server's token rule and status report, on loopback sockets only."""
import json
import urllib.error
import urllib.request

import pytest

from fish_brain import viz as viz_mod
from fish_brain.config import Config
from fish_brain.viz import VizServer, _is_loopback


@pytest.fixture
def server():
    cfg = Config()
    cfg.viz.host, cfg.viz.port, cfg.viz.token = "127.0.0.1", 0, "s3cret-token"
    srv = VizServer(cfg)
    srv.start()
    srv.url = f"http://127.0.0.1:{srv._httpd.server_address[1]}"
    yield srv
    srv.stop()


def post(url, body, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_post_needs_the_token(server):
    assert post(server.url + "/ptt", {"down": False})[0] == 403
    assert post(server.url + "/ptt", {"down": False}, {"X-Fish-Token": "s3cret-token"})[0] == 200
    assert post(server.url + "/ptt?token=s3cret-token", {"down": False})[0] == 200


def test_trust_local_lets_this_machine_in_without_it(server):
    server.cfg.viz.trust_local = True
    assert post(server.url + "/ptt", {"down": False})[0] == 200


def test_trust_local_is_only_for_loopback(server, monkeypatch):
    server.cfg.viz.trust_local = True
    monkeypatch.setattr(viz_mod, "_is_loopback", lambda addr: False)   # as if from the LAN
    assert post(server.url + "/ptt", {"down": False})[0] == 403


@pytest.mark.parametrize("addr,want", [
    ("127.0.0.1", True), ("127.8.9.1", True), ("::1", True), ("::ffff:127.0.0.1", True),
    ("192.168.1.114", False), ("10.42.0.7", False), ("::ffff:192.168.1.5", False),
    ("fe80::1", False), ("not-an-address", False)])
def test_is_loopback(addr, want):
    assert _is_loopback(addr) is want


def test_status_reports_and_never_leaks(server):
    server.register_status(lambda: {"link": {"desc": "serial /dev/ttyHS1", "health": "ok"},
                                    "online": True, "backends": {"tts": "loq"}})
    with urllib.request.urlopen(server.url + "/status", timeout=3) as r:
        text = r.read().decode()
    data = json.loads(text)
    assert data["ok"] is True and data["link"]["health"] == "ok" and data["online"] is True
    assert data["ready"] is False and "up_s" in data and "ip" in data
    assert "s3cret-token" not in text


def test_status_survives_a_failing_provider(server):
    def boom():
        raise RuntimeError("secret detail")
    server.register_status(boom)
    with urllib.request.urlopen(server.url + "/status", timeout=3) as r:
        text = r.read().decode()
    assert json.loads(text)["status_error"] == "RuntimeError" and "secret detail" not in text
