# UNO Q: the burble and the fillers in real turns — 2026-10-13

Host: the board `segunda` under systemd (`fish-brain.service`), home Wi-Fi, speaker at 100 %,
no motor drivers attached. Commit `0c78df5` plus the uncommitted work of 2026-10-12 and 13
(Canary, the long route, ADR 0010). Start-up line: `stt=canary>groq llm=echo tts=loq`. He
spoke into the remote with its OK button held; the fish repeats what it heard (echo mode).
Level 5. The lines are from `journalctl --user -u fish-brain`.

Times in a `[turn]` line: `rec` the hold; `stt`, `tts` the stage's own seconds; `play_start`
from the start of the voice render to its first sample; `burble` from the end of the
recording to the burble's first sample; `fill` the time spent saying fillers.

## Fillers of 2.6 to 4.4 s, first at 2.5 s, one delay for the whole turn (18:09 UTC)

| Heard | `[turn]` line | Filler |
|---|---|---|
| "Hola, ¿nos quiere ustedes ver?" | `rec=2.0s stt=3.0s tts=0.6s play_start=0.7s burble=0.1s fill=3.2s` | "Espérame tantito, que el agua está turbia." |
| "Hola, ¿miss Goody Sing?" | `rec=2.1s stt=3.0s tts=0.6s play_start=0.6s burble=0.1s fill=3.6s` | "Qué interesante… déjame consultarlo con las aguas." |

The transcript was ready at 3.0 s, but the phrase had started at 2.5 s and ran to about 6 s:
the echo began about 6.5 s after release where 3.7 s was possible. What he said in these two
turns is not recorded, so the transcripts are not scored.

## Fillers of 0.9 to 1.9 s, each stage with the delay of its own (18:21 UTC)

| Heard | `[turn]` line | Filler | Release to echo |
|---|---|---|---|
| "Hola." | `rec=1.0s stt=1.8s tts=0.4s play_start=0.5s burble=0.2s` | none | about 2.3 s |
| "¿cómo estás?" | `rec=1.4s stt=2.0s tts=0.4s play_start=0.5s burble=0.1s` | none | about 2.5 s |
| "Hola pescadito." | `rec=1.7s stt=2.2s tts=0.5s play_start=0.6s burble=0.2s` | none | about 2.8 s |

Release to echo is `stt` + `play_start`, a sum, not a measurement. In the third turn the
voice render crossed the 2.5 s mark (2.2 s + 0.6 s) and no filler was said: the change of the
same day (ADR 0010, point 12). All three transcripts are what he said. His word: keep it.

## The phrases as Loquendo renders them

Measured from the cached WAVs on the board.

| | First version | Since 18:14 UTC |
|---|---|---|
| `filler_first_*` (8) | 2.6 to 4.4 s | 0.9 to 1.8 s |
| `filler_more_*` (6) | 2.7 to 3.9 s | 1.1 to 1.9 s |
| `timeout_stt_*` (2) | 3.5 and 4.2 s | unchanged |
| burbles (4, synthesized) | 0.33, 0.45, 0.45 and 0.58 s | |

Rendering the 16 phrases took Loquendo 13 s (`--prerender-canned`, daemon warm).

## Reading

- The burble starts 0.1 to 0.2 s after the end of the recording (five turns).
- Canary took 1.8 to 3.0 s for recordings of 1.0 to 2.1 s in the service, against 2.3 s
  (median, takes under 3 s) on the bench with the fish stopped
  ([takes](2026-10-13-unoq-stt-his-takes.md)).
- A long filler that starts just before the answer is ready costs its whole length; a
  short one costs about a second and a half.
- With the burble, the short fillers and the per-stage delay, a short turn is burble, then
  the reply 2.3 to 2.8 s after release.

## Found on the way

- At 16:40 UTC the remote's microphone did not start (`spa.alsa: set_hw_params: Connection
  timed out`; the source went `suspended -> error`), 40 minutes after its last use. The fish
  printed `PulseAudio: Unable to create stream: Timeout` and nothing more for 90 minutes: no
  turn, no line, no press taken. `/status` still answered `listening: true`.
- That process did not stop when asked at 18:09 UTC: `State 'stop-sigterm' timed out.
  Killing.` after the unit's 15 s. Every other stop that day took 4 to 5 s. A process killed
  this way sends no `STOP`. The cause was not traced (no stack was taken); the turn loop
  stuck inside the audio library after the failed start is the likely one.

## Not measured

A filler since the phrases were shortened (none fired in the three turns); a recording over
6 s through the service (the Groq route) with the burble; the apology at 12 s in a real
turn; the reading turn; LLM mode (`luna`); the conductor's lateness while an abandoned
transcription runs; whether the burble is heard in a noisy hall; the tail's flap and the
close pulse on a fish with drivers; the hotspot.
