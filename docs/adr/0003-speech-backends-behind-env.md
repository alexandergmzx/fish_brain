# 0003 — Speech backends chosen by environment

**Status:** accepted · **Date:** 2026-10-10

## Context

The laptop transcribes locally (faster-whisper) and speaks with Loquendo through `loq`. On
the board the `small` model takes 20 to 23 s per turn, `base` about 8 s and `tiny` about 4 s
([results](../results/2026-10-10-unoq-local-stt.md)). Loquendo there runs under x86
emulation.

## Decision

`FISH_STT_BACKEND` (`local`, `openai`, `groq`) and `FISH_TTS_BACKEND` (`loq`, `openai`). The
defaults are the laptop's. The board's `.env` selects the cloud ones. Every backend returns
the same thing to the rest of the program: text, or a plain WAV file.

Amendment, 2026-10-10: Loquendo was measured on the board at about 0.75 s per short sentence
with its daemon warm ([results](../results/2026-10-10-unoq-audio-and-loq.md)), so the board's
`.env` uses `loq` for the voice. Speech-to-text there stays on a cloud backend.

Amendment, 2026-10-12: the board transcribes locally. `FISH_STT_BACKEND=canary` is a third
kind of backend: NVIDIA Canary-180m-flash through sherpa-onnx, on the machine, chosen after
nine candidates were timed and scored on the board
([results](../results/2026-10-12-unoq-stt-candidates.md)): about 2.5 s for a short turn and
level with `small` (20 s) on the owner's recorded voice. It takes recordings up to 8 s; a
longer one goes to faster-whisper on a 10 s encoder window (`FISH_STT_WINDOW_S` gives the
`local` backend the same window). The cloud backends stay as switches.

Amendment, 2026-10-13: after 62 push-to-talk takes scored on every route
([results](../results/2026-10-13-unoq-stt-his-takes.md)) Canary's limit is 6 s, and a longer
recording goes to the services in `FISH_STT_LONG` while the board is online, falling to the
local window when none answers. For this week's tests that list is `groq` (free tier, under
a second). `gpt-transcribe` makes the fewest word errors (4 % against Groq's 10 % and
Canary's 21 %) and is held for the fair, whose routing is not decided.

## Consequences

- With a cloud STT backend the recording leaves the machine; before, only text did.
- OpenAI's speech models are announced to shut down on 2027-01-06: fine for the fair, to be
  replaced after it.
- OpenAI's terms ask that listeners are told the voice is generated.
- The canned-phrase cache is keyed by backend and voice, and falls back to any older rendering
  when it cannot render.
