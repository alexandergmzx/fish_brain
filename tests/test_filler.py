"""Fillers while a turn waits, and the apology at the turn's budget (ADR 0010): a fake
speaker, a fake clock and stages held by events. No audio, no voice program, no network."""
from __future__ import annotations

import io
import threading
import time
import wave
from pathlib import Path

import pytest

from fish_brain import canned, cloud, conversation, debug, ptt, speak as speak_mod
from fish_brain.config import Config
from fish_brain.conversation import FishConversation
from fish_brain.reading import Reading, Utterance
from fish_brain.serial_link import MockSerialLink

from test_conversation import FakeLLM, FakeViz, loud_wav

T0 = 100.0
_real_sleep = time.sleep     # a test may forbid `time.sleep` to the code under test
PHRASE_S = 3.0          # how long the fake speaker takes to say a canned phrase
BURBLE_S = 0.4          # and a burble


class World:
    """The fake clock, and what happens when it reaches a moment (a stage being let go)."""

    def __init__(self):
        self.t = T0
        self.due: list[tuple[float, threading.Event]] = []

    def clock(self) -> float:
        return self.t

    def release_at(self, seconds_in: float) -> threading.Event:
        gate = threading.Event()
        self.due.append((T0 + seconds_in, gate))
        return gate

    def advance(self, seconds: float) -> None:
        self.t += seconds
        fired = [gate for at, gate in self.due if at <= self.t and not gate.is_set()]
        for gate in fired:
            gate.set()
        if fired:
            _real_sleep(0.05)            # the worker finishes its stage in real time

    def wait(self, event: threading.Event, seconds: float) -> None:
        if event.wait(0.05):             # a stage that answers at once costs no clock time
            return
        self.advance(seconds)
        event.wait(0.05)


class FakeSpeaker:
    """Records what the turn loop asks the fish to say, in order."""

    def __init__(self, world: World):
        self.world, self.events, self.last_timing, self.tails = world, [], {}, []
        self._lock = threading.Lock()

    def say_canned(self, name, *, filler=False, render=True):
        self.events.append(("filler" if filler else "canned", name))
        self.world.advance(PHRASE_S)
        return True

    def play_sound(self, wav, *, tail_chain=None, flap=None):
        self.events.append(("burble", Path(wav).name))
        self.tails.append(tail_chain)
        self.world.advance(BURBLE_S)
        return time.monotonic()

    def synthesize(self, text, timing):
        timing["tts"], timing["_t0"] = 0.5, self.world.t
        self.events.append(("synthesize", text))
        return Path("no-such-reply.wav")

    def perform(self, wav, text, timing):
        self.events.append(("perform", text))
        timing.pop("_t0", None)
        timing["play_start"] = 0.6
        self.last_timing = timing
        return True

    def speak(self, text, role="fish"):
        self.events.append(("speak", text))
        return True

    def said(self, kind):
        return [name for k, name in self.events if k == kind]


class SlowSTT:
    """A transcriber held until its gate opens (no gate: answers at once)."""

    def __init__(self, text="hola pez", gate=None, error=None):
        self.text, self.gate, self.error, self.calls = text, gate, error, []

    def transcribe(self, path):
        self.calls.append(str(path))
        if self.gate is not None:
            assert self.gate.wait(5), "the test never let the transcription go"
        if self.error is not None:
            raise self.error
        return self.text


@pytest.fixture
def rig(monkeypatch, tmp_path):
    monkeypatch.setattr(ptt, "record_multi", lambda cfg, sources, inbox=None, **kw: inbox())

    def build(*, echo=True, rendered=True, enabled=True, burble=False):
        world = World()
        cfg = Config()
        cfg.filler.enabled = enabled
        cfg.filler.delay_s = 1.5                 # the arithmetic of these tests
        cfg.burble.enabled = burble
        cfg.burble.cache_dir = tmp_path / "sounds"
        cfg.canned.cache_dir = tmp_path / "canned"
        cfg.canned.cache_dir.mkdir(exist_ok=True)
        if rendered:
            for name in cfg.canned.phrases:
                (cfg.canned.cache_dir / f"{name}-0a0b0c0d.wav").write_bytes(b"RIFF")
        viz = FakeViz(None)
        viz._items.clear()
        convo = FishConversation(cfg, MockSerialLink(cfg.serial, stream=io.StringIO()),
                                 play_audio=False, viz=viz, echo=echo,
                                 clock=world.clock, wait=world.wait)
        convo._rng.seed(0)
        convo.speaker = FakeSpeaker(world)

        def offer(name="turn.wav"):
            viz._items.append(Utterance(path=loud_wav(tmp_path / name), hold_s=1.0, upload_s=0.1))
        return convo, viz, world, offer

    return build


