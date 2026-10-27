# 0018 — Claude through its own SDK: a chat profile and the reading's first reader

**Status:** proposed · **Date:** 2026-10-26

## Context

The chat ([0004](0004-llm-profiles.md)) and the reading ([0007](0007-the-reading.md)) both spoke
only to OpenAI-compatible APIs through the `openai` SDK. He has an Anthropic API key coming
(2026-10-27) and credits, and wants Claude to do the AI jobs the hat needs that a Claude model
can do. Two jobs qualify: the chat turns and the badge photo. Anthropic has no speech-to-text or
text-to-speech, so those stay as they are.

## Decision

- Claude runs through the **Anthropic SDK** (`anthropic>=2.3,<3`, API version 2026-10-21) in
  `fish_brain/claude.py`, never through an OpenAI client or Anthropic's OpenAI-compatible
  endpoint. The package is imported when a Claude call is made, so a machine without it, or
  without a key, runs the rest of the fish untouched.
- `LLM_PROFILES` gains `claude` (Haiku 5.5, thinking off, effort low; his pick) and
  `claude-sonnet` (Sonnet 5.5, to try on badges), with `provider: anthropic`.
  `llm.make_conversation` picks the class by provider. **The chat default does not change**
  (`groq` in code, `luna` on the board): Claude is chosen with `FISH_LLM_PROFILE`, `--llm` or
  the `/debug` switch.
- **The reading tries `claude` first when `ANTHROPIC_API_KEY` is set**, then the LLM profile.
  `FISH_READING_PROFILE` is now an ordered list; a profile without a key or without image input
  (`groq`) is skipped without a call; one that fails gives way to the next, and every candidate
  but the last gets 7 s (`ReadingConfig.fallback_after_s`, an estimate), so a stuck one cannot use
  up the reading. With no Anthropic key the reading behaves as
  before. To keep a photo from ever reaching a second service, name one profile.
- Claude calls run with **no SDK retries** (`max_retries=0`): SDK 2.3.0 sleeps for any
  `Retry-After` with no cap, outside the read timeout ([checked](../results/2026-10-26-anthropic-sdk-offline-checks.md)),
  which could outlive the turn's 12 s. A failed call is the fallback line or the next reading
  candidate; the visitor presses again.
- No `temperature`, `top_p` or `top_k` is ever sent (API version 2026-10-21 refuses them). A
  setting a model rejects with a 400 that names it (`thinking`, `effort`, the output schema) is
  left out once and remembered, as `llm.py` does for OpenAI's.
- The key and the host are passed to the client explicitly: `ANTHROPIC_AUTH_TOKEN`, a login
  profile on disk and `ANTHROPIC_BASE_URL` can never decide which credential is used or where
  the key or a photo goes. An
  OpenAI client refuses `ANTHROPIC_API_KEY` and the OpenAI conversation refuses a Claude profile.
- A Claude failure never marks the internet offline: the connectivity probe watches
  api.openai.com. Claude has no "known offline" shortcut; a dead network costs the 3 s connect
  timeout and then the persona's fallback line, as groq's does.

## Alternatives

- Anthropic's OpenAI-compatible endpoint, so `llm.py` stayed as it was: it ignores the strict
  output schema and the SDK's own settings, and Anthropic documents it for comparison, not for
  production.
- Claude as the reading's only reader: leaves the fish with no reading when Claude is down.
- Claude as the chat default now: nothing is measured yet, and the key is not there.

## Consequences

- **The badge photo goes to Anthropic when the key is set, and to OpenAI only if Claude fails.**
  ADR 0007's consequence and the Spanish sign at the stand name OpenAI alone; the wording is his
  to change (name both, or pin `FISH_READING_PROFILE=claude`). Anthropic's retention terms for
  the API are not recorded here. The photo is still held only in memory.
- Nothing about Claude's speed or accuracy is measured: the numbers wait for the key
  (`ab.py` for the chat, `tools/hat_rehearse.py` for the hat, `--read-badge` for the badge). The
  token caps, `fallback_after_s` and the prices' source are marked in `config.py`; the prices are
  Anthropic's published rates of 2026-10-06.
- `import anthropic` takes 0.78 s on the desktop (`openai` 0.35 s; [measured](../results/2026-10-26-anthropic-sdk-offline-checks.md)) and more on the board's
  CPU (not measured); the first import logs its time (`[claude] sdk imported in …`). It happens inside the
  first Claude turn or badge reading.
- The `/debug` switch refuses a Claude profile when the key or the package is missing.

## Amendment, 2026-10-27

Haiku is the hat's model on the board, thinking at effort low with a 2000-token cap (ADR 0022). The first SDK import on the board: 7.0 and 17.4 s ([results](../results/2026-10-27-haiku-on-the-hat.md)).
