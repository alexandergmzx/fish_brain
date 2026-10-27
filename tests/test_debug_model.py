"""What the debug view records of the models, and the bring-up checks. Fakes only."""
import struct
import threading
import time
import wave
from types import SimpleNamespace

import pytest

from fish_brain import cloud, debug, debug_checks, devices, llm, reading, stt, tts
from fish_brain.config import Config, LLMConfig, STTConfig

from test_reading import GOOD, JPEG, FakeClient as BadgeClient, wire
from test_stt import FakeClient as SttClient, PROMPT


@pytest.fixture
def hub():
    h = debug.install(Config())
    yield h
    debug.uninstall()


def answer(text="¡Hola!"):
    msg = SimpleNamespace(content=text)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")],
                           usage=SimpleNamespace(prompt_tokens=40, completion_tokens=5))


@pytest.fixture
def convo(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-0000")
    monkeypatch.setattr(cloud, "is_online", lambda: True)
    c = llm.Conversation(LLMConfig(profile="groq"))
    c.calls = []

    def create(**kw):
        c.calls.append(kw)
        return answer()
    c._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
                                with_options=lambda **kw: c._client)
    return c


def test_an_llm_call_is_recorded_with_what_was_sent_and_what_came_back(hub, convo):
    convo.extra_rules = "Reglas."
    debug.turn_open()
    assert convo.reply("hola") == "¡Hola!"
    debug.turn_set(times={"llm": 0.1})
    debug.turn_close()
    (rec,) = hub.recent("llm")
    assert [m["role"] for m in rec["messages"]] == ["system", "system", "user"]
    assert rec["messages"][-1]["content"] == "hola" and rec["reply"] == "¡Hola!"
    assert rec["tokens"] == {"prompt": 40, "completion": 5} and rec["model"] == convo.cfg.model
    assert rec["params"]["max_completion_tokens"] == convo.cfg.max_completion_tokens
    assert hub.recent("turn")[-1]["model"] == [rec["seq"]]      # the turn points at its call


def test_a_failed_call_and_an_offline_one_are_recorded_too(hub, convo, monkeypatch):
    from openai import APIConnectionError
    monkeypatch.setattr(cloud, "mark_offline", lambda: None)

    def boom(**kw):
        raise APIConnectionError(request=SimpleNamespace(url="x", method="POST"))
    convo._client.chat.completions.create = boom
    assert convo.reply("hola") == convo.cfg.fallback_reply
    assert hub.recent("llm")[-1]["error"]["type"] == "APIConnectionError"
    luna = llm.Conversation.__new__(llm.Conversation)
    luna.__dict__.update(convo.__dict__)
    luna.cfg = LLMConfig(profile="luna")
    monkeypatch.setattr(cloud, "is_online", lambda: False)
    luna.reply("hola")
    last = hub.recent("llm")[-1]
    assert last["sent"] is False and last["messages"][-1]["content"] == "hola"


def test_a_broken_response_object_never_breaks_the_call(hub, convo):
    convo._client.chat.completions.create = lambda **kw: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))], usage=None)
    hub.emit = lambda *a, **k: 1 / 0
    assert convo.reply("hola") == "ok" and hub.errors >= 1


def test_the_probe_leaves_the_conversation_alone(hub, convo):
    convo.remember("u", "a")
    before = (list(convo._history), convo.last_error, convo.last_usage)
    out = convo.probe()
    assert out["reply"] == "¡Hola!" and (list(convo._history), convo.last_error, convo.last_usage) == before
    assert hub.recent("llm")[-1]["probe"] is True           # and it shows in the Model tab
    assert convo.calls[-1]["messages"] == [{"role": "user", "content": "Responde solo: ok"}]


def test_speech_to_text_names_the_filter_and_returns_what_it_did_before(hub, monkeypatch):
    client = SttClient()
    monkeypatch.setattr(cloud, "client", lambda *a, **k: client)
    monkeypatch.setattr(cloud, "is_online", lambda: True)
    cfg = STTConfig(backend="openai", cloud_model="", prompt=PROMPT, keywords=("sí",), language="es")
    t = stt.CloudTranscriber(cfg)
    for text, want, why in ((" Sí. ", "Sí.", ""), (PROMPT, "", "prompt echo"),
                            ("Subtítulos por la comunidad de Amara.org", "", "hallucination")):
        client.text = text
        assert t.transcribe("x.wav") == want
        rec = hub.recent("stt")[-1]
        assert (rec["raw"], rec["final"], rec["dropped"]) == (text.strip(), want, why)
        assert rec["prompt"] == PROMPT and rec["keywords"] == ["sí"]
    monkeypatch.setattr(cloud, "is_online", lambda: False)
    with pytest.raises(cloud.CloudUnavailable):
        t.transcribe("x.wav")
    assert hub.recent("stt")[-1]["sent"] is False


