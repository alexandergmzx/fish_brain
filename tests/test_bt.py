"""bt.py: the speakers from the page, on the stand-in bus. No radio, no D-Bus, no sound."""
import json
import subprocess
import sys
import threading
import time

import pytest

from fish_brain import audio_route, bt, devices
from fish_brain.bt import BusError, BusTimeout, BtManager, FakeBus
from fish_brain.config import BluetoothConfig, Config

SPK = "A0:00:00:00:00:01"
OLD = "A0:00:00:00:00:02"
PRN = "DC:0D:51:92:74:DA"
SPEAKER_CLASS = 0x240414


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def rig(tmp_path):
    bus = FakeBus()
    bus.add(SPK, "JBL Flip", cls=SPEAKER_CLASS, icon="audio-card")
    clock = Clock()
    m = BtManager(bus, sinks=lambda: bus.sinks, path=tmp_path / "bt.json", clock=clock)
    m.sink_s = 0.0
    m.run_once()
    yield bus, m, clock
    bt._manager = None


def seen(bus, m):
    assert m.do({"do": "find"})[0] == 200
    m.run_once()


def names(calls):
    return [c[0] for c in calls]


def test_a_tap_stops_the_search_pairs_trusts_connects_and_chooses(rig):
    bus, m, _ = rig
    seen(bus, m)
    assert m.do({"do": "use", "mac": SPK})[0] == 200
    m.run_once()
    got = names(bus.calls)
    assert got.index("StopDiscovery") < got.index("Pair") < got.index("set") < got.index("Connect")
    assert ("set", "Trusted", True) in bus.calls
    assert m.chosen == SPK and m.result["ok"]
    assert m.snapshot()["chosen"]["ready"] is True
    assert m.snapshot()["mine"][0]["name"] == "JBL Flip"


def test_the_agent_is_registered_before_every_pair(rig):
    bus, m, _ = rig
    seen(bus, m)
    m.do({"do": "use", "mac": SPK})
    m.run_once()
    got = names(bus.calls)
    assert got.index("RegisterAgent") < got.index("Pair")


def test_a_failed_pair_is_never_trusted(rig):
    bus, m, _ = rig
    bus.behaviour[SPK] = "refuses"
    seen(bus, m)
    m.do({"do": "use", "mac": SPK})
    m.run_once()
    assert ("set", "Trusted", True) not in bus.calls
    assert m.chosen == "" and m.result["code"] == "refused"
    assert m.phase == "idle"


def test_connected_without_a_sink_tries_a2dp_then_disconnects_and_leaves_the_route(rig):
    bus, m, _ = rig
    bus.behaviour[SPK] = "no_sink"
    seen(bus, m)
    m.do({"do": "use", "mac": SPK})
    m.run_once()
    assert ("ConnectProfile", bt.A2DP_SINK) in bus.calls and "Disconnect" in names(bus.calls)
    assert m.chosen == "" and m.result["code"] == "no_sink"


def test_a_switch_disconnects_the_old_speaker_last_and_a_failed_one_keeps_it(rig):
    bus, m, _ = rig
    bus.add(OLD, "Second", cls=SPEAKER_CLASS, icon="audio-card")
    seen(bus, m)
    m.do({"do": "use", "mac": SPK})
    m.run_once()
    bus.calls.clear()
    bus.behaviour[OLD] = "held"
    m.do({"do": "use", "mac": OLD})
    m.run_once()
    assert m.chosen == SPK and "Disconnect" not in names(bus.calls)
    assert m.result["code"] == "held"
    bus.behaviour[OLD] = "good"
    bus.calls.clear()
    m.do({"do": "use", "mac": OLD})
    m.run_once()
    assert m.chosen == OLD and names(bus.calls)[-1] == "Disconnect"


