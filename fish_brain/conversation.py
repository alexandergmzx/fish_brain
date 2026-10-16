"""The conversation turn loop: input -> STT -> LLM -> fish speaks -> repeat.

Two input modes:
  - voice (default): push-to-talk mic capture -> speech-to-text
  - text  (--text):  type the user turn (skips mic + STT)

Push-to-talk can come from the browser button (--viz), a remote's button (FISH_PTT_DEVICE),
or the keyboard; the first two can be active together. With FISH_MIC_CAPTURE=browser the
page records with the phone's microphone and uploads the WAV: it arrives through the viz
inbox as an `Utterance` and takes the same path as a recording from here. In that mode a
remote's press is relayed to the page (a sourced `ptt` event) while a page has a microphone
ready; with none ready the remote records here as before.

Nothing that goes wrong inside a turn ends the loop: a failed cloud call, a missing
microphone or a bad audio file makes the fish say a short canned line and listen again.
Only quitting (Ctrl-C, a stop signal, "salir", end of input) ends it.

A recording the fish can use is answered at once with a burble (`BurbleConfig`): a short
bubble sound and a flap of the tail. While a voice turn waits for its transcription, its
reply or its voice, the fish says short canned phrases (`FillerConfig`, ADR 0010): the stage runs in a worker and this thread, which
still owns everything that is said and recorded about the turn, fills the wait. Past the
turn's budget it apologizes, drops the turn and listens again; the worker ends on its own
and its result is thrown away. With `FISH_FILLER=false` and `FISH_BURBLE=false`, and always
in text mode, every stage is called directly, as before.

Components are built lazily so `--text --dry-run` works without a mic, and so the heavy
STT model only loads when voice mode actually needs it.
"""
from __future__ import annotations

import os
import random
import threading
import time
import traceback
from collections import deque
from pathlib import Path

from . import cloud, debug, ptt, speak as speak_mod
from .conductor import Player, make_player
from .config import Config
from .serial_link import BaseLink

_QUIT_WORDS = {"salir", "quit", "exit"}


class TurnTimeout(Exception):
    """The turn passed its budget while `stage` (stt, llm or tts) was still running."""

    def __init__(self, stage: str):
        super().__init__(f"the turn's time ran out during {stage}")
        self.stage = stage


class _Job:
    """One stage of a turn running in a worker thread, so the turn loop can talk meanwhile.
    A job the turn gave up on finishes by itself; `discard` then gets its result (a file to
    delete)."""

    def __init__(self, stage: str, fn, discard=None):
        self.stage, self.done = stage, threading.Event()
        self.result, self.exc, self.seconds = None, None, 0.0
        self._discard, self._abandoned, self._lock = discard, False, threading.Lock()
        threading.Thread(target=self._run, args=(fn,), name=f"turn-{stage}", daemon=True).start()

    def _run(self, fn) -> None:
        t0 = time.monotonic()
        try:
            self.result = fn()
        except BaseException as e:               # handed to the turn loop, raised there
            self.exc = e
        self.seconds = time.monotonic() - t0     # the stage alone, without the fillers
        with self._lock:
            self.done.set()
            drop = self._abandoned
        if drop:
            self._drop()

    def abandon(self) -> None:
        with self._lock:
            self._abandoned = True
            finished = self.done.is_set()
        if finished:
            self._drop()

    def _drop(self) -> None:
        if self._discard is not None and self.exc is None:
            try:
                self._discard(self.result)
            except Exception:
                pass


