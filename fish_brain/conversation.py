"""The conversation turn loop: input -> STT -> LLM -> fish speaks -> repeat.

Two input modes:
  - voice (default): push-to-talk mic capture -> speech-to-text
  - text  (--text):  type the user turn (skips mic + STT)

Push-to-talk can come from the browser button (--viz), a remote's button (FISH_PTT_DEVICE),
or the keyboard; the first two can be active together.

Nothing that goes wrong inside a turn ends the loop: a failed cloud call, a missing
microphone or a bad audio file makes the fish say a short canned line and listen again.
Only quitting (Ctrl-C, a stop signal, "salir", end of input) ends it.

Components are built lazily so `--text --dry-run` works without a mic, and so the heavy
STT model only loads when voice mode actually needs it.
"""
from __future__ import annotations

import os
import time
import traceback
from pathlib import Path

from . import cloud, ptt, speak as speak_mod
from .conductor import Player, make_player
from .config import Config
from .serial_link import BaseLink

_QUIT_WORDS = {"salir", "quit", "exit"}


class FishConversation:
    def __init__(self, cfg: Config, link: BaseLink, *,
                 text_input: bool = False, play_audio: bool = True, viz=None,
                 echo: bool = False):
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

    # --- one turn, in stages ---------------------------------------------------------
    def _record(self) -> Path | object:
        """Wait for push-to-talk and record, or for an item the page offers through the viz
        inbox. Raises ptt.MicError / ptt.PTTUnavailable."""
        # Stream the live mic level to the on-screen fish (if any) while recording.
        on_level = (lambda lvl: self.viz.push_level(lvl)) if self.viz is not None else None
        if self.sources:
            if self.viz is not None:
                print("[ptt] mantén pulsado 'Hablar' (navegador o control) para grabar…",
                      flush=True)
                self.viz.set_listening(True)
            try:
                return ptt.record_multi(
                    self.cfg.ptt, self.sources, on_level=on_level,
                    inbox=self.viz.take_inbox if self.viz is not None else None)
            finally:
                if self.viz is not None:
                    self.viz.set_listening(False)
        return ptt.record_hold(self.cfg.ptt, on_level=on_level)

    def _handle_item(self, item) -> bool:
        """An input item that is not a recording (offered by the page). The single dispatch
        point for such items; returns whether the loop goes on."""
        from .reading import Reading
        if isinstance(item, Reading):
            return self._reading_turn(item)
        print(f"[turn] unknown input item {type(item).__name__}", flush=True)
        return True

    def _reading_turn(self, r) -> bool:
        """A visitor's name arrived (ADR 0007). A new visitor: the history is reset and the
        per-visitor rules attached. Unconfirmed (a badge): the fish asks "¿Tú eres X?" and
        the answer is the next normal voice turn, with the question seeded in the history.
        Confirmed (typed): the fish tells the future now. The quit words never apply here."""
        from . import reading
        times: dict[str, float] = {}
        look_note = f" Lleva: {r.look}." if r.look else ""
        if not self.echo:
            self.llm.reset()
            self.llm.extra_rules = self.cfg.reading.rules
        if not r.confirmed:
            question = reading.echo_question(r.first_name)
            if self.viz is not None:
                self.viz.push_reading("ask")
            print("fish> (lectura: pregunta por el nombre)", flush=True)
            self.speaker.speak(question)
            if not self.echo:
                self.llm.remember(
                    f"[Lectura] El visitante muestra su gafete: se llama {r.name}.{look_note}"
                    " Pregúntale si es él o ella; cuando confirme, dile su futuro.", question)
            times.update(self.speaker.last_timing)
            print("[turn] read=ask " + " ".join(f"{k}={v:.1f}s" for k, v in times.items())
                  + f" link={self.link.health()}", flush=True)
            return True
        if self.echo:
            reply = reading.echo_fortune(r.first_name)
        else:
            t0 = time.monotonic()
            reply = self.llm.reply(
                f"[Lectura] Se llama {r.name}, confirmado.{look_note} Dile su futuro.")
            times["llm"] = time.monotonic() - t0
            if self.llm.last_error and self.cfg.tts.backend != "loq":
                # The model is unreachable and so, most likely, is cloud TTS: the cached line.
                print(f"[turn] lectura sin señal: {self.llm.last_error}", flush=True)
                self._apologize(self.cfg.canned.reading_fail)
                return True
        print("fish> (lectura)", flush=True)
        if not reply:
            return True
        if self.viz is not None:
            self.viz.push_reading("speaking")
        self.speaker.speak(reply)
        times.update(self.speaker.last_timing)
        print("[turn] read=tell " + " ".join(f"{k}={v:.1f}s" for k, v in times.items())
              + f" link={self.link.health()}", flush=True)
        return True

    def _transcribe(self, wav: Path) -> str:
        """Recording -> text ("" when there is nothing usable in it)."""
        try:
            if ptt.wav_duration_s(wav) < self.cfg.stt.min_clip_s:
                return ""                          # a tap, not a sentence
            # Skip silent captures: Whisper hallucinates phrases on silence (wrong/muted mic).
            rms = ptt.wav_rms(wav)
            if rms < self.cfg.ptt.silence_rms:
                print(f"you> … (grabación casi en silencio, rms={rms:.4f}; ¿micrófono correcto?)",
                      flush=True)
                if self.viz is not None:
                    self.viz.push_transcript("… (silencio, ¿micrófono correcto?)", "user")
                return ""
            text = self.stt.transcribe(wav).strip()
        finally:
            Path(wav).unlink(missing_ok=True)
        print(f"you> {text}" if text else "you> … (no te entendí, intenta de nuevo)", flush=True)
        if self.viz is not None:
            self.viz.push_transcript(text or "… (no te entendí)", "user")
        return text

    def _apologize(self, phrase: str, *, min_gap_s: float = 0.0) -> None:
        """Say a canned error line (best effort), at most once per `min_gap_s`."""
        now = time.monotonic()
        if not phrase or now - self._last_apology < min_gap_s:
            return
        self._last_apology = now
        try:
            # Under the speaker lock: the /badge handler thread says its own canned lines
            # through the same lock, so two phrases never drive the link at once.
            if not self.speaker.say_canned(phrase):
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
        else:
            t0 = time.monotonic()
            wav = self._record()
            if not isinstance(wav, Path):
                return self._handle_item(wav)
            times["rec"] = time.monotonic() - t0
            t0 = time.monotonic()
            user = self._transcribe(wav)
            times["stt"] = time.monotonic() - t0

        if user.lower().strip(" .!¡") in _QUIT_WORDS and (
                self.text_input or self.cfg.ptt.voice_quit):
            return False
        if not user:
            return True                            # nothing captured -> keep listening

        # Echo mode just speaks the transcription back -> never touches the LLM (no API key).
        if self.echo:
            reply = user
        else:
            t0 = time.monotonic()
            reply = self.llm.reply(user)
            times["llm"] = time.monotonic() - t0
            if self.llm.last_error and self.cfg.tts.backend != "loq":
                # The LLM is unreachable and so, most likely, is cloud TTS: use the cached line.
                raise cloud.CloudUnavailable(self.llm.last_error)
        print(f"fish> {reply}", flush=True)
        if not reply:
            return True
        if self.viz is not None and self.viz.wait_enabled():
            # "Wait to speak": show the reply and drop it into the editable box; the user tweaks
            # it and presses Speak (-> /speak) to make the fish say it.
            self.viz.push_transcript(reply, "fish")
            self.viz.push_draft(reply)
        else:
            self.speaker.speak(reply)              # Speaker pushes the "fish" transcript + speaks
            times.update(self.speaker.last_timing)
        if times:
            print("[turn] " + " ".join(f"{k}={v:.1f}s" for k, v in times.items())
                  + f" link={self.link.health()}", flush=True)
        return True

    def turn(self) -> bool:
        """Run one turn. Returns False to end the loop (EOF/quit). Never raises for a
        problem inside the turn; see the module docstring."""
        try:
            keep_going = self._turn()
            self._errors = 0
            return keep_going
        except ptt.PTTUnavailable:
            raise                                  # a setup problem, not a bad turn
        except cloud.CloudUnavailable as e:
            print(f"[turn] sin señal: {e}", flush=True)
            self._apologize(self.cfg.canned.no_signal)
        except cloud.CloudMisconfigured as e:
            print(f"[turn] cloud setup problem: {e}", flush=True)
            self._apologize(self.cfg.canned.no_signal, min_gap_s=30.0)
            time.sleep(2.0)
        except ptt.MicError as e:
            print(f"[turn] {e}", flush=True)
            self._apologize(self.cfg.canned.no_mic, min_gap_s=30.0)
            time.sleep(2.0)
        except Exception as e:
            print(f"[turn] error {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
            self._apologize(self.cfg.canned.no_signal, min_gap_s=30.0)
        # A failing turn that returns at once must not spin: pause, longer if it keeps failing.
        self._errors += 1
        time.sleep(5.0 if self._errors >= 5 else 1.0)
        return True

    # --- the loop --------------------------------------------------------------------
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
