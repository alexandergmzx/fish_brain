"""`record_multi` with an inbox: an item from the page ends the wait without a microphone."""
import threading
import time

import numpy as np

import pytest

from fish_brain import ptt
from fish_brain.config import PTTConfig


_REAL_RECORD_UNTIL = ptt._record_until


@pytest.fixture(autouse=True)
def no_microphone(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("the microphone must not be opened")
    monkeypatch.setattr(ptt, "_record_until", boom)
    monkeypatch.setattr(ptt, "_cut_last", False)


class Item:
    pass


def test_inbox_item_returns_without_a_microphone():
    never_held = ptt.ButtonSource(lambda: False, name="web")
    item = Item()
    got = ptt.record_multi(PTTConfig(), [never_held], inbox=lambda: item)
    assert got is item


def test_inbox_item_wins_over_a_stale_press():
    # The button reads held from the start (a lost release): the wait for idle still listens.
    stuck = ptt.ButtonSource(lambda: True, name="web")
    item = Item()
    assert ptt.record_multi(PTTConfig(), [stuck], inbox=lambda: item) is item


def test_sources_are_disarmed_after_an_inbox_item():
    armed = []
    src = ptt.ButtonSource(lambda: False, arm=armed.append, name="remote")
    ptt.record_multi(PTTConfig(), [src], inbox=lambda: Item())
    assert armed == [True, False]


def test_no_sources_waits_on_the_inbox():
    box = []
    item = Item()
    threading.Timer(0.1, lambda: box.append(item)).start()
    t0 = time.monotonic()
    got = ptt.record_multi(PTTConfig(), [], inbox=lambda: box.pop() if box else None)
    assert got is item and 0.05 < time.monotonic() - t0 < 2.0


def test_no_sources_and_no_inbox_is_unavailable():
    with pytest.raises(ptt.PTTUnavailable):
        ptt.record_multi(PTTConfig(), [])


# --- a relayed source: the page records, this side only passes the edges ------------
class Flag:
    """A button driven by a test: `held` flips, `reset()` clears it (like the remote)."""

    def __init__(self):
        self.held = False
        self.resets = 0

    def is_held(self):
        return self.held

    def reset(self):
        self.held = False
        self.resets += 1


def relayed(flag, name="remote"):
    return ptt.ButtonSource(flag.is_held, reset=flag.reset, name=name, relay=True)


def test_relayed_edges_go_to_relay_and_the_inbox_item_returns():
    flag, calls, box = Flag(), [], []
    item = Item()
    threading.Timer(0.05, lambda: setattr(flag, "held", True)).start()
    threading.Timer(0.15, lambda: setattr(flag, "held", False)).start()
    threading.Timer(0.25, lambda: box.append(item)).start()      # the page's upload
    web = ptt.ButtonSource(lambda: False, name="web")
    got = ptt.record_multi(PTTConfig(), [web, relayed(flag)],
                           inbox=lambda: box.pop() if box else None, relay=calls.append)
    assert got is item
    assert calls == [True, False]


def test_relay_false_is_sent_on_exit_while_still_held():
    flag, calls = Flag(), []
    item = Item()
    box = []
    threading.Timer(0.05, lambda: setattr(flag, "held", True)).start()
    threading.Timer(0.15, lambda: box.append(item)).start()
    got = ptt.record_multi(PTTConfig(), [relayed(flag)],
                           inbox=lambda: box.pop() if box else None, relay=calls.append)
    assert got is item and calls == [True, False]


def test_relayed_hold_is_cut_at_the_limit():
    flag, calls = Flag(), []
    cfg = PTTConfig()
    cfg.max_record_s = 0.1
    box, item = [], Item()
    threading.Timer(0.02, lambda: setattr(flag, "held", True)).start()
    threading.Timer(0.4, lambda: box.append(item)).start()
    got = ptt.record_multi(cfg, [relayed(flag)],
                           inbox=lambda: box.pop() if box else None, relay=calls.append)
    assert got is item
    assert calls == [True, False] and flag.resets == 1


def test_relayed_source_held_at_the_start_waits_for_a_release():
    flag, calls = Flag(), []
    flag.held = True                                 # a lost release, or held while speaking
    box, item = [], Item()
    threading.Timer(0.05, lambda: setattr(flag, "held", False)).start()
    threading.Timer(0.1, lambda: setattr(flag, "held", True)).start()
    threading.Timer(0.2, lambda: box.append(item)).start()
    got = ptt.record_multi(PTTConfig(), [relayed(flag)],
                           inbox=lambda: box.pop() if box else None, relay=calls.append)
    assert got is item and calls == [True, False]


def test_a_relayed_press_records_here_when_the_page_left(monkeypatch, tmp_path):
    out = tmp_path / "rec.wav"
    monkeypatch.setattr(ptt, "_record_until", lambda stop, cfg, on_level=None: out)
    flag, calls = Flag(), []
    threading.Timer(0.05, lambda: setattr(flag, "held", True)).start()
    got = ptt.record_multi(PTTConfig(), [relayed(flag)], inbox=lambda: None,
                           relay=calls.append, relay_ready=lambda: False)
    assert got == out and calls == []


def test_a_relayed_press_goes_to_the_page_while_it_is_there(monkeypatch):
    monkeypatch.setattr(ptt, "_record_until",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("recorded")))
    flag, calls, box, item = Flag(), [], [], Item()
    threading.Timer(0.05, lambda: setattr(flag, "held", True)).start()
    threading.Timer(0.15, lambda: setattr(flag, "held", False)).start()
    threading.Timer(0.25, lambda: box.append(item)).start()
    got = ptt.record_multi(PTTConfig(), [relayed(flag)],
                           inbox=lambda: box.pop() if box else None,
                           relay=calls.append, relay_ready=lambda: True)
    assert got is item and calls == [True, False]


