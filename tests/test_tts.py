"""The OpenAI voice: the WAV it writes and the cache key, with a fake client (no network)."""
from __future__ import annotations

import wave
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from fish_brain import cloud, tts
from fish_brain.config import TTSConfig

PCM = bytes(range(256)) * 200          # 25 600 samples of 16-bit mono


@pytest.fixture
def speech(monkeypatch):
    sent = []

    @contextmanager
    def create(**kw):
        sent.append(kw)
        yield SimpleNamespace(read=lambda: PCM)

    client = SimpleNamespace(audio=SimpleNamespace(speech=SimpleNamespace(
        with_streaming_response=SimpleNamespace(create=create))))
    monkeypatch.setattr(cloud, "client", lambda *a, **k: client)
    monkeypatch.setattr(cloud, "is_online", lambda: True)
    return sent


def _render(tmp_path, factor):
    out = tts.synthesize("Hmm, difícil.", TTSConfig(backend="openai", openai_rate_factor=factor),
                         tmp_path / "x.wav")
    with wave.open(str(out)) as w:
        return w.getframerate(), w.readframes(w.getnframes())


def test_the_rate_factor_relabels_the_same_samples(speech, tmp_path):
    assert _render(tmp_path, 1.0) == (24000, PCM)
    assert _render(tmp_path, 0.88) == (21120, PCM)
    assert speech[-1]["response_format"] == "pcm" and speech[-1]["voice"] == "ash"


def test_the_cache_key_changes_with_the_factor_and_not_at_one():
    key = lambda f: tts.fingerprint(TTSConfig(backend="openai", openai_rate_factor=f))
    assert "|x" not in key(1.0)                     # the files cached before the factor stay valid
    assert key(0.88) == key(1.0) + "|x0.88" and key(0.9) != key(0.88)


