# fish_brain

Conversational **Big Mouth Billy Bass**. You push-to-talk, your words are transcribed, an
LLM writes a reply, and the fish **speaks it** — mouth synced to the audio, head and tail
moving with the words.

```
[hold a button] → mic → speech-to-text → user text
          → LLM (persona + history) → reply text
          → text-to-speech → loudness envelope → mouth pulses + gestures from the text
          → play audio + stream commands on one clock → 🐟 talks
```

This is the host "brain". It runs on a Linux PC with an **Uno R4 WiFi** as motor board
(`/dev/ttyACM0`), or by itself on an **Arduino UNO Q** (see [Run on the UNO Q](#run-on-the-uno-q)).
It uses two other repos without modifying them: the motor firmware
(`~/Development/Big_mouth`, over serial) and the **`loq`** voice
(`~/Development/loquen_hack`, via its CLI). `CLAUDE.md` has the architecture and the rules.

## Setup

```bash
cd ~/Development/fish_brain

# system audio lib for the mic + playback
sudo apt install libportaudio2

python3 -m venv .venv && source .venv/bin/activate
pip install -e .                 # installs deps from pyproject.toml
# or, for the exact pinned versions this was built/tested with:
#   pip install -r requirements.txt

cp .env.example .env             # then put your keys in .env (GROQ_API_KEY and/or OPENAI_API_KEY)

# optional: fetch the speech model now (~0.5 GB for "small") so the first turn isn't slow
python -m fish_brain.app --prefetch-stt
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
`--port /dev/ttyACM0`, `--say "..."` (one-shot). Backends: `--stt local|openai|groq`,
`--tts loq|openai`, `--llm groq|luna`, `--transport serial|bridge`, `--viz-host 0.0.0.0`.
One-shots: `--check-link` (open the motor link, send `STOP`), `--prerender-canned`,
`--say-canned NAME`, `--list-canned`, `--prefetch-stt`.
In the loop, say/type **`salir`** or hit Ctrl-C to quit; an unclear/empty recording just re-listens.
Push-to-talk: with `--viz`, **hold the on-screen button** (or the browser spacebar) and pick your
mic from the dropdown — easiest for debugging. Without `--viz`, hold **space** in the terminal
(falls back to Enter-to-toggle in a terminal if `pynput`/display is unavailable). A remote's
button works too: see `FISH_PTT_DEVICE` below.

## Configuration

Everything is set in `.env` (plain `KEY=value` lines) or the environment. With nothing set
you get the laptop set-up: local speech-to-text, `loq`, the `groq` LLM profile, `/dev/ttyACM0`.

| Variable | Default | Meaning |
|---|---|---|
| `GROQ_API_KEY`, `OPENAI_API_KEY` | — | Keys. Groq: the `groq` LLM profile and Groq STT. OpenAI: the `luna` profile, OpenAI STT and TTS |
| `FISH_LLM_PROFILE` | `groq` | `groq` (GPT-OSS-20B) or `luna` (GPT-6 Luna). `FISH_LLM_MODEL` and `FISH_LLM_REASONING` override one field. Compare them with `python -m fish_brain.ab` |
| `FISH_STT_BACKEND` | `local` | `local` (faster-whisper, `FISH_STT_MODEL`), `openai` or `groq` (**the recording is uploaded**). `FISH_STT_CLOUD_MODEL`, `FISH_STT_PROMPT`, `FISH_STT_KEYWORDS` tune the cloud ones |
| `FISH_TTS_BACKEND` | `loq` | `loq` or `openai` (`FISH_TTS_MODEL`, `FISH_TTS_VOICE`, `FISH_TTS_INSTRUCTIONS`) |
| `FISH_SERIAL_PORT` | `/dev/ttyACM0` | Motor board port |
| `FISH_SERIAL_TRANSPORT` | `serial` | `serial`, or `bridge` (UNO Q: through the router to a Bridge sketch) |
| `FISH_SERIAL_REQUIRED` | `true` | `false`: keep talking when the motor link can't open, and keep retrying it |
| `FISH_ROUTER_RELEASE`, `FISH_ROUTER_SOCKET` | `true`, `/var/run/arduino-router.sock` | UNO Q: ask the router to release `/dev/ttyHS*` before opening it |
| `FISH_PTT_DEVICE` | off | Push-to-talk from an input device: a `/dev/input/...` path, `name:<part of its name>`, or `auto` |
| `FISH_PTT_KEY`, `FISH_PTT_MODE` | `KEY_VOICECOMMAND`, `hold` | Which key; `hold` to talk or `toggle` (press to start, press to stop) |
| `FISH_PTT_MAX_S` | `15` | Longest recording; also ends a stuck button |
| `FISH_MIC_SOURCE`, `FISH_MIC_DEVICE`, `FISH_SPEAKER_DEVICE` | system default | PipeWire source name; or a device number or part of its name |
| `FISH_VIZ_HOST`, `FISH_VIZ_PORT`, `FISH_VIZ_TOKEN` | `127.0.0.1`, `8723`, none | Where the page listens; with a token, open it as `/?token=...` |
| `FISH_VOICE_QUIT` | `true` | Saying "salir" ends the program |
| `FISH_WELCOME_ONCE` | `false` | Greet once per boot instead of at every start |
| `FISH_CLOUD_TIMEOUT`, `FISH_CLOUD_CONNECT_TIMEOUT` | `10`, `3` | Seconds before a cloud call gives up |

When a cloud call fails the fish says a short "no signal" line and listens again; nothing
that goes wrong inside a turn ends the program.

If you use an OpenAI voice in public, OpenAI's terms ask you to tell listeners the voice is
generated. OpenAI has announced the end of its current speech models for 2027-01-06.

To find a remote's device and key: `python -m fish_brain.evdev_button --list`, then
`--watch` and press the button. Your user must be in the `input` group.

## Run on the UNO Q

The board runs the same program with a different `.env`. Full steps, and which of them need
`sudo`, are in [`deploy/README.md`](deploy/README.md). In short, on the board:

```bash
git clone https://github.com/alexandergmzx/fish_brain ~/fish_brain && cd ~/fish_brain
git checkout braintip
deploy/unoq_setup.sh install      # prints the apt line to run; makes the venv; stops until .env has a key
deploy/unoq_setup.sh service      # start at boot as a user service
tools/unoq_checks.sh              # what the board sees: USB, audio, input devices, router
journalctl --user -u fish-brain -f
```

- The motor MCU is on `/dev/ttyHS1`, which the board's `arduino-router` holds. The program
  asks the router to release it and gives it back on exit. No udev rule is needed.
- `tools/sketches/` has two small MCU test sketches and `tools/uart_check.py` measures the
  link with them. They are not the fish firmware.
- Without a screen, a turn is triggered by a remote's button (`FISH_PTT_DEVICE`) or the page
  opened from a phone (`--viz` with `FISH_VIZ_HOST=0.0.0.0`).

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
guarantees a `STOP` on exit, error and stop signal (the link's context manager), and sends a
full close pulse after every utterance.