def test_zero_first_then_his_pin(rig):
    bus, m, _ = rig
    bus.behaviour[SPK] = "pin"
    seen(bus, m)
    m.do({"do": "use", "mac": SPK})
    m.ask_s = 5.0
    t = threading.Thread(target=m.run_once)
    t.start()
    for _ in range(200):
        if m.snapshot()["ask"]:
            break
        time.sleep(0.01)
    assert m.snapshot()["ask"]["kind"] == "pin"
    assert m.do({"do": "answer", "pin": "bad pin!"})[0] == 400
    assert m.do({"do": "answer", "pin": "4321"})[0] == 200
    t.join(5)
    assert m.chosen == SPK


def test_a_number_said_no_rejects(rig):
    bus, m, _ = rig
    bus.behaviour[SPK] = "confirm"
    seen(bus, m)
    m.do({"do": "use", "mac": SPK})
    t = threading.Thread(target=m.run_once)
    t.start()
    for _ in range(200):
        if m.snapshot()["ask"]:
            break
        time.sleep(0.01)
    assert m.snapshot()["ask"] == {"kind": "confirm", "number": "482913"}
    m.do({"do": "answer", "yes": False})
    t.join(5)
    assert m.chosen == "" and m.result["code"] == "refused"


def test_an_unanswered_ask_rejects(rig):
    bus, m, _ = rig
    bus.behaviour[SPK] = "confirm"
    m.ask_s = 0.01
    seen(bus, m)
    m.do({"do": "use", "mac": SPK})
    m.run_once()
    assert m.chosen == "" and m.snapshot()["ask"] is None


def test_the_agent_rejects_a_device_it_did_not_start(rig):
    bus, m, _ = rig
    assert m._agent_ask("pin", SPK) is None
    assert m._agent_ask("authorize", SPK) is None


def test_a_pair_timeout_cancels(rig):
    bus, m, _ = rig
    real = bus.call

    def slow(path, iface, method, *a, timeout=10.0):
        if method == "Pair":
            bus.calls.append(("Pair",))
            raise BusTimeout("Pair")
        return real(path, iface, method, *a, timeout=timeout)
    bus.call = slow
    seen(bus, m)
    m.do({"do": "use", "mac": SPK})
    m.run_once()
    assert "CancelPairing" in names(bus.calls) and m.result["code"] == "no_answer"


def test_a_device_gone_says_so(rig):
    bus, m, _ = rig
    seen(bus, m)
    m.do({"do": "use", "mac": SPK})
    del bus.known[SPK]
    m.run_once()
    assert m.result["code"] == "gone"


def test_the_search_ends_by_itself_and_on_a_turn(rig):
    bus, m, clock = rig
    seen(bus, m)
    assert m.phase == "scanning" and m.snapshot()["scan_left_s"] == 20
    clock.t += 21
    m.run_once()
    assert m.phase == "idle" and "StopDiscovery" in names(bus.calls)
    bus.calls.clear()
    seen(bus, m)
    m.busy = lambda: "speaking"
    m.run_once()
    assert m.phase == "idle" and "StopDiscovery" in names(bus.calls)
    assert "speaking" in m.result["text"]


def test_a_search_is_refused_while_busy_and_during_a_tap(rig):
    bus, m, _ = rig
    m.busy = lambda: "printing"
    assert m.do({"do": "find"}) == (409, {"ok": False, "error": "printing"})
    m.busy = lambda: ""
    seen(bus, m)
    m.do({"do": "use", "mac": SPK})
    assert m.do({"do": "find"})[0] == 409
    assert m.do({"do": "use", "mac": SPK})[0] == 409


def test_the_printer_is_never_listed_used_or_forgotten(rig):
    bus, m, _ = rig
    bus.add(PRN, "MP210", cls=0x040680, icon="printer", paired=True)
    m.run_once()
    v = m.snapshot()
    assert PRN not in [r["mac"] for r in v["mine"] + v["nearby"] + v["others"]]
    assert m.do({"do": "use", "mac": PRN})[0] == 400
    assert m.do({"do": "forget", "mac": PRN, "confirm": True})[0] == 400
    assert PRN in bus.known


def test_the_printer_by_its_setting_whatever_its_class(tmp_path):
    bus = FakeBus()
    bus.add(PRN, "Thing", paired=True, icon="audio-card")
    m = BtManager(bus, printer_mac=PRN, path=tmp_path / "b.json")
    m.run_once()
    assert m.snapshot()["mine"] == []
    assert m.do({"do": "forget", "mac": PRN, "confirm": True})[0] == 400


