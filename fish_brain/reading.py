"""The reading (ADR 0007): a badge photo becomes a name; the fish asks, then tells the future.

`read_badge()` relays a JPEG, in memory, to a vision model with a strict JSON schema and
reasoning off. The models are the profiles of `FISH_READING_PROFILE`, in order (empty =
`claude` first, then the LLM profile; only profiles with image input: `claude`, `luna`): a
profile whose key is not set is skipped, and one that fails gives way to the next. The photo
is never written, logged or kept: it lives in the caller's local variable. The result's names
are cleaned so what the fish says is letters only, and the journal line carries timings and
confidence, never a name.

`Reading` is the item the page offers the turn loop (through the viz inbox); the loop
speaks "¿Tú eres X?" or, for a confirmed (typed) name, tells the future at once.
`Utterance` is the other item: a recording uploaded from the phone's microphone.
"""
from __future__ import annotations

import base64
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import cloud, debug
from .config import LLM_PROFILES, Config

JPEG_MAGIC = b"\xff\xd8\xff"

# What the vision call must answer. Every field required, nullable where the badge may lack it.
BADGE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "badge_found": {"type": "boolean"},
        "full_name": {"type": ["string", "null"]},
        "given_names": {"type": ["string", "null"]},
        "surnames": {"type": ["string", "null"]},
        "name_for_speech": {"type": ["string", "null"]},
        "look": {"type": ["string", "null"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["badge_found", "full_name", "given_names", "surnames", "name_for_speech",
                 "look", "confidence"],
    "additionalProperties": False,
}


@dataclass
class BadgeRead:
    """What the model read on the badge. `found` False = nothing usable."""
    found: bool = False
    full_name: str = ""
    given_names: str = ""
    surnames: str = ""
    name_for_speech: str = ""
    look: str | None = None
    confidence: str = "low"
    seconds: float = 0.0
    tokens: int = 0
    profile: str = ""             # the LLM profile that read it


@dataclass
class Reading:
    """An input item for the turn loop: a visitor's name, from a badge or typed.
    `confirmed` False = the fish asks first; True = tell the future at once."""
    name: str
    first_name: str
    look: str | None = None
    confirmed: bool = False


@dataclass
class Utterance:
    """An input item for the turn loop: a recording the page made with the phone's
    microphone and uploaded (`POST /utterance`). `path` is a temporary WAV the loop
    unlinks after transcribing; `hold_s` how long the target was held, `upload_s` how long
    the body took to arrive (together they stand for the turn's `rec` time)."""
    path: Path
    hold_s: float = 0.0
    upload_s: float = 0.0


_NAME_CHARS = re.compile(r"[^A-Za-zÀ-ÖØ-öø-ÿ' -]+")
_LETTERS = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")


def clean_name(text) -> str:
    """Letters (accents included), spaces, hyphens and apostrophes only, collapsed, in Title
    Case, at most 40 characters. Empty when nothing is left. Never starts with "-" (a text
    that opens with one is read by `loq` as an option)."""
    if not isinstance(text, str):
        return ""
    kept = _NAME_CHARS.sub(" ", text)
    words = [w.strip("-' ") for w in kept.split()]
    out = " ".join(w for w in words if w)
    out = _LETTERS.sub(lambda m: m.group()[:1].upper() + m.group()[1:].lower(), out)
    return out[:40].strip("-' ")


def first_word(name: str) -> str:
    return (name.split() or [""])[0]


_noted: set[str] = set()


def _once(note: str) -> None:
    """Say a skip once per process: a fish without a Claude key would otherwise repeat it for
    every badge."""
    if note not in _noted:
        _noted.add(note)
        print(f"[reading] {note}", file=sys.stderr, flush=True)


def _candidates(cfg: Config) -> list[tuple[str, dict]]:
    """The profiles that may read the badge, in the order they are tried: FISH_READING_PROFILE,
    or Claude and then the LLM profile. An unknown name is a set-up error."""
    names = list(cfg.reading.profiles) or ["claude", cfg.llm.profile]
    out: list[tuple[str, dict]] = []
    for name in names:
        if name not in LLM_PROFILES:
            raise cloud.CloudMisconfigured(
                f"FISH_READING_PROFILE={name!r}; choose from {list(LLM_PROFILES)}")
        if all(name != taken for taken, _ in out):
            out.append((name, LLM_PROFILES[name]))
    return out


def read_badge(jpeg: bytes, cfg: Config, *, want_look: bool) -> BadgeRead:
    """Read a badge photo. Raises ValueError for a non-JPEG or oversized body,
    `cloud.CloudUnavailable` when offline or when a call failed transiently and none other
    answered, `cloud.CloudMisconfigured` for a missing key or a rejected request."""
    if not isinstance(jpeg, (bytes, bytearray)) or jpeg[:3] != JPEG_MAGIC:
        raise ValueError("not a JPEG")
    if len(jpeg) > cfg.reading.max_image_bytes:
        raise ValueError("image too large")
    candidates = _candidates(cfg)
    ask = "Lee el gafete." + (" Describe también el look." if want_look
                              else " No describas a la persona: look es null.")
    problems: list[str] = []
    for name, profile in candidates:
        if not profile.get("vision"):                 # nothing is sent to a model that cannot see
            _once(f"{name} takes no images; skipped")
            problems.append(f"{name} takes no images")
    usable = [(name, profile) for name, profile in candidates if profile.get("vision")]
    if not usable:
        raise cloud.CloudMisconfigured(
            "no profile for the reading takes images (FISH_READING_PROFILE: luna or claude); "
            + "; ".join(problems))
    errors: list[Exception] = []
    for i, (name, profile) in enumerate(usable):
        last = i == len(usable) - 1
        try:
            return _read_one(name, profile, cfg, bytes(jpeg), ask, want_look, last=last)
        except cloud.CloudUnavailable as e:
            errors.append(e)
            problems.append(f"{name}: {e}")
            if not last:
                print(f"[reading] {name} unavailable ({e}); trying {usable[i + 1][0]}",
                      file=sys.stderr, flush=True)
        except cloud.CloudMisconfigured as e:
            errors.append(e)
            problems.append(f"{name}: {e}")
            if not last:
                _once(f"{name} not usable ({e}); trying {usable[i + 1][0]}")
    if len(errors) == 1 and len(problems) == 1:
        raise errors[0]                                # one profile, its own error
    transient = any(isinstance(e, cloud.CloudUnavailable) for e in errors)
    raise (cloud.CloudUnavailable if transient else cloud.CloudMisconfigured)("; ".join(problems))


def _read_one(name: str, profile: dict, cfg: Config, jpeg: bytes, ask: str, want_look: bool,
              *, last: bool) -> BadgeRead:
    """One profile's attempt. A profile that is not the last gets `fallback_after_s`, so a
    stuck one cannot use up the whole reading."""
    anthropic = profile.get("provider") == "anthropic"
    timeout_s = (cfg.reading.timeout_s if last
                 else min(cfg.reading.fallback_after_s, cfg.reading.timeout_s))
    if anthropic:
        from . import claude
        claude.ready(profile["api_key_env"])        # no key / no package: skipped, nothing recorded
    elif not profile.get("base_url") and not cloud.is_online():
        # The probe watches api.openai.com, so it only speaks for profiles hosted there.
        raise cloud.CloudUnavailable("offline")
    # For /debug: what the vision model was asked. Never the photo or its data URL.
    sent = {"profile": name, "model": profile["model"], "prompt": cfg.reading.badge_prompt,
            "ask": ask, "image_bytes": len(jpeg)}
    t0 = time.monotonic()
    try:
        if anthropic:
            resp = claude.ask_badge(profile, system=cfg.reading.badge_prompt, jpeg=jpeg, ask=ask,
                                    schema=BADGE_SCHEMA, timeout_s=timeout_s)
        else:
            client = cloud.client(profile["base_url"], profile["api_key_env"],
                                  timeout_s=timeout_s)
            data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
            resp = _ask_badge(client, profile, cfg, ask, data_url)
    except Exception as e:
        debug.model("vision", sent, error=e, seconds=time.monotonic() - t0)
        raise
    seconds = time.monotonic() - t0
    out = _parse_badge(resp, seconds, want_look)
    out.profile = name
    debug.model("vision", sent, seconds=seconds, tokens=out.tokens, found=out.found,
                confidence=out.confidence, name=out.full_name,
                name_for_speech=out.name_for_speech, look=out.look)
    print(f"[reading] badge {seconds:.1f}s tokens={out.tokens} found={str(out.found).lower()} "
          f"confidence={out.confidence} profile={name}", file=sys.stderr, flush=True)
    return out


def _ask_badge(client, profile: dict, cfg: Config, ask: str, data_url: str):
    with cloud.guard():
        return client.chat.completions.create(
            model=profile["model"],
            reasoning_effort="none",
            max_completion_tokens=300,
            store=False,
            response_format={"type": "json_schema",
                             "json_schema": {"name": "badge", "strict": True,
                                             "schema": BADGE_SCHEMA}},
            messages=[
                {"role": "system", "content": cfg.reading.badge_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": ask},
                    {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
                ]},
            ],
        )


def _parse_badge(resp, seconds: float, want_look: bool) -> BadgeRead:
    usage = getattr(resp, "usage", None)
    tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    choice = resp.choices[0]
    out = BadgeRead(seconds=seconds, tokens=tokens)
    refusal = getattr(choice.message, "refusal", None)
    if not refusal and getattr(choice, "finish_reason", None) != "length":
        try:
            raw = json.loads(choice.message.content or "")
        except (ValueError, TypeError):
            raw = None
        if isinstance(raw, dict):
            full = clean_name(raw.get("full_name"))
            speech = clean_name(raw.get("name_for_speech")) or first_word(full)
            look = raw.get("look") if want_look else None
            out.found = bool(raw.get("badge_found")) and bool(full or speech)
            out.full_name = full or speech
            out.given_names = clean_name(raw.get("given_names"))
            out.surnames = clean_name(raw.get("surnames"))
            out.name_for_speech = speech
            out.look = (str(look).strip()[:120] or None) if isinstance(look, str) else None
            conf = raw.get("confidence")
            out.confidence = conf if conf in ("high", "medium", "low") else "low"
    return out


# --- stand-ins for --echo (no model) -------------------------------------------------
def echo_question(name: str) -> str:
    return f"¿Tú eres {name}?"


def echo_fortune(name: str) -> str:
    return (f"{name}, veo en tu futuro… que todo lo que me digas hoy te lo voy a repetir.")