def turn_line(capsys):
    return [l for l in capsys.readouterr().out.splitlines() if l.startswith("[turn] ")][-1]


# --- the chain -----------------------------------------------------------------------------

def test_a_quick_turn_says_no_filler(rig, capsys):
    convo, viz, world, offer = rig()
    offer()
    convo._stt = SlowSTT("hola pez")
    assert convo.turn() is True
    assert convo.speaker.events == [("synthesize", "hola pez"), ("perform", "hola pez")]
    assert "fill=" not in turn_line(capsys)


def test_a_filler_covers_a_slow_transcription_and_the_reply_follows_it(rig, capsys):
    convo, viz, world, offer = rig()
    offer()
    convo._stt = SlowSTT("hola pez", gate=world.release_at(3.0))    # lands during the phrase
    convo.turn()
    events = convo.speaker.events
    assert [k for k, _ in events] == ["filler", "synthesize", "perform"]
    name = events[0][1]
    assert name.startswith("filler_first_")
    assert ("fish", convo.cfg.canned.phrases[name]) in viz.transcripts     # the bubble
    assert world.t == pytest.approx(T0 + 1.5 + PHRASE_S)       # 1.5 s of silence, the phrase
    line = turn_line(capsys)
    assert "fill=3.0s" in line and "stt=" in line


def test_nothing_is_said_before_the_delay(rig):
    convo, viz, world, offer = rig()
    offer()
    convo._stt = SlowSTT(gate=world.release_at(1.0))
    convo.turn()
    assert convo.speaker.said("filler") == []


def test_a_long_wait_gets_a_chain_with_pauses_and_no_repeats(rig):
    convo, viz, world, offer = rig()
    offer()
    convo._stt = SlowSTT(gate=world.release_at(11.0))
    convo.turn()
    said = convo.speaker.said("filler")
    # 1.5 s: first (to 4.5); pause to 6.5: more (to 9.5); the result lands in the next pause
    assert len(said) == 2 and said[0].startswith("filler_first_")
    assert said[1].startswith("filler_more_")
    assert world.t == pytest.approx(T0 + 11.5)
    assert convo.speaker.events[-1] == ("perform", "hola pez")


def test_a_result_in_the_pause_is_spoken_without_another_filler(rig):
    convo, viz, world, offer = rig()
    offer()
    convo._stt = SlowSTT(gate=world.release_at(5.0))            # the pause is 4.5 to 6.5
    convo.turn()
    assert len(convo.speaker.said("filler")) == 1


def test_the_same_fillers_are_not_said_turn_after_turn(rig):
    convo, viz, world, offer = rig()
    firsts = []
    for i in range(4):
        world.t, world.due = T0, []
        offer(f"t{i}.wav")
        convo._stt = SlowSTT(gate=world.release_at(3.0))
        convo.turn()
        firsts.append(convo.speaker.said("filler")[-1])
    assert len(set(firsts)) == 4


def test_a_slow_model_after_a_quick_transcript_gets_its_filler(rig):
    convo, viz, world, offer = rig(echo=False)
    offer()
    convo._stt = SlowSTT("¿qué ves?", gate=world.release_at(1.0))
    gate = world.release_at(4.0)
    llm = FakeLLM()
    quick = llm.reply

    def slow_reply(text):
        assert gate.wait(5)
        return quick(text)
    llm.reply = slow_reply
    convo._llm = llm
    convo.turn()
    kinds = [k for k, _ in convo.speaker.events]
    # the transcript is seen at the first check (1.5 s on this clock), then the model gets
    # the delay of its own: the phrase comes 1.5 s later, while the model is still thinking
    assert kinds == ["filler", "synthesize", "perform"]
    assert world.t == pytest.approx(T0 + 1.5 + 1.5 + PHRASE_S)
    assert convo.speaker.events[-1] == ("perform", "Tu futuro: helado.")


