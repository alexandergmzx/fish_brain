"""What the debug page may do, on the mock link with fakes: arming, the shape of a motor test,
every refusal, STOP, restart. Nothing here can move a motor or start a voice."""
import io
import re
import threading
import time

import pytest

from fish_brain import debug, debug_actions
from fish_brain.config import Config
from fish_brain.debug_actions import DebugActions, build_lines, check_line
from fish_brain.serial_link import MockSerialLink
from fish_brain.viz import VizServer


class Speaker:
    def __init__(self):
        self._lock = threading.Lock()


class Player:
    def __init__(self):
        self.played = []

    def play(self, path):
        self.played.append(str(path))

    def wait(self):
        pass


class Convo:
    def __init__(self):
        self.speaker, self.player, self.sources = Speaker(), Player(), []


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


@pytest.fixture
def rig(tmp_path):
    cfg = Config()
    cfg.viz.host, cfg.viz.port = "127.0.0.1", 0
    cfg.canned.cache_dir = tmp_path
    hub = debug.DebugHub(cfg)
    out = io.StringIO()
    link = MockSerialLink(cfg.serial, stream=out)
    viz = VizServer(cfg)                     # never started: only its inbox is used
    convo, clock, terminated = Convo(), Clock(), []
    act = DebugActions(cfg, link, convo, viz, hub, clock=clock, supervised=True,
                       terminate=lambda: terminated.append(1), sleep=lambda s: False)
    stop = threading.Event()

    def loop():                              # stands in for the turn loop
        while not stop.is_set():
            item = viz.take_inbox()
            if item is not None:
                item.run_in_loop(convo)
            time.sleep(0.005)
    threading.Thread(target=loop, daemon=True).start()
    viz.set_listening(True)

    class Rig:
        pass
    r = Rig()
    r.cfg, r.hub, r.link, r.viz, r.convo, r.clock, r.act, r.terminated = (
        cfg, hub, link, viz, convo, clock, act, terminated)
    r.sent = lambda: [l.strip().removeprefix("TX").strip() for l in out.getvalue().splitlines()
                      if l.strip()]
    yield r
    stop.set()


def test_motor_test_needs_arming_and_the_arm_runs_out(rig):
    assert rig.act.motor("mouth") == (403, {"ok": False, "error": "not armed"})
    assert rig.act.arm(True)[1]["armed_s"] == 60
    assert rig.act.motor("mouth")[0] == 200
    rig.clock.t += 61
    assert rig.act.armed_s() == 0
    assert rig.act.motor("mouth")[0] == 403


def test_mouth_test_is_one_timed_pulse_then_the_close_pulse(rig):
    rig.act.arm(True)
    status, out = rig.act.motor("mouth")
    assert status == 200 and out["result"] == "sent"
    assert out["lines"] == ["MOUTH 238 104", "MOUTH -200 74"] == rig.sent()
    assert not any(re.fullmatch(r"(MOUTH|NECK|TAIL) -?\d+", l) for l in rig.sent())   # never held


def test_neck_and_tail_are_one_chain_each_from_the_configuration(rig):
    rig.act.arm(True)
    assert rig.act.motor("neck")[1]["lines"] == ["NECK 230 650 -200 560"]
    assert rig.act.motor("tail")[1]["lines"] == ["TAIL 210 230 -210 210"]
    assert rig.act.motor("fins")[0] == 400
    assert rig.act.planned_lines()["mouth"] == ["MOUTH 238 104", "MOUTH -200 74"]


@pytest.mark.parametrize("line", ["MOUTH 238", "NECK 230", "MOUTH 999 100", "MOUTH 238 99999",
                                  "NECK 230 900 -200 900", "STOP", "MOUTH 1 2 3 4 5 6",
                                  "MOUTH 238 0", "ARM 1 1", "MOUTH 238 104; STOP"])
def test_a_line_that_is_not_a_short_timed_stroke_is_refused(line):
    with pytest.raises(ValueError):
        check_line(line)


def test_a_hostile_configuration_never_reaches_the_link(rig):
    rig.cfg.gesture.neck_out = "230"                 # would be a held drive
    rig.cfg.mouth.open_curve = [(1.0, 99999)]
    rig.act.arm(True)
    assert rig.act.motor("neck")[0] == 400 and rig.act.motor("mouth")[0] == 400
    assert rig.sent() == []
    assert "error" in rig.act.planned_lines()["neck"]
    with pytest.raises(ValueError):
        build_lines(rig.cfg, "mouth")


