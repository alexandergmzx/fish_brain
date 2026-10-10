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

## Status (as of 2026-10-10)

| Item | State |
|---|---|
| Laptop fish (Billy Bass #1, Uno R4) | Working since June 2026 |
| `braintip`: software for the UNO Q | Written 2026-10-10; not yet run on the board |
| Board: USB hub, speaker, remote | Not attached yet; Braintip Phase 1 checks wait for them |
| MCU firmware for the UNO Q, motors | Braintip Phases 4 and 5; not started, not in this repo |
| Fair | **2026-10-17**. Billy Bass #2 first; the Sorting Hat only if it arrives |

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
[hold a button] → mic → speech-to-text → LLM (persona + history) → text-to-speech → WAV
   → loudness envelope → mouth pulses  +  text-driven neck/tail gestures
   → play audio and stream commands on one clock → the fish speaks → listen again
```

The whole command schedule is computed from the finished WAV, then audio and commands run
together.

| Part | What it does | Where |
|---|---|---|
| Push-to-talk | Keyboard key, browser button, or a remote's button; a fresh press starts a recording, a 15 s limit ends a stuck one | [`ptt.py`](fish_brain/ptt.py), [`evdev_button.py`](fish_brain/evdev_button.py) |
| Speech-to-text | `local` faster-whisper, or the recording uploaded to `openai` / `groq` | [`stt.py`](fish_brain/stt.py) |
| LLM | Profiles `groq` (GPT-OSS-20B) and `luna` (GPT-6 Luna); bounded history; fallback line on error | [`llm.py`](fish_brain/llm.py), [`ab.py`](fish_brain/ab.py) |
| Cloud plumbing | One client per service, short timeouts, a background "is the internet there" flag, two error types | [`cloud.py`](fish_brain/cloud.py) |
| Text-to-speech | `loq` (Loquendo "Jorge") or `openai`; always a WAV file, never played here | [`tts.py`](fish_brain/tts.py) |
| Canned phrases | welcome, goodbye, no_signal, no_mic; cached by text and voice; an older rendering is used when a new one can't be made | [`canned.py`](fish_brain/canned.py) |
| Mouth | WAV → openness (0..1) → timed pulses through measured curves | [`envelope.py`](fish_brain/envelope.py) |
| Gestures | Head out on words, home on sentence ends; tail flaps | [`gestures.py`](fish_brain/gestures.py) |
| Conductor | Plays the audio and sends each command at its time | [`conductor.py`](fish_brain/conductor.py), [`speak.py`](fish_brain/speak.py) |
| Motor link | pyserial, or MessagePack-RPC through the UNO Q's router; a mock for `--dry-run`; a wrapper that keeps the fish talking without motors | [`serial_link.py`](fish_brain/serial_link.py), [`router_rpc.py`](fish_brain/router_rpc.py) |
| Turn loop | One turn in stages; no error inside a turn ends the loop | [`conversation.py`](fish_brain/conversation.py) |
| On-screen fish | Browser view with hold-to-talk, mic picker, transcript | [`viz.py`](fish_brain/viz.py), [`web/`](fish_brain/web/), [`docs/viz.md`](docs/viz.md) |
| Entry point | Flags, start-up checks, one-shots | [`app.py`](fish_brain/app.py) |

Other repos. **They stay untouched; this repo only calls them.**

| Repo | Role | Touched via |
|---|---|---|
| `~/Development/Big_mouth` | Firmware, Uno R4 WiFi: executes motor commands. Pins: its `include/Config.h` | Serial, 115200 baud |
| `~/Development/loquen_hack` (laptop), `loq_winer` (board) | `loq`, the Loquendo voice | `loq -o FILE.wav -- "texto"` |

## Targets and hosts (measured 2026-10-10)

| | Laptop (Linux Mint) | UNO Q `segunda` (`ssh arduino@segunda.local`) |
|---|---|---|
| Python | 3.12 in `.venv` | 3.13.5; needs `python3-venv python3-dev gcc libportaudio2` from apt |
| Motor board | Uno R4 WiFi on `/dev/ttyACM0` | STM32U585 on `/dev/ttyHS1` (`root:dialout`), owned by `arduino-router` 0.10.0 |
| MCU core | — | `arduino:zephyr` 0.55.2: the Linux link is `Serial2` |
| Audio | PipeWire with `pactl` | PipeWire as user services, no `pactl` (`wpctl`, `pw-dump`); own sound card besides USB |
| Voice | `loq` under Wine. **Wine does not work on this desktop (NVIDIA): never run `loq` or any `.exe` here** | Hangover Wine + Loquendo installed, untested |
| USB | — | Needs a hub with its own power input; none attached yet |

Bodies: Billy Bass #1 (laptop, calibrated June 2026), Billy Bass #2 (fair, not calibrated),
Sorting Hat (maybe). Full board notes:
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
| Speech backends | By environment; laptop defaults are local STT and `loq` (ADR 0003) | 2026-10-10 |
| LLM | Profiles; `groq` in code, `luna` on the board (ADR 0004) | 2026-10-10 |
| `master` | Untouched. On `braintip` the laptop must still run with no environment set | 2026-10-10 |

Not decided: the fair voice; whether `loq` runs on the board; the remote and its key; a tamer
set of canned phrases and the generated-voice notice; local STT when offline.

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
| [`tools/`](tools/) | yes | `uart_check.py` (link soak test), `unoq_checks.sh` (board checks), `sketches/` (two MCU test sketches, not the fish firmware) |
| [`deploy/`](deploy/) | yes | The unit, the board set-up script, the board's example environment. **The repo is the source of truth for the board: never hand-edit it without the same change here** |
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
- Set `FISH_VIZ_TOKEN` whenever the page listens on `0.0.0.0`.
- The switches that differ between targets: `FISH_SERIAL_PORT`, `FISH_SERIAL_TRANSPORT`,
  `FISH_SERIAL_REQUIRED`, `FISH_STT_BACKEND`, `FISH_TTS_BACKEND`, `FISH_LLM_PROFILE`,
  `FISH_PTT_DEVICE`, `FISH_PTT_KEY`, `FISH_PTT_MODE`, `FISH_VIZ_HOST`, `FISH_WELCOME_ONCE`,
  `FISH_VOICE_QUIT`. Full list: README and [`deploy/env.unoq.example`](deploy/env.unoq.example).

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

# laptop, no hardware (cloud voice, so Wine is not involved)
.venv/bin/python -m fish_brain.app --dry-run --text --no-audio --tts openai   # type a turn; expect TX lines and a [turn] line
.venv/bin/python -m fish_brain.app --dry-run --echo --viz --tts openai        # hold the button in the browser, it repeats you
.venv/bin/python -m fish_brain.ab --no-vote                                   # both LLM profiles: latency and cost

# laptop with the fish (his to run: uses loq and motors)
python -m fish_brain.app
python tools/uart_check.py --port /dev/ttyACM0 --expect any --count 300

# board, as arduino in ~/fish_brain
deploy/unoq_setup.sh install      # prints the sudo lines for him; venv, canned phrases, link check
deploy/unoq_setup.sh service      # install and start the user unit
deploy/unoq_setup.sh status
tools/unoq_checks.sh              # the Braintip Phase 1 table
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
| Fish does not move | `--dry-run` output; `--check-link`; `tools/uart_check.py`; the start-up line `link=`; on the board, whether the router gave up the port |
| Mouth out of sync | The `[turn]` line (`play_start`); `sync_offset_ms` |
| "no te entendí" every time | The level meter in the page; the selected source (`wpctl status`); `silence_rms` |
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
| Firmware for the UNO Q MCU; motors on it | Braintip Phases 4 and 5 |
| Local STT fallback when offline; Moonshine | Idea only |
| Replacing OpenAI speech | After the fair, before 2027-01-06 |

## Quick reference

- **Before any `braintip` change:** [`docs/BRAINTIP.md`](docs/BRAINTIP.md)
- **Before touching the link or the router:** [`docs/UNOQ_BRIDGE_RPC_EXPLAINED.md`](docs/UNOQ_BRIDGE_RPC_EXPLAINED.md), [ADR 0001](docs/adr/0001-release-the-uart-through-the-router.md)
- **Before touching the page:** [`docs/viz.md`](docs/viz.md)
- **Board set-up:** [`deploy/README.md`](deploy/README.md) · **Sketches:** [`tools/sketches/README.md`](tools/sketches/README.md)
- **Decisions:** [`docs/adr/`](docs/adr/) · **Measurements:** [`docs/results/`](docs/results/)
- **User guide:** [`README.md`](README.md)