def test_only_rendered_phrases_are_said_and_none_is_no_problem(rig):
    convo, viz, world, offer = rig(rendered=False)
    offer()
    convo._stt = SlowSTT(gate=world.release_at(8.0))
    assert convo.turn() is True
    assert convo.speaker.said("filler") == []
    assert convo.speaker.events[-1] == ("perform", "hola pez")
    one = "filler_first_3"
    (convo.cfg.canned.cache_dir / f"{one}-00000000.wav").write_bytes(b"RIFF")
    assert canned.cached(one, convo.cfg) and not canned.cached("filler_first_1", convo.cfg)
    assert not canned.cached("no-such-phrase", convo.cfg)
    world.t, world.due = T0, []
    offer("again.wav")
    convo._stt = SlowSTT(gate=world.release_at(3.0))
    convo.turn()
    assert convo.speaker.said("filler") == [one]


# --- the budget ----------------------------------------------------------------------------

def test_past_the_budget_the_fish_apologizes_and_listens_again(rig, capsys, monkeypatch):
    monkeypatch.setattr(conversation.time, "sleep", lambda s: pytest.fail("no back-off"))
    hub = debug.install(Config())
    try:
        convo, viz, world, offer = rig()
        offer()
        gate = threading.Event()                               # never opened by the clock
        convo._stt = SlowSTT("tarde", gate=gate)
        assert convo.turn() is True
        fillers, apology = convo.speaker.said("filler"), convo.speaker.said("canned")
        assert len(fillers) == 3 and len(set(fillers)) == 3     # 1.5, 6.5 and 11.5 s
        assert len(apology) == 1 and apology[0].startswith("timeout_stt_")
        assert convo.speaker.said("perform") == [] and convo._errors == 0
        assert ("user", "… (no te escuché bien)") in viz.transcripts
        record = hub.recent("turn")[-1]
        assert record["outcome"] == "timeout: stt" and record["fillers"] == fillers
        assert "[turn] timeout: stt" in capsys.readouterr().out
        # The next turn waits for the abandoned transcription before starting its own.
        late = convo._stt
        world.t, world.due = T0, []
        world.due.append((T0 + 2.0, gate))
        offer("next.wav")
        convo._stt = SlowSTT("ahora sí")
        convo.turn()
        assert len(late.calls) == 1 and len(convo._stt.calls) == 1
        assert convo.speaker.events[-1] == ("perform", "ahora sí")     # "tarde" was dropped
        assert convo._stale == {}
    finally:
        debug.uninstall()


def test_out_of_time_in_the_model_says_the_lost_signal_line(rig):
    convo, viz, world, offer = rig(echo=False)
    offer()
    convo._stt = SlowSTT("hola")
    gate = threading.Event()
    llm = FakeLLM()
    llm.reply = lambda text: gate.wait(5) and "tarde"
    convo._llm = llm
    convo.turn()
    assert convo.speaker.said("canned") == [convo.cfg.canned.no_signal]
    assert ("user", "… (no te escuché bien)") not in viz.transcripts
    gate.set()


def test_a_voice_file_that_comes_late_is_deleted(tmp_path):
    made = tmp_path / "late.wav"
    gate = threading.Event()

    def render():
        gate.wait(5)
        made.write_bytes(b"RIFF")
        return made
    job = conversation._Job("tts", render, discard=lambda p: Path(p).unlink(missing_ok=True))
    job.abandon()
    gate.set()
    assert job.done.wait(5)
    _real_sleep(0.05)
    assert not made.exists()
    done = conversation._Job("tts", lambda: made.write_bytes(b"RIFF") and made,
                             discard=lambda p: Path(p).unlink(missing_ok=True))
    assert done.done.wait(5) and made.exists()                  # kept while the turn wants it
    done.abandon()
    assert not made.exists()


