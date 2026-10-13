# UNO Q: faster local speech-to-text, candidates — 2026-10-12

Run in the night of 2026-10-12 into the 13th; the board's clock is UTC, so its logs say the 13th.

Host: the board `segunda` (4 cores at 2.0 GHz, 3.6 GiB RAM, no fan), on a power bank,
`fish-brain` stopped during every timed run. Commit `0c78df5` plus the uncommitted
`transcribe_window` in `fish_brain/stt.py` and `tools/stt_bench.py`. Fish environment:
faster-whisper 1.2.1, ctranslate2 4.8.2, Python 3.13.5. Scratch environment
`~/stt_bench/.venv`: sherpa-onnx 1.13.8, moonshine-voice 0.1.5. Question: what gets a turn
well under 5 s with quality near `small`, which takes about 20 s today. No pass line for
quality was fixed beforehand.

Command, one per set and environment (`--runs 3` for the first table, `--runs 1` after):

    tools/stt_bench.py run --clips DIR --runs N --rest 20 --md --cand ... --cand ...
    tools/stt_bench.py split --clips DIR --model small --md

Seconds are the median per clip with the model loaded. WER is strict: lowercase, no
punctuation, accents kept ("Si" for "Sí" is an error), errors over reference words summed
over the set.

## Candidates

| Name here | `--cand` | What it is |
|---|---|---|
| `small` today | `fw:model=small` | faster-whisper as `Transcriber` calls it: beam 5, VAD, 30 s window |
| `small` light | `fw:model=small,beam=1,light=1` | beam 1, no timestamps, temperature 0 |
| `small` w10 | `fw-window:model=small,window=10` | `transcribe_window`: encoder window = clip + 3 s, at least 10 s; beam 1 |
| `base` w10 | `fw-window:model=base,window=10` | the same with `base` |
| `base-es` w10 | `fw-window:model=.../base-es,window=10` | `deepdml/whisper-base-es-mix-norm`, converted to CTranslate2 int8 on the laptop |
| Canary | `canary:dir=...` | `sherpa-onnx-nemo-canary-180m-flash-en-es-de-fr-int8`, language forced to `es` |
| Parakeet | `parakeet:dir=...` | `sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8`; it guesses the language |
| Moonshine small / tiny | `moonshine`, `moonshine:arch=tiny-streaming` | `small-streaming-es`, `tiny-streaming-es`; the package prints that both are under the non-commercial Moonshine Community License |

## Sets

| Set | Clips | How it was made |
|---|---|---|
| clean 9 | 9 (2.8 to 18.8 s) | Loquendo sentences rendered on the board, 1 s of silence each side |
| clean 29 | 29 | the 9 and 20 more |
| loop | 29 | clean 29 played through the USB speaker at 100 %, recorded by the RedOctane (it clipped) |
| voice | 36 (1.1 to 5.5 s) | Alexander, 18 Mexico City lines said twice in one take into the RedOctane, cut at the silences with 0.3 s around each line; the second round is faster |
| voice + 1 s | 36 | the same clips with 1 s of digital silence each side |

The remote's microphone was recorded in parallel for the voice take and the loop: exact
zeros in both, so it has no set.

## Speed and memory (clean 9, three runs per clip)

| Candidate | Load s | Median s | The 18.8 s clip | WER % | Peak MB |
|---|---|---|---|---|---|
| `small` today | 5.7 | 19.65 | 44.8 | 3.4 | 722 |
| `small` light | 5.7 | 17.25 | 27.9 | 2.6 | 717 |
| `base`, as `Transcriber` would call it | 3.5 | 6.50 | 33.6 | 5.1 | 508 |
| `small` w10 | 6.6 | 5.51 | 21.3 | 2.6 | 624 |
| `small`, window 15 s | 5.8 | 7.77 | 21.3 | 2.6 | 624 |
| `small`, window = clip + 5 s | 5.8 | 4.91 | 23.3 | 3.4 | 624 |
| `small` w10, `float32` | 6.0 | 9.88 | 39.3 | 3.4 | 1195 |
| `base` w10 | 3.8 | 1.74 | 7.6 | 3.4 | 336 |
| `base`, window 15 s, beam 5 | 3.6 | 3.13 | 13.2 | 3.4 | 347 |
| Canary | 9.7 | 2.61 | 27.5 | 0.9 | 609 |
| Parakeet | 19.9 | 3.35 | 14.1 | 6.0 | 1111 |
| Moonshine small | 1.4 | 4.31 | 27.1 | 4.3 | 466 |
| Moonshine tiny | 5.7 (with its download) | 1.56 | 9.2 | 3.4 | 243 |

The CPU was at 44 to 54 C before a candidate and 55 to 72 C after it (first run); throttling was not
checked.

Where a `small` turn goes (2.8 s clip, beam 1): features 0.009 s; encoder 13.84 s at 3000
frames, 5.28 s at 1500, 3.24 s at 1000; decoder 1.87, 1.12, 0.92 s. For `base`: encoder
4.13, 1.50, 0.92 s; decoder 0.59, 0.36, 0.29 s.

Seconds against clip length (clean 29, one run):

| Clip | Canary | Moonshine tiny | Moonshine small | `base` w10 | `small` w10 |
|---|---|---|---|---|---|
| 2.8 s | 1.19 | 0.74 | 1.61 | 1.32 | 4.26 |
| 4.3 s | 2.59 | 1.54 | 4.34 | 1.80 | 5.54 |
| 6.6 s | 4.51 | 2.64 | 8.07 | 2.40 | 7.27 |
| 8.6 s | 7.53 | not read | 10.51 | 2.80 | 9.10 |
| 18.8 s | 27.43 | 9.17 | 27.22 | 7.52 | 21.38 |

## Quality on Loquendo speech