class FishConversation:
    def __init__(self, cfg: Config, link: BaseLink, *,
                 text_input: bool = False, play_audio: bool = True, viz=None,
                 echo: bool = False, clock=time.monotonic, wait=None, rng=None):
        self.cfg = cfg
        self.link = link
        self.text_input = text_input
        self.echo = echo
        self.player: Player = make_player(play_audio, cfg.ptt.speaker)
        self.viz = viz
        # Serialized speak path, shared with the on-screen text box (registered into viz by app.py).
        self.speaker = speak_mod.Speaker(link, cfg, player=self.player, viz=viz)
        self._llm = None
        self._stt = None
        self._errors = 0                  # consecutive failed turns (for the back-off)
        self._last_apology = 0.0          # when a canned error line was last spoken
        # Fillers (see the module docstring). `_wait` is the open turn's: its deadline, when
        # the next phrase is due, the phrases said, the seconds spent saying them.
        self._clock = clock
        self._wait_on = wait or (lambda event, seconds: event.wait(seconds))
        self._rng = rng or random.Random()
        self._wait: dict | None = None
        self._stale: dict[str, _Job] = {}     # a stage a turn gave up on, still running
        self._stage_s: float | None = None    # the last awaited stage's own seconds
        self._last_burble = None              # the burble said last, not to repeat it
        self._recent: deque[str] = deque(maxlen=3)   # fillers not to say again so soon
        # The hat's visit (visit.py): built from the persona whatever echo is, so a /debug
        # switch to the model turns it on; `_visit_on()` decides it turn by turn.
        self.visit = None
        if cfg.visit.rules:
            from .visit import Visit
            self.visit = Visit(cfg.visit.stages, cfg.visit.idle_s, clock=clock)
        self._heard_at: float | None = None   # when the visitor started talking, this turn
        # Button-like push-to-talk sources (browser button, remote). Empty -> keyboard.
        self.button = None
        self.sources: list[ptt.ButtonSource] = []
        if not text_input:
            if viz is not None:
                self.sources.append(viz.ptt_source())
            if cfg.ptt.evdev_device:
                from .evdev_button import EvdevButton   # lazy: needs python-evdev
                self.button = EvdevButton(cfg.ptt)
                self.sources.append(ptt.ButtonSource(
                    self.button.is_held, reset=self.button.reset, arm=self.button.arm,
                    name="remote"))

    def ptt_summary(self) -> str:
        """How a turn is triggered, for the startup line."""
        if self.text_input:
            return "text"
        if not self.sources:
            return "keyboard"
        parts = [s.name for s in self.sources]
        if self.button is not None:
            parts[-1] = self.button.describe()
        if self.viz is not None and self.cfg.ptt.capture == "browser":
            parts[0] = "web+browser-mic"             # the page records, this side transcribes
            if self.button is not None:
                parts[-1] += "→page"                  # its press is relayed to the page
        return "+".join(parts)

    @property
    def llm(self):
        if self._llm is None:
            from .llm import Conversation
            self._llm = Conversation(self.cfg.llm)
        return self._llm

    @property
    def stt(self):
        if self._stt is None:
            from .stt import make_transcriber
            self._stt = make_transcriber(self.cfg.stt)
        return self._stt

    def warm_stt(self) -> None:
        """Load the speech model in the background (nothing to do for a cloud backend)."""
        transcriber = self.stt

        def load():
            try:
                transcriber.ensure_loaded()
            except Exception as e:               # the turn that needs it reports it again
                print(f"[stt] could not load the model: {type(e).__name__}: {e}", flush=True)
        threading.Thread(target=load, name="stt-warm", daemon=True).start()

    # --- waiting for a stage: fillers and the turn's budget ----------------------------
    def _start_wait(self, t0: float, *, burble: bool = False) -> None:
        """A voice turn's wait starts (the recording just ended): from here the fillers and
        the budget count, and a turn that came from a recording (`burble`) is answered with
        the burble first. Nothing in text mode, or with the fillers and the burble off.
        With only the burble on there is no budget: it acknowledges, nothing more."""
        f = self.cfg.filler
        fillers = f.enabled and self.cfg.canned.enabled and not self.text_input
        burble = burble and self.cfg.burble.enabled and not self.text_input
        if not (fillers or burble):
            self._wait = None
            return
        never = float("inf")
        self._wait = {"deadline": t0 + f.turn_timeout_s if fillers else never,
                      "next": t0 + f.delay_s if fillers else never,
                      "used": [], "fill": 0.0, "burble": burble, "ended": time.monotonic()}

    def _settle(self, stage: str) -> None:
        """Wait for a job of `stage` that an earlier turn gave up on, so the same model is
        never asked twice at once. The fillers and the budget apply to this wait too; with
        the fillers off (switched off since) it is a plain wait."""
        job = self._stale.pop(stage, None)
        if job is None:
            return
        if self._wait is None:
            job.done.wait()
        else:
            self._wait_for(job, self._wait["deadline"])

    def _await(self, stage: str, fn, *, discard=None):
        """`fn()`: a stage of the turn. Directly when the turn has no wait state; else in a
        worker while this thread says fillers, up to the turn's deadline (`TurnTimeout`).
        What `fn` raises is raised here."""
        self._stage_s = None
        if self._wait is not None and self._wait["burble"] and stage in self._stale:
            self._say_burble()                   # the release is answered before the old job is waited for
        self._settle(stage)
        if self._wait is None:
            return fn()
        mark = debug.seq()
        w, now = self._wait, self._clock()
        if not w["used"] and w["next"] != float("inf"):
            # Until a filler has been said, each stage gets the whole delay of its own: a
            # transcript that came in under the delay is not followed by a phrase just
            # because the voice render crossed it.
            w["next"] = max(w["next"], now + self.cfg.filler.delay_s)
        job = _Job(stage, fn, discard)
        if self._wait["burble"]:
            self._say_burble()                   # the stage is already running beside it
        # A stage always gets a moment of its own, even when a filler ran past the budget.
        deadline = max(self._wait["deadline"], self._clock() + self.cfg.filler.stage_grace_s)
        try:
            self._wait_for(job, deadline)
        finally:
            self._stage_s = job.seconds if job.done.is_set() else None
            debug.turn_adopt(mark)               # the worker's model records, to this turn
        if job.exc is not None:
            raise job.exc
        return job.result

    def _stage_time(self, wall: float) -> float:
        """Seconds for the `[turn]` line: the stage's own when it ran in a worker (the
        fillers said meanwhile are `fill`), else the time around the call."""
        return self._stage_s if self._stage_s is not None else wall

    def _wait_for(self, job: _Job, deadline: float) -> None:
        w = self._wait
        while not job.done.is_set():
            now = self._clock()
            if now >= deadline:
                job.abandon()
                self._stale[job.stage] = job
                raise TurnTimeout(job.stage)
            until = min(deadline, w["next"])
            if until == float("inf"):
                job.done.wait()                  # the burble alone: no filler, no budget
            elif now < until:
                self._wait_on(job.done, until - now)
            else:
                self._say_filler()

    def _say_burble(self) -> None:
        """The answer to a released button: a short bubble sound and one flap of the tail,
        once per turn, never the same sound twice running. Skipped when something else has
        the speaker."""
        from . import burble
        w = self._wait
        w["burble"] = False
        lock = getattr(self.speaker, "_lock", None)
        if lock is not None and lock.locked():
            return
        try:
            sounds = burble.ensure(self.cfg.burble.cache_dir, self.cfg.burble.sound)
            wav = self._rng.choice([p for p in sounds if p != self._last_burble] or sounds)
            chain = (self._rng.choice(self.cfg.gesture.tail_chains)
                     if self.cfg.burble.tail and self.cfg.gesture.enabled else None)
            started = self.speaker.play_sound(wav, tail_chain=chain)
            if started is not None:
                self._last_burble = wav
                w["burble_s"] = max(0.0, started - w["ended"])
        except Exception as e:                   # a burble must never be the problem
            print(f"[turn] could not burble: {e}", flush=True)

    def _say_filler(self) -> None:
        """One phrase to cover the wait: a "first" one, then "more" ones, never the same
        twice in a turn nor one of the last few said. Only phrases already rendered: a
        missing one is skipped, not rendered here."""
        from . import canned
        w, f = self._wait, self.cfg.filler
        prefix = f.more_prefix if w["used"] else f.first_prefix
        pool = sorted(n for n in self.cfg.canned.phrases
                      if n.startswith(prefix) and n not in w["used"]
                      and canned.cached(n, self.cfg))
        fresh = [n for n in pool if n not in self._recent]
        t0 = self._clock()
        lock = getattr(self.speaker, "_lock", None)
        if lock is not None and lock.locked():
            pool = []                            # the page's text box or a badge is talking
        if pool:
            name = self._rng.choice(fresh or pool)
            text = self.cfg.canned.phrases[name]
            print(f"fish> (espera) {text}", flush=True)
            if self.viz is not None:
                self.viz.push_transcript(text, "fish")
            try:
                if self.speaker.say_canned(name, filler=True):
                    w["used"].append(name)
                    self._recent.append(name)
            except Exception as e:               # a filler must never be the problem
                print(f"[turn] could not say {name!r}: {e}", flush=True)
        now = self._clock()
        w["fill"] += now - t0
        w["next"] = now + f.gap_s

    def _speak_reply(self, text: str) -> bool:
        """Say the reply. With a wait state the voice is rendered in a worker (fillers may
        cover it) and then performed; a filler that is still playing is finished first, so
        the reply follows it and is never dropped for it."""
        if self._wait is None:
            return self.speaker.speak(text)
        text = (text or "").strip()
        if not text:
            return False
        timing: dict = {}
        wav = self._await("tts", lambda: self.speaker.synthesize(text, timing),
                          discard=lambda path: Path(path).unlink(missing_ok=True))
        return self.speaker.perform(wav, text, timing)

    def _note_fill(self, times: dict) -> None:
        """The burble and the fillers of this turn, into its timings and its record:
        `burble` is the time from the end of the recording to the sound."""
        w = self._wait
        if w and "burble_s" in w:
            times["burble"] = w["burble_s"]
        if w and w["used"]:
            times["fill"] = w["fill"]
            debug.turn_set(fillers=list(w["used"]))

    def _say_timeout(self, stage: str, *, bubble: bool = True) -> None:
        """The line for a turn that ran out of time: "I did not hear you well" while it was
        being transcribed, the lost-signal line after that. From a WAV that exists: nothing
        is rendered here."""
        from . import canned
        name = self.cfg.canned.no_signal
        if stage == "stt":
            pool = sorted(n for n in self.cfg.canned.phrases
                          if n.startswith(self.cfg.filler.timeout_stt_prefix)
                          and canned.cached(n, self.cfg))
            if pool:
                name = self._rng.choice(pool)
            if bubble and self.viz is not None:
                self.viz.push_transcript("… (no te escuché bien)", "user")
        self._apologize(name, render=False)

    # --- one turn, in stages ---------------------------------------------------------
    def _record(self) -> Path | object:
        """Wait for push-to-talk and record, or for an item the page offers through the viz
        inbox. Raises ptt.MicError / ptt.PTTUnavailable."""
        # Stream the live mic level to the on-screen fish (if any) while recording.
        on_level = (lambda lvl: self.viz.push_level(lvl)) if self.viz is not None else None
        if self.sources:
            if self.viz is not None:
                where = ("teléfono: la página graba" if self.cfg.ptt.capture == "browser"
                         else "navegador o control")
                print(f"[ptt] mantén pulsado 'Hablar' ({where}) para grabar…", flush=True)
                self.viz.set_listening(True)
            try:
                return ptt.record_multi(
                    self.cfg.ptt, self.sources, on_level=on_level,
                    inbox=self.viz.take_inbox if self.viz is not None else None,
                    relay=self._relay(), relay_ready=self._relay_ready())
            finally:
                if self.viz is not None:
                    self.viz.set_listening(False)
        return ptt.record_hold(self.cfg.ptt, on_level=on_level)

    def _relay(self):
        """Whether the remote's press goes to the page this wait: in browser-mic mode, when
        a page has its microphone ready. Decided before every wait, so a phone that comes or
        goes needs no restart. Returns the relay callable or None."""
        remotes = [s for s in self.sources if s.name == "remote"]
        use = bool(remotes) and self.cfg.ptt.capture == "browser" and (
            self.viz is not None and self.viz.mic_pages() > 0)
        for s in remotes:
            s.relay = use
        return self.viz.relay_ptt if use else None

    def _relay_ready(self):
        """Asked by `record_multi` at each press of a relayed source: is a page still there?
        A phone pocketed mid-wait (ready false, or the keep-alive expired) hands the press
        back to the board's microphone instead of leaving the remote dead."""
        if self.viz is None:
            return None
        return lambda: self.viz.mic_pages() > 0

    def _handle_item(self, item) -> bool:
        """An input item that is not a recording (offered by the page). The single dispatch
        point for such items; returns whether the loop goes on."""
        from .reading import Reading, Utterance
        from .visit import NewVisit
        if hasattr(item, "run_in_loop"):
            # A test from the debug page (a motor pulse, the microphone check): it runs here,
            # on the turn loop's own thread, and answers for its own errors.
            item.run_in_loop(self)
            return True
        if isinstance(item, Reading):
            return self._reading_turn(item)
        if isinstance(item, Utterance):
            return self._utterance_turn(item)
        if isinstance(item, NewVisit):
            return self._new_visit_turn(item)
        print(f"[turn] unknown input item {type(item).__name__}", flush=True)
        return True

    def _utterance_turn(self, u) -> bool:
        """A recording the page made with the phone's microphone and uploaded. From here on
        it is a normal voice turn: the hold plus the upload stand for the recording time."""
        times: dict[str, float] = {"rec": u.hold_s + u.upload_s}
        self._heard_at = self._clock() - times["rec"]
        debug.turn_set(trigger="phone microphone")
        t0 = time.monotonic()
        self._start_wait(self._clock(), burble=True)
        try:
            user = self._transcribe(u.path, origin="upload")   # unlinks the file
        finally:
            times["stt"] = self._stage_time(time.monotonic() - t0)
            debug.turn_set(times=times)            # also when the stage failed
        return self._finish_turn(user, times)

    def _reading_turn(self, r) -> bool:
        """A visitor's name arrived (ADR 0007). A new visitor: the history is reset and the
        per-visitor rules attached. Unconfirmed (a badge): the fish asks "¿Tú eres X?" and
        the answer is the next normal voice turn, with the question seeded in the history.
        Confirmed (typed): the fish tells the future now. The quit words never apply here."""
        if self._visit_on():
            return self._visit_reading_turn(r)
        from . import reading
        times: dict[str, float] = {}
        look_note = f" Lleva: {r.look}." if r.look else ""
        self._start_wait(self._clock())
        if not self.echo:
            try:
                self._settle("llm")                # a late answer must not land after the reset
            except TurnTimeout:
                pass                               # still running: the name is not lost for it
        if r.confirmed:
            # A typed name: /debug forgets the earlier visitor's prompts here. With a badge
            # that happened before the photo was read (viz.read_badge), so its own record stays.
            debug.new_visitor()
        if not self.echo:
            self.llm.reset()
            self.llm.extra_rules = self.cfg.reading.rules
        if not r.confirmed:
            question = reading.echo_question(r.first_name)
            if self.viz is not None:
                self.viz.push_reading("ask")
            print("fish> (lectura: pregunta por el nombre)", flush=True)
            if not self.echo:
                # Before the question is said: if its voice runs out of time the answer
                # "sí" must still find the name in the history.
                self.llm.remember(
                    f"[Lectura] El visitante muestra su gafete: se llama {r.name}.{look_note}"
                    " Pregúntale si es él o ella; cuando confirme, dile su futuro.", question)
            said = self._speak_reply(question)
            times.update(self.speaker.last_timing)
            self._note_fill(times)
            debug.turn_set(trigger="reading", times=times, link=self.link.health(),
                           outcome="read: ask" if said else "dropped: speaking")
            print("[turn] read=ask " + " ".join(f"{k}={v:.1f}s" for k, v in times.items())
                  + f" link={self.link.health()}", flush=True)
            return True
        if self.echo:
            reply = reading.echo_fortune(r.first_name)
        else:
            t0 = time.monotonic()
            ask = self.llm.reply                   # the client is built here, on this thread
            said_to_llm = f"[Lectura] Se llama {r.name}, confirmado.{look_note} Dile su futuro."
            reply = self._await("llm", lambda: ask(said_to_llm))
            times["llm"] = self._stage_time(time.monotonic() - t0)
            if self.llm.last_error and self.cfg.tts.backend != "loq":
                # The model is unreachable and so, most likely, is cloud TTS: the cached line.
                print(f"[turn] lectura sin señal: {self.llm.last_error}", flush=True)
                debug.turn_set(trigger="reading", times=times, outcome="read: no signal")
                self._apologize(self.cfg.canned.reading_fail)
                return True
        print("fish> (lectura)", flush=True)
        if not reply:
            return True
        if self.viz is not None:
            self.viz.push_reading("speaking")
        said = self._speak_reply(reply)
        times.update(self.speaker.last_timing)
        self._note_fill(times)
        debug.turn_set(trigger="reading", times=times, link=self.link.health(),
                       outcome="read: tell" if said else "dropped: speaking")
        print("[turn] read=tell " + " ".join(f"{k}={v:.1f}s" for k, v in times.items())
              + f" link={self.link.health()}", flush=True)
        return True

    def _transcribe(self, wav: Path, origin: str = "host") -> str:
        """Recording -> text ("" when there is nothing usable in it)."""
        self._stage_s = None
        try:
            debug.recording(wav, origin)           # the newest one, in memory, for /debug
            if ptt.wav_duration_s(wav) < self.cfg.stt.min_clip_s:
                debug.turn_set(outcome="too short")
                return ""                          # a tap, not a sentence
            # Skip silent captures: Whisper hallucinates phrases on silence (wrong/muted mic).
            rms = ptt.wav_rms(wav)
            if rms < self.cfg.ptt.silence_rms:
                print(f"you> … (grabación casi en silencio, rms={rms:.4f}; ¿micrófono correcto?)",
                      flush=True)
                if self.viz is not None:
                    self.viz.push_transcript("… (silencio, ¿micrófono correcto?)", "user")
                debug.turn_set(outcome="silence")
                return ""
            transcribe = self.stt.transcribe       # the transcriber is built on this thread
            text = self._await("stt", lambda: transcribe(wav)).strip()
        finally:
            Path(wav).unlink(missing_ok=True)
        debug.turn_set(user=text, **({} if text else {"outcome": "not understood"}))
        print(f"you> {text}" if text else "you> … (no te entendí, intenta de nuevo)", flush=True)
        if self.viz is not None:
            self.viz.push_transcript(text or "… (no te entendí)", "user")
        return text

    def _apologize(self, phrase: str, *, min_gap_s: float = 0.0, render: bool = True) -> None:
        """Say a canned error line (best effort), at most once per `min_gap_s`.
        `render=False`: only from a WAV that exists (after a turn's wait)."""
        now = time.monotonic()
        if not phrase or now - self._last_apology < min_gap_s:
            return
        self._last_apology = now
        try:
            # Under the speaker lock: the /badge handler thread says its own canned lines
            # through the same lock, so two phrases never drive the link at once.
            said = (self.speaker.say_canned(phrase) if render
                    else self.speaker.say_canned(phrase, render=False))
            if not said:
                print(f"[turn] skipped {phrase!r}: already speaking", flush=True)
        except Exception as e:                      # the apology must never be the problem
            print(f"[turn] could not say {phrase!r}: {e}", flush=True)

    def _turn(self) -> bool:
        times: dict[str, float] = {}
        if self.text_input:
            try:
                user = input("you> ").strip()
            except EOFError:
                return False                       # Ctrl-D
            self._heard_at = self._clock()
            debug.turn_set(trigger="text", user=user)
        else:
            t0 = time.monotonic()
            wav = self._record()
            if not isinstance(wav, Path):
                return self._handle_item(wav)
            # The hold itself, not the wait for a press (the wait can be minutes long).
            times["rec"] = ptt.wav_duration_s(wav)
            self._heard_at = self._clock() - times["rec"]
            cut = ptt.last_recording_was_cut()
            info = ptt.last_info()
            debug.turn_set(trigger=info.get("trigger", "button"), ended=info.get("ended", ""),
                           device=info.get("device", ""))
            t0 = time.monotonic()
            self._start_wait(self._clock(), burble=True)
            try:
                user = self._transcribe(wav)
            finally:
                times["stt"] = self._stage_time(time.monotonic() - t0)
                debug.turn_set(times=times)        # also when the stage failed
            if cut and user:
                # The visitor was still talking at the limit: the fish must know it heard a
                # beginning, not a whole sentence (the echo repeats the words as they are).
                times["cut"] = self.cfg.ptt.max_record_s
                if not self.echo:
                    user += (f" [Nota: la grabación se cortó a los {self.cfg.ptt.max_record_s:.0f} "
                             "segundos y el visitante seguía hablando; dilo con gracia y pídele "
                             "la versión corta.]")
        return self._finish_turn(user, times)

    def _finish_turn(self, user: str, times: dict[str, float]) -> bool:
        """The rest of a turn once the user's text is known (typed, transcribed here, or
        transcribed from an uploaded recording): quit words, the LLM or the echo, speaking."""
        if user.lower().strip(" .!¡") in _QUIT_WORDS and (
                self.text_input or self.cfg.ptt.voice_quit):
            return False
        if not user:
            self._note_fill(times)
            if times:
                debug.turn_set(times=times)
            if self._wait and self._wait["used"]:
                # A filler promised an answer and there is nothing to answer: say so.
                self._say_timeout("stt", bubble=False)
            return True                            # nothing captured -> keep listening

        # Echo mode just speaks the transcription back -> never touches the LLM (no API key).
        visit_turn = None
        if self.echo:
            reply = user
        elif self._visit_on():
            visit_turn = self._visit_ask(user, times)
            reply = visit_turn["spoken"]
        else:
            t0 = time.monotonic()
            ask = self.llm.reply                   # the client is built here, on this thread
            reply = self._await("llm", lambda: ask(user))
            times["llm"] = self._stage_time(time.monotonic() - t0)
            debug.turn_set(times=times)
            if self.llm.last_error and self.cfg.tts.backend != "loq":
                # The LLM is unreachable and so, most likely, is cloud TTS: use the cached line.
                raise cloud.CloudUnavailable(self.llm.last_error)
        print(f"fish> {reply}", flush=True)
        debug.turn_set(reply=reply, times=times)
        if not reply:
            debug.turn_set(outcome="empty reply")
            return True
        if self.viz is not None and self.viz.wait_enabled():
            # "Wait to speak": show the reply and drop it into the editable box; the user tweaks
            # it and presses Speak (-> /speak) to make the fish say it.
            self.viz.push_transcript(reply, "fish")
            self.viz.push_draft(reply)
            debug.turn_set(outcome="draft (wait-to-speak)")
            delivered = True                       # the operator says it
        else:
            # Speaker pushes the "fish" transcript + speaks; False = it was already speaking.
            delivered = self._speak_reply(reply)
            if not delivered:
                debug.turn_set(outcome="dropped: speaking")
            times.update(self.speaker.last_timing)
        if visit_turn is not None:
            self._visit_commit(visit_turn, delivered)
        self._note_fill(times)
        debug.turn_set(times=times, link=self.link.health())
        if times:
            print("[turn] " + " ".join(f"{k}={v:.1f}s" for k, v in times.items())
                  + f" link={self.link.health()}", flush=True)
        return True

    def turn(self) -> bool:
        """Run one turn. Returns False to end the loop (EOF/quit). Never raises for a
        problem inside the turn; see the module docstring."""
        debug.turn_open()
        self._wait = None
        self._heard_at = None
        try:
            keep_going = self._turn()
            self._errors = 0
            debug.turn_close()
            return keep_going
        except ptt.PTTUnavailable:
            raise                                  # a setup problem, not a bad turn
        except TurnTimeout as e:
            # Not a failure to back off from: the fish already spent the turn's budget.
            w = self._wait or {"used": []}
            debug.turn_set(fillers=list(w["used"]))
            debug.turn_close(f"timeout: {e.stage}")
            print(f"[turn] timeout: {e.stage} still running after "
                  f"{self.cfg.filler.turn_timeout_s:.0f}s, {len(w['used'])} fillers said",
                  flush=True)
            self._wait = None
            self._say_timeout(e.stage)
            return True
        except cloud.CloudUnavailable as e:
            debug.turn_close("offline", e)
            print(f"[turn] sin señal: {e}", flush=True)
            self._apologize(self.cfg.canned.no_signal)
        except cloud.CloudMisconfigured as e:
            debug.turn_close("misconfigured", e)
            print(f"[turn] cloud setup problem: {e}", flush=True)
            self._apologize(self.cfg.canned.no_signal, min_gap_s=30.0)
            time.sleep(2.0)
        except ptt.MicError as e:
            debug.turn_close("mic error", e)
            print(f"[turn] {e}", flush=True)
            self._apologize(self.cfg.canned.no_mic, min_gap_s=30.0)
            time.sleep(2.0)
        except Exception as e:
            debug.turn_close("error", e)
            print(f"[turn] error {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
            self._apologize(self.cfg.canned.no_signal, min_gap_s=30.0)
        finally:
            self._wait = None                      # the welcome and the like are no turn's
            if self.visit is not None:
                self.visit.touch(self._clock())    # the hat's last speech, for the idle rule
        # A failing turn that returns at once must not spin: pause, longer if it keeps failing.
        self._errors += 1
        time.sleep(5.0 if self._errors >= 5 else 1.0)
        return True

    # --- the hat's visit (visit.py) -------------------------------------------------
    def _visit_on(self) -> bool:
        return self.visit is not None and self.cfg.visit.enabled and not self.echo

    def _push_visit(self) -> None:
        push = getattr(self.viz, "push_visit", None)
        if push is not None and self.visit is not None:
            push(**self.visit.view())

    def _new_visit(self, first: str = "", *, forget: bool = True) -> None:
        """A new visitor, on the loop's thread: the model forgets the last one and gets the
        visit's rules. `forget=False` keeps /debug's records (a badge: its vision record was
        made for this visitor, after viz.read_badge had already forgotten the last one)."""
        from .visit import begin_model
        if forget:
            debug.new_visitor()
        begin_model(self.llm, self.cfg.visit.rules)
        self.visit.start(first, self._clock())   # last: a model that cannot be built leaves it closed
        print(f"[visit] new #{self.visit.n}", flush=True)
        self._push_visit()

    def _visit_ask(self, user: str, times: dict[str, float]) -> dict:
        """One visit turn up to the reply: a new visitor when it is one (or when the model
        was rebuilt by a switch and lost the rules), the stage and the cues on the text, the
        "CASA:" line split off. Nothing is remembered here (see `_visit_commit`)."""
        from .visit import split_reply
        llm = self.llm
        at = self._heard_at if self._heard_at is not None else self._clock()
        if self.visit.needs_new(at) or llm.extra_rules != self.cfg.visit.rules:
            self._new_visit()
        stage = self.visit.stage
        tagged, snapshot = self.visit.prepare(user)
        t0 = time.monotonic()
        raw = self._await("llm", lambda: llm.reply(tagged, remember=False))
        times["llm"] = self._stage_time(time.monotonic() - t0)
        debug.turn_set(times=times)
        if llm.last_error and self.cfg.tts.backend != "loq":
            raise cloud.CloudUnavailable(llm.last_error)
        spoken, house = split_reply(raw)
        return {"stage": stage, "tagged": tagged, "raw": raw, "snapshot": snapshot,
                "spoken": spoken, "house": house, "ok": not llm.last_error}

    def _visit_commit(self, t: dict, delivered: bool) -> None:
        """The reply was spoken (or drafted): only now does it enter the model's history and
        the stage move on. A fallback line, a dropped or empty reply changes nothing."""
        if not (delivered and t["ok"] and t["spoken"]):
            return
        self.llm.remember(t["tagged"], t["raw"])
        self.visit.delivered(t["house"], t["snapshot"], self._clock())
        print(f"[visit] etapa {t['stage']}/{self.visit.stages}"
              + (f" casa={t['house']}" if t["house"] else "")
              + (" fin" if self.visit.done else ""), flush=True)
        debug.turn_set(visit=f"{t['stage']}/{self.visit.stages}")
        self._push_visit()

    def _visit_reading_turn(self, r) -> bool:
        """A name for the hat's visit (ADR 0007): a new visitor. A badge's "¿Tú eres X?" is
        stage 1, said without the model and remembered before it is said (so a "sí" still
        finds the name if the voice runs out of time); a typed name gets stage 1 from the
        model. Only the first name reaches the model."""
        from . import reading
        from .visit import note
        times: dict[str, float] = {}
        cfg = self.cfg.visit
        first = r.first_name
        self._start_wait(self._clock())
        self._new_visit(first, forget=r.confirmed)
        if not r.confirmed:
            question = reading.echo_question(first)
            if self.viz is not None:
                self.viz.push_reading("ask")
            print("fish> (lectura: pregunta por el nombre)", flush=True)
            self.llm.remember(f"[ETAPA 1/{self.visit.stages}] "
                              + note(cfg.badge_note, first, r.look), question)
            self.visit.delivered(None, None, self._clock())
            self._push_visit()
            said = self._speak_reply(question)
            times.update(self.speaker.last_timing)
            self._note_fill(times)
            debug.turn_set(trigger="reading", times=times, link=self.link.health(),
                           outcome="read: ask" if said else "dropped: speaking")
            print("[turn] read=ask " + " ".join(f"{k}={v:.1f}s" for k, v in times.items())
                  + f" link={self.link.health()}", flush=True)
            return True
        t = self._visit_ask_reading(note(cfg.name_note, first, r.look), times)
        if t is None:
            return True
        print("fish> (lectura)", flush=True)
        if not t["spoken"]:
            return True
        if self.viz is not None:
            self.viz.push_reading("speaking")
        said = self._speak_reply(t["spoken"])
        self._visit_commit(t, said)
        times.update(self.speaker.last_timing)
        self._note_fill(times)
        debug.turn_set(trigger="reading", times=times, link=self.link.health(),
                       outcome="read: tell" if said else "dropped: speaking")
        print("[turn] read=tell " + " ".join(f"{k}={v:.1f}s" for k, v in times.items())
              + f" link={self.link.health()}", flush=True)
        return True

    def _visit_ask_reading(self, text: str, times: dict[str, float]) -> dict | None:
        """A typed name's stage 1 from the model; None when it could not be asked."""
        from .visit import split_reply
        llm = self.llm
        tagged, snapshot = self.visit.prepare(text)
        t0 = time.monotonic()
        raw = self._await("llm", lambda: llm.reply(tagged, remember=False))
        times["llm"] = self._stage_time(time.monotonic() - t0)
        if llm.last_error and self.cfg.tts.backend != "loq":
            print(f"[turn] lectura sin señal: {llm.last_error}", flush=True)
            debug.turn_set(trigger="reading", times=times, outcome="read: no signal")
            self._apologize(self.cfg.canned.reading_fail)
            return None
        spoken, house = split_reply(raw)
        return {"stage": 1, "tagged": tagged, "raw": raw, "snapshot": snapshot,
                "spoken": spoken, "house": house, "ok": not llm.last_error}

    def _new_visit_turn(self, item) -> bool:
        """"Nuevo visitante" from the sheet: a new visit and the canned greeting (stage 1,
        no model). Moot when a turn already started a visit after it was asked for. In echo
        mode the hat only greets."""
        v = self.visit
        if v is None:
            print("[turn] a new visit, but this persona has none", flush=True)
            return True
        if v.open and v.started_at is not None and v.started_at >= item.at:
            return True
        debug.turn_set(trigger="visit")
        on = self._visit_on()
        if on:
            self._new_visit()
        name = self.cfg.visit.greeting
        text = self.cfg.canned.phrases.get(name, "")
        from . import canned
        if canned.cached(name, self.cfg):
            if self.viz is not None:
                self.viz.push_transcript(text, "fish")   # canned.play shows no bubble
            said = self.speaker.say_canned(name, render=False)
        else:
            said = self.speaker.speak(text)              # rendered now, live
        if said and on:
            self.llm.remember(f"[ETAPA 1/{v.stages}] " + self.cfg.visit.arrival_note, text)
            v.delivered(None, None, self._clock())
            self._push_visit()
        debug.turn_set(outcome="visit: greeting" if said else "dropped: speaking")
        print(f"[turn] visit=greeting said={said}", flush=True)
        return True

    # --- the loop --------------------------------------------------------------------
    def _say_address(self) -> None:
        """With FISH_SAY_ADDRESS and the page open to the network, say the last two octets
        of the LAN address after the welcome (a phone on its own hotspot cannot resolve
        `segunda.local`). Guarded like the welcome: never ends the loop."""
        viz_cfg = self.cfg.viz
        if (self.viz is None or not viz_cfg.say_address
                or viz_cfg.host not in ("0.0.0.0", "::")):
            return
        try:
            ip = self.viz.lan_ip()
            octets = ip.split(".")
            if len(octets) != 4 or ip.startswith(("127.", "169.254.")):
                # No route yet (the service starts before the Wi-Fi is associated): a
                # loopback or link-local address would be a false one. Say nothing.
                print(f"[viz] no LAN address yet ({ip}): the address line is skipped",
                      flush=True)
                return
            line = f"Búscame en el punto {octets[2]} punto {octets[3]}"
            print(f"[viz] address line: {line}", flush=True)
            self.speaker.speak(line)
        except Exception as e:                      # best effort, like the welcome
            print(f"[turn] could not say the address: {e}", flush=True)

    def _should_welcome(self) -> bool:
        c = self.cfg.canned
        if not (c.enabled and c.welcome):
            return False
        if not c.welcome_once:
            return True
        # Once per boot: the runtime dir is cleared at reboot, a service restart keeps it.
        marker = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "fish_brain.welcomed"
        if marker.exists():
            return False
        try:
            marker.touch()
        except OSError:
            pass
        return True

    def run(self) -> None:
        print("Conversation ready. (Ctrl-C or 'salir' to quit.)", flush=True)
        if self._should_welcome():
            self._apologize(self.cfg.canned.welcome)   # guarded: a dead speaker must not end us
        self._say_address()
        clean = False
        try:
            while True:
                try:
                    if not self.turn():
                        clean = True
                        break
                except KeyboardInterrupt:
                    print()
                    clean = True
                    break
        finally:
            if self.button is not None:
                self.button.close()
            # Say goodbye when asked to stop, not when something broke on the way out.
            if clean and self.cfg.canned.enabled and self.cfg.canned.goodbye:
                self._apologize(self.cfg.canned.goodbye)