def test_motor_test_is_refused_while_speaking_busy_recording_or_without_a_link(rig, monkeypatch):
    rig.act.arm(True)
    with rig.convo.speaker._lock:                    # the fish is speaking
        assert rig.act.motor("mouth")[1]["error"] == "speaking"
    rig.convo.sources = [type("S", (), {"is_held": lambda self: True})()]
    assert rig.act.motor("mouth")[1]["error"] == "recording"
    rig.convo.sources = []
    rig.viz.set_listening(False)                     # thinking: not waiting for input
    assert rig.act.motor("mouth")[1]["error"] == "busy"
    rig.viz.set_listening(True)
    monkeypatch.setattr(type(rig.link), "attached", property(lambda self: False))
    assert rig.act.motor("mouth")[1]["error"] == "link off"
    assert rig.sent() == []


def test_a_test_that_is_not_picked_up_at_once_is_never_run_late(rig):
    item = debug_actions._Item(lambda convo: {"ok": True}, rig.clock() + 0.5, rig.clock)
    rig.clock.t += 1.0
    item.run_in_loop(rig.convo)
    assert item.result == {"ok": False, "error": "expired"}


def test_stop_works_unarmed_drops_the_arm_and_a_stopped_test_sends_only_stop(rig):
    assert rig.act.stop()[0] == 200 and rig.sent() == ["STOP"]
    rig.act.arm(True)
    rig.act._wait = lambda s: True                   # STOP arrives during the pulse
    out = rig.act.motor("mouth")[1]
    assert out["result"] == "stopped" and out["lines"] == ["MOUTH 238 104"]
    assert rig.sent()[-2:] == ["MOUTH 238 104", "STOP"]     # no close pulse after a STOP
    rig.act.stop()
    assert rig.act.armed_s() == 0


def test_a_failing_link_still_ends_in_the_close_pulse_and_never_raises(rig):
    rig.act.arm(True)
    real, calls = rig.link.send, []

    def flaky(line, **kw):
        calls.append(line)
        if len(calls) == 1:
            raise OSError("port gone")
        real(line, **kw)
    rig.link.send = flaky
    status, out = rig.act.motor("mouth")
    assert status == 409 and out["error"] == "OSError"
    assert calls == ["MOUTH 238 104", "MOUTH -200 74"]
    assert not rig.convo.speaker._lock.locked()


def test_ping_is_motor_safe_and_runs_in_the_loop(rig):
    status, out = rig.act.ping()
    assert status == 200 and out["result"] == "cannot tell"      # the mock cannot answer
    assert rig.sent() == ["PING 1"]
    rig.viz.set_listening(False)                     # mid-turn: no request thread takes the lock
    assert rig.act.ping()[1]["error"] == "busy"


def test_a_stop_that_arrives_after_the_request_wins(rig):
    rig.act.arm(True)
    seen = rig.act._stops
    rig.act.stop()                                   # between the request and the loop
    rig.act.arm(True)                                # even if somebody arms again at once
    out = rig.act._run_motor(rig.convo, "mouth", ["MOUTH 238 104", "MOUTH -200 74"], seen)
    assert out == {"ok": False, "error": "stopped"}
    assert rig.sent() == ["STOP"]


def test_stop_says_so_when_nothing_reached_the_mcu(rig, monkeypatch):
    monkeypatch.setattr(type(rig.link), "attached", property(lambda self: False))
    assert rig.act.stop()[1] == {"ok": False, "error": "link off", "speaking": False}


def test_no_test_while_a_phone_is_the_microphone(rig, monkeypatch):
    rig.cfg.ptt.capture = "browser"
    monkeypatch.setattr(rig.viz, "mic_pages", lambda: 1)
    rig.act.arm(True)
    assert rig.act.motor("mouth")[1]["error"] == "a phone is the microphone"
    assert rig.sent() == []


def test_speaker_test_plays_a_rendered_phrase_and_nothing_else(rig, tmp_path, monkeypatch):
    from fish_brain import tts
    monkeypatch.setattr(tts, "synthesize", lambda *a, **k: 1 / 0)    # must never be reached
    assert rig.act.say("welcome") == (404, {"ok": False, "error": "not rendered"})
    assert rig.act.say("nope")[0] == 400
    (tmp_path / "welcome-12345678.wav").write_bytes(b"RIFF")
    status, out = rig.act.say("welcome")
    assert status == 200 and rig.convo.player.played == [str(tmp_path / "welcome-12345678.wav")]
    assert rig.sent() == []                           # nothing to the motors


