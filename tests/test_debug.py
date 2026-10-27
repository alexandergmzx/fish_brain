"""The debug hub: the log tee, the rings, the scrubber, the state. No hardware, no network."""
import io
import os
import struct
import sys
import threading
import wave

import pytest

from fish_brain import debug, debug_state
from fish_brain.config import Config


@pytest.fixture
def make_hub(monkeypatch):
    """The hub is installed inside the test body: pytest swaps sys.stdout between a
    fixture's set-up and the test, and the tee must sit on the stream the test prints to."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-FAKEFAKEFAKE1234")

    def make():
        cfg = Config()
        cfg.viz.token = "s3cret-token"
        return debug.install(cfg)
    yield make
    debug.uninstall()


def lines(h, tag=None):
    return [r["text"] for r in h.recent("log", 500) if tag is None or r["tag"] == tag]


def test_hooks_without_a_hub_do_nothing():
    assert debug.hub() is None
    debug.emit("x", a=1)
    debug.tx("MOUTH 1 2")
    debug.turn_open()
    debug.turn_close("error", RuntimeError("x"))
    debug.key("/dev/input/event1", "n", 28, "KEY_ENTER", 1, True)


def test_tee_passes_output_through_and_keeps_tagged_lines(make_hub, capsys):
    hub = make_hub()
    print("[turn] rec=1.2s stt=0.8s link=ok", flush=True)
    print("you> hola", flush=True)
    print("[cloud] offline", file=sys.stderr, flush=True)
    print("no newline yet", end="")
    out = capsys.readouterr()
    assert "[turn] rec=1.2s" in out.out and "[cloud] offline" in out.err   # the real streams first
    recs = hub.recent("log", 10)
    assert [(r["tag"], r["stream"]) for r in recs] == [("turn", "out"), ("you", "out"), ("cloud", "err")]
    print(" ... done")
    assert lines(hub)[-1] == "no newline yet ... done"


def test_lines_from_two_threads_do_not_interleave(make_hub):
    hub = make_hub()
    def talk(name):
        for i in range(50):
            print(f"[{name}] part one,", end=" ")
            print(f"part two {i}")
    ts = [threading.Thread(target=talk, args=(n,)) for n in ("aa", "bb")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    got = lines(hub)
    assert len(got) == 100
    assert all(l.count("part one") == 1 and l.count("part two") == 1 for l in got)


def test_a_broken_hub_never_breaks_a_print_or_a_hook(make_hub, capsys):
    hub = make_hub()
    hub._log_line = lambda *a: 1 / 0
    hub.emit = lambda *a, **k: 1 / 0
    print("still printed")
    debug.tx("MOUTH 238 104")
    debug.turn_close("error", RuntimeError("x"))
    assert "still printed" in capsys.readouterr().out
    assert hub.errors >= 2


def test_a_write_from_inside_the_hub_passes_straight_through(make_hub, capsys):
    hub = make_hub()
    real = hub._log_line
    def chatty(stream, line):
        print("from inside")                 # would recurse without the pass-through flag
        real(stream, line)
    hub._log_line = chatty
    print("one line")
    assert capsys.readouterr().out.count("from inside") == 1
    assert lines(hub) == ["one line"]


def test_uninstall_restores_the_streams():
    before = sys.stdout, sys.stderr
    debug.install(Config())
    assert sys.stdout is not before[0]
    debug.uninstall()
    assert (sys.stdout, sys.stderr) == before and debug.hub() is None


def test_secrets_are_scrubbed_and_key_codes_are_not(make_hub):
    hub = make_hub()
    print("[llm] luna AuthenticationError: bad key sk-test-FAKEFAKEFAKE1234 for you")
    print("[viz] open /?token=s3cret-token on the phone")
    print("[cloud] header Bearer abcdefgh12345678")
    print("[ptt] evdev: listening on /dev/input/event2 'Remote' for KEY_ENTER")
    debug.turn_open()
    debug.turn_close("error", RuntimeError("401 with sk-test-FAKEFAKEFAKE1234"))
    blob = repr(hub.since(0, 500))
    assert "FAKEFAKE" not in blob and "s3cret-token" not in blob and "abcdefgh12345678" not in blob
    assert "KEY_ENTER" in blob


def test_rings_are_bounded_and_the_first_lines_survive(make_hub):
    hub = make_hub()
    for i in range(debug.LOG_LINES + 300):
        print(f"[turn] line {i}")
    assert len(hub.recent("log", 10 ** 6)) == debug.LOG_LINES
    replay = []
    seq = 0
    while True:
        chunk = hub.since(seq, 200)
        if not chunk:
            break
        assert len(chunk) <= 200
        replay += [r["text"] for r in chunk if r["kind"] == "log"]
        seq = chunk[-1]["seq"]
    assert replay[0] == "[turn] line 0" and replay[-1] == f"[turn] line {debug.LOG_LINES + 299}"
    assert len(replay) == debug.LOG_LINES + debug.BOOT_LINES


def _wav(tmp_path, samples, rate=16000):
    p = tmp_path / "r.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return p


def test_recording_stats_tell_zeros_from_a_quiet_room(make_hub, tmp_path):
    hub = make_hub()
    debug.recording(_wav(tmp_path, [0] * 16000))
    dead = hub.recording_stats()
    assert dead["zero_frac"] == 1.0 and dead["rms"] == 0.0 and dead["dur_s"] == 1.0
    debug.recording(_wav(tmp_path, [(-1) ** i * 40 for i in range(16000)]))
    quiet = hub.recording_stats()
    assert quiet["zero_frac"] == 0.0 and 0 < quiet["rms"] < 0.005
    assert hub.recording_bytes()[:4] == b"RIFF"       # the newest only
    debug.recording(_wav(tmp_path, [32767] * 800), "microphone check")
    assert hub.recording_stats()["clip_frac"] == 1.0 and hub.recording_stats()["origin"] == "microphone check"


def test_turn_record_carries_times_outcome_and_the_recording(make_hub, tmp_path):
    hub = make_hub()
    debug.turn_open()
    debug.recording(_wav(tmp_path, [0] * 8000))
    debug.turn_set(trigger="remote", times={"rec": 0.5, "stt": 0.0}, outcome="silence")
    debug.turn_close()
    debug.turn_open()
    debug.turn_close()                               # nothing happened: no record
    debug.turn_open()
    debug.turn_set(times={"rec": 1.0})
    debug.turn_close("offline", RuntimeError("no network"))
    t1, t2 = hub.recent("turn")
    assert (t1["id"], t1["outcome"], t1["rec"]["zero_frac"], t1["times"]["rec"]) == (1, "silence", 1.0, 0.5)
    assert (t2["id"], t2["outcome"], t2["error"]["type"]) == (2, "offline", "RuntimeError")
    assert "rec" not in t2


def test_a_key_that_is_not_the_button_is_recorded_and_text_keys_are_only_counted(make_hub):
    hub = make_hub()
    debug.key("/dev/input/event3", "Remote Mouse", 272, "BTN_LEFT", 1, False, True, False)
    debug.key("/dev/input/event3", "Remote Mouse", 272, "BTN_LEFT", 0, False, True, False)
    debug.key("/dev/input/event9", "Keyboard", 30, "KEY_A", 1, False)      # a letter
    debug.key("/dev/input/event2", "Remote", 28, "KEY_ENTER", 2, True)      # autorepeat
    keys = hub.recent("key")
    assert [k["key"] for k in keys] == ["BTN_LEFT", "BTN_LEFT", "text key"]
    assert "KEY_A" not in repr(hub.since(0, 500))
    press = hub.recent("press")[-1]
    assert (press["key"], press["outcome"], press["configured"]) == ("BTN_LEFT", "not configured", False)
    assert hub._key_other == {"BTN_LEFT": 1} and hub._text_keys == 1


def test_state_never_carries_a_secret_and_survives_a_failing_section(make_hub, monkeypatch):
    hub = make_hub()
    hub.cfg.viz.tls_key = "/fake/tls.key"
    monkeypatch.setattr(debug_state, "system", lambda: 1 / 0)
    st = hub.state()
    blob = repr(st)
    assert "s3cret-token" not in blob and "FAKEFAKE" not in blob and "/fake/tls.key" not in blob
    assert st["system"] == {"error": "ZeroDivisionError"} and st["ok"] and st["token"] is True
    rows = {(r["section"], r["field"]): r for r in st["config"]}
    assert rows[("viz", "token")]["value"] == "set"
    assert rows[("ptt", "evdev_key")]["env"] == "FISH_PTT_KEY"
    assert rows[("stt", "backend")]["env"] == "FISH_STT_BACKEND"


def test_backends_name_the_speech_routes_keys_and_last_route_without_building(make_hub,
                                                                             monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    hub = make_hub()
    hub.cfg.stt.backend, hub.cfg.stt.online_first, hub.cfg.stt.long_online = (
        "canary", ("openai",), ("groq",))

    class Convo:
        echo, sources, _llm, player, button = True, [], None, None, None
        _stt = type("T", (), {"last": {"service": "openai", "route": "online first",
                                       "seconds": 0.9}})()

        def ptt_summary(self): return "web"

        @property
        def stt(self): raise AssertionError("the state never builds a transcriber")
    hub.attach(convo=Convo())
    be = hub.state()["backends"]
    assert be["stt_online"] == ["openai"] and be["stt_long"] == ["groq"]
    assert be["stt_keys"] == ["GROQ_API_KEY", "OPENAI_API_KEY"]
    assert be["stt_last"] == {"service": "openai", "route": "online first", "seconds": 0.9}
    assert be["keys"]["GROQ_API_KEY"] is False
    hub.cfg.stt.backend = "local"                     # the lists are canary's alone
    be = hub.state()["backends"]
    assert be["stt_online"] == [] and be["stt_keys"] == []


def test_every_secret_looking_config_field_is_classified():
    """A new field whose name smells of a secret must be put in NOT_SHOWN or REVIEWED."""
    assert debug_state.unclassified_fields(Config()) == []


def test_readers_against_a_fake_root(tmp_path):
    z = tmp_path / "sys/class/thermal/thermal_zone0"
    z.mkdir(parents=True)
    (z / "temp").write_text("43700\n"); (z / "type").write_text("cpu\n")
    (tmp_path / "proc/self").mkdir(parents=True)
    (tmp_path / "proc/loadavg").write_text("0.08 0.10 0.09 1/200 999\n")
    (tmp_path / "proc/meminfo").write_text("MemTotal: 3800000 kB\nMemAvailable: 2900000 kB\n")
    (tmp_path / "proc/uptime").write_text("7980.11 1.0\n")
    (tmp_path / "sys/class/typec/port0").mkdir(parents=True)
    (tmp_path / "sys/class/typec/port0/data_role").write_text("host [device]\n")
    (tmp_path / "proc/self/cgroup").write_text("0::/user.slice/user@1000.service/app.slice/fish-brain.service\n")
    s = debug_state.system(str(tmp_path))
    assert s["thermal"] == [{"name": "cpu", "c": 43.7}] and s["load"][0] == 0.08
    assert s["mem_mb"] == {"total": 3710, "available": 2832} and s["usb_role"] == "host [device]"
    assert debug_state.service(str(tmp_path)) ["supervised"] is True
    (tmp_path / "proc/self/cgroup").write_text("0::/user.slice/app-code.scope\n")
    assert debug_state.service(str(tmp_path))["supervised"] is False
    git = tmp_path / ".git"; (git / "refs/heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/braintip\n")
    (git / "refs/heads/braintip").write_text("4a3a7150000000000000000000000000000000ab\n")
    assert debug_state.version(tmp_path) == {"commit": "4a3a715", "branch": "braintip"}


def test_hints_name_the_wrong_key_zeros_and_echo(make_hub, tmp_path):
    hub = make_hub()
    class Button:
        def snapshot(self):
            return {"keys": "KEY_ENTER", "devices": [{"path": "/dev/input/event3", "name": "R"}],
                    "mode": "hold", "held": False, "armed": True, "need_release": False}
    class Convo:
        button, echo, sources, _llm, player = Button(), True, [], None, None
        def ptt_summary(self): return "web+evdev(1 device, KEY_ENTER, hold)"
    hub.attach(convo=Convo())
    for _ in range(2):
        debug.key("/dev/input/event3", "XING WEI Mouse", 272, "BTN_LEFT", 1, False, True)
        debug.key("/dev/input/event3", "XING WEI Mouse", 272, "BTN_LEFT", 0, False, True)
    debug.recording(_wav(tmp_path, [0] * 16000))
    hints = hub.state()["hints"]
    text = " | ".join(h["text"] + " " + h["fix"] for h in hints)
    assert "BTN_LEFT arrived 2 time(s) from 'XING WEI Mouse'" in text
    assert "FISH_PTT_KEY=KEY_ENTER,BTN_LEFT" in text
    assert "digital zeros" in text and "ECHO mode" in text
    # the right key works again: the wrong-key hint goes
    debug.key("/dev/input/event2", "XING WEI", 28, "KEY_ENTER", 1, True, True)
    debug.key("/dev/input/event2", "XING WEI", 28, "KEY_ENTER", 0, True, True)
    assert "BTN_LEFT arrived" not in repr(hub.state()["hints"])


def test_a_short_token_is_scrubbed_only_where_a_token_is_written(monkeypatch):
    cfg = Config()
    cfg.viz.token = "ok"
    hub = debug.DebugHub(cfg)
    rec = hub.emit("turn", link="ok", text="open /?token=ok on the phone")
    assert rec["link"] == "ok" and "token=ok" not in rec["text"]


def test_a_phrase_spoken_from_another_thread_is_not_the_waiting_turns(make_hub):
    hub = make_hub()
    debug.turn_open()                                # the loop waits for a press
    t = threading.Thread(target=lambda: debug.turn_set(perf={"result": "ok"}, outcome="spoken"))
    t.start(); t.join()                              # /speak from an HTTP thread
    debug.turn_set(outcome="too short")
    debug.turn_close()
    turn = hub.recent("turn")[-1]
    assert turn["outcome"] == "too short" and "perf" not in turn


def test_a_fifth_debug_page_is_refused_not_rotated(make_hub):
    hub = make_hub()
    pages = [hub.stream_open() for _ in range(debug.MAX_STREAMS)]
    assert all(pages) and hub.stream_open() is None and not any(p["closed"] for p in pages)
    hub.stream_close(pages[0])
    assert hub.stream_open() is not None


def test_a_page_that_reconnects_replaces_its_own_stream(make_hub):
    hub = make_hub()
    others = [hub.stream_open() for _ in range(debug.MAX_STREAMS - 1)]
    first = hub.stream_open("phone")
    assert all(others) and first and hub.viewers() == debug.MAX_STREAMS
    again = hub.stream_open("phone")               # the same page, after a sleep
    assert again and first["closed"] and hub.viewers() == debug.MAX_STREAMS
    assert hub.stream_open("stranger") is None     # anyone else is still refused


def test_the_state_tells_the_page_about_the_visit_and_the_reader(make_hub):
    from types import SimpleNamespace
    from fish_brain.visit import Visit
    hub = make_hub()
    page = hub.state()["page"]
    assert page["visit_enabled"] is False and page["fortune_enabled"] is False
    v = Visit()
    v.start("Ana")
    hub.attach(viz=SimpleNamespace(_visit=v, _reader=object(), _tls_httpd=None))
    hub.cfg.visit.enabled = True
    page = hub.state()["page"]
    assert page["visit_enabled"] and page["visit"]["first"] == "Ana" and page["reading"]
    assert page["tls_port"] is None and page["capture"] == hub.cfg.ptt.capture
    assert page["silence_end_s"] == 0.0 and page["quiet_rms"] == 0.04     # off on the laptop
    hub.cfg.ptt.silence_end_s = 10.0
    assert hub.state()["page"]["silence_end_s"] == 10.0
    assert "fortune" not in page["visit"]
    fortune = SimpleNamespace(open=True, view=lambda: {"open": True, "q": 2})
    hub.attach(convo=SimpleNamespace(fortune=fortune, show=None),
               viz=SimpleNamespace(_visit=v, _reader=object(), _tls_httpd=None,
                                   mic_pages=lambda: 0))
    st = hub.state()
    assert st["page"]["fortune_enabled"] and st["page"]["visit"]["fortune"] == {"open": True, "q": 2}
    f = st["show_tab"]["fortune"]
    assert f["open"] is True and f["deck"] == "tarot" and f["cup"] is False and f["place"] == "otro"
    assert f["lines"] == 0 and f["ready"] == 0                   # the fish: no fortune lines
    assert "fortune" in debug._RECORD_KINDS


def test_service_says_whether_the_unit_is_enabled_and_on_the_bench(tmp_path, monkeypatch):
    """The fair's first failure: the fish left disabled after a motor test."""
    monkeypatch.setenv("HOME", "/home/arduino")
    (tmp_path / "proc/self").mkdir(parents=True)
    (tmp_path / "proc/self/cgroup").write_text("0::/user.slice/user@1000.service/app.slice/fish-brain.service\n")
    units = tmp_path / "home/arduino/.config/systemd/user"
    units.mkdir(parents=True)
    s = debug_state.service(str(tmp_path))
    assert s["enabled"] is False and s["bench"] is False
    (units / "default.target.wants").mkdir()
    (units / "default.target.wants/fish-brain.service").write_text("")
    (units / "fish-brain.service.d").mkdir()
    (units / "fish-brain.service.d/80-bench.conf").write_text("")
    s = debug_state.service(str(tmp_path))
    assert s["enabled"] is True and s["bench"] is True


