# fish_brain

Conversational **Big Mouth Billy Bass**. You push-to-talk, the PC transcribes you
locally, a cloud LLM writes a reply, and the fish **speaks it** — mouth synced to the
audio, with random neck/tail gestures.

```
[hold key] → mic → local STT (faster-whisper) → user text
          → OpenAI chat (persona + history) → reply text
          → loq TTS → loudness envelope → mouth track + random gestures
          → play audio + stream serial on one clock → 🐟 talks
```

This is the host "brain". It drives two other repos on this machine without modifying
them: the **ESP32-S3 firmware** (`~/Development/Big_mouth`, over serial) and the **`loq`**
TTS engine (`~/Development/loq_winer`, via its CLI). See [Architecture](#architecture) below.

## Architecture

`fish_brain` is the third piece of a 3-repo system, and the only one that orchestrates the
others. The other two are left untouched — this repo only calls them:

| Repo | Role | Touched via |
|------|------|-------------|
| `~/Development/Big_mouth` | ESP32-S3 firmware — a thin serial motor executor | **serial port**, 115200 baud |
| `~/Development/loq_winer` | `loq` TTS engine (Loquendo "Jorge", MX Spanish) | **`loq` CLI** (`loq -o out.wav`) |
| `~/Development/fish_brain` | **this repo** — STT + LLM + audio analysis + motion | — |

### Pipeline (one conversation turn)

```
[hold key] → mic record → local STT (faster-whisper) → user text
          → OpenAI chat (history + fish persona) → reply text
          → loq -o reply.wav → loudness envelope → mouth track
                                                  + random neck/tail gestures
          → play audio + stream serial on ONE monotonic clock → fish speaks
          → back to listening
```

Per reply we **pre-compute** the whole motor-command schedule from the rendered WAV, then
play the audio and stream the commands together on one clock. That makes A/V sync robust and
the code simple.

### Design decisions (deliberate)

- **STT is local** (faster-whisper, CPU): only your transcribed *text* ever leaves the machine.
- **LLM is cloud** (OpenAI): API key in `.env` (`OPENAI_API_KEY`), never committed.
- **TTS is local** (`loq`): we render to a WAV *silently* (`loq -o FILE.wav`, **not** `loq -p`)
  so the host owns playback and can keep it in sync with the streamed motor commands. A warm
  daemon makes each phrase ~0.5 s.
- **Turn trigger** is push-to-talk (hold a key/button to record, release to send).
- **Mouth sync**: loudness → openness fraction (0..1) → **attack-time `MOUTH <pwm> <ms>`
  pulses** (openness is set by how *long* the motor runs at full drive, not by held PWM).
- **Language is Spanish** throughout (matches the Jorge voice) — STT and the LLM persona.

### Serial protocol (the firmware is the executor)

Commands are `\n`-terminated, case-insensitive (the firmware upper-cases), 115200 baud, with
a PWM range of **−255..255**. Convention: **+ = open/out, − = close/return.**

- `MOUTH <pwm> <ms>` — a single **timed pulse**: drive `pwm` for `ms`, then auto-stop. This is
  what we stream for mouth sync.
- `MOUTH <n>` — immediate signed PWM, held until the next command. Used for manual calibration
  (e.g. `MOUTH 238` to find full-open travel); not streamed during speech.
- `MOUTH 0` — rest / closed.
- `NECK 180 500 -180 400`, `TAIL 200 300 -200 300` — **timed gesture chains** the firmware
  sequences and auto-stops; used for the random neck/tail motion.
- `STOP` / `S` — stop all motors. **Always sent on exit/error.**

The firmware **echoes every command** back; the host **ignores all inbound serial**. There is
**no current sensing** on the hardware — a 5 s `MAX_RUN_TIME` watchdog is the only guard — so
the host must send `STOP`/`MOUTH 0` on shutdown, Ctrl-C, and exceptions (it does; see *Safety*).

### Code layout

```
fish_brain/
  config.py        # all tunables: serial port/baud, mouth PWMs + attack-time curves,
                   #   thresholds/smoothing/rate cap, sync offset, gesture params,
                   #   STT model+language, LLM model+persona prompt
  ptt.py           # push-to-talk: hold key -> record mic (sounddevice)
  stt.py           # transcribe WAV -> text (faster-whisper, VAD + silence blocklist)
  llm.py           # OpenAI chat client + bounded history + fish persona
  conversation.py  # the turn loop: PTT -> STT -> LLM -> speak; clean teardown
  tts.py           # synthesize(text) -> WAV path (wraps `loq -o`)
  envelope.py      # WAV -> RMS frames -> openness track -> MOUTH <pwm> <ms> pulses
  gestures.py      # gesture_track(dur) -> random neck/tail timed-chain commands
  serial_link.py   # pyserial writer: append \n, rate-limit, ignore inbound,
                   #   STOP-on-exit; plus a dry-run mock
  conductor.py     # merge mouth+gesture tracks; play audio; stream on one clock
  speak.py         # speak(text) / perform_wav(wav): tts -> envelope+gestures -> conductor
  canned.py        # pre-rendered fixed phrases (welcome/goodbye), cached by text-hash
  viz.py           # VizServer: stdlib HTTP/SSE server for the on-screen browser fish
  web/             # index.html + fish.js + fish.css — the canvas Billy Bass in the browser
  app.py           # entry point: parse flags, build the engine, run the loop
```

### Canned phrases

Fixed phrases live in `config.CannedConfig.phrases` (name → Spanish text). `canned.py` renders
each via `loq` once and caches it under `~/.cache/fish_brain/canned/`, keyed by a hash of the
text — so replays are instant and editing the wording transparently re-renders. `welcome` plays
at startup and `goodbye` on teardown (including Ctrl-C). Playback reuses `speak.perform_wav`, so
canned phrases drive the mouth/gestures (and the on-screen fish) exactly like live speech.
List them with `--list-canned`; play one and exit with `--say-canned NAME`.

### On-screen fish (`--viz`)

A browser fallback/debug view of what the fish is saying — handy when the physical fish
misbehaves or for an audience. `viz.py` runs a stdlib `ThreadingHTTPServer` (no extra deps): it
serves `web/`, streams a `speak` event per reply over **Server-Sent Events** (`/events`)
carrying the audio URL + the precomputed **mouth loudness envelope** + NECK/TAIL gesture timing,
and serves the spoken WAV at `/audio/<token>`. The browser (`fish.js`) runs a **sprite state
machine**: each frame it picks one whole-fish composite PNG for the current `(neck, mouth, tail)`
state — mouth `0..3` driven from the sent envelope on the browser's own spring-smoothed clock,
neck `Rest|Out` and tail `Rest|Flap` from whether a gesture is firing. Driving the mouth from the
envelope (not live audio) means it animates even with sound off / autoplay blocked. Because the
greeting plays before any browser connects, `viz.py` **replays the last `speak` event** to a
browser that connects within 30 s.

The page also has a **mic picker + level meter** (recording is host-side, so the browser can't
use its own devices): `GET /mics` enumerates host input devices and `POST /mic` selects one. It
prefers **PipeWire/Pulse sources** (stable names) over raw `sounddevice` indices (unstable, and a
raw `hw:` device can capture silence). A **transcript panel** shows the last STT (🗣️) and reply
(🐟). With `--viz` the turn is triggered by an on-screen **hold-to-talk** button (or the browser
spacebar) instead of the keyboard — it POSTs `/ptt`, and `conversation` records via the web path.
An empty/too-short recording just **re-listens**; only `salir`/EOF/Ctrl-C quits.

## Setup

```bash
cd ~/Development/fish_brain

# system audio lib for the mic + playback
sudo apt install libportaudio2

python3 -m venv .venv && source .venv/bin/activate
pip install -e .                 # installs deps from pyproject.toml
# or, for the exact pinned versions this was built/tested with:
#   pip install -r requirements.txt

cp .env.example .env             # then put your OPENAI_API_KEY in .env

# optional: fetch the speech model now (~0.5 GB for "small") so the first turn isn't slow
python -m fish_brain.app --prefetch-stt
```

### TTS engine path (this laptop)

`loq` (the Loquendo engine) must be installed in Wine and on your `PATH`. On **this Linux
Mint laptop** Loquendo lives under `Program Files` (not the usual `Program Files (x86)`),
so `loq` needs to be told where to look or it reports *"synthesis failed (voice 'Jorge')"*
and `loq --list` shows no voices. This is already handled for `fish_brain` via `.env`:

```ini
# in fish_brain/.env  (loaded at startup, inherited by the loq subprocess)
LOQ_LTTS=/home/alexmint/.wine/drive_c/Program Files/Loquendo/LTTS7
```

If you also want to run `loq` **directly** in a terminal (e.g. `loq --status`), add the same
line to your shell profile so it's always set:

```bash
echo 'export LOQ_LTTS="/home/alexmint/.wine/drive_c/Program Files/Loquendo/LTTS7"' >> ~/.profile
```

The STT model is cached under `~/.cache/huggingface/` after the first download, so later runs
reuse it. If you skip `--prefetch-stt`, the very first voice turn downloads it on demand (you'll
see a Hugging Face progress bar, and a harmless "set a HF_TOKEN" notice — no token is needed).

`pyproject.toml` is the source of truth for dependencies; `requirements.txt` is a pinned
snapshot (`pip freeze`) for reproducing the exact environment on a fresh clone. Regenerate it
after changing deps with `pip freeze --exclude-editable > requirements.txt`.

Serial access: your user must be in the `dialout` group (log out/in after adding):
```bash
sudo usermod -aG dialout "$USER"
```

## Run

```bash
# No hardware, no mic — type a turn, watch the commands print. Best first test.
python -m fish_brain.app --dry-run --text --no-audio

# Speak one phrase and exit (no LLM/mic) — good for tuning the mouth.
python -m fish_brain.app --dry-run --no-audio --say "Hola, soy un pez parlante."

# No fish, but real voice + LLM + audio (prints the commands it would send).
python -m fish_brain.app --dry-run

# Full system: real serial + mic + fish.
python -m fish_brain.app

# Easiest voice testing: on-screen fish with a hold-to-talk button in the browser.
python -m fish_brain.app --echo --dry-run --viz   # open http://127.0.0.1:8723
```

Flags: `--dry-run` (mock serial, prints commands), `--text` (type instead of mic),
`--echo` (repeat you back, no API key), `--no-audio` (don't play TTS), `--viz` (on-screen fish),
`--port /dev/ttyACM0`, `--say "..."` (one-shot).
In the loop, say/type **`salir`** or hit Ctrl-C to quit; an unclear/empty recording just re-listens.
Push-to-talk: with `--viz`, **hold the on-screen button** (or the browser spacebar) and pick your
mic from the dropdown — easiest for debugging. Without `--viz`, hold **space** in the terminal
(falls back to Enter-to-toggle if `pynput`/display is unavailable).

## Demo day — after turning on the laptop

Once everything above is set up, a cold boot needs no rebuild. Checklist for showing it off:

1. **Plug in the hardware.** Connect the fish's USB cable → it should appear as
   `/dev/ttyACM0` (`ls /dev/ttyACM*`). Turn on the speakers and make sure a mic is connected.
2. **Open a terminal in the repo and activate the venv:**
   ```bash
   cd ~/Development/fish_brain && source .venv/bin/activate
   ```
3. **Check `.env` has a real `OPENAI_API_KEY`** (it's gitignored, so it survives reboots but
   you set it once). Without a key you can still demo `--echo` mode (the fish repeats you).
4. **Run it:**
   ```bash
   python -m fish_brain.app            # full: real fish + mic + LLM
   # or, with the on-screen browser fish too (great for an audience / a flaky mic):
   python -m fish_brain.app --viz      # then open http://127.0.0.1:8723
   ```
   The app **auto-starts and warms the `loq` daemon** on launch (using `LOQ_LTTS` from `.env`),
   so the first phrase is fast. A startup greeting plays — if you hear Billy say hello and his
   mouth moves, the whole pipeline is live.
5. **Talk to it:** hold **space** to record, release to send (or, with `--viz`, hold the
   on-screen button / browser spacebar and pick your mic from the dropdown).
6. **Quit cleanly:** say/type **`salir`** or press **Ctrl-C**. A goodbye phrase plays and the
   fish is sent `STOP` so no motor is left running.

No-hardware / no-key fallbacks if something acts up mid-demo:
```bash
python -m fish_brain.app --echo --dry-run --viz   # software-only fish in the browser, no API key
python -m fish_brain.app --say "Hola, soy Billy."  # speak one phrase to the real fish and exit
```

## Troubleshooting

- **`loq: synthesis failed (voice 'Jorge')` / `loq --list` shows no voices** — `LOQ_LTTS`
  isn't pointing at the install. On this laptop it's under `Program Files` (see *TTS engine
  path* above). `fish_brain` reads it from `.env`; for manual `loq` use, export it / add it to
  `~/.profile`.
- **Speech is slow (~2 s/phrase) instead of snappy (~0.5 s)** — the warm daemon isn't being
  used and `loq` is falling back to a one-shot Wine call per phrase. Restart it:
  `LOQ_LTTS=... loq --restart` (or just relaunch the app, which warms it). The daemon binary
  `loqd.exe` is built once in `~/Development/loq_winer` via `./build-loqd.sh`; rebuild it there
  if it's missing. (Note: that daemon path needs Wine's CRLF stripped from its replies — already
  fixed in `loq_winer`.)
- **`/dev/ttyACM0` missing** — replug the USB cable; check `dmesg | tail` and `ls /dev/ttyACM*`.
  If it's there but permission is denied, confirm your user is in `dialout`/`plugdev`
  (`groups`) and that you logged out/in after adding.
- **Push-to-talk key does nothing (Wayland)** — the global key listener may be unavailable; it
  falls back to **Enter-to-toggle** in the terminal. Easiest fix: use `--viz` and the on-screen
  hold-to-talk button instead.
- **Mic records silence** — pick the right source from the `--viz` dropdown (prefer a
  PipeWire/Pulse source over a raw `hw:` device); the level meter should move while you hold to talk.

## Calibration

All tunables live in `fish_brain/config.py`. The mouth is driven by **time, not held PWM**:
loudness → openness fraction (0..1) → a motor *pulse duration* via measured attack-time
curves. Calibrate by measuring those curves over a serial monitor (115200 baud).

**1. Drive PWMs.** From closed, raise the PWM until more gives no extra travel — that is
`open_pwm` (the firmware also caps there). Pick a close drive for `close_pwm`:

```
MOUTH 0              # rest / closed
MOUTH 238            # raise until the jaw stops opening further -> open_pwm
```

**2. Opening curve.** From fully closed each time, fire single timed pulses at `open_pwm`
and note the resulting openness — these are your `(openness_fraction, ms)` anchors:

```
MOUTH 0 ; MOUTH 238 14     # -> ~0.15 open
MOUTH 0 ; MOUTH 238 104    # -> ~1.0 open
```

Always start from closed: the model uses cumulative drive-time-from-closed as the position
axis. **3. Closing curve:** the same, from fully open with `MOUTH -200 <ms>` (closing is
faster — spring/gravity assist).

Then copy into `config.py`:
- `MouthConfig.open_curve` / `close_curve` — the `(openness, ms)` anchors above; interpolated.
- `MouthConfig.open_pwm` / `close_pwm` — the open/close drive magnitudes.
- `MouthConfig.noise_floor`, `attack`, `release` — sensitivity and snappiness.
- `ConductorConfig.sync_offset_ms` — shift commands vs audio (covers output latency +
  motor lag). Tune by ear; positive sends commands earlier.
- `GestureConfig` — how often/which neck & tail gestures fire.

> The firmware's `SET MOUTH OPEN|CLOSE|PULSE` presets no longer affect the mouth — the host
> streams raw `MOUTH <pwm> <ms>` timed pulses directly. They still apply to neck/tail gestures.

## Safety

The firmware has **no current sensing** — a 5 s watchdog is the only guard. `fish_brain`
guarantees a `STOP` on exit/error (serial link context manager), and closes the mouth
(`MOUTH 0`) after every utterance.
