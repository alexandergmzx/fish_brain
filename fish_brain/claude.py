"""Claude (Anthropic) for the fish: the chat conversation and the badge reading's vision call.

Both go through the Anthropic SDK (never an OpenAI client, never the OpenAI-compatible
endpoint). The package is imported when the first call is made, so a machine without it, or
without a key, runs the rest of the fish untouched; the missing package or key surfaces as
`cloud.CloudMisconfigured`, the way a missing OpenAI key does.

API version 2026-10-21 (SDK 2.x) has no `temperature`, `top_p` or `top_k`: nothing here sends
them. The key is always passed explicitly (the SDK would otherwise look at
`ANTHROPIC_AUTH_TOKEN` and profiles on disk) and so is the host (`ANTHROPIC_BASE_URL` never
redirects it). A Claude connection error does not mark the whole internet offline: the
connectivity probe watches api.openai.com, not Anthropic (`stt.py` treats another service's
failure the same way).

No call retries inside the SDK (`max_retries=0`): SDK 2.3.0 sleeps for whatever `Retry-After`
a response carries, with no cap (the `openai` SDK caps it at 60 s), and the sleep is outside
the read timeout, so one rate-limited call could outlive the turn's 12 s or hold a badge
request for minutes. A failed call is the fallback line, or the next reading candidate, and the
visitor presses again.
"""
from __future__ import annotations

import base64
import copy
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from types import SimpleNamespace

from . import cloud, debug, llm
from .config import LLMConfig

# Clients shared by the reading (HTTP handler threads) and anything else, by (key variable,
# host, key): rebuilt when the key changes. Guarded by `_lock`.
_lock = threading.Lock()
_shared: dict[tuple, object] = {}
# (option, model) pairs the vision API rejected with a 400; not sent again for that model.
_vision_rejected: set[tuple[str, str]] = set()

CONNECT_TIMEOUT_S = 3.0           # a dead hotspot fails in seconds, as in llm.py
SDK_RETRIES = 0                   # see the module docstring
VISION_MAX_TOKENS = 800           # (estimate) the JSON is short; room for thinking if it is on


# --- the SDK, the key, the client ----------------------------------------------------------
def _sdk():
    """The `anthropic` module. Imported here: 0.78 s on the desktop where `openai` takes
    0.35 s (docs/results/2026-10-26-anthropic-sdk-offline-checks.md), more on the board's CPU,
    so the first import says how long it took."""
    fresh = "anthropic" not in sys.modules
    t0 = time.monotonic()
    try:
        import anthropic
    except ImportError as e:             # also a module set to None in sys.modules
        raise cloud.CloudMisconfigured(
            "the anthropic package is not installed (pip install 'anthropic>=2.3,<3')") from e
    if fresh:
        print(f"[claude] sdk imported in {time.monotonic() - t0:.1f}s", file=sys.stderr, flush=True)
    return anthropic


def _api_key(api_key_env: str) -> str:
    key = os.environ.get(api_key_env or "", "").strip()
    if not key:
        raise cloud.CloudMisconfigured(f"{api_key_env} is not set (put it in .env)")
    return key


def _make_client(api_key_env: str, base_url: str, timeout_s: float):
    """A new Anthropic client. The key is checked before the package is imported."""
    key = _api_key(api_key_env)
    sdk = _sdk()
    return sdk.Anthropic(
        api_key=key,                      # explicit: the one credential this client holds
        base_url=base_url or None,        # explicit: the environment cannot redirect it
        timeout=sdk.Timeout(timeout_s, connect=CONNECT_TIMEOUT_S),
        max_retries=SDK_RETRIES,
    )


def ready(api_key_env: str) -> None:
    """Raise `CloudMisconfigured` unless the key is set and the package imports. Cheap to ask
    before a call, so a fish without a Claude key skips Claude without a record or a delay."""
    _api_key(api_key_env)
    _sdk()


def shared_client(api_key_env: str, base_url: str, timeout_s: float = 10.0):
    """One cached client per (key variable, host, key); the caller sets the timeout and the
    timeout of each call with `.with_options(...)`."""
    key = _api_key(api_key_env)
    token = (api_key_env, base_url, key)
    with _lock:
        client = _shared.get(token)
        if client is None:
            client = _shared[token] = _make_client(api_key_env, base_url, timeout_s)
    return client


