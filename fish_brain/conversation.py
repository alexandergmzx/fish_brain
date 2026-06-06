"""The conversation turn loop: input -> STT -> LLM -> fish speaks -> repeat.

Two input modes:
  - voice (default): push-to-talk mic capture -> local STT
  - text  (--text):  type the user turn (skips mic + STT)

Components are built lazily so `--text --dry-run` works without a mic, and so the heavy
STT model only loads when voice mode actually needs it.
"""
from __future__ import annotations

from . import canned, ptt, speak as speak_mod
from .conductor import Player, make_player
from .config import Config
from .serial_link import BaseLink


class FishConversation:
    def __init__(self, cfg: Config, link: BaseLink, *,
                 text_input: bool = False, play_audio: bool = True, viz=None,
                 echo: bool = False):
        self.cfg = cfg
        self.link = link
        self.text_input = text_input
        self.echo = echo
        self.player: Player = make_player(play_audio)
        self.viz = viz
        self._llm = None
        self._stt = None

    @property
    def llm(self):
        if self._llm is None:
            from .llm import Conversation
            self._llm = Conversation(self.cfg.llm)
        return self._llm

    @property
    def stt(self):
        if self._stt is None:
            from .stt import Transcriber
            self._stt = Transcriber(self.cfg.stt)
        return self._stt

    def _get_user_text(self) -> str | None:
        """The user's turn: text, "" if nothing was captured, or None on EOF (quit)."""
        if self.text_input:
            try:
                return input("you> ").strip()
            except EOFError:
                return None
        # Voice: push-to-talk -> transcribe. Stream the live mic level to the on-screen
        # fish (if any) so the web GUI draws a meter while recording. With --viz the turn is
        # triggered by the browser's hold-to-talk button; otherwise by the keyboard.
        on_level = (lambda lvl: self.viz.push_level(lvl)) if self.viz is not None else None
        if self.viz is not None:
            wav = ptt.record_web(self.cfg.ptt, self.viz.ptt_held, on_level=on_level)
        else:
            wav = ptt.record_hold(self.cfg.ptt, on_level=on_level)
        from pathlib import Path
        try:
            # Skip silent captures: Whisper hallucinates phrases on silence (wrong/muted mic).
            rms = ptt.wav_rms(wav)
            if rms < self.cfg.ptt.silence_rms:
                print(f"you> … (grabación casi en silencio, rms={rms:.4f}; ¿micrófono correcto?)")
                if self.viz is not None:
                    self.viz.push_transcript("… (silencio, ¿micrófono correcto?)", "user")
                return ""
            text = self.stt.transcribe(wav).strip()
        finally:
            Path(wav).unlink(missing_ok=True)
        print(f"you> {text}" if text else "you> … (no te entendí, intenta de nuevo)")
        if self.viz is not None:
            self.viz.push_transcript(text or "… (no te entendí)", "user")
        return text

    def turn(self) -> bool:
        """Run one turn. Returns False to end the loop (EOF/quit)."""
        user = self._get_user_text()
        if user is None:
            return False                       # EOF (Ctrl-D in --text)
        user = user.strip()
        if user.lower() in {"salir", "quit", "exit"}:
            return False
        if not user:
            return True                        # nothing captured -> keep listening
        # Echo mode just speaks the transcription back -> never touches the LLM (no API key).
        reply = user if self.echo else self.llm.reply(user)
        print(f"fish> {reply}")
        if self.viz is not None and reply:
            self.viz.push_transcript(reply, "fish")
        if reply:
            speak_mod.speak(reply, self.link, self.cfg, player=self.player, viz=self.viz)
        return True

    def run(self) -> None:
        print("Conversation ready. (Ctrl-C or 'salir' to quit.)")
        if self.cfg.canned.enabled and self.cfg.canned.welcome:
            canned.play(self.cfg.canned.welcome, self.link, self.cfg,
                        player=self.player, viz=self.viz)
        try:
            while True:
                try:
                    if not self.turn():
                        break
                except KeyboardInterrupt:
                    print()
                    break
        finally:
            if self.cfg.canned.enabled and self.cfg.canned.goodbye:
                canned.play(self.cfg.canned.goodbye, self.link, self.cfg,
                            player=self.player, viz=self.viz)
