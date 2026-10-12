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
sudo apt update && sudo apt install libportaudio2

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
`--say-canned NAME`, `--list-canned`, `--prefetch-stt`, `--read-badge FILE` (read the name on a
badge photo with the vision model and print the JSON; it starts no voice and no motors:
`python -m fish_brain.app --tts openai --llm luna --read-badge foto.jpg`, needs
`OPENAI_API_KEY`).
In the loop, say/type **`salir`** or hit Ctrl-C to quit; an unclear/empty recording just re-listens.
Push-to-talk: with `--viz`, **hold the on-screen button** (or the browser spacebar) and pick your
mic from the dropdown — easiest for debugging. Without `--viz`, hold **space** in the terminal
(falls back to Enter-to-toggle in a terminal if `pynput`/display is unavailable). A remote's
button works too: see `FISH_PTT_DEVICE` below; with `FISH_MIC_CAPTURE=browser` its press is
relayed to the phone page, which records with its own microphone while a page has one ready.

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
| `FISH_PTT_DEAD_S` | `0` | End a recording once the microphone stream has delivered only digital zeros for this many seconds after sound (a remote whose microphone streams only while its key is held) |
| `FISH_PTT_PAUSE_S`, `FISH_PTT_QUIET_RMS` | `0`, `0.04` | End a recording after this long a pause once speech (chunks above the RMS) was heard: tap, talk, stop talking |
| `FISH_MIC_SOURCE`, `FISH_MIC_DEVICE`, `FISH_SPEAKER_DEVICE` | system default | PipeWire source name; or a device number or part of its name |
| `FISH_MIC_CAPTURE` | `host` | `host`: this machine records. `browser`: the page records with the phone's microphone and uploads the WAV (`POST /utterance`); needs `--viz` and https on the phone, falls back to the host microphone per device (`docs/viz.md`) |
| `FISH_VIZ_HOST`, `FISH_VIZ_PORT`, `FISH_VIZ_TOKEN` | `127.0.0.1`, `8723`, none | Where the page listens; with a token, open it as `/?token=...` |
| `FISH_VIZ_TRUST_LOCAL` | `false` | `true`: requests from the machine itself need no token (the board's own display) |
| `FISH_VIZ_TLS_CERT`, `FISH_VIZ_TLS_KEY` | empty | Plain http only. Both set: a second, HTTPS listener for the same page (the phone's microphone needs https); a bad path exits 78 |
| `FISH_VIZ_TLS_PORT` | `8724` | Port of the HTTPS listener, bound to `FISH_VIZ_HOST` |
| `FISH_SAY_ADDRESS` | `false` | `true`: after the welcome the fish says the last two octets of its IP (only when bound to `0.0.0.0`) |
| `FISH_KIOSK_MODE`, `FISH_KIOSK_OUTPUT` | empty | Board display: force a mode such as `1280x720`, pick an output; see `deploy/README.md` |
| `FISH_LINK_LOG` | empty | A file that records every line sent to the MCU and every byte read back |
| `FISH_VOICE_QUIT` | `true` | Saying "salir" ends the program |
| `FISH_WELCOME_ONCE` | `false` | Greet once per boot instead of at every start |
| `FISH_READING_PROFILE` | empty = `FISH_LLM_PROFILE` | LLM profile that reads a badge photo (the reading, ADR 0007). It needs image input: `luna` |
| `FISH_READING_LOOK` | `false` | `true`: the console shows a per-visitor consent tick and the model may add one kind line on clothing, colours or accessories |
| `FISH_CLOUD_TIMEOUT`, `FISH_CLOUD_CONNECT_TIMEOUT` | `10`, `3` | Seconds before a cloud call gives up |

When a cloud call fails the fish says a short "no signal" line and listens again; nothing
that goes wrong inside a turn ends the program.

If you use an OpenAI voice in public, OpenAI's terms ask you to tell listeners the voice is
generated. OpenAI has announced the end of its current speech models for 2027-01-06.

To find a remote's device and key: `python -m fish_brain.evdev_button --list`, then
`--watch` and press the button. Your user must be in the `input` group.

## Run on the UNO Q

The board runs the same program with a different `.env`. Full steps, and which of them need
`sudo`, are in [`deploy/README.md`](deploy/README.md).

**Status (2026-10-11).** On the board: the fish runs as a service, starts at boot, speaks its
welcome and holds a conversation started from the page on a phone or from a touch display (cloud
speech-to-text and LLM, Loquendo voice). The MCU runs the fish firmware from Big_mouth and shows
the motor signals on its LEDs. Decided, not yet built: the operator's phone as the only interface
over HTTPS, the phone's microphone, and the reading of a visitor's badge
([ADR 0006](docs/adr/0006-the-phone-is-the-interface.md), [ADR 0007](docs/adr/0007-the-reading.md)).
Not done: the phone hotspot, motor drivers and motors, calibration of the second fish.
Measurements are in [`docs/results/`](docs/results/).

### Hardware

| Part | Notes |
|---|---|
| Power | A power bank into the hub's power input, the hub's cable into the board. **The cable matters**: with one cable the board stayed in USB device mode and saw nothing on the hub; with a newer one it became the host at once. Check with `cat /sys/class/typec/port0/data_role` (want `[host]`) and `lsusb` |
| Speaker | Any USB speaker. The one tested is playback-only and also has media keys |
| Microphone | Any USB microphone (tested: RedOctane USB Microphone) |
| Push-to-talk | The page opened from the operator's phone or PC (the fair's interface, ADR 0006), a button on an input device (`FISH_PTT_DEVICE`), or the hold-to-talk target on an HDMI touch display (parked, see "Screen" below) |
| Display (optional) | HDMI touch display on the hub. **Give it its own power and switch it on before the board**: fed from the hub's power bank the board did not see it |

PipeWire picks a USB speaker and microphone as the defaults by itself. Volume:
`wpctl set-volume @DEFAULT_AUDIO_SINK@ 1.0`. At 40 % the tested speaker was too quiet for
the microphone to hear; at 100 % it was loud and clear.

### Install and run

```bash
git clone https://github.com/alexandergmzx/fish_brain ~/fish_brain && cd ~/fish_brain
git checkout braintip
sudo apt update                   # always before installing anything
deploy/unoq_setup.sh install      # prints the apt line to run; makes the venv (about 3 minutes); stops until .env has a key
deploy/unoq_setup.sh service      # start at boot as a user service
tools/unoq_checks.sh              # what the board sees: USB, audio, input devices, router
journalctl --user -u fish-brain -f
```

**Bring-up test.** `tools/unoq_bringup.sh` runs the board tests and prints PASS or FAIL for
each: the port is the USB host with a speaker and a microphone; Loquendo renders a sentence
in 2 s or less; that sentence played on the speaker is heard by the microphone; 300 lines to
the MCU (with `uart_echo` flashed) all come back. `--stt tiny` adds a local speech-to-text
timing. It needs no root and makes sound. Last run 2026-10-11: all passed.

`tools/unoq_checks.sh --mic CARD --speaker CARD` records and plays back; `--keys` finds a
button's device and key name; `--stress` is a 10-minute load test.

### Voice

Loquendo runs on the board under Hangover Wine: about 0.75 s for a short sentence once its
daemon is warm (`loq --start`), about 8 s without the daemon. The board's example `.env`
uses it (`FISH_TTS_BACKEND=loq`, `FISH_LOQ_BIN` with the full path, because a service does
not have `~/.local/bin` on its path). `FISH_TTS_BACKEND=openai` is the alternative.

Speech-to-text on the board is set to a cloud backend, because the local models are slow on
this CPU. Measured per turn, whatever the length of the recording:

| Local model | Time | Quality on the test sentence |
|---|---|---|
| `tiny` | 3.5 to 4.8 s | Spelling-level mistakes |
| `base` | about 8 s | Correct |
| `small` (the laptop default) | about 20 to 23 s | Correct |

For a board with no internet, `FISH_STT_BACKEND=local` with `FISH_STT_MODEL=tiny` is the
only local choice that is close to usable.

### The motor MCU

- The MCU is on `/dev/ttyHS1`, which the board's `arduino-router` holds. The program asks
  the router to release it and gives it back on exit; the router keeps running. No udev
  rule is needed. By hand:
  `arduino-router-cli '$/serial/close' /dev/ttyHS1` and `'$/serial/open' /dev/ttyHS1`.
- The firmware is Big_mouth's, branch `braintip`, folder `unoq/BigMouthQ`: the same
  `main.cpp` and headers as the Uno R4, built for the UNO Q. Same protocol, same pin numbers.
  It is pushed, compiled and flashed from the laptop, with a numbered log of every upload
  kept on the board:

  ```bash
  deploy/unoq_fw.sh push && deploy/unoq_fw.sh compile      # about 90 s on the board
  deploy/unoq_fw.sh upload --by <your name>                # resets the MCU; refuses while the fish runs
  deploy/unoq_fw.sh status
  ```

- **The board's LEDs show what the MCU is doing.** LED4 green blinks while the firmware
  runs and flashes blue for every line received. The matrix has one lane per motor (mouth
  nearest the USB-C connector, then neck, then tail): a lamp for `+`, a lamp for `-`, and a
  bar for the PWM. If the matrix moves with the voice and the fish does not, look after the
  MCU: drivers, wiring, motor power.
- Check the firmware with the fish stopped: `tools/fw_check.py check --release-router`
  (motor-safe lines only), `tools/fw_check.py send "MOUTH 120 50" --release-router` for one
  line with its reply. These tools, `--check-link` and the flash helper refuse to run while
  a fish holds the port.
- [`tools/sketches/`](tools/sketches/) has test sketches only: two echo sketches for the
  link and `pwm_probe`, which measures the motor pins with nothing wired.
- **Before wiring L298N boards**: while the MCU is in reset (the whole Linux boot, a router
  restart, an upload) its pins are not driven, and D8 is pulled high. Fit 10 k from each
  enable (D6, D3, D5) and from D7 and D8 to ground, and a switch on the motor pack.

### The phone as the interface, or a screen

At the fair the page is opened on the operator's phone (`FISH_VIZ_HOST=0.0.0.0`, a
`FISH_VIZ_TOKEN`, the console view, the page's default; `/?debug=1` is the old full page); the board drives no display
([ADR 0006](docs/adr/0006-the-phone-is-the-interface.md)). The display below is parked.

With an HDMI touch display on the hub the board shows the visitor view of the page
(`/?kiosk=1`) by itself: the fish and one hold-to-talk target. Set-up, what each screen state
means and the operator corner are in
[`deploy/README.md`](deploy/README.md#the-fish-page-on-the-boards-own-display-kiosk).

Without a display a turn is triggered by the page opened from a phone (`FISH_VIZ_HOST=0.0.0.0`
and a `FISH_VIZ_TOKEN`) or by a button on an input device (`FISH_PTT_DEVICE`, `FISH_PTT_KEY`,
`FISH_PTT_MODE`). With none of these the program stops with exit status 78 instead of
restarting forever. The fish itself runs the same with and without a display.

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
