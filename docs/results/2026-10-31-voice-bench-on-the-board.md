# The hat's voice candidates timed on the board — 2026-10-31

Host: the UNO Q `segunda` on the home Wi-Fi. The fish was running, idle, on ash. fish_brain was at
`46545f7` plus the uncommitted `FISH_TTS_FORMANTS` / `FISH_TTS_ROOM` change and
`tools/voice_bench.py`. sox 14.4 and rubberband-cli 3.3.0 came from apt. Nothing was played, and
no motor command was sent.

**Question:** does Jorge with his pick's effects reach a playable WAV slower than ash? (His
rule: if so, he may move to a real-time ash.)

    FISH_PERSONA=hat .venv/bin/python tools/voice_bench.py --keep ~/voice_bench-2026-10-31/wav --runs 5 \
      --cand jorge-dry:backend=loq \
      --cand jorge-pick:backend=loq,pitch_st=-2,formants=shift,room=stone \
      --cand jorge-sox:backend=loq,sox_pitch=-200,room=stone \
      --cand ash:backend=openai \
      --cand ash-072:backend=openai,pitch_st=-2,tempo=0.72

`sox_pitch=-200` was the bench's own option in that run: a plain render, then one sox call with
`pitch -200` and the room. Since the same day the fish does that itself
(`formants=shift,room=stone`), and the bench option is gone. The fish's path, timed with 3
renders per line, gave 0.53 / 0.80 / 1.59 / 3.94 s, the same as jorge-sox. Its WAVs differ from
the bench's only by sox's dither: 77 dB below the signal on the vision line, and a
`voice_compare` shape of 0.8 (`~/voice_bench-2026-10-31/bench-fishpath.txt`).

Each line was rendered once cold, then 5 more times. "total" is the median seconds from the text
to a playable WAV. The lines are in `tools/voice_bench.py` (`LINES`); "reading" is a model reading
of about 60 words. The licence probe ran at start-up: `[voice] CLEAN (3.01 s)`.

| Candidate | Line | Audio s | Cold s | Render | Shape | Room | **Total** |
|---|---|---|---|---|---|---|---|
| jorge-dry | short | 1.61 | 0.53 | 0.53 | — | — | **0.53** |
| jorge-dry | medium | 3.24 | 0.76 | 0.73 | — | — | **0.73** |
| jorge-dry | vision | 8.15 | 1.45 | 1.45 | — | — | **1.45** |
| jorge-dry | reading | 22.48 | 3.68 | 3.53 | — | — | **3.53** |
| jorge-pick (rubberband + sox) | short | 1.61 | 0.68 | 0.52 | 0.12 | 0.03 | **0.67** |
| jorge-pick | medium | 3.24 | 1.02 | 0.73 | 0.21 | 0.05 | **0.99** |
| jorge-pick | vision | 8.15 | 2.06 | 1.47 | 0.49 | 0.10 | **2.06** |
| jorge-pick | reading | 22.48 | 5.11 | 3.56 | 1.33 | 0.24 | **5.13** |
| jorge-sox (one sox pass) | short | 1.61 | 0.58 | 0.51 | — | 0.04 | **0.55** |
| jorge-sox | medium | 3.24 | 0.78 | 0.73 | — | 0.07 | **0.80** |
| jorge-sox | vision | 8.15 | 1.60 | 1.45 | — | 0.15 | **1.59** |
| jorge-sox | reading | 22.48 | 3.94 | 3.54 | — | 0.38 | **3.93** |
| ash | short | 2.05 | 8.66 | 1.25 | — | — | **1.25** |
| ash | medium | 6.10 | 1.47 | 1.34 | — | — | **1.34** |
| ash | vision | 14.25 | 3.05 | 3.05 | — | — | **3.05** |
| ash | reading | 30.50 | 4.78 | 4.86 | — | — | **4.86** |
| ash-072 (the board today) | short | 4.79 | 1.41 | 1.20 | 0.49 | — | **1.78** |
| ash-072 | medium | 8.12 | 2.60 | 1.27 | 0.77 | — | **1.99** |
| ash-072 | vision | 16.60 | 3.94 | 2.33 | 2.01 | — | **4.23** |
| ash-072 | reading | 44.10 | 10.22 | 4.83 | 4.86 | — | **9.68** |

- **jorge-sox is faster than ash on every line**: 0.55 against 1.25 s for the short line, 3.93
  against 4.86 s for the reading. It is also faster than today's board voice on every line, by
  1.2 to 5.8 s.
- **jorge-pick is faster than ash up to the vision line** (2.06 against 3.05 s). On the reading
  it is 0.27 s slower (5.13 against 4.86 s), because rubberband costs 0.06 s per second of
  audio.
- **ash's first call was 8.66 s.** That is a cold connection; Jorge's cold renders were within
  0.2 s of their medians.
- **sox's `pitch` costs 0.017 s per second of audio** and rubberband 0.06 s; sox's room alone
  costs 0.011 s.
- ash speaks the same text in 1.3 to 1.9 times Jorge's audio length.
- For comparison, real-time ash's first audio was 1.5 to 1.95 s on 2026-10-28
  ([results](2026-10-28-openai-voice-samples.md)). The fish plays only finished WAVs, so that
  figure needs a streaming player first.

Kept: the last WAV of each cell and `bench.txt`, on the board in `~/voice_bench-2026-10-31/` and
on the desktop in `~/fish_brain_canned/voice_bench-2026-10-31/`, outside git.

Not measured: a live turn's `tts=`, his ear on jorge-sox against his pick (sent 2026-10-31,
`~/fish_brain_canned/samples-2026-10-29/r9/`), and the cost per line of ash.