def test_the_reshaping_runs_rubberband_after_the_render_and_keys_the_cache(speech, tmp_path,
                                                                          monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        src, dst = Path(cmd[-2]), Path(cmd[-1])
        dst.write_bytes(src.read_bytes())          # stands in for the shaped file
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(tts.subprocess, "run", fake_run)
    cfg = TTSConfig(backend="openai", pitch_st=-2.0, tempo=0.72)
    out = tts.synthesize("Hmm, difícil.", cfg, tmp_path / "x.wav")
    assert calls == [["rubberband", "-q", "-F", "-p-2", "-T0.72", str(out), str(out) + ".shaped.wav"]]
    assert out.exists() and not Path(str(out) + ".shaped.wav").exists()
    plain = tts.fingerprint(TTSConfig(backend="openai"))
    assert tts.fingerprint(cfg) == plain + "|p-2t0.72"
    assert tts.fingerprint(TTSConfig(backend="loq", pitch_st=-2.0)).endswith("|p-2t1")
    calls.clear()
    tts.synthesize("Hmm.", TTSConfig(backend="openai"), tmp_path / "y.wav")
    assert calls == []                             # untouched unless asked


def test_a_missing_rubberband_fails_the_render_and_names_the_package(speech, tmp_path,
                                                                    monkeypatch, capsys):
    cfg = TTSConfig(backend="openai", pitch_st=-2.0, tempo=0.72,
                    rubberband_bin="/nonexistent/rubberband")
    with pytest.raises(RuntimeError, match="rubberband-cli"):
        tts.synthesize("Hmm.", cfg, tmp_path / "x.wav")
    tts.warm(cfg)
    assert "rubberband-cli" in capsys.readouterr().err


def test_a_factor_out_of_range_is_refused(monkeypatch):
    for bad in (0.4, 1.6):
        with pytest.raises(ValueError):
            TTSConfig(openai_rate_factor=bad)
        with pytest.raises(ValueError):
            TTSConfig(tempo=bad)
    with pytest.raises(ValueError):
        TTSConfig(pitch_st=-13.0)
    monkeypatch.setenv("FISH_TTS_RATE_FACTOR", "0.88")
    assert TTSConfig().openai_rate_factor == 0.88


def _fake_tools(monkeypatch, calls):
    def fake_run(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == "loq":                         # the render: a small valid WAV
            with wave.open(cmd[2], "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(PCM)
            return SimpleNamespace(returncode=0, stderr="", stdout="")
        src, dst = (cmd[-2], cmd[-1]) if cmd[0] == "rubberband" else (cmd[2], cmd[3])
        Path(dst).write_bytes(Path(src).read_bytes())
        return SimpleNamespace(returncode=0, stderr="")
    monkeypatch.setattr(tts.subprocess, "run", fake_run)


STONE = ["highpass", "80", "equalizer", "140", "1q", "+3", "reverb", "25", "60", "25", "100",
         "5", "-3", "gain", "-n", "-1"]


def test_shifted_formants_are_one_sox_pass_after_the_licence_guard(tmp_path, monkeypatch):
    calls, order = [], []
    _fake_tools(monkeypatch, calls)
    monkeypatch.setattr(tts.voice_guard, "before_render", lambda cfg: None)
    monkeypatch.setattr(tts.voice_guard, "after_render",
                        lambda cfg, path: order.append(len(calls)))
    cfg = TTSConfig(backend="loq", pitch_st=-2.0, formants="shift", room="stone")
    out = tts.synthesize("Lo veo clarito.", cfg, tmp_path / "x.wav")
    assert [c[0] for c in calls] == ["loq", "sox"]  # no rubberband
    assert order == [1]                             # the guard saw the raw render only
    assert calls[1] == ["sox", "-q", str(out), str(out) + ".sox.wav", "pitch", "-200", *STONE]
    assert not Path(str(out) + ".sox.wav").exists()
    assert tts.fingerprint(cfg).endswith("|p-2t1fs|room=stone")


def test_a_tempo_with_shifted_formants_is_in_the_same_pass(speech, tmp_path, monkeypatch):
    calls = []
    _fake_tools(monkeypatch, calls)
    out = tts.synthesize("Hmm.", TTSConfig(backend="openai", pitch_st=-1.0, tempo=0.9,
                                           formants="shift"), tmp_path / "x.wav")
    assert calls == [["sox", "-q", str(out), str(out) + ".sox.wav", "pitch", "-100", "tempo", "0.9"]]


def test_kept_formants_stay_on_rubberband_and_the_room_follows_in_sox(speech, tmp_path,
                                                                     monkeypatch):
    calls = []
    _fake_tools(monkeypatch, calls)
    out = tts.synthesize("Hmm.", TTSConfig(backend="openai", pitch_st=-2.0, room="stone"),
                         tmp_path / "x.wav")
    assert calls == [["rubberband", "-q", "-F", "-p-2", "-T1", str(out), str(out) + ".shaped.wav"],
                     ["sox", "-q", str(out), str(out) + ".sox.wav", *STONE]]
    calls.clear()
    tts.synthesize("Hola.", TTSConfig(backend="openai", room="stone"), tmp_path / "y.wav")
    assert [c[0] for c in calls] == ["sox"]         # a room alone, no shaping
    assert TTSConfig().formants == "keep"           # the laptop keeps them


def test_no_effect_by_default_and_the_key_unchanged(speech, tmp_path, monkeypatch):
    calls = []
    _fake_tools(monkeypatch, calls)
    tts.synthesize("Hmm.", TTSConfig(backend="openai"), tmp_path / "x.wav")
    assert calls == []
    assert "room" not in tts.fingerprint(TTSConfig(backend="loq"))
    kept = tts.fingerprint(TTSConfig(backend="openai", pitch_st=-2.0))
    assert tts.fingerprint(TTSConfig(backend="openai", pitch_st=-2.0, formants="shift")) == kept + "fs"


def test_a_missing_sox_fails_the_render_and_names_the_package(speech, tmp_path, capsys):
    cfg = TTSConfig(backend="openai", pitch_st=-2.0, formants="shift", sox_bin="/nonexistent/sox")
    with pytest.raises(RuntimeError, match="apt install sox"):
        tts.synthesize("Hmm.", cfg, tmp_path / "x.wav")
    tts.warm(cfg)
    err = capsys.readouterr().err
    assert "apt install sox" in err and "rubberband" not in err


def test_unknown_formants_or_room_are_refused(monkeypatch):
    with pytest.raises(ValueError):
        TTSConfig(formants="up")
    with pytest.raises(ValueError):
        TTSConfig(room="cathedral")
    monkeypatch.setenv("FISH_TTS_ROOM", "stone")
    monkeypatch.setenv("FISH_TTS_FORMANTS", "shift")
    assert (TTSConfig().room, TTSConfig().formants) == ("stone", "shift")