def test_hints_name_a_disabled_fish_and_the_bench():
    class Hub:
        cfg = __import__("fish_brain.config", fromlist=["Config"]).Config()

        def recent(self, *_):
            return []
    out = debug_state.hints({"service": {"supervised": True, "enabled": False, "bench": True}}, Hub())
    texts = " ".join(h["text"] for h in out)
    assert "not enabled" in texts and "BENCH" in texts


def test_state_carries_the_device_table_its_summary_and_the_timings(make_hub, monkeypatch, tmp_path):
    from fish_brain import devices, hw
    monkeypatch.setattr(hw, "_marks", hw.Marks(tmp_path / "hw.json"))
    hub = make_hub()
    st = hub.state()
    assert [d["id"] for d in st["devices"]] == list(devices.IDS)
    assert st["summary"]["level"] in ("ok", "warn", "bad") and "text" in st["summary"]
    assert {"show_tab", "devices", "checks", "hints", "total"} <= set(st["timing"])
    assert all(isinstance(v, float) for v in st["timing"].values())
    assert "hw" in st["show_tab"] and "capture" in st["page"]      # the old keys stay beside it
    # The board's role reaches the USB rows; a failing system section hides them.
    monkeypatch.setattr(debug_state, "system", lambda: {"usb_role": "host [device]", "usb": []})
    rows = devices.by_id(hub.state()["devices"])
    assert rows["usb_port"]["level"] == "bad" and rows["usb_devices"]["level"] == "warn"
    monkeypatch.setattr(debug_state, "system", lambda: 1 / 0)
    rows = devices.by_id(hub.state()["devices"])
    assert rows["usb_port"]["level"] == "off"


