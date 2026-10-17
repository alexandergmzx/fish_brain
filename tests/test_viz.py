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
from fish_brain.viz import CertificateError, VizServer, _is_loopback


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
    for path in ("/", "/index.html", "/face", "/fish.js", "/fish.css", "/rec.js", "/status"):
        assert get(server.url + path)[0] == 200, path


def test_root_is_the_operators_page_and_face_the_old_one(server):
    # No hub here: the page itself is still served (its data routes answer 404, it says so).
    for path in ("/", "/index.html", "/debug"):
        assert b'src="/debug.js"' in get(server.url + path)[1], path
    assert b'src="/fish.js"' in get(server.url + "/face")[1]


def test_his_hat_sprites_are_served_from_img_hat(server):
    hat = viz_mod.WEB_DIR / "img" / "hat"
    for m in range(4):
        name = f"neckRest_mouth{m}_tailRest.png"
        status, body = get(server.url + "/img/" + name)
        assert status == 200 and body == (hat / name).read_bytes(), name
    assert get(server.url + "/img/neckOut_mouth0_tailFlap.png")[0] == 404   # the fish's, parked


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


def test_a_filler_is_marked_and_never_the_replayed_event(server, tmp_path):
    q = server._subscribe()
    server.announce_speech(tiny_wav(tmp_path / "reply.wav"), 10, [], [])
    reply = json.loads(q.get_nowait())
    server.announce_speech(tiny_wav(tmp_path / "wait.wav"), 10, [], [], filler=True)
    filler = json.loads(q.get_nowait())
    assert filler["filler"] is True and "filler" not in reply
    assert filler["audio"] != reply["audio"]
    late = server._subscribe()                       # a page that connects now
    assert json.loads(late.get_nowait())["audio"] == reply["audio"]
    server._unsubscribe(q)
    server._unsubscribe(late)


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


# --- the reading: /badge and /reading --------------------------------------------------
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
AUTH = {"X-Fish-Token": "s3cret-token"}


def post_raw(url, body, headers):
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def post_badge(server, body=JPEG, headers=None, ctype="image/jpeg"):
    return post_raw(server.url + "/badge", body, {"Content-Type": ctype, **(headers or {})})


class StubReader:
    def __init__(self, found=True):
        self.found = found
        self.calls = []

    def __call__(self, data, want_look):
        from fish_brain.reading import BadgeRead
        self.calls.append((len(data), want_look))
        if not self.found:
            return BadgeRead(found=False)
        return BadgeRead(found=True, full_name="Garcia Lopez Maria Jose",
                         name_for_speech="María José", confidence="high",
                         look="gorra roja" if want_look else None)


def test_badge_without_a_reader_is_503(server):
    assert post_badge(server, headers=AUTH) == (503, {"ok": False, "error": "no reader"})


def test_badge_needs_the_token(server):
    server.register_reader(StubReader())
    assert post_badge(server)[0] == 403


def test_badge_over_the_cap_is_413(server):
    server.register_reader(StubReader())
    conn = http.client.HTTPConnection("127.0.0.1", server._httpd.server_address[1], timeout=3)
    conn.putrequest("POST", "/badge?token=s3cret-token")
    conn.putheader("Content-Type", "image/jpeg")
    conn.putheader("Content-Length", str(server.cfg.reading.max_image_bytes + 1))
    conn.endheaders()
    resp = conn.getresponse()
    assert resp.status == 413
    conn.close()


def test_badge_wrong_magic_or_type_is_400(server):
    reader = StubReader()
    server.register_reader(reader)
    assert post_badge(server, body=b"\x89PNG" + b"\x00" * 20, headers=AUTH)[0] == 400
    assert post_badge(server, headers=AUTH, ctype="image/png")[0] == 400
    assert reader.calls == []


def test_badge_found_queues_an_unconfirmed_reading(server):
    from fish_brain.reading import Reading
    reader = StubReader()
    server.register_reader(reader)
    server.set_listening(True)
    status, out = post_badge(server, headers=AUTH)
    assert status == 200
    assert out == {"ok": True, "found": True, "name": "Garcia Lopez Maria Jose",
                   "first_name": "María José", "confidence": "high"}
    item = server.take_inbox()
    assert isinstance(item, Reading) and item.confirmed is False
    assert item.name == "Garcia Lopez Maria Jose" and item.first_name == "María José"
    assert item.look is None
    assert reader.calls == [(len(JPEG), False)]
    # Nothing of the photo stays on the server object.
    for value in server.__dict__.values():
        assert not (isinstance(value, (bytes, bytearray)) and JPEG[:4] in value)
    assert JPEG[:4] not in repr(server.__dict__).encode("latin-1", "ignore")