def test_a_source_without_relay_still_records(monkeypatch, tmp_path):
    out = tmp_path / "rec.wav"
    monkeypatch.setattr(ptt, "_record_until", lambda stop, cfg, on_level=None: out)
    flag, calls = Flag(), []
    web = Flag()
    threading.Timer(0.05, lambda: setattr(web, "held", True)).start()   # a fresh press on the page
    src = ptt.ButtonSource(web.is_held, reset=web.reset, name="web")
    got = ptt.record_multi(PTTConfig(), [src, relayed(flag)], inbox=lambda: None,
                           relay=calls.append)
    assert got == out and calls == []


def test_relay_flag_without_a_relay_callable_records_as_before(monkeypatch, tmp_path):
    out = tmp_path / "rec.wav"
    monkeypatch.setattr(ptt, "_record_until", lambda stop, cfg, on_level=None: out)
    flag = Flag()
    threading.Timer(0.05, lambda: setattr(flag, "held", True)).start()
    assert ptt.record_multi(PTTConfig(), [relayed(flag)], inbox=lambda: None) == out


def test_a_dead_stream_ends_the_recording(monkeypatch, tmp_path):
    """A remote whose microphone streams only while its key is held: exact zeros after sound
    end the recording by themselves (FISH_PTT_DEAD_S)."""
    import queue as queue_mod
    import types
    from fish_brain import ptt
    from fish_brain.config import PTTConfig

    cfg = PTTConfig()
    cfg.dead_s = 0.2
    chunks = [np.full(160, 0.3, dtype="float32")] * 3 + [np.zeros(160, dtype="float32")] * 200
    served = {"n": 0}

    class FakeStream:
        def __init__(self, **kw):
            self.cb = kw["callback"]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_get(self, timeout=None):
        if served["n"] >= len(chunks):
            raise queue_mod.Empty
        c = chunks[served["n"]]
        served["n"] += 1
        time.sleep(0.01)
        return (c * 32767).astype(np.int16)

    fake_sd = types.SimpleNamespace(InputStream=FakeStream)
    monkeypatch.setattr(ptt, "_resolve_input", lambda sd, cfg: (None, 16000))
    monkeypatch.setitem(__import__("sys").modules, "sounddevice", fake_sd)
    monkeypatch.setattr(queue_mod.Queue, "get", fake_get)
    monkeypatch.setattr(queue_mod.Queue, "empty", lambda self: True)
    t0 = time.monotonic()
    path = _REAL_RECORD_UNTIL(lambda: False, cfg)   # a fake stream; the predicate never stops it
    assert time.monotonic() - t0 < 2.0
    assert ptt.wav_duration_s(path) < 0.4            # three sound chunks and a short dead tail
    path.unlink()


