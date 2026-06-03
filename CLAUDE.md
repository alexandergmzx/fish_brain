# fish_brain — conversational Big Mouth Billy Bass

## Overview
A two-way voice assistant that talks back through a hacked Big Mouth Billy Bass.
**Push-to-talk → local speech-to-text → cloud LLM → local TTS → the fish speaks the reply**
with a mouth synced to the audio and random neck/tail gestures.

This is the **host "brain"** on a Linux Mint PC. It is the third piece of a 3-repo system
and is the only one that orchestrates the others:

| Repo | Role | This repo touches it via |
|------|------|--------------------------|
| `~/Development/Big_mouth` | ESP32-S3 firmware — thin serial motor executor | **serial port** (115200 baud) |
| `~/Development/loquen_hack` | `loq` TTS engine (Loquendo "Jorge", MX Spanish) | **`loq` CLI** (`loq -o out.wav`) |
| `~/Development/fish_brain` | **this repo** — STT + LLM + audio analysis + motion | — |

The other two repos stay **untouched**; this repo only calls them.

## Pipeline (one conversation turn)
```
[hold key] → mic record → local STT (faster-whisper) → user text
          → OpenAI chat (history + fish persona) → reply text
          → loq -o reply.wav → loudness envelope → mouth track
                                                  + random neck/tail gestures
          → play audio + stream serial on ONE monotonic clock → fish speaks
          → back to listening
```
Per reply we **pre-compute** the whole command schedule from the rendered WAV, then play
audio and stream commands together — robust sync, simple code.

## Design decisions (locked)
- **STT**: local (faster-whisper, CPU). Only text leaves the machine.
- **LLM**: cloud (OpenAI). Key in `.env` (`OPENAI_API_KEY`), never committed.
- **TTS**: local `loq -o FILE.wav "texto"` — rendered **silently**; we own playback for
  sync (do NOT use `loq -p`). Warm daemon ≈ 50 ms.
- **Turn trigger**: push-to-talk (hold a key to record, release to send).
- **Mouth sync**: **proportional loudness** → immediate `MOUTH <n>` PWM.
- **Language**: Spanish (matches the Jorge voice) for STT + the LLM persona.

## Serial protocol (the firmware is the executor)
Commands are **`\n`-terminated, case-insensitive (firmware upper-cases), 115200 baud**,
PWM range **−255..255**. Convention: **+ = open/out, − = close/return.**
- `MOUTH <n>` — immediate signed PWM, **holds until the next command**. This is what we
  stream for live mouth sync. (Do NOT use `MOUTH OPEN`/`CLOSE`: those fire a one-shot
  `pulseMs` then auto-stop — wrong for streaming.)
- `MOUTH 0` — rest/closed.
- `NECK 180 500 -180 400`, `TAIL 200 300 -200 300` — **timed gesture chains** the firmware
  sequences and auto-stops; used for random neck/tail motion.
- `STOP` / `S` — stop all motors. **Always sent on exit/error.**

Safety: the firmware has **no current sensing**; a 5 s `MAX_RUN_TIME` watchdog is the only
guard. So the host MUST send `STOP`/`MOUTH 0` on shutdown, Ctrl-C, and exceptions.
The firmware **echoes every command** back — the host **ignores inbound serial**.