def test_badge_not_found_answers_found_false(server):
    server.register_reader(StubReader(found=False))
    server.set_listening(True)
    assert post_badge(server, headers=AUTH) == (200, {"ok": True, "found": False})
    assert server.take_inbox() is None


def test_badge_while_not_listening_is_busy(server):
    server.register_reader(StubReader())
    assert post_badge(server, headers=AUTH) == (409, {"ok": False, "busy": True})


def test_badge_look_header_follows_the_setting(server):
    reader = StubReader()
    server.register_reader(reader)
    server.set_listening(True)
    server.cfg.reading.look = False
    post_badge(server, headers={**AUTH, "X-Fish-Look": "1"})
    assert reader.calls[-1][1] is False and server.take_inbox().look is None
    server.cfg.reading.look = True
    post_badge(server, headers={**AUTH, "X-Fish-Look": "1"})
    assert reader.calls[-1][1] is True and server.take_inbox().look == "gorra roja"
    post_badge(server, headers=AUTH)
    assert reader.calls[-1][1] is False


def test_badge_cloud_errors_are_503(server):
    from fish_brain import cloud

    def offline(data, want_look):
        raise cloud.CloudUnavailable("offline")

    def bad_key(data, want_look):
        raise cloud.CloudMisconfigured("OPENAI_API_KEY is not set")

    server.register_reader(offline)
    assert post_badge(server, headers=AUTH) == (503, {"ok": False, "error": "offline"})
    server.register_reader(bad_key)
    status, out = post_badge(server, headers=AUTH)
    assert (status, out["error"]) == (503, "misconfigured") and "KEY" not in json.dumps(out)


def test_badge_says_the_canned_lines(server):
    class Mouth:
        said = []

        def say_canned(self, name):
            self.said.append(name)
            return True

    server.register_speaker(Mouth())
    server.register_reader(StubReader(found=False))
    server.set_listening(True)
    post_badge(server, headers=AUTH)
    assert Mouth.said == [server.cfg.canned.reading_wait, server.cfg.canned.reading_fail]


def test_reading_queues_a_confirmed_name(server):
    from fish_brain.reading import Reading
    server.set_listening(True)
    status, out = post(server.url + "/reading", {"name": " maría   JOSÉ, garcía "}, AUTH)
    assert status == 200 and out == {"ok": True, "name": "María José García"}
    item = server.take_inbox()
    assert isinstance(item, Reading) and item.confirmed is True
    assert item.name == "María José García" and item.first_name == "María"
    assert post(server.url + "/reading", {"name": "!!!"}, AUTH)[0] == 400
    assert post(server.url + "/reading", {"name": "Ana"})[0] == 403


def test_reading_while_not_listening_is_busy(server):
    assert post(server.url + "/reading", {"name": "Ana"}, AUTH) == (409, {"ok": False, "busy": True})


def test_status_says_whether_a_reader_is_there(server):
    data = json.loads(get(server.url + "/status")[1])
    assert data["reading"] is False and data["reading_look"] is False
    server.register_reader(StubReader())
    server.cfg.reading.look = True
    data = json.loads(get(server.url + "/status")[1])
    assert data["reading"] is True and data["reading_look"] is True


# --- the HTTPS listener (FISH_VIZ_TLS_CERT / FISH_VIZ_TLS_KEY) ---
import shutil
import ssl
import subprocess

needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not found")


@pytest.fixture
def cert_pair(tmp_path):
    crt, key = tmp_path / "t.crt", tmp_path / "t.key"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-days", "2",
                    "-noenc", "-keyout", str(key), "-out", str(crt), "-subj", "/CN=localhost",
                    "-addext", "subjectAltName=IP:127.0.0.1"],
                   check=True, capture_output=True)
    return crt, key


