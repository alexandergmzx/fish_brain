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
TTS engine (`~/Development/loquen_hack`, via its CLI). See `CLAUDE.md` for architecture.

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