# --- errors ---------------------------------------------------------------------------------
def _names(exc: BaseException) -> set[str]:
    return {c.__name__ for c in type(exc).__mro__}


def is_sdk_error(exc: BaseException) -> bool:
    """An error of the Anthropic SDK (by class name, so the package is not needed to ask)."""
    return "APIError" in _names(exc)


def classify(exc: BaseException) -> RuntimeError:
    """`CloudUnavailable` (no signal, a timeout, a rate limit, a server error: try later) or
    `CloudMisconfigured` (a bad or exhausted key, an unknown model, a rejected request).
    Never marks the internet offline."""
    status = getattr(exc, "status_code", None)
    name = type(exc).__name__
    if ("APIConnectionError" in _names(exc)          # includes APITimeoutError
            or status in (408, 409, 429)
            or (isinstance(status, int) and status >= 500)):
        return cloud.CloudUnavailable(f"{name}: {exc}")
    return cloud.config_error(f"{name} status={status}: {exc}")


def _rejected(exc: BaseException, words: dict[str, tuple[str, ...]], dropped=()) -> list[str]:
    """The optional request settings a 400 names (a model that does not take one of them).
    Only a 400 that names one counts: any other is not ours to fix by sending less."""
    if getattr(exc, "status_code", None) != 400:
        return []
    text = str(exc).lower()
    return [opt for opt, keys in words.items()
            if opt not in dropped and any(k in text for k in keys)]


