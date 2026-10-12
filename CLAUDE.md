# CLAUDE.md — fish_brain (the talking Billy Bass brain)

This file is read by Claude Code at the start of every session in this repo. It says who the
user is, what is in use, the rules, and how to work here. As of 2026-10-10, branch `braintip`:
read [`docs/BRAINTIP.md`](docs/BRAINTIP.md) before changing code on this branch.
[`README.md`](README.md) is the user guide (setup, flags, environment, calibration); this file
does not repeat it.

## Who you are working with

You are working with **Alexander Gomez** (GitHub: `alexandergmzx`), an embedded software
engineer. Skip beginner-level explanations of Linux, serial, audio or Python. Push back with
data when warranted.

### Working style with Alexander

- Lead with the decision and the trade-off, not the rationale. He'll ask if he wants more.
- **Questions and review items go in the chat, never in a file he has to open.** Do not
  create a file for him to fill in, and do not end a turn with "see X.md".
- **Do the work; hand him only what is his**: `sudo` on the board, flashing the MCU, router
  changes, Wi-Fi profiles, anything that moves a motor. Each as a ready command with what it
  changes.
- **Show results, not files.** Summaries, changed lines and numbers appear in the chat.
- **Recommend, then act.** Put the recommended option first when asking.
- **Say plainly when something went wrong**: what it touched and whether it is undone.
- **Judge by use.** Get the fish talking in front of him early rather than polishing unseen.
- When a question has a clean experimental answer, propose the experiment instead of
  guessing. Don't add scope beyond what the task asks.

## Status (as of 2026-10-11)

| Item | State |
|---|---|
| Laptop fish (Billy Bass #1, Uno R4) | Working since June 2026 |
| `braintip`: software for the UNO Q | Runs on the board as `fish-brain.service` with linger since 2026-10-11: boots alone, welcome, real turns from the page on a phone or from the touch display (`stt=openai llm=luna tts=loq`), about 4.3 s from release to voice on the home Wi-Fi. Not yet on the hotspot. The phone as the interface, HTTPS, the phone's microphone and the reading: built 2026-10-11 (ADR 0006, 0007 proposed), level 0 to 2 on the laptop, the reading at level 1 on the board; the phone itself untested |
| Board: hub, USB speaker, RedOctane microphone | Working on a power bank. Speaker to microphone loop checked. The microphone stays plugged in as the fallback once the phone's is in use |
| Board: Loquendo | Works; about 0.75 s per short sentence with the daemon warm |
| Board: MCU firmware | Big_mouth `braintip` (`unoq/BigMouthQ`) flashed 2026-10-11, no drivers attached: protocol transcript 122 of 122, pulses within 1 ms, 9,999 of 9,999 lines in a soak. LED matrix mirrors the nine L298 signals. PWM measured good on D3, D5, D6 |
| Board: bring-up script | `tools/unoq_bringup.sh`: all tests passed 2026-10-11 |
| Board: local speech-to-text | Slow: `tiny` 3.5 to 4.8 s, `base` 8 s, `small` 20 to 23 s per turn |
| Board: push-to-talk | The page on the operator's phone or PC (the default view), hold-to-talk with the board's microphone; the browser's own microphone over HTTPS (`FISH_MIC_CAPTURE=browser`, the board's default since 2026-10-11) works from the laptop's Chrome; not yet tried on his phone. The touch display's kiosk is parked. `FISH_PTT_DEVICE=auto` also adopted the headset jack as a trigger (results 2026-10-11) |
| Board: HDMI touch display | Unplugged since 2026-10-12 (ADR 0005 replaced by 0006): the browser cost 1.1 to 1.3 cores and 60 to 68 C; without it the board idles at 1 % and 41 to 44 C, a turn peaks at 30 % (results 2026-10-12). The LightDM session stays installed, it starts nothing |
| The reading (la lectura) | Built (ADR 0007, proposed): badge photo on the phone → `gpt-6-luna` through the board (4.3 to 6.7 s, 1163 image tokens, surnames split, accents restored: `docs/results/2026-10-11-reading-badge.md`) → the fish asks "¿Tú eres X?" → the answer is a turn. Not yet tried with a real badge or on the phone |
| Motors on the UNO Q (L298N), Billy Bass #2 calibration | Not started. Before wiring: 10 k pull-downs on D6, D3, D5 and on D7, D8 (D8 is pulled high in reset) |
| Fair | **2026-10-17**. Billy Bass #2 first; the Spin Master hat body only if it arrives. Interface: the page on the operator's phone (ADR 0006) |