@pytest.fixture
def tls_server(cert_pair):
    cfg = Config()
    cfg.viz.host, cfg.viz.port, cfg.viz.token = "127.0.0.1", 0, "s3cret-token"
    cfg.viz.tls_cert, cfg.viz.tls_key, cfg.viz.tls_port = str(cert_pair[0]), str(cert_pair[1]), 0
    srv = VizServer(cfg)
    srv.start()
    srv.url = f"http://127.0.0.1:{srv._httpd.server_address[1]}"
    srv.tls_url = f"https://127.0.0.1:{srv.tls_port_bound}"
    yield srv
    srv.stop()


def get_https(url, timeout=3):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(url, timeout=timeout, context=ctx) as r:
        return r.status, r.read()


@needs_openssl
def test_status_over_https(tls_server):
    status, body = get_https(tls_server.tls_url + "/status")
    assert status == 200
    data = json.loads(body)
    assert data["tls"] is True
    assert b"s3cret-token" not in body
    # The plain listener is untouched.
    status, body = get(tls_server.url + "/status")
    assert status == 200 and json.loads(body)["tls"] is True


@needs_openssl
def test_a_silent_client_does_not_block_the_tls_listener(tls_server):
    silent = socket.create_connection(("127.0.0.1", tls_server.tls_port_bound))
    try:
        t0 = time.monotonic()
        status, _ = get_https(tls_server.tls_url + "/status", timeout=2)
        assert status == 200
        assert time.monotonic() - t0 < 1.0
    finally:
        silent.close()


@needs_openssl
def test_a_plain_http_client_on_the_tls_port_is_dropped(tls_server):
    with pytest.raises((urllib.error.URLError, ConnectionError, OSError)):
        get(tls_server.tls_url.replace("https", "http") + "/status", timeout=3)
    assert get_https(tls_server.tls_url + "/status")[0] == 200


def test_a_wrong_certificate_path_is_an_oserror(tmp_path):
    cfg = Config()
    cfg.viz.host, cfg.viz.port, cfg.viz.tls_port = "127.0.0.1", 0, 0
    cfg.viz.tls_cert, cfg.viz.tls_key = str(tmp_path / "no.crt"), str(tmp_path / "no.key")
    srv = VizServer(cfg)
    with pytest.raises(CertificateError):     # an OSError: app.py maps it to exit 78
        srv.start()
    srv.stop()


def test_a_busy_port_is_not_a_certificate_error():
    """A busy port is transient (a quick restart): the unit must retry, not stop at 78."""
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    try:
        cfg = Config()
        cfg.viz.host, cfg.viz.port = "127.0.0.1", holder.getsockname()[1]
        srv = VizServer(cfg)
        with pytest.raises(OSError) as info:
            srv.start()
        assert not isinstance(info.value, CertificateError)
        srv.stop()
    finally:
        holder.close()


def test_no_environment_means_plain_http_only(monkeypatch):
    for name in ("FISH_VIZ_TLS_CERT", "FISH_VIZ_TLS_KEY", "FISH_VIZ_TLS_PORT", "FISH_SAY_ADDRESS"):
        monkeypatch.delenv(name, raising=False)
    cfg = Config()
    assert cfg.viz.tls_cert == "" and cfg.viz.tls_key == ""
    assert cfg.viz.tls_port == 8724 and cfg.viz.say_address is False
    cfg.viz.host, cfg.viz.port = "127.0.0.1", 0
    srv = VizServer(cfg)
    srv.start()
    try:
        assert srv.tls_port_bound is None
        status, body = get(f"http://127.0.0.1:{srv._httpd.server_address[1]}/status")
        assert status == 200 and json.loads(body)["tls"] is False
    finally:
        srv.stop()


# --- the phone's microphone: /utterance and the listen event ----------------------------
import glob
import io
import os
import tempfile


def wav_bytes(seconds=0.5, rate=16000, channels=1):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00" * int(seconds * rate) * channels)
    return buf.getvalue()


def post_utt(server, body, headers=None, ctype="audio/wav"):
    return post_raw(server.url + "/utterance", body, {"Content-Type": ctype, **(headers or {})})


def pending_uploads():
    return set(glob.glob(os.path.join(tempfile.gettempdir(), "fish_in_*.wav")))


def test_utterance_needs_the_token(server):
    assert post_utt(server, wav_bytes())[0] == 403