# --- what a Claude reply looks like to the rest of the fish ---------------------------------
@dataclass
class Usage:
    """Token counts under the names `ab.py`, `hat_rehearse.py` and the debug page read.
    `prompt_tokens` includes cached tokens; `completion_tokens` includes thinking."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


_FINISH = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length",
           "model_context_window_exceeded": "length", "refusal": "content_filter"}


@dataclass
class Answer:
    """A Messages reply reduced to what the fish uses. `choices` is the OpenAI-shaped view
    that `debug.model` and `reading._parse_badge` read; it always has one entry."""
    text: str = ""
    stop_reason: str | None = None
    usage: Usage = field(default_factory=Usage)
    refusal: str | None = None

    @property
    def choices(self) -> list:
        message = SimpleNamespace(content=self.text, refusal=self.refusal)
        finish = _FINISH.get(self.stop_reason or "", self.stop_reason)
        return [SimpleNamespace(message=message, finish_reason=finish)]


def answer_from(resp) -> Answer:
    """Read a Messages response by block type (thinking blocks may come first)."""
    text = "".join((getattr(b, "text", "") or "") for b in (resp.content or [])
                   if getattr(b, "type", None) == "text")
    u = getattr(resp, "usage", None)
    read = int(getattr(u, "cache_read_input_tokens", 0) or 0)
    wrote = int(getattr(u, "cache_creation_input_tokens", 0) or 0)
    usage = Usage(
        prompt_tokens=int(getattr(u, "input_tokens", 0) or 0) + read + wrote,
        completion_tokens=int(getattr(u, "output_tokens", 0) or 0),
        cache_read_tokens=read, cache_write_tokens=wrote)
    stop = getattr(resp, "stop_reason", None)
    refusal = None
    if stop == "refusal":
        category = getattr(getattr(resp, "stop_details", None), "category", None)
        refusal = f"refusal:{category}" if category else "refusal"
    return Answer(text=text, stop_reason=stop, usage=usage, refusal=refusal)


# --- the chat ---------------------------------------------------------------------------------
# Words in a 400's text that name the optional setting it refused.
_CHAT_WORDS = {"thinking": ("thinking",), "effort": ("effort",)}


class Conversation(llm._Chat):
    """The fish's chat on a profile with `provider: anthropic`. Same surface as
    `llm.Conversation`: `reply`, `probe`, `remember`, `reset`, `extra_rules`, `last_*`."""

    def __init__(self, cfg: LLMConfig, *, client=None):
        if cfg.provider != "anthropic":
            raise cloud.CloudMisconfigured(
                f"profile {cfg.profile!r} is a {cfg.provider} profile: build it with "
                "llm.make_conversation")
        super().__init__(cfg)
        self._client = client if client is not None else _make_client(
            cfg.api_key_env, cfg.base_url, cfg.timeout_s)

    def _system(self) -> list[dict]:
        """The persona, then the visitor's rules, as the API's top-level system blocks."""
        return [{"type": "text", "text": t}
                for t in (self.cfg.system_prompt, self.extra_rules) if t and t.strip()]

    def _api_messages(self, user_text: str) -> list[dict]:
        """History and the new turn. An empty turn in the history is left out (the API refuses
        an empty text block, and one would fail every turn after it)."""
        msgs = [{"role": m["role"], "content": m["content"]} for m in self._history
                if str(m.get("content", "")).strip()]
        msgs.append({"role": "user", "content": user_text})
        return msgs

    def _options(self) -> dict:
        """Thinking and effort, unless the API refused one of them once."""
        opts: dict = {}
        thinking = getattr(self, "thinking", None) or self.cfg.thinking
        if thinking and "thinking" not in self._dropped:
            opts["thinking"] = {"type": thinking}
        effort = (self.cfg.reasoning_effort or "").strip().lower()
        if effort and effort != "none" and "effort" not in self._dropped:
            opts["output_config"] = {"effort": effort}
        return opts

    def _create(self, user_text: str) -> Answer:
        opts = self._options()
        max_tokens = self.cfg.max_completion_tokens
        # For /debug: the OpenAI-style list (system, system, history, user) whatever the API gets.
        sent = {"profile": self.cfg.profile, "model": self.cfg.model,
                "messages": self._messages(user_text), "params": {"max_tokens": max_tokens, **opts}}
        system = self._system()
        t0 = time.monotonic()
        try:
            resp = self._client.messages.create(
                model=self.cfg.model, max_tokens=max_tokens,
                messages=self._api_messages(user_text),
                **({"system": system} if system else {}), **opts)
        except Exception as e:
            debug.model("llm", sent, error=e, seconds=time.monotonic() - t0)
            raise
        answer = answer_from(resp)
        debug.model("llm", sent, resp=answer, seconds=time.monotonic() - t0,
                    stop_reason=answer.stop_reason)
        return answer

    def probe(self) -> dict:
        """One tiny call for the debug page's cloud check. It leaves the history and the
        `last_*` fields alone, never retries and gives up after 6 s."""
        client = self._client.with_options(max_retries=0, timeout=6.0)
        opts = self._options()
        messages = [{"role": "user", "content": "Responde solo: ok"}]
        sent = {"profile": self.cfg.profile, "model": self.cfg.model, "messages": messages,
                "params": {"max_tokens": 64, **opts}, "probe": True}
        t0 = time.monotonic()
        try:
            resp = client.messages.create(
                model=self.cfg.model, max_tokens=64, messages=messages, **opts)
        except Exception as e:
            debug.model("llm", sent, error=e, seconds=time.monotonic() - t0)
            raise
        answer = answer_from(resp)
        debug.model("llm", sent, resp=answer, seconds=time.monotonic() - t0,
                    stop_reason=answer.stop_reason)
        return {"seconds": round(time.monotonic() - t0, 2), "model": self.cfg.model,
                "reply": answer.text.strip()[:40]}

    def reply(self, user_text: str, *, remember: bool = True) -> str:
        """Send a user turn, return the assistant reply, and update history. With
        `remember=False` the caller remembers the pair itself once the answer was delivered.
        An API error, a refusal or an empty reply leaves `last_error` set, the history alone,
        and returns the persona's fallback line."""
        self.last_error, self.last_usage = None, None
        t0 = time.monotonic()
        try:
            try:
                answer = self._create(user_text)
            except Exception as e:
                # A model that doesn't take one of the optional settings: drop it, retry once.
                bad = _rejected(e, _CHAT_WORDS, self._dropped)
                if not bad:
                    raise
                self._dropped.update(bad)
                print(f"[llm] {self.cfg.profile} rejected {bad}; retrying without",
                      file=sys.stderr)
                answer = self._create(user_text)
        except Exception as e:
            if not is_sdk_error(e):
                raise
            # Offline / timeout / bad key / rate limit: say something instead of crashing the
            # loop. Not added to history, so the next turn retries cleanly.
            self.last_latency_s = time.monotonic() - t0
            self.last_error = f"{type(e).__name__}: {e}"
            print(f"[llm] {self.cfg.profile} {self.last_error}", file=sys.stderr)
            return self.cfg.fallback_reply
        self.last_latency_s = time.monotonic() - t0
        self.last_usage = answer.usage            # billed even when nothing is said
        print(f"[llm] {self.cfg.profile} {self.cfg.model} {self.last_latency_s:.2f}s",
              file=sys.stderr)
        text = answer.text.strip()
        problem = answer.refusal or (None if text else
                                     f"empty reply (stop_reason={answer.stop_reason})")
        if problem:
            self.last_error = problem
            print(f"[llm] {self.cfg.profile} {problem}", file=sys.stderr)
            return self.cfg.fallback_reply
        if remember:
            self.remember(user_text, text)
        return text