Ask before starting the next Braintip phase. Until the fair, prefer work that closes the fair
path over polishing one module. The phase list lives in `docs/BRAINTIP.md`; keep this table
short and overwrite it, never append to it.

## Safety — the host always stops the motors

The firmware has no current sensing. Its 5 s run limit is the only hard guard, and gesture
chains are not covered by it. So:

1. **`STOP` on every exit** (normal, Ctrl-C, exception, stop signal) and a full close pulse
   after every utterance. Enforced by the link's context manager, the conductor's `finally`,
   the SIGTERM handler in `app.py` and `KillSignal=SIGINT` in the unit. Never remove these.
2. **During speech only timed `MOUTH <pwm> <ms>` pulses.** Held `MOUTH <n>` is for manual
   calibration.
3. **No motors unattended.** Nothing past `--dry-run` unless Alexander is at the fish. Tell
   him before the first real-motor run of any change.
4. **Link tests use motor-safe lines** (`PING <n>`, which the firmware answers
   "Unknown command").
5. **Never flash the MCU, change router units or drive GPIO 37/70 on the board** without his
   word. Those steps are his.
6. **Calibration pulses start from the closed position.**
7. **During the fair, ask before restarting `fish-brain` or rebooting the board.**

## What is in use

```
[hold on the phone page] → mic (the board's, or the phone's own over HTTPS) → speech-to-text
   → LLM (persona + history) → text-to-speech → WAV
   → loudness envelope → mouth pulses  +  text-driven neck/tail gestures
   → play audio and stream commands on one clock → the fish speaks → listen again
[badge photo on the phone] → name (vision model) → "¿Tú eres X?" → the answer is a turn   (ADR 0007)
```

The whole command schedule is computed from the finished WAV, then audio and commands run
together.

| Part | What it does | Where |
|---|---|---|
| Push-to-talk | Keyboard key, the page's hold button, or a remote's button; a fresh press starts a recording, a 15 s limit ends a stuck one. With `FISH_MIC_CAPTURE=browser` the page records with its own microphone and uploads a 16 kHz WAV (`POST /utterance`), taken by the loop through one inbox like a board recording; a remote's press is relayed to the page in browser mode | [`ptt.py`](fish_brain/ptt.py), [`evdev_button.py`](fish_brain/evdev_button.py), [`viz.py`](fish_brain/viz.py) |
| Speech-to-text | `local` faster-whisper, or the recording uploaded to `openai` / `groq` | [`stt.py`](fish_brain/stt.py) |
| LLM | Profiles `groq` (GPT-OSS-20B) and `luna` (GPT-6 Luna); bounded history; fallback line on error. `reading.read_badge` turns a badge photo into a name (`luna` only: it takes images, `groq` does not) | [`llm.py`](fish_brain/llm.py), [`ab.py`](fish_brain/ab.py) |
| Cloud plumbing | One client per service, short timeouts, a background "is the internet there" flag, two error types | [`cloud.py`](fish_brain/cloud.py) |
| Text-to-speech | `loq` (Loquendo "Jorge") or `openai`; always a WAV file, never played here | [`tts.py`](fish_brain/tts.py) |
| Canned phrases | welcome, goodbye, no_signal, no_mic, reading_wait, reading_fail; cached by text and voice; an older rendering is used when a new one can't be made | [`canned.py`](fish_brain/canned.py) |
| Mouth | WAV → openness (0..1) → timed pulses through measured curves | [`envelope.py`](fish_brain/envelope.py) |
| Gestures | Head out on words, home on sentence ends; tail flaps | [`gestures.py`](fish_brain/gestures.py) |
| Conductor | Plays the audio and sends each command at its time | [`conductor.py`](fish_brain/conductor.py), [`speak.py`](fish_brain/speak.py) |
| Motor link | pyserial, or MessagePack-RPC through the UNO Q's router; a mock for `--dry-run`; a wrapper that keeps the fish talking without motors | [`serial_link.py`](fish_brain/serial_link.py), [`router_rpc.py`](fish_brain/router_rpc.py) |
| Turn loop | One turn in stages; no error inside a turn ends the loop | [`conversation.py`](fish_brain/conversation.py) |
| The page | Browser view on a phone or PC: hold-to-talk, mic picker, transcript, the visitor view (`?kiosk=1`). The operator console (the default view; `?debug=1` the old page): hold-to-talk, the badge photo, the name; HTTPS as a second listener behind `FISH_VIZ_TLS_CERT`; the phone's microphone; the token on `/events` and `/audio` | [`viz.py`](fish_brain/viz.py), [`web/`](fish_brain/web/), [`docs/viz.md`](docs/viz.md) |
| Entry point | Flags, start-up checks, one-shots | [`app.py`](fish_brain/app.py) |