def test_restart_needs_the_arm_the_word_and_a_service_and_signals_once(rig):
    assert rig.act.restart("restart")[0] == 403
    rig.act.arm(True)
    assert rig.act.restart("yes")[0] == 400
    rig.act._supervised = False
    assert rig.act.restart("restart")[0] == 409
    rig.act._supervised = True
    assert rig.act.restart("restart")[0] == 200
    assert rig.act.restart("restart")[0] in (403, 409)        # the arm dropped, and once only
    time.sleep(0.1)
    assert rig.terminated == [1]


# ---- the bring-up tests: loop, voice render, cloud round trip (fakes) ----

def _fake_recorder(monkeypatch, tmp_path, levels):
    """ptt.record_for writes a WAV at the next level in `levels` (amplitude, 0..1)."""
    import struct
    import wave
    from fish_brain import ptt
    seq = list(levels)

    def record_for(seconds, cfg, on_level=None):
        amp = seq.pop(0)
        p = tmp_path / f"r{len(seq)}.wav"
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(struct.pack("<4000h", *[int(amp * 32767) * (1 if i % 2 else -1) for i in range(4000)]))
        return p
    monkeypatch.setattr(ptt, "record_for", record_for)


def test_loop_test_hears_the_speaker_or_says_why_not(rig, tmp_path, monkeypatch):
    (tmp_path / "welcome-12345678.wav").write_bytes(b"RIFF")
    _fake_recorder(monkeypatch, tmp_path, [0.01, 0.2, 0.01, 0.015, 0.0, 0.0])
    status, out = rig.act.loop()
    assert status == 200 and out["verdict"] == "heard" and out["played"] == "welcome"
    assert rig.convo.player.played and rig.sent() == []           # sound only, no motor line
    assert rig.act.last["loop"]["status"] == "pass"
    assert rig.hub.recording_stats()["origin"] == "loop test"
    assert rig.act.loop()[1]["verdict"] == "too quiet at the microphone"
    assert rig.act.loop()[1]["verdict"] == "zeros" and rig.act.last["loop"]["status"] == "fail"
    rig.convo.player = type("SilentPlayer", (), {})()
    assert rig.act.loop()[1]["error"].startswith("no audio")


def test_voice_render_is_timed_and_never_played(rig, monkeypatch):
    from fish_brain import tts
    made = []
    monkeypatch.setattr(tts, "synthesize", lambda text, cfg, out_path=None: made.append(text))
    status, out = rig.act.voice()
    assert status == 200 and made == [debug_actions.VOICE_PHRASE] and "seconds" in out
    assert rig.convo.player.played == [] and rig.sent() == []
    monkeypatch.setattr(tts, "synthesize", lambda *a, **k: 1 / 0)
    assert rig.act.voice()[1]["error"] == "ZeroDivisionError"
    assert rig.act.last["voice"]["status"] == "fail"


def test_cloud_round_trip_reports_each_service_and_skips_what_is_not_used(rig):
    rig.cfg.stt.backend = "openai"
    rig.convo.echo = False
    rig.convo.stt = type("S", (), {"transcribe": lambda self, p: ""})()
    rig.convo.llm = type("L", (), {"probe": lambda self: {"seconds": 0.4, "model": "m", "reply": "ok"}})()
    parts = rig.act.cloud()[1]["parts"]
    assert parts["stt"]["ok"] and parts["llm"]["ok"] and rig.act.last["cloud"]["status"] == "pass"
    rig.convo.llm = type("L", (), {"probe": lambda self: 1 / 0})()
    assert rig.act.cloud()[1]["parts"]["llm"] == {"ok": False, "error": "ZeroDivisionError", "status": None}
    assert rig.act.last["cloud"]["status"] == "fail"
    rig.cfg.stt.backend, rig.convo.echo = "local", True
    parts = rig.act.cloud()[1]["parts"]
    assert "skipped" in parts["stt"] and "skipped" in parts["llm"]
    assert rig.act.last["cloud"]["status"] == "skip"


# ---- switches: the running fish only ----

def _values(rig):
    return {w["name"]: w for w in rig.act.switches()}