# --- the badge (vision) -------------------------------------------------------------------------
# Words in a 400's text that name the vision setting it refused ("format" alone would also match
# an error about the image's format, and the schema would be dropped for nothing).
_VISION_WORDS = {"format": ("output_config.format", "json_schema", "schema"),
                 "thinking": ("thinking",), "effort": ("effort",)}
_JSON_ONLY = (" Responde solo con un objeto JSON, sin texto antes ni después, con estas claves: "
              "badge_found, full_name, given_names, surnames, name_for_speech, look, confidence.")


def anthropic_schema(schema: dict) -> dict:
    """A copy of a JSON schema with `{"type": [X, "null"]}` written as `anyOf`, the nullable
    form the structured-output API documents (the SDK's own `transform_schema` refuses a type
    list). The schema the OpenAI call uses is not touched."""
    out = copy.deepcopy(schema)

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        if isinstance(node.get("type"), list):
            types = [t for t in node.pop("type") if t != "null"]
            rest = dict(node)
            node.clear()
            node["anyOf"] = [{**rest, "type": t} for t in types] + [{"type": "null"}]
        for value in node.values():
            walk(value)

    walk(out)
    return out


def _json_object(text: str) -> str:
    """The JSON object in a reply that may be wrapped in a code fence or a sentence."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[A-Za-z]*\s*|\s*```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start:end + 1]
    return text


def ask_badge(profile: dict, *, system: str, jpeg: bytes, ask: str, schema: dict,
              timeout_s: float) -> Answer:
    """Read a badge photo with Claude. `profile` is an LLM_PROFILES entry. The reply text is
    one JSON object. Raises `CloudUnavailable` / `CloudMisconfigured`; the SDK's errors never
    leave this function."""
    model = profile["model"]
    client = shared_client(profile["api_key_env"], profile.get("base_url", ""))
    sdk = _sdk()
    client = client.with_options(timeout=sdk.Timeout(timeout_s, connect=CONNECT_TIMEOUT_S),
                                 max_retries=SDK_RETRIES)
    image = {"type": "image", "source": {
        "type": "base64", "media_type": "image/jpeg",
        "data": base64.b64encode(bytes(jpeg)).decode("ascii")}}
    for _ in range(len(_VISION_WORDS) + 1):          # each retry leaves one setting out
        skip = {opt for opt, m in _vision_rejected if m == model}
        opts: dict = {}
        output_config: dict = {}
        if "format" not in skip:
            output_config["format"] = {"type": "json_schema", "schema": anthropic_schema(schema)}
        effort = (profile.get("reasoning_effort") or "").strip().lower()
        if effort and effort != "none" and "effort" not in skip:
            output_config["effort"] = effort
        if output_config:
            opts["output_config"] = output_config
        if profile.get("thinking") and "thinking" not in skip:
            opts["thinking"] = {"type": profile["thinking"]}
        text = ask + (_JSON_ONLY if "format" in skip else "")
        try:
            resp = client.messages.create(
                model=model, max_tokens=VISION_MAX_TOKENS, system=system,
                messages=[{"role": "user", "content": [image, {"type": "text", "text": text}]}],
                **opts)
        except Exception as e:
            if not is_sdk_error(e):
                raise
            bad = _rejected(e, _VISION_WORDS, skip)
            if bad:
                _vision_rejected.update((opt, model) for opt in bad)
                print(f"[claude] {model} rejected {bad}; asking again without",
                      file=sys.stderr, flush=True)
                continue
            raise classify(e) from e
        answer = answer_from(resp)
        answer.text = _json_object(answer.text)
        return answer
    raise cloud.config_error("the vision call was refused twice")      # unreachable
