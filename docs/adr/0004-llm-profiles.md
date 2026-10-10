# 0004 — LLM profiles

**Status:** accepted · **Date:** 2026-10-10

## Context

Replies must come back fast enough for speech. Two candidates speak the same API:
GPT-OSS-20B on Groq and GPT-6 Luna on OpenAI.

## Decision

`LLM_PROFILES` in `config.py` holds one entry per service (URL, key variable, model,
reasoning effort, temperature, prices); `FISH_LLM_PROFILE` picks one. The code default is
`groq`; the board's `.env` sets `luna`. `python -m fish_brain.ab` compares them blind.

Luna runs with reasoning effort `none`. On OpenAI's reasoning models temperature is only
accepted at that effort, so it is left out at any other.

## Consequences

- Each profile needs its own key (`GROQ_API_KEY`, `OPENAI_API_KEY`).
- An API error makes the fish say a fallback line; the failed turn is not added to history.
