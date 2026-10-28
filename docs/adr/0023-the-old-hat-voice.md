# 0023 — The old hat's voice: OpenAI ash, lower and slower, instead of Loquendo

**Status:** proposed · **Date:** 2026-10-28

## Context

Loquendo "Jorge" has been the board's voice since 2026-10-10: local, 0.75 s warm, but a fixed
voice, a licence guarded by a start-up probe (ADR 0013), and Wine. The hat needs an elegant, old
voice. Of the services with a key here, only OpenAI speaks Spanish: Anthropic's API has no speech
output, Groq's voices are English and Saudi Arabic. OpenAI's one text-to-speech model,
`gpt-4o-mini-tts`, is deprecated and ends on 2027-01-06; its newer voices are Realtime models over
a WebSocket. Three rounds of samples rendered on the board
([results](../results/2026-10-28-openai-voice-samples.md)): with an "ancient hat" instruction and
the WAV relabelled to 0.88 of its rate, ash was "great" on both `gpt-4o-mini-tts` and
`gpt-realtime-2.1`. The first renders a whole line in 1.4 to 2.8 s, the second needs 4.7 to 7.4 s
for a whole file, and the fish plays only finished files.

## Decision

1. **The board's voice is `gpt-4o-mini-tts`, voice `ash`, the hat's old-hat instruction, at
   `FISH_TTS_RATE_FACTOR=0.88`** (`FISH_TTS_BACKEND=openai`). The factor relabels the WAV header
   (24000 → 21120 Hz): lower and slower, the same samples, no resampling. It is part of the
   canned cache key when it is not 1.0.
2. **Every canned phrase is rendered once and kept** (the existing cache, filled at start-up in
   the background); only live replies call the service.
3. The laptop's defaults stay Loquendo (`FISH_TTS_BACKEND` defaults to `loq`).

4. **Amended the same day: pitch and tempo apart.** From a grid of 19 versions of his phrase
   made on the desktop (no new render), he picked 2 semitones lower at 0.72 tempo with the
   formants kept (`rubberband -F -p-2 -T0.72`). `FISH_TTS_PITCH_ST=-2` and `FISH_TTS_TEMPO=0.72`
   reshape every render, after any backend, through the `rubberband` program
   (`rubberband-cli`), and enter the cache key; they replace `FISH_TTS_RATE_FACTOR=0.88`, which
   goes back to 1.0. On the board since 2026-10-28 22:06 UTC: the 307 phrases rendered again in
   17 min 38 s with no failure ([results](../results/2026-10-28-openai-voice-on-the-board.md)).

## Consequences

- Offline the live replies have no voice; cached phrases still play, `no_signal` among them.
- About 1 to 2 s more per reply than Loquendo (measured per line, not yet in a turn).
- A phrase whose new render failed plays its newest older rendering, which may be Loquendo's,
  until the next prerender.
- Changing the instruction, the voice, the model, the factor, the pitch or the tempo renders all
  307 phrases again.
- The reshaping adds time to every live reply on the board's CPU (0.84 s for an 8 s line by
  hand; not measured in a turn), and a 0.72
  tempo makes every phrase about 1.4 times longer than its render.
- Without `rubberband` installed, a reshaping setting fails every render (the start-up line
  warns); the cached phrases still play.
- Before 2027-01-06 a Realtime backend replaces this one, or the voice changes again.
- Replaces the 2026-10-10 decision that the board's voice is Loquendo.
