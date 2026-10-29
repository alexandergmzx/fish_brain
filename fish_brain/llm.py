"""Cloud LLM with bounded history + fish persona.

Only text leaves the machine. Which backend is used comes from LLMConfig.profile
(FISH_LLM_PROFILE in .env); its API key is read from the env var the profile names.
`Conversation` speaks to any OpenAI-compatible API (Groq, OpenAI, ...); a profile with
`provider: anthropic` is served by claude.Conversation. `make_conversation` picks.
"""
from __future__ import annotations

import os
import sys
import time

from . import cloud, debug
from .config import LLMConfig


class _Chat:
    """What every provider's conversation shares: the persona, the per-visitor rules and the
    bounded history. A subclass sends the request and sets `last_*` in `reply()`."""

    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        # Request options the API rejected once (HTTP 400); not sent again.
        self._dropped: set[str] = set()
        # Rolling history of {"role","content"} (user/assistant only; system is fixed).
        self._history: list[dict[str, str]] = []
        # Rules for the current visitor (the reading), sent as a second system message right
        # after the persona. Empty = none; `reset()` clears them with the history.
        self.extra_rules: str = ""
        # The thinking mode for the current visitor's calls, over the profile's (anthropic
        # profiles only; the fortune's reading sets "disabled", ADR 0026). None = the profile's;
        # `reset()` clears it with the rules.
        self.thinking: str | None = None
        # Stats from the last reply() call (used by `python -m fish_brain.ab`).
        self.last_latency_s: float = 0.0
        self.last_usage = None
        self.last_error: str | None = None

    def _messages(self, user_text: str) -> list[dict[str, str]]:
        msgs = [{"role": "system", "content": self.cfg.system_prompt}]
        if self.extra_rules:
            msgs.append({"role": "system", "content": self.extra_rules})
        msgs.extend(self._history)
        msgs.append({"role": "user", "content": user_text})
        return msgs

    def reset(self) -> None:
        """Forget the history and the per-visitor rules (a new visitor)."""
        self._history.clear()
        self.extra_rules = ""
        self.thinking = None

    def remember(self, user_text: str, answer: str) -> None:
        """Append one user/assistant pair to the history (trimmed to the last N pairs), as
        if `answer` had been the model's reply. Also seeds a turn that was spoken without
        the model (the reading's question)."""
        self._history.append({"role": "user", "content": user_text})
        self._history.append({"role": "assistant", "content": answer})
        max_msgs = self.cfg.max_history_turns * 2
        if len(self._history) > max_msgs:
            self._history = self._history[-max_msgs:]


class Conversation(_Chat):
    """The OpenAI-compatible provider (Groq, OpenAI)."""

    def __init__(self, cfg: LLMConfig):
        if cfg.provider != "openai":
            # Its key would be sent to api.openai.com (an empty base_url means that host).
            raise cloud.CloudMisconfigured(
                f"profile {cfg.profile!r} is a {cfg.provider} profile: build it with "
                "llm.make_conversation")
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
        super().__init__(cfg)

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
        messages, kwargs = self._messages(user_text), self._kwargs()
        sent = {"profile": self.cfg.profile, "model": self.cfg.model, "messages": messages,
                "params": {"max_completion_tokens": self.cfg.max_completion_tokens, **kwargs}}
        t0 = time.monotonic()
        try:
            resp = self._client.chat.completions.create(
                model=self.cfg.model,
                max_completion_tokens=self.cfg.max_completion_tokens,
                messages=messages,
                **kwargs,
            )
        except Exception as e:
            debug.model("llm", sent, error=e, seconds=time.monotonic() - t0)   # for /debug
            raise
        debug.model("llm", sent, resp=resp, seconds=time.monotonic() - t0)
        return resp

    def probe(self) -> dict:
        """One tiny call for the debug page's cloud check. It leaves the history and the
        `last_*` fields alone, never retries and gives up after 6 s."""
        client = self._client.with_options(max_retries=0, timeout=6.0)
        kwargs = {k: v for k, v in self._kwargs().items() if k != "temperature"}
        messages = [{"role": "user", "content": "Responde solo: ok"}]
        sent = {"profile": self.cfg.profile, "model": self.cfg.model, "messages": messages,
                "params": {"max_completion_tokens": 16, **kwargs}, "probe": True}
        t0 = time.monotonic()
        try:
            resp = client.chat.completions.create(
                model=self.cfg.model, max_completion_tokens=16, messages=messages, **kwargs)
        except Exception as e:
            debug.model("llm", sent, error=e, seconds=time.monotonic() - t0)
            raise
        debug.model("llm", sent, resp=resp, seconds=time.monotonic() - t0)
        return {"seconds": round(time.monotonic() - t0, 2), "model": self.cfg.model,
                "reply": (resp.choices[0].message.content or "").strip()[:40]}

    def reply(self, user_text: str, *, remember: bool = True) -> str:
        """Send a user turn, return the assistant reply, and update history. With
        `remember=False` the caller remembers the pair itself once the answer was delivered
        (the hat's visit: a late or unspoken answer never reaches the history)."""
        from openai import APIError, BadRequestError  # APIError: connection/timeout/status
        self.last_error, self.last_usage = None, None
        t0 = time.monotonic()
        if not self.cfg.base_url and not cloud.is_online():
            # Known offline: answer at once instead of waiting out the timeout. The probe
            # watches api.openai.com, so it only speaks for profiles hosted there.
            self.last_error = "offline"
            debug.model("llm", {"profile": self.cfg.profile, "model": self.cfg.model,
                                "messages": self._messages(user_text)},
                        sent=False, note="not sent: known offline")
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
        if remember:
            self.remember(user_text, answer)
        return answer


def make_conversation(cfg: LLMConfig) -> _Chat:
    """The conversation for the profile's provider. The SDK is imported here, when the
    object is built, so a machine that never uses a provider does not need its package."""
    if cfg.provider == "anthropic":
        from .claude import Conversation as ClaudeConversation
        return ClaudeConversation(cfg)
    if cfg.provider == "openai":
        return Conversation(cfg)
    raise ValueError(f"unknown LLM provider {cfg.provider!r} (profile {cfg.profile!r})")