Other repos. **They stay untouched; this repo only calls them.**

| Repo | Role | Touched via |
|---|---|---|
| `~/Development/Big_mouth` | Firmware: executes motor commands. `main` = Uno R4 WiFi; branch `braintip` adds the UNO Q build (`unoq/BigMouthQ`), edited from here by his word of 2026-10-11, protocol unchanged. Pins: its `include/Config.h` | Serial, 115200 baud; flashed with `deploy/unoq_fw.sh` |
| `~/Development/loquen_hack` (laptop), `loq_winer` (board) | `loq`, the Loquendo voice | `loq -o FILE.wav -- "texto"` |

## Targets and hosts (measured 2026-10-10)

| | Laptop (Linux Mint) | UNO Q `segunda` (`ssh arduino@segunda.local`) |
|---|---|---|
| Python | 3.12 in `.venv` | 3.13.5; needs `python3-venv python3-dev gcc libportaudio2` from apt |
| Motor board | Uno R4 WiFi on `/dev/ttyACM0` | STM32U585 on `/dev/ttyHS1` (`root:dialout`), owned by `arduino-router` 0.10.0 |
| MCU core | — | `arduino:zephyr` 0.55.2: the Linux link is `Serial2` |
| Audio | PipeWire with `pactl` | PipeWire as user services, no `pactl` (`wpctl`, `pw-dump`); own sound card besides USB |
| Voice | `loq` under Wine. **Wine does not work on this desktop (NVIDIA): never run `loq` or any `.exe` here** | Hangover Wine + Loquendo: works, 0.75 s warm. Running `loq` on the board is fine |
| USB | — | Power bank into a hub, hub into the board. Speaker: Jieli "UACDemoV1.0". Microphone: RedOctane. PipeWire makes them the defaults |

Bodies: Billy Bass #1 (laptop, calibrated June 2026), Billy Bass #2 (fair, not calibrated),
the Spin Master Sorting Hat (maybe; "the reading" names the badge feature, never the hat). Full board notes:
[`docs/results/2026-10-10-unoq-inspection.md`](docs/results/2026-10-10-unoq-inspection.md).

## Decisions

Changed only by a record in [`docs/adr/`](docs/adr/). Do not reopen without new evidence.