# --- off, errors, records ------------------------------------------------------------------

def test_with_fillers_off_every_stage_is_called_directly(rig):
    convo, viz, world, offer = rig(enabled=False)
    offer()
    convo._stt = SlowSTT("hola pez")
    before = threading.active_count()
    seen = []
    quick = convo._stt.transcribe
    convo._stt.transcribe = lambda p: seen.append(threading.current_thread().name) or quick(p)
    convo.turn()
    assert seen == [threading.main_thread().name] and threading.active_count() == before
    assert convo.speaker.events == [("speak", "hola pez")]


def test_text_mode_never_waits_in_a_worker():
    cfg = Config()
    cfg.filler.enabled = True
    convo = FishConversation(cfg, MockSerialLink(cfg.serial, stream=io.StringIO()),
                             text_input=True, play_audio=False)
    convo._start_wait(0.0)
    assert convo._wait is None
    cfg.canned.enabled = False
    voice = FishConversation(cfg, MockSerialLink(cfg.serial, stream=io.StringIO()),
                             play_audio=False)
    voice._start_wait(0.0)
    assert voice._wait is None


def test_a_stage_that_fails_in_its_worker_fails_the_turn_as_before(rig, monkeypatch, capsys):
    monkeypatch.setattr(conversation.time, "sleep", lambda s: None)
    convo, viz, world, offer = rig()
    offer()
    convo._stt = SlowSTT(gate=world.release_at(3.0), error=cloud.CloudUnavailable("offline"))
    assert convo.turn() is True
    assert convo.speaker.said("canned") == [convo.cfg.canned.no_signal]
    assert "[turn] sin señal: offline" in capsys.readouterr().out
    assert convo._errors == 1 and convo._wait is None


def test_the_workers_model_records_belong_to_the_turn(rig):
    hub = debug.install(Config())
    try:
        convo, viz, world, offer = rig()
        offer()

        class Recording(SlowSTT):
            def transcribe(self, path):
                debug.model("stt", {"backend": "fake"}, seconds=0.1, raw="hola")
                return super().transcribe(path)
        convo._stt = Recording("hola pez", gate=world.release_at(3.0))
        convo.turn()
        record = hub.recent("turn")[-1]
        assert record["model"] == [hub.recent("stt")[-1]["seq"]]
        assert record["times"]["fill"] == pytest.approx(PHRASE_S)
        assert len(record["fillers"]) == 1
    finally:
        debug.uninstall()


def test_adopting_records_needs_the_turns_own_thread():
    hub = debug.install(Config())
    try:
        hub.turn_open()
        mark = hub.seq
        worker = threading.Thread(target=lambda: debug.model("llm", {"model": "x"}, seconds=0.2))
        worker.start()
        worker.join()
        other = threading.Thread(target=lambda: hub.turn_adopt(mark))
        other.start()
        other.join()
        assert "model" not in hub._turn
        hub.turn_adopt(mark)
        hub.turn_adopt(mark)                                    # twice adds nothing
        assert hub._turn["model"] == [hub.recent("llm")[-1]["seq"]]
    finally:
        debug.uninstall()


# --- the reading turn ----------------------------------------------------------------------

def test_a_prophecy_is_covered_too(rig):
    convo, viz, world, offer = rig(echo=False)
    viz._items.append(Reading(name="Maria Jose", first_name="María José", confirmed=True))
    gate = world.release_at(5.0)
    llm = FakeLLM()
    quick = llm.reply
    llm.reply = lambda text: gate.wait(5) and quick(text)
    convo._llm = llm
    convo.turn()
    assert [k for k, _ in convo.speaker.events] == ["filler", "synthesize", "perform"]
    assert viz.readings == ["speaking"] and llm.resets == 1


# --- the speaker's two steps ---------------------------------------------------------------

