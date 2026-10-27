"""Speaker routes: the first route that is there plays; a failure moves the same phrase on;
nothing hangs; the motors follow the real start."""
import os
import stat
import time
import wave

import pytest

from fish_brain import audio_route
from fish_brain.audio_route import PlaybackError, PwPlayer, RoutedPlayer, parse_delays
from fish_brain.config import Config


def _wav(path, seconds=0.3):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return path


def _exe(tmp_path, name, body):
    p = tmp_path / name
    p.write_text("#!/bin/sh\n" + body + "\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def test_pw_player_plays_and_finishes(tmp_path):
    p = PwPlayer("usb", exe=_exe(tmp_path, "ok", "sleep 0.3"))
    p.play(_wav(tmp_path / "a.wav"))
    assert p.started_at is not None and p.wait() is True


def test_pw_player_that_fails_at_once_raises(tmp_path):
    p = PwPlayer("gone", exe=_exe(tmp_path, "bad", "echo 'no target' >&2; exit 1"))
    with pytest.raises(PlaybackError):
        p.play(_wav(tmp_path / "a.wav", 1.0))


def test_pw_player_that_hangs_is_cut(tmp_path):
    p = PwPlayer("stuck", exe=_exe(tmp_path, "hang", "sleep 30"), stall_s=0.3)
    p.play(_wav(tmp_path / "a.wav", 0.2))
    t0 = time.monotonic()
    assert p.wait() is False and time.monotonic() - t0 < 2.0


class Cache:
    def __init__(self, names):
        self.names, self.pokes = list(names), 0

    def sinks(self):
        return [{"id": i, "name": n, "desc": n} for i, n in enumerate(self.names)]

    def find_sink(self, pattern):
        import fnmatch
        return next((s for s in self.sinks() if fnmatch.fnmatch(s["name"], pattern)), None)

    def poke(self):
        self.pokes += 1


class FakePw:
    fail: set = set()
    played: list = []

    def __init__(self, node, stall_s=2.0):
        self.node, self.started_at = node, None

    def play(self, wav):
        if self.node in FakePw.fail:
            raise PlaybackError("gone")
        self.started_at = time.monotonic()
        FakePw.played.append(self.node)

    def wait(self, timeout=None):
        return True

    def stop(self):
        pass


class Viz:
    def __init__(self, pages=1, starts=True):
        self.pages, self.starts, self.asked = pages, starts, 0

    def speaker_pages(self):
        return self.pages

    def phone_play(self, wav, timeout_s=2.5):
        self.asked += 1
        return time.monotonic() if self.starts else None

    def phone_stop(self):
        pass


@pytest.fixture
def routed(monkeypatch, tmp_path):
    FakePw.fail, FakePw.played = set(), []
    monkeypatch.setattr(audio_route, "PwPlayer", FakePw)

    def build(sinks, viz=None, delays=""):
        cfg = Config()
        cfg.audio.routes = ("alsa_output.usb-*", "bluez_output.*", "phone")
        cfg.audio.delay_ms = delays
        return RoutedPlayer(cfg, viz, cache=Cache(sinks)), _wav(tmp_path / "w.wav")
    return build


def test_the_usb_speaker_first(routed):
    p, wav = routed(["alsa_output.platform-sound.Headphones", "alsa_output.usb-Jieli_x"])
    p.play(wav)
    assert p.route == "alsa_output.usb-*" and FakePw.played == ["alsa_output.usb-Jieli_x"]


def test_the_onboard_codec_is_never_chosen(routed):
    p, wav = routed(["alsa_output.platform-sound.Headphones"], viz=Viz(pages=0))
    p.play(wav)
    assert p.route == "none" and FakePw.played == []


def test_a_failing_route_moves_the_same_phrase_on_and_cools(routed):
    p, wav = routed(["alsa_output.usb-Jieli_x", "bluez_output.AA_BB"])
    FakePw.fail = {"alsa_output.usb-Jieli_x"}
    p.play(wav)
    assert p.route == "bluez_output.*" and "alsa_output.usb-*" in p.view()["cooling"]
    FakePw.fail = set()
    p.play(wav)                                       # still cooling: Bluetooth again
    assert p.route == "bluez_output.*"


def test_the_phone_when_no_sink_is_left(routed):
    viz = Viz(pages=1)
    p, wav = routed([], viz=viz)
    p.play(wav)
    assert p.route == "phone" and viz.asked == 1


def test_a_phone_that_does_not_start_leaves_silence(routed):
    p, wav = routed([], viz=Viz(pages=1, starts=False))
    p.play(wav)
    assert p.route == "none" and "phone" in p.view()["cooling"]


def test_route_delays_are_read_per_route(routed):
    p, wav = routed(["bluez_output.AA"], delays="bluez_output.*=180,phone=120")
    p.play(wav)
    assert p.delay_s == pytest.approx(0.18)
    assert parse_delays("x=1, bad, y=z") == [("x", 1)]


def test_no_route_means_no_motor_lines(routed, tmp_path):
    from fish_brain.conductor import perform
    from fish_brain.serial_link import MockSerialLink
    import io
    p, wav = routed([], viz=Viz(pages=0))
    out = io.StringIO()
    cfg = Config()
    link = MockSerialLink(cfg.serial, stream=out)
    perform(wav, [(0, 200, 50), (100, -200, 50)], [(50, "TAIL", "200 100")], link, cfg, player=p)
    lines = out.getvalue()
    assert "MOUTH 200 50" not in lines and "TAIL" not in lines   # only the end pulse


def test_motors_run_later_by_the_route_delay(routed, tmp_path, monkeypatch):
    from fish_brain import conductor
    from fish_brain.serial_link import MockSerialLink
    import io
    p, wav = routed(["bluez_output.AA"], delays="bluez_output.*=200")
    cfg = Config()
    cfg.conductor.sync_offset_ms = 0
    sent = []
    link = MockSerialLink(cfg.serial, stream=io.StringIO())
    monkeypatch.setattr(link, "mouth_pulse", lambda pwm, ms: sent.append(time.monotonic()))
    conductor.perform(wav, [(0, 200, 50)], [], link, cfg, player=p)
    assert sent[0] - p.started_at >= 0.18


def test_view_next_is_the_route_the_next_phrase_takes(routed, monkeypatch, tmp_path):
    from fish_brain import hw
    marks = hw.Marks(tmp_path / "hw.json")
    monkeypatch.setattr(hw, "_marks", marks)
    p, wav = routed(["alsa_output.usb-Jieli_x", "bluez_output.AA_BB"], viz=Viz(pages=1))
    assert p.view()["next"] == "alsa_output.usb-*"
    p.play(wav)
    marks.failed = {"speaker"}                       # a mark shows at once, before a phrase
    v = p.view()
    assert v["route"] == "alsa_output.usb-*" and v["next"] == "bluez_output.*"
    marks.failed = set()
    FakePw.fail = {"alsa_output.usb-Jieli_x"}
    p.play(wav)                                       # the USB route cools
    assert p.view()["next"] == "bluez_output.*"
    p2, _ = routed([], viz=Viz(pages=0))
    assert p2.view()["next"] == "none"


def test_next_after_a_mark_and_while_cooling_follows_the_device_table(routed, monkeypatch, tmp_path):
    """The routes come from devices.speaker_routes: a mark and a cooling show in `next` at once,
    and the phone only with an armed page."""
    from fish_brain import devices, hw
    marks = hw.Marks(tmp_path / "hw.json")
    monkeypatch.setattr(hw, "_marks", marks)
    viz = Viz(pages=0)
    p, wav = routed(["alsa_output.usb-Jieli_x"], viz=viz)
    assert p.view()["next"] == "alsa_output.usb-*"
    marks.failed = {"speaker"}
    assert p.view()["next"] == "none"                 # no Bluetooth, no armed phone
    viz.pages = 1
    assert p.view()["next"] == "phone"
    marks.failed = set()
    FakePw.fail = {"alsa_output.usb-Jieli_x"}
    p.play(wav)                                       # USB fails, the phone takes the phrase
    assert p.route == "phone" and p.view()["next"] == "phone"
    assert [r for r, _ in devices.speaker_routes(
        p.cfg.routes, False, p.cache.sinks(), 1, p._cool, p._clock())] == ["phone"]
