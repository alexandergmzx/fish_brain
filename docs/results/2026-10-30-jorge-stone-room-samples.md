# Jorge in a stone room: rounds 7 and 8 of the hat's voice — 2026-10-29/30

fish_brain at `46545f7` (`sorting-hat`). Every sample is the `fortune_vision_1` line:
"Sueñas así porque tienes mucha imaginación, y guardas cosas que no le cuentas a nadie. Lo veo
clarito, y no me lo tienes que confirmar." Nothing played on the board; no motor command.

All samples, raw WAVs and the scripts are copied to `~/fish_brain_canned/samples-2026-10-29/`
on the desktop (outside git): `r4-raw/`, `r7/`, `r8/`.

## Round 7: three effects × three voices × three pitches (desktop)

Sources:
- ash from `gpt-4o-mini-tts` with the labelled instruction (Voz / Tono / Ritmo / Acento).
- Jorge and Carlos from `loq -v <voice> -o … -- "$T"` on the board, 16 kHz, no prefix.

Pitch moved with the formants (ffmpeg's filter), tempo 1:

    ffmpeg -i IN -af "rubberband=pitch=0.890899:tempo=1:formant=shifted:pitchq=quality" OUT   # −2 st (−1 st: 0.943874)
    sox IN OUT highpass 80 equalizer 140 1q +3 <effect> gain -n -1

| Effect | sox chain |
|---|---|
| 1, doubling + hall | `chorus 0.8 0.85 28 0.45 0.2 1.5 -t reverb 30 50 90 100 25 -4` |
| 2, hall | `reverb 30 50 90 100 25 -4` |
| 3, stone room | `reverb 25 60 25 100 5 -3` |

Median pitch by autocorrelation (`tools/voice_compare.py`):

| Voice | Length | 0 st | −1 st | −2 st |
|---|---|---|---|---|
| ash | 12.05 s | 114 Hz | 109 Hz | 103 Hz |
| Jorge | 8.15 s | 105 Hz | 99 Hz | 95 Hz |
| Carlos | 9.19 s | 89 Hz | 87 Hz | 81 Hz |

**His pick (2026-10-30): `jorge_p-2_3_stone_room`.** Ash was "too slow", though more personal,
and costs money over time.

## Round 8: Loquendo's own controls on the board

The Loquendo TTS 7 User's Guide on the board (`LTTS7/doc/User's Guide/*.chm`, "Prosodic Controls"
and "Sound effects") lists three controls:
- `\pitch±Nst`: semitones.
- `\timbre=0..100`: a formant frequency shift, 50 the default. Its `st` and `%` forms are "Not yet
  implemented".
- `\reverb=gain,delay`: it persists across prompts until changed.

The commands:

    L=~/.local/bin/loq
    $L -r 22050 -o t${tb}_r${rv}.wav -- "\language=SpanishMx \reverb=$rv \pitch-2st \timbre=$tb $T"   # tb 50 45 40 35; rv 0,0 20,40 30,70
    $L -r 22050 -o plain.wav -- "\language=SpanishMx \reverb=0,0 $T"
    tools/voice_compare.py jorge_p-2_3_stone_room.wav plain.wav t*.wav

`-r 22050` was ignored: the files are 16 kHz, the rate of the running daemon.

The comparison metrics:
- Pitch is the median, by autocorrelation.
- A pause is an inner silence of 0.15 s or more.
- Shape is the MFCC distance after DTW alignment; lower is closer.
- Colour is the mean log-mel difference.

| Sample | Length | Pauses | Pitch | Shape | Colour |
|---|---|---|---|---|---|
| **The pick** (round 7) | 8.15 s | 0.49 s | 98 Hz | — | — |
| `jorge_p-1_3_stone_room` | 8.15 s | 0.49 s | 101 Hz | 9.90 | 1.10 |
| `jorge_p-2_2_hall` | 8.15 s | 0.47 s | 99 Hz | 10.00 | 0.61 |
| timbre 50, reverb 30,70 | 8.52 s | 0.48 s | 93 Hz | 15.94 | 1.54 |
| timbre 50, reverb 20,40 | 8.52 s | 0.49 s | 94 Hz | 16.27 | 1.67 |
| plain Jorge | 8.14 s | 0.50 s | 105 Hz | 16.84 | 2.23 |
| timbre 50, reverb 0,0 | 8.52 s | 0.49 s | 93 Hz | 17.69 | 2.11 |
| timbre 45, 40, 35 (any reverb) | 6.82 s | **none** | 87–91 Hz | 16.62–19.35 | 1.90–2.62 |

- **The tags do not reach the pick.** The best tagged sample scores 15.9, against 16.8 for
  untouched Jorge. Two processings of one render score about 10.
- **Any `\timbre` other than 50 deletes the sentence pause.** The line is 20 % shorter and every
  word is still there (faster-whisper `small`). He heard it as broken spacing.
- **The prefix does not explain the gap.** Plain Jorge with `\language=SpanishMx` against the
  round 4 render without it: shape 6.25, colour 0.04.

The reverb tag changes the signal: the difference between the files is 6.4 to 6.6 dB above the
signal, at the same length.

**Cost of the tags.** On the board, with the daemon warm, five runs each of "Hola, esta es una
prueba de la voz del sombrero.":

| Prefix | Seconds |
|---|---|
| `\language=SpanishMx \reverb=0,0 ` | 0.72 0.68 0.73 0.74 0.73 |
| `… \reverb=30,70 \pitch-2st \timbre=40 ` | 0.93 0.96 0.95 0.97 0.95 |

Not measured: the processing chain of the pick on the board (next: the bench), and his ear on
round 8 beyond "some samples don't respect the spaces timing".
