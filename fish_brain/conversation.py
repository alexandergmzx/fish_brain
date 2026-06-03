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
                 text_input: bool = False, play_audio: bool = True, viz=None):
        self.cfg = cfg
        self.link = link
        self.text_input = text_input
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
        if self.text_input:
            try:
                text = input("you> ").strip()
            except EOFError:
                return None
            return text or None
        # Voice: push-to-talk -> transcribe.
        wav = ptt.record_hold(self.cfg.ptt)
        try:
            text = self.stt.transcribe(wav).strip()
        finally:
            from pathlib import Path
            Path(wav).unlink(missing_ok=True)
        if text:
            print(f"you> {text}")
        return text or None

    def turn(self) -> bool:
        """Run one turn. Returns False to end the loop (EOF/quit)."""
        user = self._get_user_text()
        if user is None:
            return False
        if user.lower() in {"salir", "quit", "exit"}:
            return False
        reply = self.llm.reply(user)
        print(f"fish> {reply}")
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
