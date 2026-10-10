# 0003 — Speech backends chosen by environment

**Status:** accepted · **Date:** 2026-10-10

## Context

The laptop transcribes locally (faster-whisper) and speaks with Loquendo through `loq`. The
board's four A53 cores are estimated at 20 to 45 s per clip for the `small` model, and
Loquendo there depends on x86 emulation that has not been tried.

## Decision

`FISH_STT_BACKEND` (`local`, `openai`, `groq`) and `FISH_TTS_BACKEND` (`loq`, `openai`). The
defaults are the laptop's. The board's `.env` selects the cloud ones. Every backend returns
the same thing to the rest of the program: text, or a plain WAV file.

## Consequences

- With a cloud STT backend the recording leaves the machine; before, only text did.
- OpenAI's speech models are announced to shut down on 2027-01-06: fine for the fair, to be
  replaced after it.
- OpenAI's terms ask that listeners are told the voice is generated.
- The canned-phrase cache is keyed by backend and voice, and falls back to any older rendering
  when it cannot render.
