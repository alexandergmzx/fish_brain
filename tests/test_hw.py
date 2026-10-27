"""hw.py: the parts he marks failed, and what the fish does about each."""
import io
import time

import pytest

from fish_brain import audio_route, hw
from fish_brain.config import Config
from fish_brain.serial_link import MockSerialLink


@pytest.fixture
def marks(tmp_path, monkeypatch):
    m = hw.Marks(tmp_path / "hw.json")
    monkeypatch.setattr(hw, "_marks", m)
    return m


def test_marks_persist_and_unknown_parts_are_refused(marks, tmp_path):
    marks.set("speaker", True)
    assert hw.Marks(tmp_path / "hw.json").failed == {"speaker"}      # survives a restart
    marks.set("speaker", False)
    assert hw.Marks(tmp_path / "hw.json").failed == set()
    with pytest.raises(ValueError):
        marks.set("toaster", True)


def test_a_failed_mic_records_on_the_phone_and_back(marks):
    cfg = Config()
    cfg.ptt.capture = "auto"
    marks.set("mic", True)
    hw.apply(cfg)
    assert cfg.ptt.capture == "browser"
    marks.set("mic", False)
    hw.apply(cfg)
    assert cfg.ptt.capture == "auto"


def test_failed_motors_mute_the_link(marks):
    cfg = Config()
    link = MockSerialLink(cfg.serial, stream=io.StringIO())
    marks.set("motors", True)
    hw.apply(cfg, link=link)
    assert link.muted
    marks.set("motors", False)
    hw.apply(cfg, link=link)
    assert not link.muted


def test_a_failed_usb_speaker_is_skipped(marks, monkeypatch, tmp_path):
    import wave
    from test_audio_route import Cache, FakePw, Viz
    monkeypatch.setattr(audio_route, "PwPlayer", FakePw)
    FakePw.fail, FakePw.played = set(), []
    cfg = Config()
    cfg.audio.routes = ("alsa_output.usb-*", "bluez_output.*", "phone")
    p = audio_route.RoutedPlayer(cfg, Viz(pages=1), cache=Cache(["alsa_output.usb-J"]))
    wav = tmp_path / "w.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\0\0" * 1600)
    marks.set("speaker", True)
    p.play(wav)
    assert p.route == "phone"
    marks.set("speaker", False)
    p.play(wav)
    assert p.route == "alsa_output.usb-*"


def test_failed_internet_runs_the_script(marks, monkeypatch, tmp_path):
    from fish_brain import cloud
    from test_show_conversation import make  # noqa: F401  (fixture import)
    monkeypatch.setenv("FISH_PERSONA", "hat")
    monkeypatch.setenv("FISH_SHOW", "auto")
    monkeypatch.setattr(cloud, "is_online", lambda: True)
    from fish_brain.conversation import FishConversation
    cfg = Config()
    cfg.show.state = str(tmp_path / "s.json")
    c = FishConversation(cfg, MockSerialLink(cfg.serial, stream=io.StringIO()),
                         text_input=True, play_audio=False)
    marks.set("internet", True)
    assert c.show.mode_now() == ("script", "internet marked failed")