def test_the_lists(rig):
    bus, m, _ = rig
    bus.add("B0:00:00:00:00:01", "Somebody's phone", cls=0x5a020c, icon="phone", seen=True)
    bus.add("B0:00:00:00:00:02", None, seen=True)
    bus.add("B0:00:00:00:00:03", "No class", seen=True)
    bus.add("B0:00:00:00:00:04", "Same", cls=SPEAKER_CLASS, seen=True)
    bus.add("B0:00:00:00:00:05", "Same", cls=SPEAKER_CLASS, seen=True)
    seen(bus, m)
    m.run_once()
    v = m.snapshot()
    near = [r["name"] for r in v["nearby"]]
    assert "No class" in near and "Same (00:04)" in near and "Same (00:05)" in near
    assert "Somebody's phone" not in near
    assert {r["name"] for r in v["others"]} == {"Somebody's phone", "Unnamed 00:02"}
    assert not any("mac_shown" in r for r in v["nearby"])


def test_the_order_does_not_move_when_the_signal_does(rig):
    bus, m, _ = rig
    bus.add("B0:00:00:00:00:04", "Far", cls=SPEAKER_CLASS, RSSI=-80, seen=True)
    bus.add("B0:00:00:00:00:05", "Near", cls=SPEAKER_CLASS, RSSI=-40, seen=True)
    seen(bus, m)
    m.run_once()
    first = [r["mac"] for r in m.snapshot()["nearby"]]
    bus.known["B0:00:00:00:00:04"]["RSSI"] = -20
    m.run_once()
    assert [r["mac"] for r in m.snapshot()["nearby"]] == first
    assert first.index("B0:00:00:00:00:05") < first.index("B0:00:00:00:00:04")


def ready(bus, m):
    seen(bus, m)
    m.do({"do": "use", "mac": SPK})
    m.run_once()
    assert m.chosen == SPK


def test_a_drop_is_seen_retried_with_a_backoff_and_never_during_a_turn(rig):
    bus, m, clock = rig
    ready(bus, m)
    bus.drop(SPK)
    bus.behaviour[SPK] = "off"
    m.run_once()
    assert m.snapshot()["chosen"]["lost"] is True
    bus.calls.clear()
    m.run_once()
    assert "Connect" not in names(bus.calls)
    m.busy = lambda: "speaking"
    clock.t += 21
    m.run_once()
    assert "Connect" not in names(bus.calls)
    m.busy = lambda: ""
    for _ in range(bt.RETRY_FAST):
        m.run_once()
        clock.t += 21
    assert names(bus.calls).count("Connect") == bt.RETRY_FAST
    m.run_once()
    assert names(bus.calls).count("Connect") == bt.RETRY_FAST
    clock.t += 60
    m.run_once()
    assert names(bus.calls).count("Connect") == bt.RETRY_FAST + 1
    bus.behaviour[SPK] = "good"
    clock.t += 60
    m.run_once()
    m.run_once()
    assert m.snapshot()["chosen"]["ready"] is True and m._tries == 0


def test_the_choice_and_the_delay_survive_a_restart_and_connect_at_once(rig, tmp_path):
    bus, m, _ = rig
    ready(bus, m)
    assert m.do({"do": "delay", "mac": SPK, "ms": 350})[0] == 200
    bus.drop(SPK)
    bus.calls.clear()
    fresh = BtManager(bus, sinks=lambda: bus.sinks, path=tmp_path / "bt.json", clock=Clock())
    assert fresh.chosen == SPK and fresh.delays[SPK] == 350
    fresh.run_once()
    assert "Connect" in names(bus.calls)


def test_a_corrupt_state_file_is_nothing(tmp_path):
    (tmp_path / "bt.json").write_text("{nope")
    assert BtManager(FakeBus(), path=tmp_path / "bt.json").chosen == ""


