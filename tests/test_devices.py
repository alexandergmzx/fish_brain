"""The device table (ADR 0021): every row's derivation, the precedence, the decisions the acts
call, the summary and the hints. Pure functions: no hardware, no files."""
import itertools

import pytest

from fish_brain import devices
from fish_brain.devices import Facts, build, by_id

KEYS = {"id", "label", "present", "marked", "dead", "in_use", "level", "state", "reason",
        "fix", "tab"}
BOARD = dict(usb_role="[host] device", usb_products=["xHCI Host Controller", "USB2.0 Hub",
                                                     "UACDemoV1.0", "XING WEI 2.4G USB"])
ROUTES = ["alsa_output.usb-*", "bluez_output.*", "phone"]


def row(facts: Facts, id_: str) -> dict:
    return by_id(build(facts))[id_]


# ---- the schema --------------------------------------------------------------------------------

def test_the_laptop_with_nothing_set_has_no_bad_row_and_hides_the_board_rows():
    table = build(Facts())
    assert [d["id"] for d in table] == list(devices.IDS)
    for d in table:
        assert KEYS <= set(d) and d["level"] in devices.LEVELS
        assert d["level"] != "bad", d
        if d["level"] in ("ok", "off"):
            assert d["fix"] == ""
    lv = {d["id"]: d["level"] for d in table}
    assert lv["usb_port"] == lv["usb_devices"] == lv["remote"] == "off"
    assert lv["phone_speaker"] == lv["phone_mic"] == "off"
    assert lv["speaker"] == "ok" and lv["mic"] == "ok" and lv["internet"] == "ok"
    mic = row(Facts(), "mic")
    assert mic["capture"] == "host" and mic["recorder"] == "host" and mic["last_rec"] == {}
    assert row(Facts(), "phone_mic")["pages"] == 0


# ---- the USB rows ---------------------------------------------------------------------------

def test_usb_host_reads_the_type_c_role():
    assert devices.usb_host("") is None
    assert devices.usb_host("[host] device") is True
    assert devices.usb_host("host [device]") is False


def test_usb_rows_on_the_board():
    port, devs = row(Facts(**BOARD), "usb_port"), row(Facts(**BOARD), "usb_devices")
    assert port["level"] == "ok" and port["state"] == "host" and port["tab"] == "board"
    assert devs["level"] == "ok" and "Host Controller" not in devs["state"]
    assert devs["state"] == "USB2.0 Hub, UACDemoV1.0, XING WEI 2.4G USB"
    dev = Facts(usb_role="host [device]", usb_products=["xHCI Host Controller"])
    port = row(dev, "usb_port")
    assert port["level"] == "bad" and port["state"] == "device" and "cable" in port["fix"]
    devs = row(dev, "usb_devices")
    assert devs["level"] == "warn" and devs["present"] is False and devs["state"] == "none"


# ---- the speaker ------------------------------------------------------------------------------

def test_speaker_on_the_laptop_follows_the_cards_and_the_player():
    assert row(Facts(playback_cards=1), "speaker")["state"] == "default"
    assert row(Facts(playback_cards=0), "speaker")["level"] == "warn"
    assert row(Facts(no_audio=True), "speaker")["level"] == "warn"
    assert row(Facts(player="SilentPlayer"), "speaker")["level"] == "bad"
    played_badly = row(Facts(last_play="error"), "speaker")
    assert played_badly["dead"] and played_badly["level"] == "warn"


def test_speaker_level_follows_the_route_in_use():
    usb = Facts(audio_routes=ROUTES, audio_next="alsa_output.usb-*", sinks=["alsa_output.usb-Jieli"])
    d = row(usb, "speaker")
    assert d["level"] == "ok" and d["state"] == "USB" and d["present"] is True
    bt = Facts(audio_routes=ROUTES, audio_next="bluez_output.*", sinks=["bluez_output.AA"])
    d = row(bt, "speaker")
    assert d["level"] == "warn" and d["state"] == "Bluetooth" and d["present"] is False
    ph = Facts(audio_routes=ROUTES, audio_next="phone", speaker_pages=1)
    d = row(ph, "speaker")
    assert d["level"] == "warn" and d["in_use"] and d["state"] == "this phone"
    none = row(Facts(audio_routes=ROUTES, audio_next="none"), "speaker")
    assert none["level"] == "bad" and "phone" in none["fix"]
    cool = Facts(audio_routes=ROUTES, audio_next="bluez_output.*", cooling=["alsa_output.usb-*"],
                 sinks=["alsa_output.usb-Jieli", "bluez_output.AA"])
    assert row(cool, "speaker")["reason"] == "the first route is cooling"


