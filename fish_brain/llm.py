"""Cloud LLM (OpenAI) with a bounded conversation history and a fish persona.

Only text leaves the machine. The API key comes from the environment (.env →
OPENAI_API_KEY), loaded by the entry point before this is constructed.
"""
from __future__ import annotations

from .config import LLMConfig


class Conversation:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        from openai import OpenAI  # lazy import so --text/--dry-run without the key is fine
        self._client = OpenAI()
        # Rolling history of {"role","content"} (user/assistant only; system is fixed).
        self._history: list[dict[str, str]] = []

    def _messages(self, user_text: str) -> list[dict[str, str]]:
        msgs = [{"role": "system", "content": self.cfg.system_prompt}]
        msgs.extend(self._history)
        msgs.append({"role": "user", "content": user_text})
        return msgs

    def reply(self, user_text: str) -> str:
        """Send a user turn, return the assistant reply, and update history."""
        resp = self._client.chat.completions.create(
            model=self.cfg.model,
            temperature=self.cfg.temperature,
            messages=self._messages(user_text),
        )
        answer = (resp.choices[0].message.content or "").strip()
        self._history.append({"role": "user", "content": user_text})
        self._history.append({"role": "assistant", "content": answer})
        # Trim to the last N user+assistant pairs.
        max_msgs = self.cfg.max_history_turns * 2
        if len(self._history) > max_msgs:
            self._history = self._history[-max_msgs:]
        return answer