| Candidate | clean 29: WER % | loop: WER % |
|---|---|---|
| Canary | 1.5 | 4.5 |
| Moonshine small | 2.3 | 3.0 |
| Moonshine tiny | 2.7 | 4.9 |
| `small` w10 | 4.9 | 6.1 |
| `small` light | not run | 5.7 |
| Parakeet | 5.7 | 6.1 |
| `base-es` w10 | 6.4 | 6.8 |
| `base` w10 | 7.2 | 8.3 |

## Quality on his voice

Short = the 13 clips under 2 s as cut, the same 13 in both sets, 40 reference words (of 36: "¿Qué onda, pez?", "Sí, simón.", "No, nel.",
"Órale, va.", "Adiós, cuídate." and the fast second-round names).

| Candidate | Set | Median s | WER % | Short WER % | Long WER % |
|---|---|---|---|---|---|
| `small` today | voice | 20.15 | 23.3 | 45 | 19 |
| Parakeet | voice | 2.16 | 18.0 | 58 | 11 |
| Parakeet | voice + 1 s | 3.53 | 18.4 | 52 | 12 |
| Canary | voice | 1.96 | 25.2 | 65 | 18 |
| Canary | voice + 1 s | 2.66 | 21.8 | 40 | 19 |
| Moonshine tiny | voice | 1.38 | 31.6 | 75 | 24 |
| Moonshine tiny | voice + 1 s | 1.68 | 22.9 | 58 | 17 |
| Moonshine small | voice | 4.60 | 36.8 | 102 | 25 |
| `small` w10, beam 5 | voice | 7.14 | 28.9 | 52 | 25 |
| `small` w10, beam 5 | voice + 1 s | 7.28 | 29.3 | 48 | 26 |
| `small` w10, beam 1, no guard | voice | 5.67 | 71.4 | 342 | 23 |
| `small` w10, beam 1, with the guard | voice | 5.73 | 30.1 | 68 | 23 |
| `base-es` w10 | voice | 2.00 | 37.2 | 60 | 33 |
| `base` w10 | voice | 1.74 | 40.2 | 55 | 38 |
| `base` w10, beam 5 | voice + 1 s | 2.43 | 38.3 | 68 | 33 |

Texts that show the differences:

| Line | `small` today | Canary (+ 1 s) | Parakeet | `small` w10 |
|---|---|---|---|---|
| ¿Qué onda, pez? | ¿Qué onda, pez? | Qué onda pez. | Can the pizza. | not read |
| Sí, simón. | Si, Simón. | Simón. | (nothing) | Si, Simon. |
| Órale, va. | Ahora le va. | Orabe le va. | (nothing) | Ahora le va |
| Chambeo en una oficina por Reforma, pero quiero poner mi negocio. | Chan veo en una oficina por reforma pero quiero proponer mi negocio | Chambeo en una oficina por reforma, pero quiero poner mi negocio. (voice set) | Chambeo en una oficina por reforma, pero quiero prom poner mi negocio. | Chan veo en una oficina por reforma pero quiero proponer mi negocio. |
| Está bien chido tu proyecto, carnal, ¿cuánto te tardaste en hacerlo? (second round) | Estoy en chido de tu proyecto Carnival, cuándo te tardas en hacerlo? | Stewinshoot Project O Karnah, ¿Cuándo te reseña hacerlo? (voice set) | Está bien chido tu proyecto, carnal. ¿Cuánto te tardaste en hacerlo? | Estoy enchido tu proyecto Karnal, ¿cuántas harás en hacerlo? |

## Reading

- The 30 s encoder window is the cost: 13.8 of about 17 s for `small`. `transcribe_window`
  brings `small` from 19.7 s to 5.5 s and `base` from 6.5 s to 1.7 s per clip.
- `float32` is slower than `int8` on this CPU and takes twice the memory.
- Loquendo speech does not separate the candidates (1.5 to 8 %); his voice does (18 to 40 %).
- On his voice with a second of silence around the clip, Canary (21.8 %, 2.7 s) and Moonshine
  tiny (22.9 %, 1.7 s) are level with `small` today (23.3 %, 20 s). Without that silence both
  lose the short answers.
- Parakeet is the best on full sentences (11 to 12 %). On short ones it is mid-table (58 %,
  52 % with the silence), and when it fails it gives nothing, or English ("Can the pizza.").
- The short window costs `small` about 6 points on his voice, and `base` and the Spanish
  `base` are far behind `small` there (37 to 40 %).
- With one pass and beam 1 the window path looped once ("No, nel." gave "no, no, no, ..."
  for 34 s). The guard added afterwards sends such a reply through the stock path: that
  clip then takes about 23 s and comes back right.
- Canary's time grows faster than the clip: 1.2 s for 2.8 s, 7.5 s for 8.6 s, 27 s for 18.8 s.
  Its model is made for clips under 40 s; the fish allows 45 s.

## After the choice

`FISH_STT_BACKEND=canary` was written the same night (`CanaryTranscriber`: 1 s of silence
around the clip, recordings over 8 s to `small` on the 10 s window). Outside the service,
fish idle, one call each: "Qué onda pez." 2.2 s, "Simón." 1.6 s, "No." 1.5 s, "Soy Alejandro
Gómez de la Narvarte." 3.3 s, "Chambeo en una oficina por reforma, pero quiero poner mi
negocio." 4.5 s; load 9.4 s. The window path gained the stock path's no-speech rule after
these runs; the tables above are from before it.

## Not measured

A real turn through the service; any candidate with the remote's microphone; other
speakers, noise, a crowd; `small` today on the voice + 1 s set; Parakeet or Canary with
keywords; the 45 s limit; thermal throttling; load time and memory with two models loaded.
The voice set is one person and 266 reference words, so two points are five words.