def test_utterance_over_the_cap_is_413(server):
    conn = http.client.HTTPConnection("127.0.0.1", server._httpd.server_address[1], timeout=3)
    conn.putrequest("POST", "/utterance?token=s3cret-token")
    conn.putheader("Content-Type", "audio/wav")
    conn.putheader("Content-Length", str(VizServer.MAX_WAV_BYTES + 1))
    conn.endheaders()
    resp = conn.getresponse()
    assert resp.status == 413
    conn.close()


def test_utterance_rejects_what_is_not_a_short_mono_wav(server):
    server.set_listening(True)
    before = pending_uploads()
    assert post_utt(server, b"RIFF" + b"\x00" * 60, headers=AUTH) == (400, {"ok": False, "error": "not a WAV"})
    assert post_utt(server, wav_bytes(), headers=AUTH, ctype="application/octet-stream")[0] == 400
    assert post_utt(server, wav_bytes(channels=2), headers=AUTH) == (400, {"ok": False, "error": "mono expected"})
    # 40 s at 8 kHz is 640 kB: under the byte cap, over the recording limit.
    assert post_utt(server, wav_bytes(seconds=40, rate=8000), headers=AUTH) == (400, {"ok": False, "error": "too long"})
    assert post_utt(server, wav_bytes(rate=4000), headers=AUTH)[0] == 400
    assert server.take_inbox() is None
    assert pending_uploads() == before


def test_utterance_while_not_listening_is_busy_and_leaves_no_file(server):
    before = pending_uploads()
    assert post_utt(server, wav_bytes(), headers=AUTH) == (409, {"ok": False, "busy": True})
    assert pending_uploads() == before


def test_utterance_lands_in_the_inbox(server, capsys):
    from fish_brain.ptt import wav_duration_s
    from fish_brain.reading import Utterance
    server.set_listening(True)
    before = pending_uploads()
    status, out = post_utt(server, wav_bytes(0.5), headers={**AUTH, "X-Fish-Hold-Ms": "1200"})
    assert (status, out) == (200, {"ok": True})
    item = server.take_inbox()
    assert isinstance(item, Utterance)
    assert item.path.exists() and item.path.name.startswith("fish_in_")
    assert item.path.suffix == ".wav" and str(item.path) in pending_uploads() - before
    assert wav_duration_s(item.path) == 0.5
    assert item.hold_s == 1.2 and 0.0 <= item.upload_s < 2.0
    line = capsys.readouterr().out
    assert "[utt] 16000 Hz 0.5 s" in line and "upload=" in line
    item.path.unlink()


def test_listen_event_follows_set_listening(server):
    q = server._subscribe()
    server.set_listening(True)
    server.set_listening(True)                     # no change: no second event
    server.set_listening(False)
    events = []
    while not q.empty():
        events.append(json.loads(q.get_nowait()))
    assert events == [{"type": "listen", "ready": True}, {"type": "listen", "ready": False}]
    server._unsubscribe(q)


def test_rec_js_is_served(server):
    status, body = get(server.url + "/rec.js")
    assert status == 200 and b"fish-rec" in body


# --- pages with a microphone (/micstate) and the relayed remote -----------------------
def test_micstate_needs_the_token(server):
    assert post(server.url + "/micstate", {"ready": True, "page": "p1"})[0] == 403


def test_micstate_counts_ready_pages_and_forgets_them(server):
    assert server.mic_pages() == 0
    assert post(server.url + "/micstate", {"ready": True, "page": "p1"}, AUTH) == (200, {"ok": True})
    assert post(server.url + "/micstate", {"ready": True, "page": "p2"}, AUTH) == (200, {"ok": True})
    assert post(server.url + "/micstate", {"ready": True, "page": "p1"}, AUTH)[0] == 200   # keep-alive
    assert server.mic_pages() == 2
    assert json.loads(get(server.url + "/status")[1])["mic_pages"] == 2
    assert post(server.url + "/micstate", {"ready": False, "page": "p2"}, AUTH) == (200, {"ok": True})
    assert server.mic_pages() == 1
    assert post(server.url + "/micstate", {"ready": False, "page": "nobody"}, AUTH)[0] == 200
    assert server.mic_pages() == 1


def test_micstate_without_a_page_is_400(server):
    assert post(server.url + "/micstate", {"ready": True}, AUTH)[0] == 400


def test_mic_pages_expire(server, monkeypatch):
    server.set_mic_state("p1", True)
    assert server.mic_pages() == 1
    monkeypatch.setattr(VizServer, "MIC_PAGE_TTL_S", 0.05)
    time.sleep(0.1)
    assert server.mic_pages() == 0
    assert json.loads(get(server.url + "/status")[1])["mic_pages"] == 0