def test_stop_using_and_forget(rig):
    bus, m, _ = rig
    ready(bus, m)
    assert m.do({"do": "stop_using", "mac": SPK})[0] == 200
    m.run_once()
    assert m.chosen == "" and bus.known[SPK]["Paired"] and not bus.known[SPK]["Connected"]
    assert m.do({"do": "forget", "mac": SPK})[0] == 400
    assert m.do({"do": "forget", "mac": SPK, "confirm": True})[0] == 200
    m.run_once()
    assert SPK not in bus.known and SPK not in m.delays


def test_validation(rig):
    bus, m, _ = rig
    assert m.do({"do": "nope"})[0] == 400
    assert m.do({"do": "use", "mac": "not a mac"})[0] == 400
    assert m.do({"do": "use", "mac": "A0:00:00:00:00:99"})[0] == 400
    assert m.do({"do": "delay", "mac": SPK, "ms": 900})[0] == 400
    assert m.do({"do": "delay", "mac": SPK, "ms": "x"})[0] == 400
    assert m.do({"do": "answer", "pin": "1"})[0] == 409


def test_bluez_going_away_and_coming_back(rig):
    bus, m, _ = rig
    bus.up = False
    m.run_once()
    v = m.snapshot()
    assert v["alive"] is False and "not answering" in v["problem"]
    bus.up = True
    m.run_once()
    assert m.snapshot()["alive"] is True and m.snapshot()["problem"] == ""


@pytest.mark.parametrize("name,text,code", [
    ("org.bluez.Error.AuthenticationFailed", "", "refused"),
    ("org.bluez.Error.AuthenticationTimeout", "", "no_answer"),
    ("org.bluez.Error.ConnectionAttemptFailed", "Page Timeout", "off_or_far"),
    ("org.bluez.Error.Failed", "br-connection-busy", "held"),
    ("org.bluez.Error.Failed", "br-connection-refused", "held"),
    ("org.bluez.Error.Failed", "br-connection-key-missing", "key_lost"),
    ("org.bluez.Error.Failed", "something new", "off_or_far"),
])
def test_the_error_sentences(name, text, code):
    assert bt.error_code(BusError(name, text)) == code
    assert code in bt.SENTENCES


# ---- the route ------------------------------------------------------------------------------------

def test_with_chosen_nothing_chosen_is_unchanged():
    bt._manager = None
    assert bt.with_chosen(["a", "b"]) == ["a", "b"] and bt.delay_for("a") is None


def test_with_chosen_goes_first_once(rig):
    bus, m, _ = rig
    ready(bus, m)
    bt._manager = m
    route = bt.sink_pattern(SPK)
    assert route == "bluez_output.A0_00_00_00_00_01.*"
    assert bt.with_chosen(["usb", route]) == [route, "usb"]
    assert bt.delay_for(route) == bt.DELAY_MS and bt.delay_for("usb") is None


def test_chosen_beats_usb_and_a_missing_sink_falls_to_usb(rig):
    bus, m, _ = rig
    ready(bus, m)
    bt._manager = m
    usb, sink = "alsa_output.usb-Jieli", "bluez_output.A0_00_00_00_00_01.1"
    routes = bt.with_chosen(["alsa_output.usb-*", "bluez_output.*", "phone"])
    got = devices.speaker_routes(routes, False, [usb, sink], 0, {})
    assert got[0] == (bt.sink_pattern(SPK), sink)
    got = devices.speaker_routes(routes, False, [usb], 0, {})
    assert got[0] == ("alsa_output.usb-*", usb)


class _Sinks:
    def __init__(self, names):
        self.names = names

    def sinks(self):
        return [{"id": i, "name": n} for i, n in enumerate(self.names)]

    def poke(self):
        pass


def _wav(path):
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000)
        w.writeframes(b"\0\0" * 8000)
    return path