def test_the_reply_in_two_steps_keeps_its_timings(monkeypatch, tmp_path):
    cfg = Config()
    made = tmp_path / "reply.wav"
    with wave.open(str(made), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x10" * 1600)
    monkeypatch.setattr(speak_mod.tts, "synthesize", lambda text, tts_cfg: made)
    performed = []
    monkeypatch.setattr(speak_mod, "perform_wav",
                        lambda wav, link, c, **kw: performed.append((str(wav), kw["text"]))
                        or time.monotonic())
    viz = FakeViz(None)
    speaker = speak_mod.Speaker(MockSerialLink(cfg.serial, stream=io.StringIO()), cfg, viz=viz)
    timing: dict = {}
    wav = speaker.synthesize("hola", timing)
    assert wav == made and timing["tts"] >= 0 and "_t0" in timing
    assert speaker.perform(wav, "hola", timing) is True
    assert performed == [(str(made), "hola")] and ("fish", "hola") in viz.transcripts
    assert set(speaker.last_timing) == {"tts", "play_start"} and not made.exists()
    made.write_bytes(b"RIFF")
    with speaker._lock:                                         # already speaking: dropped
        assert speaker.perform(made, "otra", {}) is False
    assert not made.exists() and len(performed) == 1


# --- review cases --------------------------------------------------------------------------

def test_a_filler_is_said_from_an_older_rendering_and_never_rendered(monkeypatch, tmp_path):
    cfg = Config()
    cfg.canned.cache_dir = tmp_path
    name = "filler_first_1"
    old = tmp_path / f"{name}-deadbeef.wav"                    # not this text's own hash
    old.write_bytes(b"RIFF")
    monkeypatch.setattr(canned.tts, "synthesize", lambda *a, **k: pytest.fail("rendered"))
    played = []
    monkeypatch.setattr(canned.speak_mod, "perform_wav",
                        lambda wav, link, c, **kw: played.append((Path(wav), kw)))
    assert canned.rendered_path(name, cfg) == old
    speaker = speak_mod.Speaker(MockSerialLink(cfg.serial, stream=io.StringIO()), cfg)
    assert speaker.say_canned(name, filler=True) is True
    assert played[0][0] == old and played[0][1]["filler"] is True
    assert speaker.say_canned("timeout_stt_1", render=False) is True     # none: skipped
    assert len(played) == 1


def test_a_reply_ready_in_time_is_not_dropped_for_a_filler_that_ran_long(rig):
    convo, viz, world, offer = rig()
    offer()
    # Fillers at 1.5 (to 4.5), 6.5 (to 9.5) and 11.5 (to 14.5, past the 12 s budget); the
    # transcript was ready at 11.8. The voice still gets its moment.
    convo._stt = SlowSTT("hola pez", gate=world.release_at(11.8))
    assert convo.turn() is True
    assert len(convo.speaker.said("filler")) == 3
    assert convo.speaker.events[-1] == ("perform", "hola pez")
    assert convo.speaker.said("canned") == []


def test_stage_times_leave_the_fillers_out(rig, capsys):
    hub = debug.install(Config())
    try:
        convo, viz, world, offer = rig()
        offer()
        convo._stt = SlowSTT(gate=world.release_at(3.0))
        convo.turn()
        times = hub.recent("turn")[-1]["times"]
        assert times["fill"] == pytest.approx(PHRASE_S) and times["stt"] < 1.0   # real seconds
    finally:
        debug.uninstall()


def test_nothing_understood_after_a_filler_gets_the_apology(rig):
    convo, viz, world, offer = rig()
    offer()
    convo._stt = SlowSTT("", gate=world.release_at(3.0))
    convo.turn()
    assert len(convo.speaker.said("filler")) == 1
    said = convo.speaker.said("canned")
    assert len(said) == 1 and said[0].startswith("timeout_stt_")
    assert ("user", "… (no te escuché bien)") not in viz.transcripts    # "no te entendí" is there
    offer("quiet.wav")                                    # and a quick empty one stays silent
    world.t, world.due = T0, []
    convo._stt = SlowSTT("")
    convo.turn()
    assert len(convo.speaker.said("canned")) == 1


def test_no_filler_while_something_else_has_the_speaker(rig):
    convo, viz, world, offer = rig()
    offer()
    convo._stt = SlowSTT(gate=world.release_at(5.0))
    with convo.speaker._lock:
        convo.turn()
    assert convo.speaker.said("filler") == []
    assert not any(role == "fish" and text in convo.cfg.canned.phrases.values()
                   for role, text in viz.transcripts)


def test_switching_the_fillers_off_still_waits_for_an_abandoned_stage(rig):
    convo, viz, world, offer = rig()
    offer()
    gate = threading.Event()
    late = SlowSTT("tarde", gate=gate)
    convo._stt = late
    convo.turn()                                           # times out, the job is stale
    assert "stt" in convo._stale
    convo.cfg.filler.enabled = False
    offer("next.wav")
    order = []
    nxt = SlowSTT("ahora sí")
    quick = nxt.transcribe
    nxt.transcribe = lambda p: order.append(convo._stale.copy()) or quick(p)
    convo._stt = nxt
    threading.Timer(0.2, gate.set).start()
    convo.turn()
    assert order == [{}]                                   # started only after the old one ended
    assert convo.speaker.events[-1] == ("speak", "ahora sí")


def test_a_badge_name_survives_a_question_that_ran_out_of_time(rig):
    convo, viz, world, offer = rig(echo=False)
    viz._items.append(Reading(name="Garcia Lopez Maria", first_name="María"))
    llm = FakeLLM()
    convo._llm = llm
    gate = threading.Event()
    real = convo.speaker.synthesize
    convo.speaker.synthesize = lambda text, timing: gate.wait(5) and real(text, timing)
    assert convo.turn() is True
    gate.set()
    assert len(llm.remembered) == 1 and "Garcia Lopez Maria" in llm.remembered[0][0]
    assert convo.speaker.said("canned") == [convo.cfg.canned.no_signal]


# --- the burble ----------------------------------------------------------------------------

def test_a_recording_is_answered_with_a_burble_while_it_is_transcribed(rig, capsys):
    hub = debug.install(Config())
    try:
        convo, viz, world, offer = rig(burble=True)
        offer()
        running = []
        stt = SlowSTT("hola pez", gate=world.release_at(1.0))
        quick = stt.transcribe
        stt.transcribe = lambda p: running.append(len(convo.speaker.events)) or quick(p)
        convo._stt = stt
        convo.turn()
        kinds = [k for k, _ in convo.speaker.events]
        assert kinds == ["burble", "synthesize", "perform"]
        assert running == [0]                       # the transcription started before the sound
        assert convo.speaker.tails[0] in convo.cfg.gesture.tail_chains
        assert not any(role == "fish" and "burble" in text for role, text in viz.transcripts)
        record = hub.recent("turn")[-1]
        assert 0.0 <= record["times"]["burble"] < 1.0 and "fillers" not in record
        assert "burble=" in turn_line(capsys)
    finally:
        debug.uninstall()


def test_the_burble_then_a_filler_at_its_own_time(rig):
    convo, viz, world, offer = rig(burble=True)
    offer()
    convo._stt = SlowSTT(gate=world.release_at(3.0))
    convo.turn()
    assert [k for k, _ in convo.speaker.events] == ["burble", "filler", "synthesize", "perform"]
    # the filler's delay counts from the end of the recording, not from the burble
    assert world.t == pytest.approx(T0 + 1.5 + PHRASE_S)


def test_no_burble_for_a_tap_a_silent_recording_or_a_reading(rig, tmp_path):
    convo, viz, world, offer = rig(burble=True)
    viz._items.append(Utterance(path=loud_wav(tmp_path / "tap.wav", seconds=0.1),
                                hold_s=0.1, upload_s=0.0))
    convo._stt = SlowSTT("no")
    convo.turn()
    quiet = tmp_path / "quiet.wav"
    with wave.open(str(quiet), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)
    viz._items.append(Utterance(path=quiet, hold_s=1.0, upload_s=0.0))
    convo.turn()
    assert convo.speaker.events == [] and convo._stt.calls == []
    viz._items.append(Reading(name="Maria Jose", first_name="María José", confirmed=True))
    convo.turn()                                            # echo mode: the fortune line
    assert convo.speaker.said("burble") == []
    assert convo.speaker.said("perform")


def test_never_the_same_burble_twice_running_and_none_while_the_speaker_is_held(rig):
    convo, viz, world, offer = rig(burble=True)
    for i in range(6):
        offer(f"b{i}.wav")
        convo._stt = SlowSTT("hola")
        convo.turn()
    said = convo.speaker.said("burble")
    assert len(said) == 6 and all(a != b for a, b in zip(said, said[1:]))
    assert len(set(said)) > 2
    offer("held.wav")
    with convo.speaker._lock:
        convo.turn()
    assert len(convo.speaker.said("burble")) == 6


def test_the_burble_alone_sets_no_budget_and_says_no_filler(rig):
    convo, viz, world, offer = rig(enabled=False, burble=True)
    offer()
    gate = threading.Event()
    convo._stt = SlowSTT("al fin", gate=gate)
    threading.Timer(0.3, gate.set).start()                  # far past any budget on the fake clock
    world.t += 100.0
    assert convo.turn() is True
    assert [k for k, _ in convo.speaker.events] == ["burble", "synthesize", "perform"]
    assert convo.speaker.said("canned") == []


def test_no_tail_when_the_gestures_are_off(rig):
    convo, viz, world, offer = rig(burble=True)
    convo.cfg.gesture.enabled = False
    offer()
    convo._stt = SlowSTT("hola")
    convo.turn()
    assert convo.speaker.tails == [None]


def test_a_burble_moves_the_tail_and_never_the_mouth(tmp_path):
    from fish_brain import burble
    cfg = Config()
    out = io.StringIO()
    link = MockSerialLink(cfg.serial, stream=out)
    announced = []

    class Page:
        def announce_speech(self, wav, duration_ms, gestures, mouth_track=None, filler=False):
            announced.append((duration_ms, gestures, mouth_track, filler))

    from fish_brain.conductor import SilentPlayer
    speaker = speak_mod.Speaker(link, cfg, player=SilentPlayer(), viz=Page())
    wav = burble.ensure(tmp_path)[1]                        # the shortest, 0.33 s
    chain = cfg.gesture.tail_chains[0]
    started = speaker.play_sound(wav, tail_chain=chain)
    assert isinstance(started, float)
    lines = [l.split("TX ", 1)[-1].strip() for l in out.getvalue().splitlines() if "TX" in l]
    assert [l for l in lines if l.startswith("TAIL")] == [f"TAIL {chain}"]
    mouth = [l for l in lines if l.startswith("MOUTH")]
    close = f"MOUTH {cfg.mouth.close_pwm} {cfg.mouth.close_curve[-1][1]}"
    assert mouth == [close]                                 # only the pulse that ends every performance
    assert not any(l.startswith("NECK") for l in lines)
    duration_ms, gestures, mouth_track, filler = announced[0]
    assert 300 <= duration_ms <= 600 and gestures == [(0, "TAIL", chain)]
    assert mouth_track == [] and filler is True
    with speaker._lock:
        assert speaker.play_sound(wav) is None              # already speaking: dropped


def test_the_hats_burble_is_one_short_flap_of_the_mouth(tmp_path):
    from fish_brain import burble
    from fish_brain.config import MouthConfig
    cfg = Config()
    cfg.mouth = MouthConfig(mode="gate", open_pwm=200, gate_stop="0 1")
    out = io.StringIO()
    link = MockSerialLink(cfg.serial, stream=out)
    from fish_brain.conductor import SilentPlayer
    speaker = speak_mod.Speaker(link, cfg, player=SilentPlayer())
    wav = burble.ensure(tmp_path)[1]
    assert isinstance(speaker.play_sound(wav, flap=(200, 300)), float)
    lines = [l.split("TX ", 1)[-1].strip() for l in out.getvalue().splitlines() if "TX" in l]
    assert lines == ["MOUTH 200 300", "MOUTH 0 1"]          # the flap, then the hat's stop


def test_the_burbles_are_made_once_and_differ(tmp_path):
    from fish_brain import burble
    paths = burble.ensure(tmp_path)
    assert len(paths) == 4 and all(p.exists() for p in paths)
    sizes = {p.stat().st_size for p in paths}
    stamp = paths[0].stat().st_mtime_ns
    assert len(sizes) == 4 and burble.ensure(tmp_path) == paths
    assert paths[0].stat().st_mtime_ns == stamp             # not written again
    for p in paths:
        with wave.open(str(p)) as w:
            assert 0.3 <= w.getnframes() / w.getframerate() <= 0.6 and w.getnchannels() == 1
    assert burble.self_test() == 0


def test_the_hat_hums_instead_of_bubbling(tmp_path):
    from fish_brain import burble
    import pytest as _pytest
    hums = burble.ensure(tmp_path, "hum")
    assert [p.name for p in hums] == [f"hum_{i}-v{burble.VERSION}.wav" for i in range(1, 5)]
    assert not list(tmp_path.glob("burble_*"))
    assert len({p.stat().st_size for p in hums}) == 4
    for p in hums:
        with wave.open(str(p)) as w:
            assert 0.3 <= w.getnframes() / w.getframerate() <= 0.6 and w.getnchannels() == 1
    assert all(burble._rises(burble.hum(*r)) for r in burble.HUM_RECIPES)
    with _pytest.raises(ValueError):
        burble.ensure(tmp_path, "gong")


def test_the_hats_burble_sound_comes_from_the_persona(monkeypatch):
    from fish_brain.config import BurbleConfig
    monkeypatch.setenv("FISH_PERSONA", "hat")
    assert BurbleConfig().sound == "hum"
    monkeypatch.setenv("FISH_PERSONA", "fish")
    assert BurbleConfig().sound == "bubbles"


def test_a_recording_made_here_gets_its_burble_too(rig, monkeypatch, tmp_path):
    convo, viz, world, offer = rig(burble=True)
    wav = loud_wav(tmp_path / "host.wav")
    monkeypatch.setattr(ptt, "record_multi", lambda cfg, sources, inbox=None, **kw: wav)
    monkeypatch.setattr(ptt, "last_recording_was_cut", lambda: False)
    monkeypatch.setattr(ptt, "last_info", lambda: {"trigger": "remote"})
    convo._stt = SlowSTT("hola pez")
    hub = debug.install(Config())
    try:
        convo.turn()
        assert [k for k, _ in convo.speaker.events] == ["burble", "synthesize", "perform"]
        assert "burble" in hub.recent("turn")[-1]["times"]
    finally:
        debug.uninstall()


def test_a_burble_that_was_not_played_leaves_no_time_and_the_reply_still_comes(rig):
    convo, viz, world, offer = rig(burble=True)
    convo.speaker.play_sound = lambda wav, tail_chain=None: None        # dropped by the speaker
    offer()
    convo._stt = SlowSTT("hola pez")
    hub = debug.install(Config())
    try:
        convo.turn()
        assert "burble" not in hub.recent("turn")[-1]["times"]
        assert convo.speaker.events[-1] == ("perform", "hola pez")
    finally:
        debug.uninstall()


def test_the_burble_comes_before_waiting_for_an_abandoned_transcription(rig):
    convo, viz, world, offer = rig(burble=True)
    offer()
    gate = threading.Event()
    convo._stt = SlowSTT("tarde", gate=gate)
    convo.turn()                                            # times out: the job is stale
    assert "stt" in convo._stale
    before = len(convo.speaker.events)
    world.t, world.due = T0, [(T0 + 4.0, gate)]
    offer("next.wav")
    convo._stt = SlowSTT("ahora sí")
    convo.turn()
    kinds = [k for k, _ in convo.speaker.events[before:]]
    assert kinds[0] == "burble" and kinds.count("burble") == 1
    assert "filler" in kinds and kinds[-1] == "perform"


def test_a_transcript_in_under_the_delay_gets_no_filler_for_the_voice_render(rig):
    convo, viz, world, offer = rig()
    offer()
    convo._stt = SlowSTT("hola pez", gate=world.release_at(1.3))    # the delay is 1.5 s here
    render = world.release_at(1.9)                                  # the voice crosses 1.5 s
    real = convo.speaker.synthesize
    convo.speaker.synthesize = lambda text, timing: render.wait(5) and real(text, timing)
    convo.turn()
    assert convo.speaker.said("filler") == []
    assert convo.speaker.events[-1] == ("perform", "hola pez")