| Question | Decision | Since |
|---|---|---|
| Turn trigger | Push-to-talk | 2026-06-01 |
| Language | Spanish, for STT, the persona and the voice | 2026-06-01 |
| Playback | TTS renders silently; this program plays. Never `loq -p` | 2026-06-01 |
| Mouth | Timed pulses from measured curves, not held PWM | 2026-06-06 |
| Gestures | Driven by the text; random only when there is no text | 2026-06-06 |
| Board transport | Ask the router to release the port; Bridge RPC as alternative (ADR 0001) | 2026-10-10 |
| Board start-up | systemd user service with linger (ADR 0002) | 2026-10-10 |
| Turn trigger at the fair | The page on the operator's phone or PC; the phone's microphone when the browser has one, the board's otherwise, no restart between them; the display parked (ADR 0006, proposed, replaces 0005) | 2026-10-11 |
| The reading's model | `gpt-6-luna` through the board, strict JSON, the photo in memory only; measured 2026-10-11 | 2026-10-11 |
| The reading | A badge photo read by a vision model through the board (`luna`); the fish asks the name by voice before telling the future; the photo lives in memory only; badge-only by default, a look line only with a consent tick (ADR 0007, proposed) | 2026-10-11 |
| Motor port | One holder at a time: a lock taken before the router is asked for anything | 2026-10-11 |
| Speech backends | By environment; laptop defaults are local STT and `loq` (ADR 0003) | 2026-10-10 |
| LLM | Profiles; `groq` in code, `luna` on the board (ADR 0004) | 2026-10-10 |
| `master` | Untouched. On `braintip` the laptop must still run with no environment set | 2026-10-10 |

Not decided: which cloud speech-to-text; local STT when offline; whether the LightDM session
stays installed with no display (to be measured). Decided 2026-10-10: the board's voice is
Loquendo (`FISH_TTS_BACKEND=loq`). Decided 2026-10-11: tamer welcome and goodbye for the fair.

## Serial protocol — the contract

Lines end in `\n`, are case-insensitive, 115200 baud, PWM −255..255.
**+ = open/out, − = close/return.**

| Command | Meaning | Used for |
|---|---|---|
| `MOUTH <pwm> <ms>` | One timed pulse, then stop | Speech; the close pulse after each utterance |
| `MOUTH <n>` | Hold a PWM until the next command | Manual calibration only |
| `NECK ...`, `TAIL ...` | Chains of `<pwm> <ms>` pairs, run and stopped by the firmware | Gestures |
| `STOP` / `S` | Stop all motors | Every exit and error |

The firmware echoes every character, prints a `> ` prompt and sends no acknowledgement; an
unknown line gets "Unknown command. Type HELP". The host ignores everything inbound. Both
transports carry the same lines (Bridge: method `fish_cmd`, health call `fish_ping`).

The protocol belongs to Big_mouth's command processor. A change starts there, needs
Alexander's word, and lands on both sides together. When firmware for the UNO Q exists,
check its replies against this table.

## Repository layout

| Path | Tracked | Purpose |
|---|---|---|
| [`fish_brain/`](fish_brain/) | yes | The package; modules as in "What is in use" |
| [`tests/`](tests/) | yes | Unit tests that need no hardware and no network |
| [`tools/`](tools/) | yes | `fw_check.py` (firmware checker: replies, timing, soak, one-line send), `uart_check.py` (link soak test), `unoq_checks.sh` (board checks), `unoq_bringup.sh` (board tests with PASS/FAIL), `sketches/` (MCU test sketches: two echo sketches and the pin probe; the fish firmware is in Big_mouth) |
| [`deploy/`](deploy/) | yes | The unit, the board set-up script, the MCU flash helper (`unoq_fw.sh`), the kiosk session (`kiosk/`, parked since ADR 0006), the board's example environment. **The repo is the source of truth for the board: never hand-edit it without the same change here** |
| [`docs/`](docs/) | yes | `BRAINTIP.md`, `UNOQ_BRIDGE_RPC_EXPLAINED.md`, `viz.md`, `adr/`, `results/` |
| `gui/` | yes | June prototypes; parked |
| `.claude/settings.json` | yes | Assistant deny rules |
| `.env` | **never** | Keys and local overrides |
| `.venv/`, `~/.cache/fish_brain/canned/` | **never** | Environment; rendered phrases |

## Conventions and ground rules

### Rules from the owner

- The other repos are not edited from here.
- Animation in the browser must feel alive: springs, idle motion, nothing meter-like.
- No motors without him present (see Safety).

### Configuration and secrets

- **Every board difference sits behind a `FISH_*` variable or a flag whose default is the
  laptop's behaviour.** Nothing hard-codes `/dev/ttyHS1`, a socket path or a home directory.
