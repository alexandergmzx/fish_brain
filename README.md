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

cp .env.example .env             # then put your OPENAI_API_KEY in .env
```

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
```

Flags: `--dry-run` (mock serial, prints commands), `--text` (type instead of mic),
`--no-audio` (don't play TTS), `--port /dev/ttyACM0`, `--say "..."` (one-shot).
In the loop, say/type **`salir`** or hit Ctrl-C to quit. Push-to-talk = hold **space**
(falls back to Enter-to-toggle if `pynput`/display is unavailable).

## Calibration

All tunables live in `fish_brain/config.py`. To find good motor values, talk to the
firmware directly over a serial monitor (115200 baud) and use its live tuning:

```
MOUTH 180            # immediate signed PWM, holds until next command
MOUTH 0              # rest / closed
SET MOUTH OPEN 220   # adjust a preset live, no reflash
```

Then copy what feels right into `config.py`:
- `MouthConfig.open_pwm` / `min_open_pwm` — how wide the mouth opens at loud / threshold.
- `MouthConfig.noise_floor`, `attack`, `release` — sensitivity and snappiness.
- `ConductorConfig.sync_offset_ms` — shift commands vs audio (covers output latency +
  motor lag). Tune by ear; positive sends commands earlier.
- `GestureConfig` — how often/which neck & tail gestures fire.

## Safety

The firmware has **no current sensing** — a 5 s watchdog is the only guard. `fish_brain`
guarantees a `STOP` on exit/error (serial link context manager), and closes the mouth
(`MOUTH 0`) after every utterance.