def test_switches_list_their_value_their_start_and_what_changed(rig):
    sw = _values(rig)
    assert set(sw) == {"mode", "llm_profile", "stt", "stt_model", "tts", "gestures", "reading_look",
                       "voice_quit", "max_record_s", "mic", "motors"}
    assert sw["mode"]["value"] == "llm" and not any(w["changed"] for w in sw.values())
    assert rig.act.set("gestures", False) == (200, {"ok": True, "value": False})
    assert rig.cfg.gesture.enabled is False
    sw = _values(rig)
    assert sw["gestures"]["changed"] and sw["gestures"]["start"] is True
    assert rig.act.set("gestures", True)[1]["value"] is True and not _values(rig)["gestures"]["changed"]
    assert rig.act.set("max_record_s", 30)[1]["value"] == 30.0 and rig.cfg.ptt.max_record_s == 30.0
    assert rig.act.set("reading_look", True)[0] == 200 and rig.cfg.reading.look is True
    rig.convo._stt = object()
    assert rig.act.set("stt_model", "base")[0] == 200
    assert rig.cfg.stt.model == "base" and rig.convo._stt is None
    assert rig.act.set("stt_model", "large-v3")[0] == 400
    assert rig.act.set("mic", "browser")[0] == 200 and rig.cfg.ptt.capture == "browser"
    assert "HTTPS" in _values(rig)["mic"]["note"]


def test_a_switch_refuses_what_it_cannot_do(rig, monkeypatch):
    assert rig.act.set("nope", 1)[0] == 400
    assert rig.act.set("max_record_s", 500)[0] == 400 and rig.act.set("max_record_s", "x")[0] == 400
    assert rig.act.set("stt", "whisper-9")[0] == 400
    rig.cfg.stt.model_dir = ""                       # canary without its model: refused, kept
    answer = rig.act.set("stt", "canary")
    assert "FISH_STT_MODEL_DIR" in answer[1]["error"] and rig.cfg.stt.backend == "local"
    rig.cfg.stt.backend, rig.convo._stt = "openai", "kept"   # the local model is not in use:
    assert rig.act.set("stt_model", "tiny")[0] == 200 and rig.convo._stt == "kept"   # nothing to rebuild
    rig.cfg.stt.backend = "local"
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert rig.act.set("stt", "groq")[1]["error"] == "GROQ_API_KEY is not set"
    assert rig.act.set("llm_profile", "luna")[1]["error"] == "OPENAI_API_KEY is not set"
    rig.cfg.tts.backend = "openai"
    rig.cfg.tts.loq_bin = "no-such-loq-binary"
    assert "not installed" in rig.act.set("tts", "loq")[1]["error"]
    rig.viz.set_listening(False)                     # mid-turn
    assert rig.act.set("gestures", False)[1]["error"] == "busy" and rig.cfg.gesture.enabled is True


def test_mode_and_profile_switch_the_model_and_start_a_fresh_history(rig, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k-000000000")
    monkeypatch.setenv("OPENAI_API_KEY", "k-111111111")
    rig.convo.echo, rig.convo._llm, rig.convo._stt = True, object(), object()
    rig.act._start["mode"] = "echo"
    assert rig.act.set("mode", "llm")[0] == 200 and rig.convo.echo is False and rig.convo._llm is None
    rig.convo._llm = object()
    assert rig.act.set("llm_profile", "luna")[0] == 200
    assert rig.cfg.llm.profile == "luna" and rig.cfg.llm.model == "gpt-6-luna" and rig.convo._llm is None
    assert rig.act.set("stt", "openai")[0] in (200,) and rig.convo._stt is None or rig.cfg.stt.backend == "openai"
    assert rig.act.set("mode", "echo")[0] == 200 and rig.convo.echo is True
    monkeypatch.delenv("GROQ_API_KEY")
    rig.cfg.llm.api_key_env = "GROQ_API_KEY"
    assert rig.act.set("mode", "llm")[1]["error"] == "GROQ_API_KEY is not set" and rig.convo.echo is True


def test_motors_can_be_muted_only_when_armed_and_stop_still_passes(rig, monkeypatch):
    monkeypatch.setattr(debug, "_hub", rig.hub)      # the link's hooks report to this hub
    assert rig.act.set("motors", "muted") == (403, {"ok": False, "error": "not armed"})
    rig.act.arm(True)
    assert rig.act.set("motors", "muted")[0] == 200 and rig.link.muted
    assert rig.sent() == ["STOP"]                    # muting stops first
    rig.link.mouth_pulse(238, 104)
    rig.link.gesture("NECK", "230 650")
    rig.link.all_stop()
    assert rig.sent() == ["STOP", "STOP"]            # motor lines dropped, STOP passes
    assert [r["flag"] for r in rig.hub.recent("tx")] .count("muted") == 2
    assert rig.act.motor("mouth")[0] == 200 and "MOUTH 238 104" not in rig.sent()
    assert rig.act.set("motors", "on")[0] == 200 and not rig.link.muted
    rig.link.mouth_pulse(238, 104)
    assert rig.sent()[-1] == "MOUTH 238 104"