def test_relay_ptt_publishes_sourced_events(server):
    q = server._subscribe()
    server.relay_ptt(True)
    server.relay_ptt(False)
    server.reset_ptt()                             # the page's own press, ended by the host
    events = []
    while not q.empty():
        events.append(json.loads(q.get_nowait()))
    assert events == [{"type": "ptt", "held": True, "source": "remote"},
                      {"type": "ptt", "held": False, "source": "remote"},
                      {"type": "ptt", "held": False}]
    server._unsubscribe(q)


# --- the debug page: its own routes and stream (docs/debug.md) ---

@pytest.fixture
def dbg(server):
    from fish_brain import debug
    hub = debug.DebugHub(server.cfg)
    server.register_debug(hub)
    return hub


def test_debug_page_is_served_and_its_data_needs_the_token(server, dbg):
    for path in ("/debug", "/debug/", "/debug.html", "/debug.js", "/debug.css"):
        assert get(server.url + path)[0] == 200, path
    assert get(server.url + "/debug/state")[0] == 403
    status, body = get(server.url + "/debug/state?token=s3cret-token")
    st = json.loads(body)
    assert status == 200 and st["ok"] and st["boot"] == dbg.boot
    assert "s3cret-token" not in body.decode()
    assert get(server.url + "/debug/rec.wav")[0] == 403
    assert get(server.url + "/debug/rec.wav?token=s3cret-token")[0] == 404
    assert stream_head(server, "/debug/events")[0] == 403


def test_debug_routes_do_not_exist_without_a_hub(server):
    assert get(server.url + "/debug/state?token=s3cret-token")[0] == 404
    assert post(server.url + "/debug/stop", {}, {"X-Fish-Token": "s3cret-token"})[0] == 404


