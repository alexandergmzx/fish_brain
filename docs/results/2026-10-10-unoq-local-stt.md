# UNO Q: local speech-to-text speed — 2026-10-10

Host: the board `segunda` (4 cores at 2.0 GHz, 3.6 GiB RAM, no fan), on a power bank.
Commit `9a877dd` plus the dependency bounds. faster-whisper 1.2.1, ctranslate2 4.8.2,
PyAV 17.1.0, Python 3.13.5, `compute_type="int8"`. No pass line was fixed beforehand; the
question was whether any local model is fast enough for conversation.

Clips, both the sentence "Hola, soy un pez parlante y estoy probando la bocina.":

| Clip | Length | How it was made |
|---|---|---|
| mic | 6.48 s | Loquendo through the USB speaker, recorded by the RedOctane microphone (1 s of silence before, 2 s after) |
| clean | 3.43 s | The Loquendo WAV itself |

## fish_brain's settings today (`Transcriber`: `language="es"`, `vad_filter=True`, default beam of 5)

Seconds per clip, model already loaded, two runs each.

| Model | Load | mic | clean | Text from the mic clip |
|---|---|---|---|---|
| `tiny` | 3.6 s | 4.84, 4.62 | 4.79, 4.74 | "Soy un pés parlante y estoy probando la vocina." |
| `base` | 9.7 s | 7.91, 7.81 | 8.12, 9.25 | "Soy un pez parlante y estoy probando la bocina." |
| `small` | 21.9 s | 22.85, 22.82 | 23.04, 23.12 | "Hola, soy Unpez Parlante y estoy probando la bocina." |

The time barely depends on the clip length: the model works on a fixed 30 s window.

## Lighter decoding (mic clip, best of two runs, `cpu_threads=4`)

| Model | Beam 5 | Beam 1 | Beam 1, no timestamps, no previous-text conditioning, temperature 0 |
|---|---|---|---|
| `tiny` | 4.43 s | 3.49 s | 3.42 s |
| `base` | 7.85 s | 8.41 s | 8.24 s |
| `small` | 22.94 s | 19.41 s | 19.28 s |

## Reading

- `small`, the laptop default, is about 20 s per turn on the board: unusable for conversation.
- `tiny` is 3.5 to 4.8 s and makes spelling-level mistakes ("pés", "vocina"); `base` is about
  8 s and got the sentence right apart from dropping "Hola" on the mic clip.
- Beam 1 helps `tiny` and `small` by 15 to 20 % and did nothing for `base`.
- The CPU went from 44 °C to 59 °C over the runs; throttling was not checked and may be part
  of the `base` beam-1 figure.

Not measured: a cloud backend over the hotspot (no key on the board yet), a person speaking,
noise, Moonshine or whisper.cpp.

## Found on the way

`pip install -e .` on the board pulled PyAV 19 and the OpenAI SDK 3.x. faster-whisper 1.2.1
fails with PyAV 18 or newer (`open() got an unexpected keyword argument 'metadata_errors'`).
`pyproject.toml` now requires `av<18` and `openai>=2.41,<3`.
