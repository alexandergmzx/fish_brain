# 0007 — The reading: a badge photo becomes a name, the fish asks, then tells the future

**Status:** proposed; superseded on the page 2026-10-27 ([0019](0019-the-fortune-act.md)): the badge photo and the look tick left the operator page; the server side (`reading.py`, `/badge`, `/reading`) is parked, the typed name stays · **Date:** 2026-10-11

## Context

The fair wants a Sorting Hat moment: the fish greets a visitor by name and tells a future. The name
is on the visitor's fair badge; visitors are school children. In this repository "Sorting Hat"
names the second body (the Spin Master hat), so the feature is called **the reading** (`la
lectura`). The board's LLM profile `luna` (`gpt-6-luna`) takes image input, Structured Outputs and
`reasoning_effort="none"`; the laptop default `groq` is text only, and Groq's only vision model is a
preview. Since [0018](0018-claude-through-its-own-sdk.md) the `claude` profile takes images too. The page can take a photo over plain http (a file input with `capture`). The LLM history
in `llm.Conversation` is shared and bounded; `Speaker` drops speech that overlaps a phrase being
spoken. Loquendo renders a short sentence in about 0.75 s when warm.

## Decision

- The operator photographs the badge on the console; the page downscales it to a 1024 px JPEG and
  posts it to the board (`POST /badge`). The board relays it in memory to the first profile of
  `FISH_READING_PROFILE` that has a key and answers (empty = `claude`, then the LLM profile; `luna` on
  the board; [0018](0018-claude-through-its-own-sdk.md)) with a strict JSON schema
  (`full_name`, `given_names`, `surnames`, `name_for_speech`, `look`, `confidence`),
  `store=False`, reasoning off, image detail high, its own timeout. While the call runs the fish
  says a cached canned line (`reading_wait`).
- The name is never asserted: the fish asks "¿Tú eres X?" by voice. The question and its context
  are seeded into the LLM history and per-visitor rules are attached to the persona, so the
  visitor's spoken answer is a normal turn: "sí" gives the prophecy (three or four short sentences,
  kind and playful, a concrete absurd prediction about the rest of the day, no age, looks, health,
  money or anything sad), "no, me llamo Y" gives Y's. A name typed on the console skips the
  question. The history is reset at every new reading (a new visitor); the following voice turns
  know the name.
- An unreadable badge makes the fish say `reading_fail` ("¿Cómo te llamas?") and the spoken or
  typed name is taken instead.
- Badge-only framing by default. A "look" line (at most fifteen kind words on clothing, colours or
  accessories; never age, body, skin, health, mood or origin) is produced only when
  `FISH_READING_LOOK` is on and the operator ticks consent for that visitor after asking the
  accompanying adult.
- The photo exists only in a handler thread's local variable: never written to disk, never served,
  never in an event, never logged. The reading's own journal line carries timings and confidence,
  not the name; the fish's question and the `you>` lines of the following turns carry it as any
  turn does today.
- The welcome and goodbye phrases are replaced by tamer ones for the fair.

## Alternatives

- The operator confirms the name on the phone before the fish speaks: safe, but one more tap per
  visitor; the owner chose the voice question.
- One call that reads the badge and tells the future: a misread name spoken in public, and the
  photo in the history.
- OCR in the phone's browser (Tesseract.js, about 6 MB on first load, seconds per photo, weak on
  glossy badges) or on the board (seconds on four A53 cores, an apt install): the prophecy needs
  the cloud anyway.
- Groq's vision preview (about ten times the cost, a few readings a minute, models retired on
  short notice) and the Realtime API (Luna is not served there; it would replace the Loquendo
  voice).

## Consequences

- A badge photo leaves the machine to OpenAI (abuse logs up to 30 days, no training; zero data
  retention needs approval and is not in place). A Spanish sign at the stand says so. Since
  [0018](0018-claude-through-its-own-sdk.md) it goes to Anthropic first when `ANTHROPIC_API_KEY` is
  set, and to OpenAI only if that fails (Anthropic's retention terms are not recorded here): the
  sign's wording is his to change before the next show.
- About $0.0002 per reading (estimate; Luna's image token multiplier is not published and
  `usage.prompt_tokens` is logged to measure it).
- Loquendo's time on a four-sentence prophecy and its pronunciation of names are measured before
  the fair; the fish says the given name only.
- The speech-to-text keywords gain "sí, no, me llamo" so the one-word answer is heard.
- Since [ADR 0008](0008-the-phone-is-the-fishs-face.md) the default view is the fish's face for the visitor; the reading row is in the operator's sheet, behind the held shell.
