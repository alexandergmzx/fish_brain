"""The reading (ADR 0007): a badge photo becomes a name; the fish asks, then tells the future.

`read_badge()` relays a JPEG, in memory, to the vision model of the profile named by
`FISH_READING_PROFILE` (empty = the LLM profile; `luna` is the one with image input) with a
strict JSON schema, reasoning off and `store=False`. The photo is never written, logged or
kept: it lives in the caller's local variable. The result's names are cleaned so what the
fish says is letters only, and the journal line carries timings and confidence, never a name.

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

from . import cloud
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


def _profile(cfg: Config) -> dict:
    name = cfg.reading.profile or cfg.llm.profile
    if name not in LLM_PROFILES:
        raise cloud.CloudMisconfigured(
            f"FISH_READING_PROFILE={name!r}; choose one of {list(LLM_PROFILES)}")
    return LLM_PROFILES[name]


def read_badge(jpeg: bytes, cfg: Config, *, want_look: bool) -> BadgeRead:
    """Read a badge photo. Raises ValueError for a non-JPEG or oversized body,
    `cloud.CloudUnavailable` when offline or the call fails transiently,
    `cloud.CloudMisconfigured` for a missing key or a rejected request."""
    if not isinstance(jpeg, (bytes, bytearray)) or jpeg[:3] != JPEG_MAGIC:
        raise ValueError("not a JPEG")
    if len(jpeg) > cfg.reading.max_image_bytes:
        raise ValueError("image too large")
    profile = _profile(cfg)
    if not cloud.is_online():
        raise cloud.CloudUnavailable("offline")
    client = cloud.client(profile["base_url"], profile["api_key_env"],
                          timeout_s=cfg.reading.timeout_s)
    ask = "Lee el gafete." + (" Describe también el look." if want_look
                              else " No describas a la persona: look es null.")
    data_url = "data:image/jpeg;base64," + base64.b64encode(bytes(jpeg)).decode("ascii")
    t0 = time.monotonic()
    with cloud.guard():
        resp = client.chat.completions.create(
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
    seconds = time.monotonic() - t0
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
    print(f"[reading] badge {seconds:.1f}s tokens={tokens} found={str(out.found).lower()} "
          f"confidence={out.confidence}", file=sys.stderr, flush=True)
    return out


# --- stand-ins for --echo (no model) -------------------------------------------------
def echo_question(name: str) -> str:
    return f"¿Tú eres {name}?"


def echo_fortune(name: str) -> str:
    return (f"{name}, veo en tu futuro… que todo lo que me digas hoy te lo voy a repetir.")