def test_the_player_uses_the_speakers_own_delay_and_the_slider_follows(rig, tmp_path, monkeypatch):
    bus, m, _ = rig
    ready(bus, m)
    bt._manager = m
    m.do({"do": "delay", "mac": SPK, "ms": 350})
    cfg = Config()
    cfg.audio.routes = ["alsa_output.usb-*", "bluez_output.*"]
    cache = _Sinks(["alsa_output.usb-J", "bluez_output.A0_00_00_00_00_01.1"])
    p = audio_route.RoutedPlayer(cfg, cache=cache)
    p._cool[bt.sink_pattern(SPK)] = 0.0
    assert p._delay(bt.sink_pattern(SPK)) == 0.35
    v = p.view()
    assert v["next"] == bt.sink_pattern(SPK) and v["sink_id"] == 1


def _script(tmp_path, body):
    f = tmp_path / "fake-pw"
    f.write_text("#!/bin/sh\n" + body + "\n")
    f.chmod(0o755)
    return str(f)


def test_a_late_error_exit_is_not_heard(tmp_path):
    p = audio_route.PwPlayer("n", exe=_script(tmp_path, "sleep 0.3; exit 1"))
    p.play(_wav(tmp_path / "a.wav"))
    assert p.wait() is False


def test_a_clean_exit_and_our_own_stop_are_heard(tmp_path):
    p = audio_route.PwPlayer("n", exe=_script(tmp_path, "sleep 0.3; exit 0"))
    p.play(_wav(tmp_path / "a.wav"))
    assert p.wait() is True
    p = audio_route.PwPlayer("n", exe=_script(tmp_path, "sleep 5"))
    p.play(_wav(tmp_path / "a.wav"))
    p.stop()
    assert p.wait() is True


# ---- the device row -------------------------------------------------------------------------------

ROUTE = "bluez_output.A0_00_00_00_00_01.*"
USB = "alsa_output.usb-*"


def _row(**kw):
    f = devices.Facts(audio_routes=[ROUTE, USB], sinks=["alsa_output.usb-J"], bt_route=ROUTE,
                      bt_name="JBL", **kw)
    return devices._speaker(f)


def test_the_row_names_the_speaker():
    r = _row(audio_next=ROUTE)
    assert r["level"] == "ok" and r["state"] == "Bluetooth · JBL" and r["present"] is True


def test_a_lost_speaker_warns_and_never_offers_the_usb_mark():
    r = _row(audio_next=USB)
    assert r["level"] == "warn" and "JBL" in r["reason"] and r["state"] == "USB"
    assert r["present"] is True and r["dead"] is False


def test_no_route_left_is_still_bad():
    assert _row(audio_next="none")["level"] == "bad"


def test_nothing_chosen_is_the_old_table():
    assert devices.build(devices.Facts()) == devices.build(devices.Facts(bt_route="", bt_name=""))


# ---- the setting ----------------------------------------------------------------------------------

def test_the_setting():
    assert BluetoothConfig(setting="").kind() == "off"
    assert BluetoothConfig(setting="MOCK").kind() == "mock"
    assert BluetoothConfig(setting="on").kind() == "on"
    assert BluetoothConfig(setting="maybe").kind() == "bad" and "maybe" in BluetoothConfig(setting="maybe").problem()


def test_off_and_bad_make_nothing_and_import_no_dbus():
    code = ("import sys; from fish_brain import bt; from fish_brain.config import BluetoothConfig as C;"
            "assert bt.make_bt(C(setting='')) is None; assert bt.make_bt(C(setting='maybe')) is None;"
            "assert 'dbus_fast' not in sys.modules and 'fish_brain.bt_bluez' not in sys.modules")
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


def test_on_with_no_library_shows_the_problem_and_lives(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "fish_brain.bt_bluez", None)
    m = bt.make_bt(BluetoothConfig(setting="on", state_path=str(tmp_path / "s.json")))
    try:
        for _ in range(100):
            if m.problem:
                break
            time.sleep(0.01)
        assert m is not None and m.snapshot()["alive"] is False and m.problem
    finally:
        bt.close()


def test_the_state_file_is_valid_json(rig, tmp_path):
    bus, m, _ = rig
    ready(bus, m)
    data = json.loads((tmp_path / "bt.json").read_text())
    assert data["chosen"] == SPK and data["name"] == "JBL Flip"
