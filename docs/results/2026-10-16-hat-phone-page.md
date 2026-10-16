# The hat's visit and the operator's phone page on the board — 2026-10-16

Host: the board `segunda` on the home Wi-Fi (192.168.1.114); fish_brain `sorting-hat` `605e2e2`
synced from the laptop and the service restarted (`version.changed_since_start` false). Persona
hat, gate mouth (`50-hat.conf`), LLM mode (`echo.conf.off`, his), `stt=canary>groq llm=luna
tts=loq`. **Nothing wired to the motor driver (his word): level 5 without motors. Nothing here
shows motion.** The page was watched from the laptop's headless Chromium at 412×915 over CDP,
not from his phone.

## The act: rehearsal (no voice, no motors)

`.venv/bin/python tools/hat_rehearse.py tools/hat_visitors.txt` on the board, `luna`:

| Run | Commit | Visits with a house | House said aloud | Spoken tags | Seconds per call (median / max) | Cost |
|---|---|---|---|---|---|---|
| Afternoon, his doc's prompt | `ee94304` | 12 of 12 | 9 of 12 | 0 | 1.9 / 4.8 | $0.0058 |
| Evening, the drafted verdict | `605e2e2` (before the variety line) | 13 of 13 | 13 of 13 | 0 | 1.9 / 4.8 | $0.0074 |

Left over in the evening run: readings of three sentences (8 replies), one verdict of five
sentences, and the predictions repeat themselves (hours around "las tres y veintidós", cardboard
ducks and squirrels); the line asking for a new hour and animal each time was added after it and
is not measured.

## A whole visit on the board

`POST /visit`, `POST /cues {edad: niño, color: azul, impresion: curioso}`, then three
`POST /utterance` WAVs rendered with `loq` on the board ("Me llamo Ana.", "Un libro, claro.",
"Primero investigo.", 1.8 s each), each sent once `/status` said listening:

| Turn | Heard | `[turn]` | Visit |
|---|---|---|---|
| Nuevo visitante | — | `visit=greeting said=True` | new #1, stage 1 said from the canned WAV |
| 1 | "Mellam Oana." | `rec=1.8s stt=1.9s llm=4.7s tts=1.6s play_start=1.7s burble=0.1s fill=2.0s link=ok` | etapa 2/4 |
| 2 | "Un libro claro." | `rec=1.8s stt=1.9s llm=1.9s tts=1.9s play_start=2.0s burble=0.1s link=ok` | etapa 3/4 |
| 3 | "Primero Investigó." | `rec=1.8s stt=2.1s llm=1.8s tts=2.5s play_start=2.6s burble=0.1s link=ok` | etapa 4/4 casa=Ravenclaw fin |

The verdict: "Oana, eres curiosa, pero también sabes observar antes de actuar. ¡RAVENCLAW!
Podrías llegar muy lejos, y Ravenclaw te ayudará a lograrlo. Hoy, a las tres y veintidós, una
ardilla de peluche te hará guardia: guiñale un ojo y salúdala." Speech-to-text heard Loquendo's
"Me llamo Ana" as "Mellam Oana", and the hat used that name. The whole visit, with the script's
own pauses, took 66 s from the greeting to the end of the verdict.

## The page (`/`, the operator's)

| Check | Result |
|---|---|
| `/` over http and `https://…:8724/` | 200, `src="/debug.js"`; `/face` serves the old face (`src="/fish.js"`) |
| During the visit | The band followed it: SPEAKING (greeting) → THINKING · hearing → THINKING · model (2.0 to 8.2 s) → SPEAKING, the stage chip 1/4 → 4/4 → "Verdict: Ravenclaw"; the mouth open in the speaking frames; MOUTH and NECK lamps lit and "motor: 26 / 81 / 170 / 224 lines" after the phrases; the house's colour and "¡Ravenclaw!" after the verdict. No exception or console error |
| Over http | Chips "http: no screen lock" and "screen may sleep (http)", as designed |
| `GET /debug/state` | 33,507 bytes in 0.075 s |
| First stream replay, 4 s | 168,695 bytes, the same with `tail=1500` (the rings held fewer records than that after the restart) |
| Stream places | Four open, a fifth stranger refused with 503 |
| Board load after the visit | 0.39 0.39 0.20 |

Not shown: his phone (Chrome on the S24 Ultra, the wake lock over https, the phone-microphone
switch, haptics); the badge photo through the new page; a stream replaced by its own page id on
the board (covered by `tests/test_debug.py`).