def test_debug_posts_need_json_and_actions(server, dbg):
    tok = {"X-Fish-Token": "s3cret-token"}
    req = urllib.request.Request(server.url + "/debug/arm", data=b"on=1", headers={
        **tok, "Content-Type": "application/x-www-form-urlencoded"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=3)
    assert e.value.code == 415                     # a form from another web page cannot press it
    req = urllib.request.Request(server.url + "/debug/arm", data=b'{"on":true}', headers={
        **tok, "Content-Type": "text/plain; application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=3)
    assert e.value.code == 415                     # nor a "simple" request dressed as JSON
    assert post(server.url + "/debug/arm", {"on": True})[0] == 403
    assert post(server.url + "/debug/arm", {"on": True}, tok)[0] == 409      # no actions yet


def test_debug_stream_replays_the_rings_and_phones_get_nothing_new(server, dbg):
    phone = server._subscribe()
    dbg.emit("log", stream="out", tag="turn", thread="MainThread", text="[turn] rec=1.2s")
    dbg.emit("key", dev="/dev/input/event3", name="R", key="BTN_LEFT", code=272, value=1,
             configured=False)
    assert phone.empty()                           # a debug record never reaches a phone
    status, head = stream_head(server, "/debug/events?token=s3cret-token", want=b"BTN_LEFT")
    text = head.decode()
    assert status == 200 and '"kind": "hello"' in text
    assert "[turn] rec=1.2s" in text and "BTN_LEFT" in text and f"id: {dbg.boot}-2" in text
    assert len(server._subscribers) == 1           # and takes none of the phones' places


def test_page_events_are_copied_for_the_debug_page(server, tmp_path):
    from fish_brain import debug
    hub = debug.install(server.cfg)
    try:
        server.register_debug(hub)
        server.push_transcript("hola", "user")
        server.push_level(0.12)
        assert hub.recent("page")[-1]["ev"] == {"type": "stt", "role": "user", "text": "hola"}
        assert hub.recent("level")[-1]["rms"] == 0.12
        phone = server._subscribe()
        server.announce_speech(tiny_wav(tmp_path / "s.wav"), 400, [(0, "NECK", "230 650")],
                               [(0, 0.5), (400, 0.0)])
        mine = hub.recent("page")[-1]["ev"]              # the debug page's fish moves with these
        assert mine["type"] == "speak" and mine["mouth"] == [[0, 0.5], [400, 0.0]]
        assert mine["gestures"] == [[0, "NECK", "230 650"]]
        assert json.loads(phone.get_nowait())["mouth"] == mine["mouth"]     # the phones' event as before
    finally:
        debug.uninstall()


def test_status_keys_are_unchanged_by_the_debug_view(server, dbg):
    status, body = get(server.url + "/status")
    assert set(json.loads(body)) == {"ok", "up_s", "host", "ip", "ready", "wait", "max_record_s",
                                     "mic_capture", "tls", "listening", "mic_pages", "reading",
                                     "reading_look", "visit_enabled"}


# ---- the hat's visit: /visit and /cues ------------------------------------------------------
def _visit(server):
    from fish_brain.visit import Visit
    v = Visit()
    server.register_visit(v)
    return v


def test_visit_and_cues_need_the_token_and_a_visit(server):
    assert post(server.url + "/visit", {})[0] == 403
    assert post(server.url + "/cues", {"cues": {}})[0] == 403
    assert post(server.url + "/visit", {}, AUTH) == (503, {"ok": False, "error": "no visit"})
    assert post(server.url + "/cues", {"cues": {}}, AUTH)[0] == 503


def test_new_visit_while_busy_is_409_and_withdraws_its_request(server):
    v = _visit(server)
    v.start()
    assert post(server.url + "/visit", {}, AUTH) == (409, {"ok": False, "busy": True})
    assert not v.needs_new(time.monotonic())
    assert server.take_inbox() is None


def test_new_visit_queues_an_item_and_leaves_wait_alone(server):
    from fish_brain.visit import NewVisit
    v = _visit(server)
    v.start()
    server.set_listening(True)
    wait = server.status()["wait"]
    assert post(server.url + "/visit", {}, AUTH) == (200, {"ok": True})
    item = server.take_inbox()
    assert isinstance(item, NewVisit) and v.needs_new(time.monotonic())
    assert server.status()["wait"] == wait


def test_cues_are_set_checked_and_never_in_status(server):
    v = _visit(server)
    v.start("Ana")
    status, out = post(server.url + "/cues",
                       {"cues": {"edad": "niño", "lleva": "gorra [roja]"}}, AUTH)
    assert status == 200 and out["visit"]["cues"] == {"edad": "niño", "lleva": "gorra roja"}
    assert v.pending() == {"edad": "niño", "lleva": "gorra roja"}
    status, out = post(server.url + "/cues", {"cues": {"sabor": "fresa secreta"}}, AUTH)
    assert status == 400 and "fresa" not in json.dumps(out)
    assert post(server.url + "/cues", {"cues": "nope"}, AUTH)[0] == 400
    assert v.pending() == {"edad": "niño", "lleva": "gorra roja"}       # a refusal changes nothing
    st = get(server.url + "/status")[1].decode()
    assert json.loads(st)["visit_enabled"] is True
    text = json.dumps(json.loads(st), ensure_ascii=False)
    assert not any(x in text for x in ("gorra", "Ana", "niño"))


def test_status_says_visit_only_when_registered(server):
    assert server.status()["visit_enabled"] is False
    _visit(server)
    assert server.status()["visit_enabled"] is True


def test_a_page_that_connects_gets_the_visits_view(server):
    v = _visit(server)
    v.start("Ana")
    q = server._subscribe()
    events = []
    while not q.empty():
        events.append(json.loads(q.get_nowait()))
    seen = [e for e in events if e.get("type") == "visit"]
    assert seen and seen[-1]["first"] == "Ana" and seen[-1]["stage"] == 1
    server.push_visit(**v.view())
    assert json.loads(q.get_nowait())["type"] == "visit"


def test_an_unread_badge_asks_for_a_new_visitor(server):
    v = _visit(server)
    v.start()
    server.register_reader(StubReader(found=False))
    server.set_listening(True)
    assert post_badge(server, headers=AUTH)[1]["found"] is False
    assert v.needs_new(time.monotonic())


def test_a_first_debug_stream_with_tail_replays_only_the_last_records(server, dbg):
    for i in range(50):
        dbg.emit("log", stream="out", tag="t", thread="x", text=f"line {i}")
    status, head = stream_head(server, "/debug/events?token=s3cret-token&tail=5&page=p1",
                               want=b"line 49")
    text = head.decode()
    assert status == 200 and "line 49" in text and "line 45" in text and "line 44" not in text