def test_a_marked_speaker_beats_a_present_one():
    f = Facts(audio_routes=ROUTES, audio_next="phone", speaker_pages=1,
              sinks=["alsa_output.usb-Jieli"], marks=frozenset({"speaker"}))
    d = row(f, "speaker")
    assert d["present"] is True and d["marked"] and d["level"] == "warn"
    assert d["reason"] == "USB marked failed"


def test_speaker_routes_order_mark_cooling_and_the_phone():
    sinks = [{"name": "alsa_output.platform-codec"}, {"name": "alsa_output.usb-Jieli"},
             {"name": "bluez_output.AA"}]
    assert devices.speaker_routes(ROUTES, False, sinks, 1, {}) == [
        ("alsa_output.usb-*", "alsa_output.usb-Jieli"), ("bluez_output.*", "bluez_output.AA"),
        ("phone", "")]
    assert devices.speaker_routes(ROUTES, True, sinks, 0, {})[0] == ("bluez_output.*", "bluez_output.AA")
    assert devices.speaker_routes(ROUTES, False, sinks, 0, {"alsa_output.usb-*": 10.0}, now=5.0)[0][0] \
        == "bluez_output.*"
    assert devices.speaker_routes(ROUTES, False, sinks, 0, {"alsa_output.usb-*": 4.0}, now=5.0)[0][0] \
        == "alsa_output.usb-*"                                     # its rest is over
    assert devices.speaker_routes(ROUTES, False, ["bluez_output.AA"], 0, ["bluez_output.*"]) == []
    assert devices.speaker_routes(["alsa_output.platform-*"], False, sinks, 0, {}) == [
        ("alsa_output.platform-*", "alsa_output.platform-codec")]


# ---- the microphone --------------------------------------------------------------------------

@pytest.mark.parametrize("marked,out,pages,who", [
    (False, False, 0, "host"), (False, False, 1, "host"),
    (False, True, 0, "host"), (False, True, 1, "browser"),
    (True, False, 0, "host"), (True, False, 1, "browser"),
    (True, True, 0, "host"), (True, True, 1, "browser"),
])
def test_recorder_truth_table_for_auto(marked, out, pages, who):
    assert devices.recorder("auto", marked, out, pages) == who


def test_recorder_host_and_browser():
    assert devices.recorder("host", False, True, 1) == "host"         # host ignores the dead mic
    assert devices.recorder("host", True, False, 1) == "browser"      # but a mark wins
    assert devices.recorder("browser", False, False, 1) == "browser"
    assert devices.recorder("browser", False, False, 0) == "host"     # no phone: the board


def test_mic_rows():
    gone = Facts(capture="auto", mic_source="xw", mic_source_present=False)
    d = row(gone, "mic")
    assert d["level"] == "bad" and d["present"] is False and d["recorder"] == "host"
    d = row(Facts(capture="auto", mic_zeroed=True, mic_pages=1), "mic")
    assert d["level"] == "warn" and d["dead"] and d["in_use"] and d["state"] == "this phone"
    assert d["reason"] == "the remote sends silence"
    marked = row(Facts(capture="host", mic_source_present=True, marks=frozenset({"mic"})), "mic")
    assert marked["present"] is True and marked["marked"] and marked["level"] == "bad"
    phone = row(Facts(capture="browser", mic_pages=2), "mic")
    assert phone["level"] == "ok" and phone["recorder"] == "browser"
    assert row(Facts(capture="browser"), "mic")["level"] == "warn"
    zeros = row(Facts(last_rec={"samples": 100, "zero_frac": 1.0, "rms": 0.0}), "mic")
    assert zeros["level"] == "warn" and zeros["dead"]
    quiet = row(Facts(last_rec={"samples": 100, "zero_frac": 0.0, "rms": 0.001}), "mic")
    assert quiet["level"] == "warn" and "near silence" in quiet["reason"]
    assert row(Facts(capture_cards=0), "mic")["level"] == "warn"


def test_phone_mic_row():
    assert row(Facts(capture="host"), "phone_mic")["level"] == "off"
    need = row(Facts(capture="auto", mic_zeroed=True), "phone_mic")
    assert need["level"] == "warn" and "turn on" in need["fix"]
    on = row(Facts(capture="auto", mic_zeroed=True, mic_pages=1), "phone_mic")
    assert on["level"] == "ok" and on["in_use"] and on["pages"] == 1
    ready = row(Facts(capture="auto", mic_pages=1), "phone_mic")
    assert ready["level"] == "ok" and not ready["in_use"] and ready["state"] == "ready"


def test_phone_speaker_row():
    assert row(Facts(), "phone_speaker")["level"] == "off"
    armed = row(Facts(audio_routes=ROUTES, audio_next="phone", speaker_pages=1), "phone_speaker")
    assert armed["level"] == "ok" and armed["in_use"] and armed["pages"] == 1
    needed = row(Facts(audio_routes=ROUTES, audio_next="none"), "phone_speaker")
    assert needed["level"] == "warn" and needed["present"] is False
    idle = row(Facts(audio_routes=ROUTES, audio_next="alsa_output.usb-*"), "phone_speaker")
    assert idle["level"] == "ok" and not idle["in_use"]


