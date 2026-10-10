"""Cloud LLM (any OpenAI-compatible API: Groq, OpenAI, ...) with bounded history + fish persona.

Only text leaves the machine. Which backend is used comes from LLMConfig.profile
(FISH_LLM_PROFILE in .env); its API key is read from the env var the profile names.
"""
from __future__ import annotations

import os
import sys
import time

from . import cloud
from .config import LLMConfig


class Conversation:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        import openai  # lazy import so --text/--dry-run without the key is fine
        # Never let the SDK pick a key by itself: with none given it would fall back to
        # OPENAI_API_KEY and send it to whichever service this profile points at.
        key = os.environ.get(cfg.api_key_env or "", "").strip()
        if not key:
            raise cloud.CloudMisconfigured(f"{cfg.api_key_env} is not set (put it in .env)")
        self._client = openai.OpenAI(
            base_url=cfg.base_url or None,           # None -> api.openai.com
            api_key=key,
            # A bare float would also stretch the connect timeout; keep that one short so a
            # dead hotspot fails in seconds.
            timeout=openai.Timeout(cfg.timeout_s, connect=3.0),
            max_retries=1,
        )
        # Request options the API rejected once (HTTP 400); not sent again.
        self._dropped: set[str] = set()
        # Rolling history of {"role","content"} (user/assistant only; system is fixed).
        self._history: list[dict[str, str]] = []
        # Stats from the last reply() call (used by `python -m fish_brain.ab`).
        self.last_latency_s: float = 0.0
        self.last_usage = None
        self.last_error: str | None = None

    def _messages(self, user_text: str) -> list[dict[str, str]]:
        msgs = [{"role": "system", "content": self.cfg.system_prompt}]
        msgs.extend(self._history)
        msgs.append({"role": "user", "content": user_text})
        return msgs

    def reset(self) -> None:
        self._history.clear()

    def _kwargs(self) -> dict:
        kwargs: dict = {}
        effort = self.cfg.reasoning_effort
        if effort and "reasoning_effort" not in self._dropped:
            kwargs["reasoning_effort"] = effort
        if self.cfg.extra_body:
            kwargs["extra_body"] = self.cfg.extra_body
        # OpenAI's reasoning models only accept temperature with reasoning effort "none"
        # (Groq's GPT-OSS takes both, so the rule applies to api.openai.com only).
        temp_ok = bool(self.cfg.base_url) or not effort or effort == "none"
        if self.cfg.temperature is not None and temp_ok and "temperature" not in self._dropped:
            kwargs["temperature"] = self.cfg.temperature
        return kwargs

    def _create(self, user_text: str):
        return self._client.chat.completions.create(
            model=self.cfg.model,
            max_completion_tokens=self.cfg.max_completion_tokens,
            messages=self._messages(user_text),
            **self._kwargs(),
        )

    def reply(self, user_text: str) -> str:
        """Send a user turn, return the assistant reply, and update history."""
        from openai import APIError, BadRequestError  # APIError: connection/timeout/status
        self.last_error, self.last_usage = None, None
        t0 = time.monotonic()
        if not self.cfg.base_url and not cloud.is_online():
            # Known offline: answer at once instead of waiting out the timeout. The probe
            # watches api.openai.com, so it only speaks for profiles hosted there.
            self.last_error = "offline"
            print(f"[llm] {self.cfg.profile} offline", file=sys.stderr)
            return self.cfg.fallback_reply
        try:
            try:
                resp = self._create(user_text)
            except BadRequestError as e:
                # A model that doesn't take one of the optional settings: drop it and retry once.
                bad = [k for k in ("temperature", "reasoning_effort") if k in str(e)
                       and k not in self._dropped]
                if not bad:
                    raise
                self._dropped.update(bad)
                print(f"[llm] {self.cfg.profile} rejected {bad}; retrying without", file=sys.stderr)
                resp = self._create(user_text)
        except APIError as e:
            # Offline / timeout / bad key / rate limit: say something instead of crashing
            # the loop. Not added to history, so the next turn retries cleanly.
            self.last_latency_s = time.monotonic() - t0
            self.last_error = f"{type(e).__name__}: {e}"
            print(f"[llm] {self.cfg.profile} {self.last_error}", file=sys.stderr)
            from openai import APIConnectionError
            if isinstance(e, APIConnectionError):
                cloud.mark_offline()
            return self.cfg.fallback_reply
        self.last_latency_s = time.monotonic() - t0
        self.last_usage = resp.usage
        print(f"[llm] {self.cfg.profile} {self.cfg.model} {self.last_latency_s:.2f}s",
              file=sys.stderr)
        answer = (resp.choices[0].message.content or "").strip()
        self._history.append({"role": "user", "content": user_text})
        self._history.append({"role": "assistant", "content": answer})
        # Trim to the last N user+assistant pairs.
        max_msgs = self.cfg.max_history_turns * 2
        if len(self._history) > max_msgs:
            self._history = self._history[-max_msgs:]
        return answer
