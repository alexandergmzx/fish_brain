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