def _fake_stream(monkeypatch, chunks):
    """A sounddevice stand-in that serves `chunks` (float32) 10 ms apart, then nothing."""
    import queue as queue_mod
    import types
    served = {"n": 0}

    class FakeStream:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_get(self, timeout=None):
        if served["n"] >= len(chunks):
            time.sleep(0.01)
            raise queue_mod.Empty
        c = chunks[served["n"]]
        served["n"] += 1
        time.sleep(0.01)
        return (c * 32767).astype(np.int16)

    monkeypatch.setattr(ptt, "_resolve_input", lambda sd, cfg: (None, 16000))
    monkeypatch.setitem(__import__("sys").modules, "sounddevice", types.SimpleNamespace(InputStream=FakeStream))
    monkeypatch.setattr(queue_mod.Queue, "get", fake_get)
    monkeypatch.setattr(queue_mod.Queue, "empty", lambda self: True)


LOUD = np.full(160, 0.3, dtype="float32")
QUIET = np.full(160, 0.01, dtype="float32")             # room noise, never exact zeros


def test_silence_after_speech_ends_the_recording(monkeypatch):
    """Talk, stop talking: FISH_PTT_SILENCE_END_S of nothing at or above quiet_rms ends it."""
    cfg = PTTConfig()
    cfg.silence_end_s = 0.15
    cfg.quiet_rms = 0.04
    _fake_stream(monkeypatch, [QUIET] * 3 + [LOUD] * 10 + [QUIET] * 300)
    t0 = time.monotonic()
    path = _REAL_RECORD_UNTIL(lambda: False, cfg)
    assert time.monotonic() - t0 < 2.0
    assert 0.1 < ptt.wav_duration_s(path) < 0.5        # the speech and a short quiet tail
    assert ptt.last_info()["ended"] == "silence"
    path.unlink()


def test_silence_from_the_start_ends_the_recording(monkeypatch):
    """Counted from the start too: a hold where nobody speaks ends by itself."""
    cfg = PTTConfig()
    cfg.silence_end_s = 0.15
    cfg.quiet_rms = 0.04
    _fake_stream(monkeypatch, [QUIET] * 300)
    t0 = time.monotonic()
    path = _REAL_RECORD_UNTIL(lambda: False, cfg)
    assert time.monotonic() - t0 < 1.0
    assert ptt.wav_duration_s(path) < 0.3
    assert ptt.last_info()["ended"] == "silence"
    path.unlink()


def test_the_silence_end_is_off_by_default(monkeypatch):
    cfg = PTTConfig()
    assert cfg.silence_end_s == 0.0 and cfg.quiet_rms == 0.04
    _fake_stream(monkeypatch, [QUIET] * 40)
    end = time.monotonic() + 0.3
    path = _REAL_RECORD_UNTIL(lambda: time.monotonic() > end, cfg)
    assert ptt.last_info()["ended"] == "release"
    path.unlink()


def test_the_silence_end_counts_from_the_last_sound():
    cfg = PTTConfig()
    cfg.silence_end_s = 0.3
    q16 = (QUIET * 32767).astype(np.int16)
    l16 = (LOUD * 32767).astype(np.int16)
    s = ptt._SilenceEnd(cfg)
    assert not s.over(q16)
    time.sleep(0.2)
    assert not s.over(l16)                             # a sound restarts the count
    time.sleep(0.2)
    assert not s.over(q16)                             # 0.2 s since the sound
    time.sleep(0.2)
    assert s.over(q16)