- `.env` holds plain `KEY=value` lines. Keys live only there and are never printed: not in
  logs, the start-up line, the web page or its events.
- `FISH_VIZ_TOKEN` is optional: on his own password-protected hotspot the board runs with it empty
  (his word, 2026-10-11), so every endpoint is open and the URL is just the address. Set it only
  on a network with strangers; it then guards the POSTs, the event stream and the audio.
- The switches that differ between targets: `FISH_SERIAL_PORT`, `FISH_SERIAL_TRANSPORT`,
  `FISH_SERIAL_REQUIRED`, `FISH_STT_BACKEND`, `FISH_TTS_BACKEND`, `FISH_LLM_PROFILE`,
  `FISH_PTT_DEVICE`, `FISH_PTT_KEY`, `FISH_PTT_MODE`, `FISH_VIZ_HOST`, `FISH_WELCOME_ONCE`,
  `FISH_VOICE_QUIT`. Full list: README and [`deploy/env.unoq.example`](deploy/env.unoq.example).
  Since ADR 0006 and 0007: `FISH_VIZ_TLS_CERT`, `FISH_VIZ_TLS_KEY`, `FISH_VIZ_TLS_PORT`,
  `FISH_MIC_CAPTURE` (`host` on the laptop), `FISH_READING_PROFILE` (empty = the LLM profile),
  `FISH_READING_LOOK`, `FISH_SAY_ADDRESS`.

### Every hardware boundary has a stand-in

Mock link (`--dry-run`), typed turns (`--text`), echo instead of the LLM (`--echo`), silent
player (`--no-audio`), the browser fish (`--viz`), a fake router socket in the tests. New
hardware goes behind one too, and its library is imported only when used, so the laptop runs
without `evdev` or `msgpack`.

### Environment

- Run Python as `.venv/bin/python -m ...`. `pyproject.toml` lists the dependencies; the
  `unoq` extra adds `evdev` and `msgpack`.
- Run tests with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` (ROS is sourced in the shell on this
  desktop and its pytest plugins leak in).
- **On this desktop, never run anything that reaches `loq`**: that includes
  `python -m fish_brain.app` with `--say`, `--say-canned` or a conversation, unless
  `--tts openai` is given. Test with `--tts openai`, the unit tests and the mocks.

### Authorization boundary

- Alexander runs every `sudo` step, flashes the MCU, changes router units and Wi-Fi profiles,
  and pushes. Give him the command and what it changes.
- Claude runs everything else, including read-only checks on the board over ssh, and reports.
- **`apt update` always comes before `apt install`**, in commands handed to him and in every
  doc and script (his word, 2026-10-10).
- When he is installing or changing something on the board himself, wait: do not start
  installs there at the same time.

### Evidence

- No number is quoted without a dated file in [`docs/results/`](docs/results/) with the
  command and commit. Unmeasured values are marked "(estimate)" or "not measured".
- Calibration values belong to one fish body. Never invent them.
- **Say which level was actually run.** A dry run does not prove motion.

| Level | Command | Shows | Cannot show |
|---|---|---|---|
| 0 | `pytest`, `compileall` | Logic, framing | Anything with devices |
| 1 | `--dry-run --text --no-audio` | LLM, TTS, the command schedule | Mic, speakers, timing |
| 2 | `--echo --dry-run --viz` | Mic, STT, push-to-talk, the browser fish | Motor lag, real mouth travel |
| 3 | `tools/uart_check.py` | Link loss and round-trip time | Motion |
| 4 | Laptop with the real fish | Motion and sync | Board start-up |
| 5 | Board under systemd | Boot, restart, offline, the remote | — |

Work on motion, sync or calibration is done only after level 4 or 5 with him present.

### Documentation style

Markdown, in English. Tables carry structure; prose is for reasons. ASCII diagrams. Relative
links. Protocol → this file. Flags, environment, calibration steps → README. Phases →
`docs/BRAINTIP.md`. Decisions → `docs/adr/`. Measurements → `docs/results/`.

### No AI attribution anywhere in the repo

Alexander is the author of this repository. Never write that an AI tool or model drafted,
wrote, verified or reviewed anything: not in docs, records, code comments, commit messages
or PR descriptions. References to this `CLAUDE.md` file and the `.claude/` directory are file
paths, not attributions. Model names appear only as the things being run.

### Git

| Branch | Purpose |
|---|---|
| `master` | The laptop fish as of June 2026. Untouched |
| `text-driven-gestures` | Base of `braintip` |
| `braintip` | The UNO Q work |

Small commits, subject `<scope>: <lowercase description>`. Pushing happens when Alexander
asks. Never `--no-verify`, never `git push --force` or `git reset --hard` on these branches,
never `git clean` (it would delete `.env` and `.venv`).

## Commands

```bash
# checks that need nothing (safe on this desktop)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests   # expect all passed
.venv/bin/python -m compileall -q fish_brain                             # expect no output
.venv/bin/python tools/uart_check.py --self-test                         # expect 0 lost
.venv/bin/python tools/fw_check.py --self-test                           # expect all passed

