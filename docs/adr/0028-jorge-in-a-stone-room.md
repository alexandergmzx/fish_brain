# 0028 — The hat's voice: Loquendo Jorge, 2 semitones lower through sox, in a stone room

**Status:** proposed · **Date:** 2026-10-31 · Replaces [0023](0023-the-old-hat-voice.md)

## Context

From 2026-10-28 the board spoke with OpenAI's `gpt-4o-mini-tts` ash, reshaped through rubberband
to 2 semitones lower at a 0.72 tempo with the formants kept (ADR 0023). He found it "too too
slow". It is also paid for per line, and the service ends on 2027-01-06.

Rounds 4 to 7 of samples were made from one fortune line
([results](../results/2026-10-30-jorge-stone-room-samples.md)). They covered ash, Jorge and
Carlos at 0, −1 and −2 semitones with the formants moved along. Each had three effects chosen
from the research: doubling plus hall, a hall, and a stone room. His pick was
`jorge_p-2_3_stone_room`. Ash felt more personal but too slow.

Two ways of doing the effect inside Loquendo were tried and dropped:
- **Loquendo's own `\pitch`, `\timbre` and `\reverb` tags (round 8).** They did not come close to
  the pick. Any `\timbre` other than 50 also deletes the pause between sentences.
- **Doing it in `loq_winer`.** He allowed it, but the cost it would save is one process start.

The bench on the board ([results](../results/2026-10-31-voice-bench-on-the-board.md)) measured
one sox pass doing `pitch -200` and the room at 0.017 s per second of audio. Rubberband took
0.06 s. He heard both on the four bench lines and chose sox.

## Decision

1. **The board's voice is Loquendo Jorge** (`FISH_TTS_BACKEND=loq`) **2 semitones lower with the
   formants moved too, in the stone room** (`FISH_TTS_PITCH_ST=-2`, `FISH_TTS_FORMANTS=shift`,
   `FISH_TTS_ROOM=stone`), at his own speed.
2. **The effect runs in fish_brain after the render, as one sox pass:**
   - sox's `pitch`;
   - `tempo` if one is set;
   - the room's chain from `TTS_ROOMS`.

   It runs after the licence guard, which therefore still times the raw render. Each setting is
   part of the canned cache key.
3. `FISH_TTS_FORMANTS=keep`, the default, keeps the rubberband `-F` path for a lower voice that
   stays the same voice (ash's settings of ADR 0023). The laptop with no environment set is
   unchanged.
4. `loq_winer` is unchanged.

## Alternatives

| Option | Why not |
|---|---|
| Ash at a faster tempo | It stays paid, ends on 2027-01-06, and was 1.25 to 4.86 s a line against Jorge's 0.55 to 3.93 s |
| Real-time ash | Its first audio took 1.5 to 1.95 s on 2026-10-28, and it needs a streaming player the fish does not have |
| Loquendo's tags | They do not sound like the pick, and `\timbre` breaks the pauses |
| Rubberband without `-F`, then sox | The pick's exact chain; 0.1 to 1.2 s slower a line and not preferred by ear |
| The effect inside `loq_winer` | It would save about 10 ms a line (estimate), would put sox into a portable wrapper, and the guard and the cache key would still live here |

## Consequences

- Wine, the daemon and the licence guard (ADR 0013) are back on the board. The guard's probe
  passed at 3.01 s on 2026-10-31.
- Live replies have a voice offline again, and the voice costs nothing per line.
- sox must be on the board (`sudo apt update && sudo apt install sox`). Without it, every render
  fails: the start-up line warns, and the cached phrases still play.
- Changing the pitch, the formants, the room or the Loquendo prefix renders all the canned
  phrases again.
- The reverb tail is in the WAV that drives the mouth. Not measured on a body (level 4).
- `sox` dithers its 16-bit output, so two renders of one line are not byte-identical (the
  difference is 77 dB below the signal).