# ---- the remote and the motors ------------------------------------------------------------------

def test_remote_row():
    assert row(Facts(), "remote")["level"] == "off"
    cfg = dict(remote_device="name:XING WEI")
    assert row(Facts(**cfg, remote_devices=2, remote_alive=True), "remote")["level"] == "ok"
    none = row(Facts(**cfg, remote_devices=0, remote_alive=True), "remote")
    assert none["level"] == "warn" and none["present"] is False and none["state"] == "not found"
    marked = row(Facts(**cfg, remote_devices=1, remote_alive=True, marks=frozenset({"remote"})), "remote")
    assert marked["present"] is True and marked["state"] == "marked failed" and marked["level"] == "warn"
    stopped = row(Facts(**cfg, remote_devices=1, remote_alive=False), "remote")
    assert stopped["dead"] and stopped["level"] == "warn"


def test_motor_rows():
    ok = {"kind": "SerialLink", "attached": True, "health": "ok"}
    assert row(Facts(link=ok), "motors")["level"] == "ok"
    assert row(Facts(link={**ok, "mock": True}), "motors")["state"].startswith("mock")
    assert row(Facts(link={**ok, "attached": False, "health": "off"}), "motors")["level"] == "bad"
    silent = row(Facts(link={**ok, "health": "silent", "unanswered": 4}), "motors")
    assert silent["level"] == "bad" and silent["dead"] and "4 lines" in silent["reason"]
    assert row(Facts(link={**ok, "muted": True}), "motors")["level"] == "warn"
    assert row(Facts(link=ok, bench=True), "motors")["state"] == "bench mode"
    marked = row(Facts(link=ok, marks=frozenset({"motors"})), "motors")
    assert marked["marked"] and marked["level"] == "warn" and marked["present"] is True
    assert row(Facts(), "motors")["state"] == "not opened yet"


# ---- the internet ---------------------------------------------------------------------------

def test_internet_why_strings_are_the_acts():
    assert devices.internet(True, True) == (False, "internet marked failed")
    assert devices.internet(False, False) == (False, "offline")
    assert devices.internet(False, True) == (True, "online")


def test_internet_level_follows_whether_the_script_covers_it():
    assert row(Facts(online=False), "internet")["level"] == "bad"
    assert row(Facts(online=False, offline_ok=True), "internet")["level"] == "warn"
    m = row(Facts(marks=frozenset({"internet"}), offline_ok=True), "internet")
    assert m["marked"] and m["level"] == "warn" and m["state"] == "marked failed"
    ap = row(Facts(net_state="ap", online=False, offline_ok=True), "internet")
    assert "own Wi-Fi" in ap["state"]


# ---- the summary, the hints, the checks ------------------------------------------------------

def test_summary_names_the_worst_rows():
    mock = {"kind": "MockSerialLink", "attached": True, "health": "ok", "mock": True}
    assert devices.summary(build(Facts(link=mock))) == {"level": "ok", "bad": [], "warn": [],
                                                         "text": "Ready for visitors"}
    s = devices.summary(build(Facts(link=mock, online=False, offline_ok=True)))
    assert s["level"] == "warn" and s["warn"] == ["internet"]
    assert s["text"].startswith("Ready, with a warning: Internet")
    s = devices.summary(build(Facts(link=mock, usb_role="host [device]", online=False,
                                    offline_ok=True)))
    assert s["level"] == "bad" and s["bad"] == ["usb_port"] and s["text"] == "Check: USB port · device"


def test_one_hint_per_bad_device_on_its_tab():
    table = build(Facts(usb_role="host [device]", online=False))
    hints = devices.hints_for(table)
    assert [(h["panel"], h["level"]) for h in hints] == [("board", "bad"), ("cloud", "bad")]
    assert hints[0]["fix"] == "change the USB-C cable" and hints[0]["text"].startswith("USB port: device")
    assert devices.hints_for(build(Facts())) == []


def test_check_status_maps_every_level():
    assert [devices.check_status(lv) for lv in devices.LEVELS] == ["pass", "warn", "fail", "skip"]


def test_every_combination_of_marks_builds_valid_rows():
    parts = ("speaker", "mic", "remote", "motors", "internet")
    for n in range(len(parts) + 1):
        for marks in itertools.combinations(parts, n):
            f = Facts(**BOARD, marks=frozenset(marks), audio_routes=ROUTES, capture="auto",
                      remote_device="name:X", remote_devices=1, remote_alive=True,
                      link={"kind": "RouterLink", "attached": True, "health": "ok"})
            for d in build(f):
                assert d["level"] in devices.LEVELS
                assert d["marked"] == (d["id"] in marks)