def test_the_canned_rows_read_the_cache_once(make_hub, monkeypatch, tmp_path):
    hub = make_hub()
    hub.cfg.canned.cache_dir = tmp_path
    (tmp_path / "welcome-abc123.wav").write_bytes(b"")
    calls = []
    real = os.listdir
    monkeypatch.setattr(debug_state.os, "listdir", lambda d: calls.append(d) or real(d))
    rows = {r["name"]: r["rendered"] for r in debug_state._canned(hub)}
    assert rows["welcome"] is True and rows["goodbye"] is False
    debug_state._canned(hub)
    assert len(calls) == 1                            # cached for 10 s


def test_the_volume_is_read_in_the_background_and_seeded_after_a_set():
    import threading
    gate = threading.Event()
    calls = []

    def read(sid):
        calls.append(sid)
        gate.wait(2)
        return 0.7
    sid = "test-sink-volume"
    debug_state._vol.pop(sid, None)
    assert debug_state.volume(sid, read=read) is None   # never waits on wpctl
    assert debug_state.volume(sid, read=read) is None and len(calls) <= 1   # one read at a time
    gate.set()
    for _ in range(100):
        if debug_state._vol[sid]["value"] is not None:
            break
        threading.Event().wait(0.01)
    assert debug_state.volume(sid, read=read) == 0.7 and calls == [sid]
    debug_state.seed_volume(sid, 0.3)
    assert debug_state.volume(sid, read=read) == 0.3
