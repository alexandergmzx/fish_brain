# OpenAI voices for the hat, rendered on the board — 2026-10-28

Host: the UNO Q `segunda` over the home Wi-Fi, fish_brain at `ce4cf24`, `openai` 2.54.0 in the
board's venv (`websockets` for the Realtime runs from a temporary `--target` folder, removed after).
The fish stayed up; nothing played, no motor command. Question: which provider can give the hat an
elegant Spanish voice, and how long does a render take from the board?

Providers, read online the same day: Anthropic has no speech output in the API; Groq's TTS is
Orpheus in English and Saudi Arabic only; OpenAI's only text-to-speech model, `gpt-4o-mini-tts`,
is deprecated (shut down 2027-01-06), and its newer voices are Realtime models over a WebSocket.

    .venv/bin/python voice_samples.py OUT            # gpt-4o-mini-tts through tts.synthesize
    PYTHONPATH=rtlib .venv/bin/python voice_samples.py OUT --realtime

Three lines from `fortune_bank.py` (intro_otro, vision, suspense). "profesor" is the instruction
"Voz masculina madura y elegante, un profesor sabio y antiguo de un colegio de magia. Español
latinoamericano neutro, dicción cuidada, pausas solemnes, cálido y con un toque de misterio y de
humor seco. Ritmo pausado, nunca apresurado." `ash-actual` is the hat's instruction of today.
The Realtime model was also told to read the text word for word; "verbatim" compares its
transcript with the text.

| Model | Voice | Render s (intro / vision / suspense) | First audio s | Verbatim |
|---|---|---|---|---|
| gpt-4o-mini-tts | ash, today's instruction | 5.79 / 2.89 / 2.05 | (whole file) | — |
| gpt-4o-mini-tts | cedar, profesor | 1.98 / 2.12 / 2.29 | (whole file) | — |
| gpt-4o-mini-tts | marin, profesor | 2.26 / 2.05 / 2.12 | (whole file) | — |
| gpt-4o-mini-tts | ash, profesor | 2.03 / 2.52 / 1.42 | (whole file) | — |
| gpt-4o-mini-tts | onyx, profesor | 2.20 / 2.17 / 2.19 | (whole file) | — |
| gpt-realtime-2.1-mini | cedar | 8.08 / 4.69 / 4.40 | 4.67 / 1.50 / 1.65 | 3 of 3 |
| gpt-realtime-2.1-mini | marin | 5.02 / 5.42 / 3.99 | 1.57 / 2.09 / 1.36 | 3 of 3 |
| gpt-realtime-2.1 | cedar | 5.94 / 5.32 / 4.50 | 1.37 / 1.23 / 1.33 | 3 of 3 |
| gpt-realtime-2.1 | marin | 5.94 / 5.12 / 4.50 | 1.23 / 1.13 / 1.23 | 3 of 3 |

Audio lengths 5.5 to 15.1 s. The Realtime render time includes a new WebSocket per line; since
it streams, its first audio is the figure that could start playback sooner (the fish today plays
only a finished WAV). Loquendo for comparison: 0.75 s warm (2026-10-10).

## Rounds 2 and 3: the old hat

Same script, instruction "Eres un sombrero mágico viejísimo, de mil años … voz de anciano muy
mayor: grave, rasposa, un poco quebrada y temblorosa … habla despacio … nada de energía juvenil";
round 3 on his line "Hmm, difícil, muy difícil. Veo que tienes valor, y una mente muy valiosa, y
una sed. ¿No en Slytherin? ¿Estás seguro?". Each WAV also copied with its header rate × 0.88
(lower and slower, no resampling).

| Model | Voice | Render s (round 2: intro / vision / suspense; round 3) | First audio s | Verbatim |
|---|---|---|---|---|
| gpt-4o-mini-tts | ash | 6.69 / 2.55 / 1.79; 5.08 | (whole file) | — |
| gpt-4o-mini-tts | onyx | 2.23 / 2.08 / 1.45; 2.51 | (whole file) | — |
| gpt-4o-mini-tts | cedar | 3.38 / 2.00 / 1.48; 2.13 | (whole file) | — |
| gpt-4o-mini-tts | ballad | 2.22 / 2.42 / 1.79; 2.76 | (whole file) | — |
| gpt-realtime-2.1 | cedar | 7.36 / 5.94 / 4.71; 6.99 | 2.28 / 1.84 / 1.61; 2.48 | 4 of 4 |
| gpt-realtime-2.1 | ash | 6.14 / 6.35 / 4.81; 6.55 | 1.56 / 1.80 / 1.54; 1.95 | 4 of 4 |

His ear: ash at 0.88 is "great" on both `gpt-4o-mini-tts` and `gpt-realtime-2.1`.

Not measured: how the voices sound (his ear), offline behaviour, cost per line.