def test_the_voice_record_has_the_text_and_the_failure(hub, tmp_path, monkeypatch):
    def fake_loq(text, cfg, out_path):
        with wave.open(str(out_path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
            w.writeframes(b"\x00\x01" * 4000)
    monkeypatch.setattr(tts, "_synthesize_loq", fake_loq)
    cfg = Config().tts
    cfg.backend = "loq"
    tts.synthesize("Hola, soy el pez.", cfg, out_path=tmp_path / "a.wav")
    assert hub.recent("tts")[-1]["text"] == "Hola, soy el pez." and "error" not in hub.recent("tts")[-1]
    monkeypatch.setattr(tts, "_synthesize_loq", lambda *a: (_ for _ in ()).throw(RuntimeError("loq failed (rc=1)")))
    with pytest.raises(RuntimeError):
        tts.synthesize("Hola", cfg, out_path=tmp_path / "b.wav")
    assert hub.recent("tts")[-1]["error"]["type"] == "RuntimeError"


def test_a_badge_reading_is_recorded_without_the_photo_and_without_a_print(hub, monkeypatch, capsys):
    monkeypatch.setenv("FISH_READING_PROFILE", "luna")
    cfg = Config()
    wire(monkeypatch, BadgeClient(GOOD))
    res = reading.read_badge(JPEG, cfg, want_look=False)
    rec = hub.recent("vision")[-1]
    assert rec["found"] and rec["name"] == res.full_name and rec["tokens"] == 1234
    assert rec["ask"].startswith("Lee el gafete.") and rec["prompt"] == cfg.reading.badge_prompt
    blob = repr(hub.since(0, 500))
    assert "data:image" not in blob and "base64" not in blob
    out = capsys.readouterr()
    assert res.full_name not in out.out + out.err          # the journal never carries the name
    debug.new_visitor()
    assert hub.recent("vision") == [] and hub.recent("llm") == []
    assert hub.since(0, 500)[-1]["kind"] == "visitor"      # an open page is told to forget too


def test_a_key_in_an_error_text_is_scrubbed(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-FAKEFAKEFAKE1234")
    hub = debug.install(Config())
    try:
        debug.model("llm", {"model": "m", "messages": [{"role": "user", "content": "hola"}]},
                    error=RuntimeError("401 Incorrect API key provided: sk-test-FAKEFAKEFAKE1234"))
        assert "FAKEFAKE" not in repr(hub.recent("llm"))
    finally:
        debug.uninstall()


# ---- the bring-up checks ----------------------------------------------------------------------

def board_root(tmp_path, speaker=True):
    tmp_path = tmp_path / ("with" if speaker else "without")
    if tmp_path.exists():
        return str(tmp_path)
    a = tmp_path / "proc/asound"
    (a / "card0").mkdir(parents=True)
    (a / "card0/id").write_text("Device\n"); (a / "card0/usbid").write_text("1915:1025\n")
    (a / "card0/stream0").write_text("XING WEI\n  Capture:\n")
    cards = " 0 [Device         ]: USB-Audio - USB Composite Device\n                      XING WEI at usb, full speed\n"
    if speaker:
        (a / "card1").mkdir()
        (a / "card1/id").write_text("UACDemoV10\n"); (a / "card1/usbid").write_text("4c4a:4155\n")
        (a / "card1/stream0").write_text("Jieli\n  Playback:\n")
        cards += " 1 [UACDemoV10     ]: USB-Audio - UACDemoV1.0\n                      Jieli Technology UACDemoV1.0 at usb\n"
    (a / "cards").write_text(cards)
    return str(tmp_path)


SND = {"tool": "wpctl", "answered": True, "age_s": 1.0,
       "sink": {"name": "alsa_output.usb-Jieli_Technology_UACDemoV1.0-00.analog-stereo",
                "description": "UACDemoV1.0 Analog Stereo", "volume": 1.0, "muted": False},
       "source": {"name": "alsa_input.remote", "description": "USB Composite Device Mono",
                  "volume": 1.0, "muted": False},
       "sources": ["alsa_input.remote"]}


def rows(hub, root, snd, facts=None, **st):
    """The checks over a state with its device table (ADR 0021): the table is derived from
    the same system and link facts unless `facts` says otherwise."""
    base = {"system": {"usb_role": "[host] device", "usb": [{"id": "x", "product": "Hub"}]},
            "backends": {"player": "SounddevicePlayer", "online": True, "keys": {}},
            "flags": {}, "service": {}, "link": {"mock": True}, "remote": {}, "canned": []}
    base.update(st)
    f = {"usb_role": base["system"].get("usb_role", ""),
         "usb_products": [u.get("product", "") for u in base["system"].get("usb") or ()],
         "link": base["link"], "player": "SounddevicePlayer", **(facts or {})}
    base["devices"] = devices.build(devices.Facts(**f))
    return {(r["group"], r["name"]): r for r in debug_checks.run(base, hub, root, snd)}


def test_checks_see_the_speaker_its_sink_and_the_source(hub, tmp_path):
    hub.cfg.ptt.source = "alsa_input.remote"
    r = rows(hub, board_root(tmp_path), SND)
    assert r[("Speaker", "A playback sound card is present")]["status"] == "pass"
    assert "UACDemoV1.0" in r[("Speaker", "A playback sound card is present")]["detail"]
    assert r[("Speaker", "Default sink")]["status"] == "pass"
    assert r[("Speaker", "Sink volume")]["status"] == "pass"
    assert r[("Microphone", "A capture sound card is present")]["status"] == "pass"
    assert r[("Microphone", "FISH_MIC_SOURCE exists")]["status"] == "pass"
    assert r[("Power and USB", "The port is the USB host")]["status"] == "pass"


def test_checks_fail_without_a_speaker_muted_or_with_a_wrong_source(hub, tmp_path):
    hub.cfg.ptt.source = "alsa_input.gone"
    muted = {**SND, "sink": {**SND["sink"], "muted": True}}
    r = rows(hub, board_root(tmp_path, speaker=False), muted,
             system={"usb_role": "host [device]", "usb": []})
    assert r[("Speaker", "A playback sound card is present")]["status"] == "fail"
    assert r[("Speaker", "Sink volume")]["status"] == "fail" and "set-mute" in r[("Speaker", "Sink volume")]["fix"]
    assert r[("Microphone", "FISH_MIC_SOURCE exists")]["status"] == "fail"
    assert r[("Power and USB", "The port is the USB host")]["status"] == "fail"
    low = {**SND, "sink": {**SND["sink"], "volume": 0.4}}
    assert rows(hub, board_root(tmp_path), low)[("Speaker", "Sink volume")]["status"] == "warn"
    dead = rows(hub, board_root(tmp_path), {"tool": "wpctl", "answered": False, "error": "TimeoutExpired"})
    assert dead[("Speaker", "The sound server answers")]["status"] == "fail"
    s = debug_checks.summary(list(r.values()))
    assert s["failed"] >= 4 and s["of"] < len(r)             # skipped rows are not counted


def test_the_sound_server_is_parsed_from_wpctl_and_pactl():
    wp = {("inspect", "@DEFAULT_AUDIO_SINK@"): '  * node.description = "UACDemoV1.0 Analog Stereo"\n  * node.name = "alsa_output.usb-Jieli"\n',
          ("get-volume", "@DEFAULT_AUDIO_SINK@"): "Volume: 0.40 [MUTED]\n",
          ("inspect", "@DEFAULT_AUDIO_SOURCE@"): '  * node.name = "alsa_input.remote"\n  * node.description = "USB Composite Device Mono"\n',
          ("get-volume", "@DEFAULT_AUDIO_SOURCE@"): "Volume: 1.00\n"}
    out = debug_checks.probe_sound(run=lambda cmd: wp[(cmd[1], cmd[2])],
                                   which=lambda name: name == "wpctl")
    assert out["answered"] and out["sink"] == {"name": "alsa_output.usb-Jieli", "description":
                                               "UACDemoV1.0 Analog Stereo", "volume": 0.4, "muted": True}
    assert out["source"]["volume"] == 1.0 and not out["source"]["muted"]
    pa = {"get-default-sink": "alsa_output.pci\n", "get-sink-volume": "Volume: front-left: 26214 /  40% / -23.88 dB\n",
          "get-sink-mute": "Mute: no\n", "get-default-source": "alsa_input.usb\n",
          "get-source-volume": "Volume: mono: 65536 / 100%\n", "get-source-mute": "Mute: yes\n"}
    out = debug_checks.probe_sound(run=lambda cmd: pa[cmd[1]], which=lambda name: name == "pactl")
    assert out["sink"]["volume"] == 0.4 and out["source"]["muted"] and out["tool"] == "pactl"
    assert debug_checks.probe_sound(run=lambda cmd: 1 / 0, which=lambda n: n == "wpctl")["error"] == "ZeroDivisionError"


def test_a_hanging_sound_server_never_holds_a_request(monkeypatch):
    monkeypatch.setattr(debug_checks, "_sound", {"t": 0.0, "data": None, "busy": False})
    gate = threading.Event()
    t0 = time.monotonic()
    assert debug_checks.sound(probe=lambda: (gate.wait(5), {"answered": True})[1]) is None
    assert debug_checks.sound(probe=lambda: 1 / 0) is None      # one refresh at a time
    assert time.monotonic() - t0 < 0.5
    gate.set()
    for _ in range(100):
        if debug_checks._sound["data"]:
            break
        time.sleep(0.01)
    assert debug_checks.sound()["answered"] is True


def test_the_presence_checks_follow_the_device_table(hub, tmp_path):
    root = board_root(tmp_path)
    hub.cfg.ptt.evdev_device = "name:XING WEI"
    one = {"keys": "KEY_ENTER", "devices": [{"path": "/dev/input/event3", "name": "R"}]}
    r = rows(hub, root, SND, facts={"remote_device": "name:XING WEI", "remote_devices": 1,
                                    "remote_alive": True}, remote=one)
    assert r[("Remote", "Devices read")]["status"] == "pass"
    # A marked remote is set aside, not failed: the page's hold remains.
    r = rows(hub, root, SND, facts={"remote_device": "name:XING WEI", "remote_devices": 1,
                                    "marks": frozenset({"remote"})}, remote=one)
    assert r[("Remote", "Devices read")]["status"] == "warn"
    r = rows(hub, root, SND, facts={"remote_device": "name:XING WEI", "remote_devices": 0},
             remote={"devices": []})
    assert r[("Remote", "Devices read")]["status"] == "warn"
    # A detached link fails; on the bench it is a warning.
    off = {"kind": "router", "health": "off", "attached": False, "desc": "router: no port"}
    assert rows(hub, root, SND, link=off)[("Link", "Attached")]["status"] == "fail"
    bench = rows(hub, root, SND, facts={"bench": True}, link=off)
    assert bench[("Link", "Attached")]["status"] == "warn"
    assert bench[("Link", "The MCU answers")]["status"] == "warn"
    # Offline: bad with a cloud stage in the turn path, a warning when the script covers it.
    net = rows(hub, root, SND, facts={"online": False})[("Voice and cloud", "Internet")]
    assert net["status"] == "fail" and net["detail"].startswith("offline")
    net = rows(hub, root, SND, facts={"online": False, "offline_ok": True})
    assert net[("Voice and cloud", "Internet")]["status"] == "warn"
    # The laptop: no type-C port, so the USB rows do not apply.
    lap = rows(hub, root, SND, system={})
    assert lap[("Power and USB", "The port is the USB host")]["status"] == "skip"
    assert lap[("Power and USB", "Devices on USB")]["status"] == "skip"


def test_the_capture_card_check_is_lenient_when_a_phone_records(hub, tmp_path):
    root = str(tmp_path / "empty")
    (tmp_path / "empty/proc/asound").mkdir(parents=True)
    (tmp_path / "empty/proc/asound/cards").write_text("")
    r = rows(hub, root, SND)
    assert r[("Microphone", "A capture sound card is present")]["status"] == "fail"
    hub.cfg.ptt.capture = "browser"
    r = rows(hub, root, SND, facts={"capture": "browser", "mic_pages": 1})
    assert r[("Microphone", "A capture sound card is present")]["status"] == "warn"
    assert ("Microphone", "Phones can record (HTTPS)") in r
