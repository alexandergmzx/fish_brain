"""The page server's token rule and status report, on loopback sockets only."""
import http.client
import json
import socket
import time
import urllib.error
import urllib.request
import wave

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


def get(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def stream_head(server, path, timeout=3.0, want=b"", min_bytes=1):
    """Open an SSE stream and return the bytes read within `timeout` (stops early once
    `want` is in them and at least `min_bytes` arrived)."""
    conn = http.client.HTTPConnection("127.0.0.1", server._httpd.server_address[1],
                                      timeout=timeout)
    conn.request("GET", path)
    resp = conn.getresponse()
    got = b""
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            chunk = resp.fp.read1(4096) if hasattr(resp.fp, "read1") else resp.read(1)
            if not chunk:
                break
            got += chunk
            if want in got and len(got) >= min_bytes:
                break
    except (socket.timeout, OSError):
        pass
    finally:
        conn.close()
    return resp.status, got


def tiny_wav(path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 160)
    return path


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


def test_status_has_the_console_fields(server):
    server.set_listening(True)
    data = json.loads(get(server.url + "/status")[1])
    assert data["max_record_s"] == float(server.cfg.ptt.max_record_s)
    assert data["mic_capture"] == "host" and data["tls"] is False
    assert data["listening"] is True


def test_events_need_the_token(server):
    status, body = get(server.url + "/events")
    assert status == 403 and json.loads(body) == {"ok": False, "error": "bad token"}
    status, head = stream_head(server, "/events?token=s3cret-token", want=b"retry: 2000")
    assert status == 200
    assert b": connected" in head and b"retry: 2000\n\n" in head


def test_audio_needs_the_token(server):
    assert get(server.url + "/audio/1.wav")[0] == 403
    assert get(server.url + "/audio/1.wav?token=s3cret-token")[0] == 404


def test_trust_local_lets_this_machine_read_the_stream_and_audio(server):
    server.cfg.viz.trust_local = True
    assert get(server.url + "/audio/1.wav")[0] == 404
    status, head = stream_head(server, "/events", want=b"retry: 2000")
    assert status == 200 and b": connected" in head


def test_page_status_and_mics_stay_open(server):
    for path in ("/", "/index.html", "/fish.js", "/fish.css", "/status"):
        assert get(server.url + path)[0] == 200, path


def test_post_without_a_length_is_411(server):
    conn = http.client.HTTPConnection("127.0.0.1", server._httpd.server_address[1], timeout=3)
    conn.putrequest("POST", "/ptt?token=s3cret-token")
    conn.putheader("Content-Type", "application/json")
    conn.endheaders()
    resp = conn.getresponse()
    assert resp.status == 411 and json.loads(resp.read())["ok"] is False
    conn.close()


def test_post_over_the_cap_is_413(server):
    conn = http.client.HTTPConnection("127.0.0.1", server._httpd.server_address[1], timeout=3)
    conn.putrequest("POST", "/ptt?token=s3cret-token")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", str(VizServer.MAX_JSON_BYTES + 1))
    conn.endheaders()
    resp = conn.getresponse()
    assert resp.status == 413 and json.loads(resp.read())["error"] == "too large"
    conn.close()


def test_bad_json_is_400(server):
    req = urllib.request.Request(server.url + "/ptt?token=s3cret-token", data=b"{not json",
                                 headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=3)
    assert e.value.code == 400


def test_heartbeat_is_a_data_event(server, monkeypatch):
    monkeypatch.setattr(VizServer, "HEARTBEAT_S", 0.2)
    status, head = stream_head(server, "/events?token=s3cret-token", timeout=3,
                               want=b'data: {"type":"hb"}')
    assert status == 200 and b'data: {"type":"hb"}\n\n' in head
    assert b"keep-alive" not in head


def test_replayed_speak_event_carries_its_age(server, tmp_path):
    server.announce_speech(tiny_wav(tmp_path / "a.wav"), 10, [], [(0, 0.5)])
    live = json.loads(server._last_event)
    assert live["type"] == "speak" and live["age_ms"] == 0
    time.sleep(0.05)
    q = server._subscribe()
    replayed = json.loads(q.get_nowait())
    assert replayed["audio"] == live["audio"] and replayed["age_ms"] > 0
    server._unsubscribe(q)


def test_live_speak_event_has_age_zero_and_the_audio_is_served(server, tmp_path):
    q = server._subscribe()
    server.announce_speech(tiny_wav(tmp_path / "a.wav"), 10, [], [])
    event = json.loads(q.get_nowait())
    assert event["age_ms"] == 0
    assert get(server.url + event["audio"] + "?token=s3cret-token")[0] == 200
    server._unsubscribe(q)


def test_ninth_subscriber_evicts_the_first(server):
    queues = [server._subscribe() for _ in range(VizServer.MAX_SUBSCRIBERS)]
    ninth = server._subscribe()
    assert queues[0].get_nowait() is None           # the sentinel ends its handler loop
    assert queues[0] not in server._subscribers
    assert len(server._subscribers) == VizServer.MAX_SUBSCRIBERS
    for q in queues[1:] + [ninth]:
        assert q.empty()
        server._unsubscribe(q)


def test_inbox_only_takes_while_listening(server):
    assert server.offer("x") is False and server.take_inbox() is None
    server.set_listening(True)
    assert server.listening is True
    assert server.offer("a") and server.offer("b")
    assert server.offer("c") is False               # full: two items at most
    assert server.take_inbox() == "a" and server.take_inbox() == "b"
    assert server.take_inbox() is None
