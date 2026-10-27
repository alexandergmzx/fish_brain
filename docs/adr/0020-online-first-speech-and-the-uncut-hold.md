# 0020 — Online first, Canary offline; the hold is never cut short, silence ends it

**Status:** proposed · **Date:** 2026-10-27

## Context

On 2026-10-27, with the board driven from the phone alone, a visitor's answer "ir por mi
novia" came back from Canary as "Herria por mi novela" (board journal, 15:07 UTC; the line is
not in a results file). It is the error rate measured on his own takes on 2026-10-13
([results](../results/2026-10-13-unoq-stt-his-takes.md)):

| Route (RedOctane takes) | Median time, takes of 0-3 s | Word errors, takes up to 8 s |
|---|---|---|
| `openai` (`gpt-transcribe`) | 0.62 s | 4.5 % |
| `groq` (turbo) | 0.40 s | 13.0 % |
| `canary` | 2.28 s | 21.4 % |

`gpt-transcribe` was "held for the fair" then ([0003](0003-speech-backends-behind-env.md),
amendment of 2026-10-13); the fair failed and no show date is set. His word (2026-10-27):
`gpt-transcribe` "for now, connected to the network".

Two more things surfaced the same day:

- **The clamp.** With `FISH_SHOW` on, the conversation clamped every hold to 5.5 s
  (`ShowConfig.max_record_s`) and emptied `FISH_STT_LONG` so no answer took the slow local
  route; the fortune lifted the cap to 10 s for its dream question and put the long route
  back ([0015](0015-the-scripted-visit.md) point 6, [0019](0019-the-fortune-act.md) point 4).
  An adult's answer is a sentence: a hold inside an act was cut at 5.5 s.
- **The transcriber bug.** Canary's transcriber was built after the show emptied
  `long_online` and kept its own copy of the routes; nothing rebuilt it when the fortune
  restored them. The fortune's 10 s dream on 2026-10-27 went to the local model, not to Groq:
  the "to Groq" in that run's [results](../results/2026-10-27-fortune-on-the-board.md) was
  the act's own print, not evidence of the route.

## Decision

1. **Online first.** `FISH_STT_ONLINE` (a list like `FISH_STT_LONG`; empty by default) names
   the services every recording goes to first while the board is online; the board's is
   `openai`. Canary hears the recording when the board is offline, or when no listed service
   answers within its read limit (`ONLINE_TIMEOUT_S`, 4 s, an estimate; the connect limit
   stays 3 s), refuses, or has no key. A failed service rests 60 s, for the whole run when its
   key is missing or rejected, and the journal says so once.
2. **The long route stays the second chance.** A recording over `canary_long_s` (6 s,
   unchanged) goes next to `FISH_STT_LONG` (a name already tried is not asked twice), then to
   the local model on the 10 s window.
3. **The routes are read at every recording**, from the configuration, never copied at build
   time. `/debug` → Switches → `stt_online` (`openai`, `groq`, `off`) takes effect at the
   next recording, nothing rebuilt; refused without the service's key.
4. **No act clamps the hold.** `ShowConfig.max_record_s`, `FortuneConfig.dream_record_s` and
   the lift and restore of the fortune's dream are gone. The cap is `FISH_PTT_MAX_S` alone
   (45 s on the board); with the show on, the speech routes stay as configured.
5. **Silence ends a hold.** `FISH_PTT_SILENCE_END_S` (0 = off, the default; 10 on the board)
   replaces the unused `FISH_PTT_PAUSE_S`: once nothing reached `FISH_PTT_QUIET_RMS` (0.04)
   for that long, counted from the start and from the last sound, the recording ends, the
   button is cleared and the clip is answered. The board's recorders and the phone's
   microphone follow the same values; the upload says how the hold ended
   (`X-Fish-End: silence|limit|release`). The level is not `silence_rms` (0.005): the remote's
   room floor is 0.01 to 0.03 (measured 2026-10-12).

## Alternatives

- **Canary first, the service on a miss**: a miss cannot be seen from the transcript ("Herria
  por mi novela" is well-formed Spanish).
- **`gpt-transcribe` as the backend, no local fallback**: offline the scripted visit would be
  deaf; Canary keeps it hearing.
- **Groq first**: quicker (0.40 s) but three times the word errors of `gpt-transcribe` on his
  takes.
- **Keep the act's cap and raise it**: any fixed cap cuts someone; the silence end ends a hold
  that nobody releases.

## Consequences

- Every recording leaves the board while it is online (before: only those over 6 s, to Groq).
- The board needs `OPENAI_API_KEY`, which it already holds for `luna` and the voice fallback.
- The route uses `gpt-transcribe`; the 2027-02-26 shutdown announced for OpenAI's older
  transcription models ([`BRAINTIP.md`](../BRAINTIP.md), read 2026-10-10) does not name it,
  and no end date for it is recorded here. The route is a list, so another service takes its
  place by name.
- Measured on the board 2026-10-27 ([results](../results/2026-10-27-stt-online-first.md)):
  `gpt-transcribe` on the remote's 63 takes, 0.72 s median and 6.0 % word errors (Groq turbo
  0.41 s and 14.0 % on the same takes); through `CanaryTranscriber`, 0.8 to 1.1 s a clip and
  3.39 s for the first call after the warm-up. Not measured yet: the online route in a real
  turn, the fall-back with the data cut mid-hold, the silence end from the remote and from
  the phone, a 30 s hold online and offline.

### Known limits (not changed by this record)

- **Offline, a clip over about 10 s times out.** Canary took 16.6 s and `small` 15.7 s on
  10-20 s takes ([results](../results/2026-10-13-unoq-stt-his-takes.md)), past the turn's
  12 s budget; the abandoned worker then stalls the next turn's transcription stage
  (`conversation.py`, `_await` and `_wait_for`). Trimming an offline clip to its first
  6 s is open, his call.
- **The first online call of a process is cold**: 6.8 to 8.0 s on 2026-10-13, past the 4 s
  limit, so it falls to Canary. `/debug/cloud` (the warm-up button) makes that call; an
  automatic warm call at start-up is open.
- **The phone's level after Chrome's gain control is not measured**; the page uses the same
  0.04 until the `[utt]` lines say otherwise.