## Code layout
```
fish_brain/
  config.py        # serial port+baud, mouth PWM range, threshold, smoothing, rate cap,
                   #   SYNC_OFFSET_MS, gesture params, STT model+language, LLM model+prompt
  ptt.py           # push-to-talk: hold key -> record mic (sounddevice input)
  stt.py           # transcribe WAV -> text (faster-whisper)
  llm.py           # OpenAI chat client + bounded history + fish persona
  conversation.py  # turn loop: PTT -> STT -> LLM -> speak; clean teardown
  tts.py           # synthesize(text) -> Path  (wraps `loq -o`)
  envelope.py      # WAV -> RMS frames -> normalized proportional MOUTH <n> track
  gestures.py      # gesture_track(dur) -> random neck/tail timed-chain commands
  serial_link.py   # pyserial writer: +\n, rate-limit, ignore inbound, STOP-on-exit; dry-run mock
  conductor.py     # merge mouth+gesture tracks; play audio; stream on one clock
  speak.py         # speak(text) + perform_wav(wav): tts -> envelope+gestures -> conductor
  canned.py        # pre-rendered fixed phrases (welcome/goodbye/…), cached WAVs by text-hash
  viz.py           # VizServer: stdlib HTTP/SSE server for the on-screen browser fish
  web/             # index.html + fish.js + fish.css — drawn canvas Billy Bass (browser)
  app.py           # entry point: build engine, run conversation loop
```

## Canned phrases
Fixed phrases live in `config.CannedConfig.phrases` (name → Spanish text). `canned.py`
renders each via `loq` once and caches it under `~/.cache/fish_brain/canned/` keyed by a
hash of the text, so replays are instant and editing the wording transparently re-renders.
`welcome` plays at startup and `goodbye` on teardown (incl. Ctrl-C). Playback reuses
`speak.perform_wav`, so canned phrases drive the mouth/gestures (and the on-screen fish)
identically to live speech.

## On-screen fish (`--viz`)
A browser fallback/debug view of what the fish is saying — useful when the physical fish
misbehaves. `viz.py` runs a stdlib `ThreadingHTTPServer` (daemon thread): it serves `web/`,
streams a `speak` event per reply over **Server-Sent Events** (`/events`) carrying the audio
URL + NECK/TAIL gesture timing, and serves the spoken WAV bytes at `/audio/<token>`. The
browser (`fish.js`) plays + analyzes the audio itself (Web Audio `AnalyserNode`, like the
original `gui/` sketch) to drive the **mouth**, and tweens **neck/tail** from the gesture
events — so it animates even in `--dry-run` (no hardware). All motion rides springs
(overshoot/settle) with idle life (breathing, blinks, eye saccades, bubbles) so it reads as
a character, not a meter. The host also plays the audio (double audio is intentional).

## Run
```bash
# from ~/Development/fish_brain, with the venv active and .env set
python -m fish_brain.app --dry-run --text   # no fish, no mic: type a turn, prints commands
python -m fish_brain.app --dry-run          # no fish: push-to-talk, prints commands
python -m fish_brain.app                     # full: real serial + mic + fish
python -m fish_brain.app --dry-run --text --viz   # software-only fish in the browser
```
- `--dry-run` — mock serial: prints `MOUTH/NECK/TAIL` instead of driving motors.
- `--text` — type the user turn instead of using the mic (skips STT).
- `--viz` / `--viz-port N` — serve the on-screen browser fish (default port 8723).
- `--say-canned NAME` — speak one canned phrase and exit; `--list-canned` lists names.

## Dependencies
`pyserial`, `numpy`, `sounddevice` (needs system `libportaudio2`), `faster-whisper`,
`openai`, `python-dotenv`. Serial access needs the user in the `dialout` group.
The on-screen fish (`--viz`) uses only the Python stdlib (`http.server`) — no extra deps.

## Calibration
Use the firmware's live tuning over a plain serial monitor — `SET <CH> OPEN|CLOSE|PULSE
<value>` and manual `MOUTH <n>` — to find good PWM ranges, then copy them into `config.py`.
Tune `SYNC_OFFSET_MS` by ear (covers audio output latency + motor mechanical lag).

## Build order (incremental, each step testable)
1. Scaffold + `config.py` + `serial_link.py` (with `--dry-run`); manual `MOUTH 180`/`MOUTH 0`.
2. Speak engine: `tts.py` → `envelope.py` → `conductor.py` → `speak.py`.
3. `gestures.py`, layered into the conductor.
4. Conversation: `llm.py` → `stt.py` + `ptt.py` → `conversation.py` / `app.py`.