# laptop, no hardware (cloud voice, so Wine is not involved)
.venv/bin/python -m fish_brain.app --dry-run --text --no-audio --tts openai   # type a turn; expect TX lines and a [turn] line
.venv/bin/python -m fish_brain.app --dry-run --echo --viz --tts openai        # hold the button in the browser, it repeats you; the console is the default view; ?debug=1 the old page
FISH_MIC_CAPTURE=browser .venv/bin/python -m fish_brain.app --dry-run --echo --viz --tts openai   # the browser's own microphone (localhost is a secure context)
.venv/bin/python -m fish_brain.app --dry-run --text --no-audio --tts openai --llm luna --read-badge foto.jpg   # the badge call alone, prints the JSON (needs the key)
.venv/bin/python -m fish_brain.ab --no-vote                                   # both LLM profiles: latency and cost

# laptop with the fish (his to run: uses loq and motors)
python -m fish_brain.app
python tools/uart_check.py --port /dev/ttyACM0 --expect any --count 300

# board, as arduino in ~/fish_brain
deploy/unoq_setup.sh sync         # from the laptop: copy this tree to the board without pushing
deploy/unoq_setup.sh install      # prints the sudo lines for him; venv, canned phrases, link check
deploy/unoq_setup.sh service      # install and start the user unit
deploy/unoq_setup.sh status
deploy/unoq_setup.sh tls [ip ...]  # board: self-signed certificate for the https page; prints the .env lines and the phone steps
deploy/unoq_setup.sh kiosk on|off|pause|resume|status   # parked (ADR 0005, replaced by 0006): the page on the board's display
deploy/unoq_fw.sh push | compile [--trace] | upload --by <who> | status | log   # from the laptop: MCU sketches
tools/unoq_checks.sh              # the Braintip Phase 1 table (what the board sees)
tools/unoq_bringup.sh             # usb, voice, speaker-to-mic loop, MCU link; expect "all tests passed"
.venv/bin/python tools/fw_check.py check --release-router   # firmware flashed, fish stopped; expect RESULT PASS
.venv/bin/python tools/fw_check.py send "MOUTH 120 50" --release-router   # one line, prints the reply
.venv/bin/python tools/uart_check.py --release-router      # needs the uart_echo sketch; expect 0 lost
systemctl --user restart fish-brain
journalctl --user -u fish-brain -f
```

`--viz` and the service never exit: run them in the background.

## Calibration

The mouth is driven by time. Loudness becomes an openness fraction, and the curves in
`MouthConfig` turn that into a pulse length. The curves, the drive PWMs and
`ConductorConfig.sync_offset_ms` are measured on one body, starting from closed each time,
and recorded in `docs/results/<date>-calibration-<body>.md`. Billy Bass #2 and the hat need
their own. The steps are in the README.

## Where to look when something breaks

| Symptom | Look at |
|---|---|
| Fish does not move | The board's LEDs first: LED4 green must blink (MCU alive), the matrix must move with speech (MCU got the commands: then look after the MCU, at drivers and power). The `[turn]` line's `link=` and any `[link] MCU silent`. With the service stopped: `--check-link` (says whether the MCU answers) and `tools/fw_check.py check --release-router`. These tools refuse while a fish holds the port |
| Mouth out of sync | The `[turn]` line (`play_start`); `sync_offset_ms` |
| "no te entendí" every time | The level meter in the page; the selected source (`wpctl status`); `silence_rms`. With the phone's microphone: the `[utt]` line (rate, seconds, bytes) and the ring on the target; `?mic=host` brings the board microphone back |
| No "Activar micrófono" button on the phone | The page is not a secure context: plain http, or the certificate warning not accepted; the hold still records with the board microphone |
| The badge is never read | The `[reading]` line: `offline`, `misconfigured` (the profile has no image input, or no key); type the name in the field |
| Remote does nothing | `python -m fish_brain.evdev_button --list` and `--watch`; the start-up line `ptt=` |
| Says "no signal" every turn | The `[cloud]` and `[llm]` lines name the error; keys in `.env` |
| Bridge transport silent | `nc 127.0.0.1 7500`; router error 2 means no sketch registered the method |
| Service keeps stopping | `journalctl --user -u fish-brain`; exit status 78 means nothing can trigger a turn |

## Hard-won findings

Machine and tool facts only, each dated.

**Audio and speech**

- **A raw `hw:` device can record silence, and sounddevice indices change between boots**
  (2026-06-05). Pick a PipeWire source by name.
- **Whisper invents subtitles credits on silence** (2026-06-05): silent recordings are
  skipped, the voice filter is on, and known phrases are dropped.
- **`pynput` needs a display, and Enter-to-talk needs a terminal** (2026-10-10). Under a
  service neither exists; the program now exits with status 78 instead of failing each turn.
- **A reply starting with "-" was read by `loq` as an option** (2026-10-10): the text now
  follows `--`.
- **OpenAI's streamed WAV can carry a placeholder length** (reported; 2026-10-10): ask for
  `pcm` and write the header locally.
- **`gpt-transcribe` takes `languages=["es"]`, a list**, passed through `extra_body` with the
  pinned SDK (2026-10-10).
- **A bare number as the OpenAI client timeout also raises the connect timeout** (2026-10-10,
  SDK 2.41): use `openai.Timeout(read, connect=3)`.
- **A recording limit must also clear the button** (2026-10-10): otherwise a lost release
  starts one recording after another.
- OpenAI shuts down its speech models on 2027-01-06 and the older transcription models on
  2027-02-26 (announced; read 2026-10-10).

**UNO Q** (2026-10-10, router 0.10.0, core 0.55.2)

- **The USB-C cable decides whether the board becomes the USB host.** With one cable it
  stayed in device mode and `lsusb` was empty; with a newer one it worked at once. Check
  `/sys/class/typec/port0/data_role`.
- **Loquendo runs under Hangover Wine**: 8 s one-shot, 0.75 s with the daemon warm.
- **`arduino-cli upload` on the board needs no port and no password**, with the router up.
- **An unpinned `pip install` pulled PyAV 19, which breaks faster-whisper 1.2.1**, and the
  OpenAI SDK 3.x; both are now bounded in `pyproject.toml`.
- **Local speech-to-text takes the same time for a 3 s and a 6 s recording** (fixed 30 s
  window): `tiny` about 4 s, `base` 8 s, `small` 20 s or more.
- **The tested speaker at 40 % was inaudible to the microphone; at 100 % it was loud.**

- **`systemctl mask` fails for the router**: its units are real files in `/etc/systemd/system`.
- **Stopping the router resets the MCU and leaves it in the boot animation**: the loader
  waits for GPIO line 70, which the router raises.
- **The router's serial arguments are in a generated drop-in**, not in the unit.
- **`$/serial/close` releases the port**; while released, MCU methods are unregistered and a
  Bridge sketch that starts hangs in `Bridge.begin()`.
- **A router restart reopens the port and the other holder sees no error.**
- **The Linux link is `Serial2`. `Serial` is the Bridge monitor and blocks without the router.**
- **A notification to an unregistered Bridge method vanishes; a call returns error 2.**
- **Bridge sketches must use the default "Wait for Linux" start mode.**
- **Sketches may only call Zephyr functions exported in `syms-dynamic.ld`**
  (`k_thread_name_get` is not).
- **From router 0.11 the socket is `0660 root:arduino-router`.**
- **Every byte the MCU sends while the router owns the port is one error line in the router's
  journal** (2026-10-11): a sketch that prints unprompted floods it. Keep the port released
  while a chatty sketch is flashed.
- **The core's `portInputRegister()` does not compile** (2026-10-11); take the port block
  from the Zephyr GPIO device (see `tools/sketches/pwm_probe`).
- **PWM is 500 Hz and a duty change waits for the next period**: 0 to 2 ms from
  `analogWrite` to the pin (2026-10-11). Direction pins change at once.
- **At MCU reset D8 (PB4) is pulled high and D2 (PB3) is in a debug function**; the other
  header pins used by the fish float (2026-10-11).
- **`pinMode` before `analogWrite` does not break PWM on core 0.55.2** (2026-10-11, D9/D10).
- **The HDMI display needs its own power and must be on before the board boots**
  (2026-10-11); on the shared power bank the board did not see it at all.
- **Without linger the user manager, and PipeWire with it, stops 10 s after the last ssh
  logout**; after it starts, the USB speaker is the default output only 3 s later.
- **The kiosk browser is the whole cost of the display** (2026-10-11): with it closed the board
  idles at under 2 % CPU, Xorg at 0.4 %, and the hottest zone drops from 68 C to 48 C in four
  minutes; the LightDM session and the supervisor are below the noise.

**This desktop and the assistant's environment**

- **Wine does not work here** (NVIDIA; his word, 2026-10-10). `loq` crashes and puts error
  windows on his screen.
- **The assistant cannot read `.env` or any `.env.*`**, which includes `.env.example`
  (2026-10-10). The board's example is `deploy/env.unoq.example` for that reason; changes to
  `.env.example` are shown to him in the chat.
- **`~/.ssh` is unreadable to the assistant, but `ssh arduino@segunda.local` works**
  (2026-10-10).

## Parked

Nothing here is started or extended without his word.

| What | State |
|---|---|
| `gui/` | June prototypes, replaced by `fish_brain/web/` |
| Bridge transport | Written and unit-tested; not the default until a Bridge build of the firmware exists |
| Motors on the UNO Q | Braintip Phase 5 (the Phase 4 firmware is flashed since 2026-10-11) |
| The page on the board's display (`kiosk.py`, `deploy/kiosk/`, `tests/test_kiosk.py`, `FISH_KIOSK_*`; `FISH_VIZ_TRUST_LOCAL` stays for the tunnel) | Works (ADR 0005, replaced by 0006); not taken to the fair; needs the plain-http listener |
| Local STT fallback when offline; Moonshine | Idea only |
| Replacing OpenAI speech | After the fair, before 2027-01-06 |

## Quick reference

- **Before any `braintip` change:** [`docs/BRAINTIP.md`](docs/BRAINTIP.md)
- **Before touching the link or the router:** [`docs/UNOQ_BRIDGE_RPC_EXPLAINED.md`](docs/UNOQ_BRIDGE_RPC_EXPLAINED.md), [ADR 0001](docs/adr/0001-release-the-uart-through-the-router.md)
- **Before touching the page, the phone or the reading:** [`docs/viz.md`](docs/viz.md), [ADR 0006](docs/adr/0006-the-phone-is-the-interface.md), [ADR 0007](docs/adr/0007-the-reading.md)
- **Board set-up:** [`deploy/README.md`](deploy/README.md) · **Sketches:** [`tools/sketches/README.md`](tools/sketches/README.md)
- **Decisions:** [`docs/adr/`](docs/adr/) · **Measurements:** [`docs/results/`](docs/results/)
- **User guide:** [`README.md`](README.md)
