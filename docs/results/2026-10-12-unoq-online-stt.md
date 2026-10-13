# UNO Q: online speech-to-text against the local routes, by recording length — 2026-10-12

Run in the night of 2026-10-12 into the 13th on the board `segunda`, home Wi-Fi, `fish-brain`
running and idle (Canary and `small` loaded in it). Commit `0c78df5` plus the uncommitted
Canary backend and `tools/stt_bench.py` with its `cloud` candidate, which sends the same
request as `fish_brain.stt.CloudTranscriber`. Question: from what recording length is an
online service the better route. The local numbers for short clips are in
[2026-10-12-unoq-stt-candidates.md](2026-10-12-unoq-stt-candidates.md).

    tools/stt_bench.py run --clips DIR --runs 3 --rest 5 --md --cand cloud:profile=openai \
        --cand cloud:profile=groq --cand cloud:profile=groq,model=whisper-large-v3
    tools/stt_bench.py run --clips ~/stt_bench/clips/voz-long --runs 1 --rest 20 --md \
        --cand canary:dir=... --cand fw-window:model=small,window=10

Seconds are the median per clip; WER as in the candidates file (strict, accents kept).

| Set | Clips | What it is |
|---|---|---|
| voice + 1 s | 36 (3 to 7.5 s) | his 36 lines, 1 s of silence each side |
| voice long | 10 (11.2 to 47.4 s) | his lines joined with 0.6 s pauses: about 10, 15, 20, 30 and 45 s, two of each |
| clean 29 | 29 (2.8 to 18.8 s) | Loquendo sentences |

## OpenAI `gpt-transcribe` (`FISH_STT_BACKEND=openai`)

| Set | Median s | Worst s | WER % | Calls failed |
|---|---|---|---|---|
| voice + 1 s | 0.61 | 0.82 | 6.4 | 0 of 108 |
| voice long | 1.38 | 2.25 | 5.6 | 0 of 30 |
| clean 29 | 0.71 | 0.92 | 2.7 | 0 of 87 |

By recording length, his voice: 3 to 6 s 0.61 s (7 %, 34 clips); 6 to 10 s 0.82 s (0 %, 2);
10 to 20 s 1.07 s (9 %, 4); over 20 s 1.58 s (5 %, 6). The 47.4 s clip took 1.74 s with 6
errors in 116 words. The first call of each process took 6.7 to 9.6 s (it includes loading
the client library and opening the connection). One clip came back empty: the fast "No, nel."
of the second round.

Texts: "¿Qué onda, pez?", "Sí, Simón.", "Chambeo en una oficina por reforma, pero quiero
poner mi negocio.", "No manches, ¿a poco sí hablas?", "Está bien chido tu proyecto, carnal.
¿Cuánto tardaste en hacerlo?" (one word missing); "Órale, va." came back as "Ahora le va.",
as from every local model.

## The local routes on the long clips (one run each, the fish idle beside them)

| Recording | `small` on the 10 s window | Canary |
|---|---|---|
| 11.2 s | 10.0 s | 8.6 s |
| 12.1 s | 11.9 s | 57.4 s |
| 14.8 s | 14.7 s | 13.9 s |
| 17.5 s | 21.1 s | 31.2 s |
| 22.9 s | 27.0 s | 33.8 s |
| 22.6 s | 29.6 s | 40.9 s |
| 34.0 s | 63.6 s | 76.0 s |
| 32.1 s | 68.4 s | 79.5 s |
| 47.4 s | 77.1 s | 228.9 s |
| 46.4 s | 81.8 s | 215.4 s |

WER over the ten: `small` on the window 21.3 %, Canary 88.8 % (it is not made for this
length; the fish sends it nothing over 8 s). Over about 27 s of speech the window path
hands the clip to the stock call, which is why the 30 s and 45 s rows jump.

## Groq (`whisper-large-v3-turbo`, `whisper-large-v3`)

Most calls were refused with HTTP 429 ("Rate limit reached ... service tier `on_demand`"):
for each model 79 of 108 on the voice set, 9 of 30 on the long set and 59 of 87 on the clean
set, with the three candidates run back to back and 5 s between them. The bench sends a
call every half second, which a fair would not; which of Groq's limits was hit (requests
per minute or audio seconds per hour) was not read from the full message.

The calls that were answered took 0.41 s (short clips) to about 1 s (long ones). WER on the
answered clips only, so not comparable with the tables above: voice + 1 s turbo 11.4 % and
large-v3 20.9 % (9 clips each); voice long 14.6 % and 11.8 % (7 and 6 clips); clean 2.2 %
and 2.4 % (8 clips each).

## Reading

- On this network `gpt-transcribe` is quicker than every local route at every length
  measured, and far more accurate on his voice: 0.6 s and 6.4 % against Canary's 2.7 s and
  21.8 % on the same 36 clips, and 1.4 s and 5.6 % against 28 s and 21.3 % on the long ones.
  There is no length below which the local route wins on time or on words.
- Its time barely grows with the recording: 0.6 s at 4 s, 1.7 s at 47 s.
- The local long route is worse than estimated: about a second per second up to 15 s, then
  more, and over a minute from 30 s.
- Groq is the quickest per answered call and was unusable in this test because of its rate
  limit; its accuracy here rests on too few clips to rank it.

## Research (web, 2026-10-12, not called live)

- `gpt-6-luna` takes text and images only; it cannot be sent audio. OpenAI's audio chat
  models (`gpt-audio-1.5`) are a different model at $32 per million audio input tokens.
- xAI has a speech-to-text API: `POST https://api.x.ai/v1/stt`, model
  `grok-voice-transcribe-2.0`, `language=es`, $0.10 per audio hour. It is not shaped like
  OpenAI's endpoint, so `CloudTranscriber` cannot reach it without its own request. Not
  tested: there is no xAI key on the board.
- `gpt-transcribe` costs $0.0045 per minute; Groq turbo $0.04 per audio hour with 10 s billed
  per request at least.

## Not measured

The fair's hotspot or any weaker network; a real turn through the service with the cloud
route for long recordings; xAI; Groq without its rate limit; what the cloud returns for
noise or silence; other speakers. The long clips are his short lines joined, not one long
sentence spoken in one breath.
