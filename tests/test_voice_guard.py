"""voice_guard: the Loquendo licence warning is never spoken live and never cached."""
import wave
from pathlib import Path

import pytest

from fish_brain import canned, tts, voice_guard
from fish_brain.config import Config, TTSConfig

CLEAN_S, WARNING_S = 3.0, 4.5


def _wav(path: Path, seconds: float, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))


@pytest.fixture
def voice(monkeypatch):
    """A fake loq: each render takes its length from `lengths` (the last one repeats)."""
    lengths: list[float] = []
    calls: list[str] = []

    def synth(text, cfg, out_path):
        calls.append(text)
        _wav(Path(out_path), lengths.pop(0) if len(lengths) > 1 else lengths[0])

    monkeypatch.setattr(tts, "_synthesize_loq", synth)
    monkeypatch.setattr(tts.subprocess, "run", lambda *a, **k: None)     # loq --start
    recovered: list[int] = []
    monkeypatch.setattr(voice_guard, "recover", lambda cfg: recovered.append(1))
    started: list[int] = []
    monkeypatch.setattr(voice_guard, "_start_recheck", lambda cfg: started.append(1))
    monkeypatch.setattr(voice_guard, "_state", voice_guard.OFF)
    return lengths, calls, recovered, started


def _cfg(**kw) -> TTSConfig:
    c = TTSConfig()
    c.backend = "loq"
    c.loq_prefix, c.loq_hum, c.say_as = "", "", {}
    c.loq_probe_s = kw.get("probe_s", CLEAN_S)
    c.loq_warning_s = kw.get("warning_s", WARNING_S)
    return c


def test_off_without_a_probe_length(voice):
    lengths, calls, _, _ = voice
    lengths.append(CLEAN_S)
    assert voice_guard.warm(_cfg(probe_s=0)) == voice_guard.OFF
    assert calls == []
    voice_guard.before_render(_cfg(probe_s=0))          # never refuses


def test_a_clean_probe(voice):
    lengths, calls, recovered, _ = voice
    lengths.append(CLEAN_S + 0.1)
    assert voice_guard.warm(_cfg()) == voice_guard.CLEAN
    assert len(calls) == 1 and recovered == []


def test_a_warning_at_start_recovers_on_a_fresh_wineserver(voice):
    lengths, calls, recovered, started = voice
    lengths.extend([WARNING_S, CLEAN_S])
    assert voice_guard.warm(_cfg()) == voice_guard.CLEAN
    assert recovered == [1] and started == []


def test_still_bad_is_tainted_and_nothing_renders(voice, tmp_path):
    lengths, calls, recovered, started = voice
    lengths.append(WARNING_S)
    cfg = _cfg()
    assert voice_guard.warm(cfg) == voice_guard.TAINTED
    assert started == [1]
    n = len(calls)
    with pytest.raises(voice_guard.VoiceUnavailable):
        tts.synthesize("Hola", cfg, tmp_path / "x.wav")
    assert len(calls) == n and not (tmp_path / "x.wav").exists()


def test_a_render_as_long_as_the_warning_is_deleted_when_the_probe_fails(voice, tmp_path):
    lengths, calls, _, started = voice
    lengths.extend([CLEAN_S, WARNING_S, WARNING_S])     # warm clean; then the voice turns bad
    cfg = _cfg()
    assert voice_guard.warm(cfg) == voice_guard.CLEAN
    out = tmp_path / "reply.wav"
    with pytest.raises(voice_guard.VoiceUnavailable):
        tts.synthesize("Una respuesta cualquiera.", cfg, out)
    assert not out.exists() and voice_guard.state() == voice_guard.TAINTED and started == [1]


def test_a_render_as_long_as_the_warning_is_kept_when_the_probe_is_clean(voice, tmp_path):
    lengths, calls, _, _ = voice
    lengths.extend([CLEAN_S, WARNING_S, CLEAN_S])       # a real phrase that happens to be 4.5 s
    cfg = _cfg()
    voice_guard.warm(cfg)
    out = tts.synthesize("Una frase de cuatro segundos y medio.", cfg, tmp_path / "ok.wav")
    assert out.exists() and voice_guard.state() == voice_guard.CLEAN


def test_other_lengths_are_not_probed_again(voice, tmp_path):
    lengths, calls, _, _ = voice
    lengths.extend([CLEAN_S, 2.0])
    cfg = _cfg()
    voice_guard.warm(cfg)
    tts.synthesize("Corta.", cfg, tmp_path / "s.wav")
    assert len(calls) == 2                              # the probe and the phrase only


def test_a_canned_phrase_falls_back_instead_of_caching_the_warning(voice, tmp_path):
    lengths, calls, _, _ = voice
    lengths.extend([CLEAN_S, WARNING_S, WARNING_S])
    cfg = Config()
    cfg.tts = _cfg()
    cfg.canned.cache_dir = tmp_path
    cfg.canned.phrases = {"welcome": "Bienvenidos al sombrero."}
    older = tmp_path / "welcome-00000000.wav"
    _wav(older, 2.0)
    voice_guard.warm(cfg.tts)
    assert canned.ensure_rendered("welcome", cfg) == older
    assert sorted(p.name for p in tmp_path.iterdir()) == [older.name]


def test_own_mac_reads_only_the_permaddr_flag(monkeypatch):
    class Out:
        def __init__(self, s):
            self.stdout = s
    monkeypatch.setattr(voice_guard.subprocess, "run",
                        lambda *a, **k: Out('[{"ifname":"wlan0","address":"aa"}]'))
    assert voice_guard.own_mac("wlan0")
    monkeypatch.setattr(voice_guard.subprocess, "run",
                        lambda *a, **k: Out('[{"ifname":"wlan0","permaddr":"bb"}]'))
    assert not voice_guard.own_mac("wlan0")