def test_a_silence_end_clears_the_button_and_is_not_a_cut(monkeypatch, tmp_path, capsys):
    out = tmp_path / "x.wav"
    cfg = PTTConfig()
    cfg.silence_end_s = 10.0

    def fake(stop, cfg, on_level=None):
        ptt._info["ended"] = "silence"
        return out
    monkeypatch.setattr(ptt, "_record_until", fake)
    flag = Flag()
    flag.held = True
    src = ptt.ButtonSource(lambda: flag.held, reset=flag.reset, name="remote")
    # Held at the start reads as stale: release it, then press again in a moment.
    threading.Timer(0.05, lambda: setattr(flag, "held", True)).start()
    flag.held = False
    got = ptt.record_multi(cfg, [src], inbox=lambda: None)
    assert got == out
    assert flag.resets >= 1 and not flag.held          # cleared at once, still pressed or not
    assert not ptt.last_recording_was_cut()             # the LLM is not told it was cut
    assert "[ptt] silence end: nothing heard for 10 s" in capsys.readouterr().out


def test_pw_record_capture_ends_on_silence(monkeypatch, tmp_path):
    import stat
    fake = tmp_path / "pw-record"
    fake.write_text("#!/bin/sh\nhead -c 64000 /dev/zero\nsleep 30\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr("shutil.which", lambda name: str(fake) if name == "pw-record" else None)
    cfg = PTTConfig()
    cfg.backend, cfg.source, cfg.silence_end_s = "pw-record", "mic", 0.3
    t0 = time.monotonic()
    wav = _REAL_RECORD_UNTIL(lambda: time.monotonic() - t0 > 5.0, cfg)
    assert time.monotonic() - t0 < 2.5
    assert ptt.last_info()["ended"] == "silence"
    wav.unlink()


def test_pw_record_capture_never_hangs_and_ends_its_process(monkeypatch, tmp_path):
    """A microphone that sends nothing is a MicError within the open limit (2026-10-13)."""
    import stat, time as _t
    from fish_brain import ptt as P
    from fish_brain.config import PTTConfig
    fake = tmp_path / "pw-record"
    fake.write_text("#!/bin/sh\nsleep 30\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr("shutil.which", lambda name: str(fake) if name == "pw-record" else None)
    cfg = PTTConfig()
    cfg.backend, cfg.source, cfg.open_timeout_s = "pw-record", "mic", 0.5
    t0 = _t.monotonic()
    with pytest.raises(P.MicError):
        _REAL_RECORD_UNTIL(lambda: False, cfg)
    assert _t.monotonic() - t0 < 3


def test_pw_record_capture_records_what_it_reads(monkeypatch, tmp_path):
    import stat
    from fish_brain import ptt as P
    from fish_brain.config import PTTConfig
    fake = tmp_path / "pw-record"
    fake.write_text("#!/bin/sh\nhead -c 32000 /dev/urandom\nsleep 30\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr("shutil.which", lambda name: str(fake) if name == "pw-record" else None)
    cfg = PTTConfig()
    cfg.backend, cfg.source = "pw-record", "mic"
    end = __import__("time").monotonic() + 0.8
    wav = _REAL_RECORD_UNTIL(lambda: __import__("time").monotonic() > end, cfg)
    assert 0.9 <= P.wav_duration_s(wav) <= 1.01      # 32000 bytes = 1 s at 16 kHz
    wav.unlink()


def test_two_silent_takes_of_exact_zeros_make_the_mic_dead(monkeypatch):
    import numpy as _np
    from fish_brain import ptt as P
    from fish_brain.config import PTTConfig
    monkeypatch.setattr(P, "_zero_takes", 0)
    P._note_take([_np.zeros(160, dtype=_np.int16)])
    assert not P.mic_dead(PTTConfig())
    P._note_take([_np.zeros(160, dtype=_np.int16)])
    assert P.mic_dead(PTTConfig())
    P._note_take([_np.ones(160, dtype=_np.int16)])       # one real take: alive again
    assert not P.mic_dead(PTTConfig())
