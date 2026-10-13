# UNO Q: every speech-to-text route on his push-to-talk takes — 2026-10-13

Host: the board `segunda`, home Wi-Fi, `fish-brain` stopped. Commit `0c78df5` plus the
uncommitted Canary backend and `tools/stt_bench.py`. Question: with clips cut by the remote's
button, as the fish gets them, which route for which recording length.

## The takes

Recorded by him with `tools/stt_bench.py record --remote "name:XING WEI"` (hold OK, three
takes a line, left arrow to drop one), both microphones at once. He spoke into the remote;
the RedOctane stood behind it and has more gain.

| | Takes | Level (RMS) |
|---|---|---|
| RedOctane | 63 | 0.04 to 0.085 |
| The remote's microphone | 63, the same presses | 0.010 to 0.022 (the fish's silence gate is 0.005) |

Lines 1 to 18 three takes each (0.6 to 4.2 s); line 19 (lines 5 to 8 in one press) three
takes of about 7 s; line 20 two of 11 s; line 21 one of 17.6 s; line 22 three of 25 s.
Take `voz01_1` is left out of every figure: it was a trial press where he said another
sentence, which every route wrote down the same way. 918 reference words remain. The
remote's OK button sent `BTN_LEFT` (its mouse mode) throughout.

## Routes

    tools/stt_bench.py run --clips ~/stt_bench/clips/sesion/redoctane --runs 1 --md --cand ...

| Name | `--cand` | Notes |
|---|---|---|
| Canary, as the fish | `fish:backend=canary` | the fish's transcriber from its `.env`: 1 s of silence around the clip, recordings over 8 s to `small` on the 10 s window |
| `small` w10 | `fw-window:model=small,window=10` | |
| Groq turbo, Groq large | `cloud:profile=groq`, `...,model=whisper-large-v3`, with `--gap 4` | free tier, one call every 4 s: no call refused in 192 |
| OpenAI | `cloud:profile=openai` | `gpt-transcribe`; no call refused in 64 |

## RedOctane: median seconds and WER by recording length

| Route | 0-3 s (46) | 3-6 s (8) | 6-10 s (3) | 10-20 s (3) | 20+ s (3) | WER up to 8 s | WER over 8 s | WER all |
|---|---|---|---|---|---|---|---|---|
| Canary, as the fish | 2.28 s | 4.28 s | 9.11 s | 16.56 s | 43.10 s | 21.4 % | 18.4 % | 19.9 % |
| `small` w10 | 5.69 s | 7.08 s | 9.71 s | 15.66 s | 41.52 s | 28.8 % | 18.4 % | 23.6 % |
| Groq turbo | 0.40 s | 0.45 s | 0.50 s | 0.81 s | 0.89 s | 13.0 % | 6.6 % | 9.8 % |
| Groq large | 0.40 s | 0.61 s | 1.02 s | 1.08 s | 1.95 s | 13.0 % | 6.8 % | 9.9 % |
| OpenAI | 0.62 s | 0.67 s | 0.82 s | 0.96 s | 1.52 s | 4.5 % | 4.2 % | 4.4 % |

The seconds are with `voz01_1` in; the WER without it. First call of a process: Canary
3.0 s, the online ones 6.8 to 8.0 s.

## The remote's microphone, the same presses

| Route | 0-3 s | 3-6 s | 6-10 s | 10-20 s | 20+ s | WER up to 8 s | WER over 8 s | WER all |
|---|---|---|---|---|---|---|---|---|
| Canary, as the fish | 2.27 s | 4.45 s | 8.74 s | 16.10 s | 42.05 s | 24.5 % | 20.8 % | 22.7 % |
| Groq turbo | 0.40 s | 0.57 s | 0.71 s | 1.12 s | 1.72 s | 14.7 % | 11.8 % | 13.3 % |

## Texts (first take of the line, RedOctane)

| Line | Canary | `small` w10 | Groq turbo | OpenAI |
|---|---|---|---|---|
| Sí, simón. | Simón. | Si, Simon. | Sí, Simón. | Sí, Simón. |
| No, nel. | No. | NONEL | No, no. | No, Nel. |
| Órale, va. | Hora le va. | ¿Odala? | ¡Órale va! | Órale va. |
| ¿Voy a pasar el semestre o ya valió? | Voy a pasar el semestre o ya alió. | Voy a pasar el semestre hoyo, hoyo. | Voy a pasar el semestre o ya valió? | ¿Voy a pasar el semestre o ya valió? |
| Adiós, cuídate. | Adiós, cuídate. | Adios, cuídate. | Adiós, cuídate. | Adiós, cuídate. |

## Reading

- Up to 8 s, Canary is the quickest local route (2.3 s for the usual take) at 21 % word
  errors; `small` on the window is slower and worse (29 %) on these fast, tightly cut takes.
- Over 8 s the local route takes 16 to 43 s. Groq turbo takes under a second at 6.6 %, OpenAI
  1 to 1.5 s at 4.2 %.
- The two Groq models are level on words; turbo is quicker on the long takes.
- Groq's free tier refused nothing at one call every 4 s; the refusals of 2026-10-12 came
  from the bench calling twice a second.
- The remote's microphone costs 2 to 5 points against the RedOctane on the same presses,
  and its level is two to four times the silence gate: a softer voice may be gated out.
- The 7 s takes are the local route's worst case under the limit: 9 s on Canary.

## The choice (his word, 2026-10-13)

Canary's limit by word errors over all the takes, Canary below it and Groq turbo above:
0 s 9.8 %, 2 s 11.4 %, 3 s 12.2 %, 5 s 13.0 %, 8 s 14.1 %; the longest wait in the set is
1.0, 3.2, 3.9, 4.9 and 9.4 s. No take lies between 4.2 and 6.8 s. For this week's tests:
Canary up to 6 s, Groq turbo above (`FISH_STT_LONG=groq`), `small` on the window when the
board is offline or Groq does not answer. `gpt-transcribe` is held for the fair.

## Not measured

A turn through the service; the hotspot; Groq's hourly and daily limits over a fair day;
other speakers; noise. One run per take, so the seconds carry no spread.
