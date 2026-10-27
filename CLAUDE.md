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

## Status (as of 2026-10-27)

| Item | State |
|---|---|
| Laptop fish (Billy Bass #1, Uno R4) | Working since June 2026 |
| `braintip`: software for the UNO Q | Runs on the board as `fish-brain.service` with linger since 2026-10-11: boots alone, welcome, real turns from the remote and from the page on a phone (`stt=openai llm=luna tts=loq`), about 4 s from release to voice on the home Wi-Fi (`rec=3.3s stt=0.6s tts=0.8s`, 2026-10-12). Not yet on the hotspot. Since 2026-10-11: no display, the phone page as the interface, HTTPS, the reading (ADR 0006, 0007 proposed). In echo mode (a unit drop-in) while the remote is being tuned |
| Board: hub, USB speaker, the 2.4 GHz remote | Working on a power bank. The remote (XING WEI, Nordic) is trigger and microphone (`FISH_PTT_DEVICE=name:XING WEI`, `FISH_PTT_KEY=KEY_ENTER`, `FISH_MIC_SOURCE=…XING_WEI…`); the RedOctane is out, it draws more current than the board gives (2026-10-12) |
| Board: Loquendo | Works; about 0.75 s per short sentence with the daemon warm. Since 2026-10-26 a start-up probe guards the licence (ADR 0013): `wlan0` scans with its own MAC, a bad probe restarts the voice on a fresh wineserver, else no live render. The 80 clean clips are backed up (`docs/results/2026-10-25-canned-backup.md`) |
| Board: MCU firmware | Big_mouth `braintip` (`unoq/BigMouthQ`) flashed 2026-10-11, no drivers attached: protocol transcript 122 of 122, pulses within 1 ms, 9,999 of 9,999 lines in a soak. LED matrix mirrors the nine L298 signals. PWM measured good on D3, D5, D6 |
| Board: bring-up script | `tools/unoq_bringup.sh`: all tests passed 2026-10-11 |
| Board: local speech-to-text | **Canary for recordings up to 6 s, Groq turbo above, `small` on the window when offline** (`FISH_STT_BACKEND=canary`, `FISH_STT_LONG=groq`; his word 2026-10-13 for this week's tests, from 62 push-to-talk takes: `docs/results/2026-10-13-unoq-stt-his-takes.md`). Canary 2.3 s and 21 % word errors on short takes, Groq turbo under 1 s and 7 % on long ones, `gpt-transcribe` 0.6 to 1.5 s and 4 % (held for the fair; its routing is not decided). In real turns Canary took 1.8 to 3.0 s for recordings of 1 to 2 s (2026-10-13); the Groq route not yet in a real turn. `/debug` → Switches flips backend and model without a restart |
| Board: while it thinks | **A burble at the release, short fillers, a 12 s limit** (ADR 0010, his word 2026-10-13: "I love this"). The burble (a synthesized bubble sound and one tail chain, never the mouth) starts 0.1 to 0.2 s after the recording ends; no burble = not heard. A filler of 1 to 2 s only when a stage is still running after 2.5 s of its own; at 12 s an apology and the turn is dropped. A short turn is burble, then the reply 2.3 to 2.8 s after release (`docs/results/2026-10-13-unoq-burble-and-fillers.md`). Not yet in a real turn: a filler since they were shortened, the apology, the reading, LLM mode. Open: whether the close pulse stays on a burble once drivers are wired |
| Board: push-to-talk | Hold the remote's OK button, talk, release (up to 45 s; the LLM is told when a hold was cut); the page on the phone drives the same recording as the backup. Both record through the remote's microphone (results 2026-10-12). The browser's own microphone over HTTPS (`FISH_MIC_CAPTURE=browser`) works from the laptop's Chrome, off on the board. The display and its kiosk are parked |
| Board: HDMI touch display | Unplugged since 2026-10-12 (ADR 0005 replaced by 0006): the browser cost 1.1 to 1.3 cores and 60 to 68 C; without it the board idles at 1 % and 41 to 44 C, a turn peaks at 30 % (results 2026-10-12). The LightDM session stays installed, it starts nothing |
| The reading (la lectura) | Built (ADR 0007, proposed): badge photo on the phone → `gpt-6-luna` through the board (4.3 to 6.7 s, 1163 image tokens, surnames split, accents restored: `docs/results/2026-10-11-reading-badge.md`) → the fish asks "¿Tú eres X?" → the answer is a turn. Since 2026-10-26 (ADR 0018, proposed) Claude reads first when `ANTHROPIC_API_KEY` is set and luna after it; Claude is built and unit-tested, not measured (key due 2026-10-27). Not yet tried with a real badge or on the phone. Since 2026-10-27 the badge photo and the look tick are off the operator's page (ADR 0019); the server side is parked, the typed name stays |
| Motors on the UNO Q (L298N), Billy Bass #2 calibration | Not started. Before wiring: 10 k pull-downs on D6, D3, D5 and on D7, D8 (D8 is pulled high in reset) |
| Fair | **2026-10-17/18: failed** (the hub enumerated nothing at the venue; the fish had been left disabled; the laptop fallback was untested): `docs/results/2026-10-25-fair-postmortem.md`. No next show date |
| Board + phone only (`docs/BRAINTIP.md` Phase 7) | On the board 2026-10-26: Phase 1 (licence guard, STOP watcher, bench mode, records); the scripted visit (`FISH_SHOW=auto`, ADR 0015); the phone as the console in English, in the study from `/face`, hardware he marks failed, one Mode control (ADR 0017); speaker routes USB → Bluetooth → phone and a `pw-record` capture (ADR 0016, `docs/results/2026-10-26-phone-console-and-audio-routes.md`); the motor link back since `arduino` joined `arduino-router`. **On the board 2026-10-27: the fortune act for adults** (ADR 0019, proposed: date → sign, the open dream, a tarot card, the cup, the animal, the moon, a magic word; the reading from the clips or from the model): 139 `fortune_*` clips rendered in 3 min 22 s at the first boot; a scripted act and a model act ran end to end through the page's routes with no error line, the model's reading in 7.2 s (`docs/results/2026-10-27-fortune-on-the-board.md`); Canary writes a spoken date as words or Roman numerals, never digits (`docs/results/2026-10-27-fortune-answers-canary.md`). The three tabs Visit · Status · Settings; the adult register; the house act's 143 kid lines wait for his pass. Not yet: his voice through a fortune. Next: his look on the phone; then slow uploads from the phone (4 to 26 s) and the remote's microphone sending zeros |

Ask before starting the next Braintip phase. Until the fair, prefer work that closes the fair
path over polishing one module. The phase list lives in `docs/BRAINTIP.md`; keep this table
short and overwrite it, never append to it.

## Safety — the host always stops the motors

The firmware has no current sensing. Its 5 s run limit is the only hard guard, and gesture
chains are not covered by it. So:

1. **`STOP` on every exit** (normal, Ctrl-C, exception, stop signal) and a full close pulse
   after every utterance. Enforced by the link's context manager, the conductor's `finally`,
   the SIGTERM handler in `app.py` and `KillSignal=SIGINT` in the unit. Never remove these.
   On the hat's cam (`FISH_MOUTH_MODE=gate`) there is no closed position: the end of an
   utterance is the `FISH_MOUTH_STOP` line (`0 1`, a coast, by default).
2. **During speech only timed `MOUTH <pwm> <ms>` pulses.** Held `MOUTH <n>` is for manual
   calibration.
3. **No motors unattended.** Nothing past `--dry-run` unless Alexander is at the fish. Tell
   him before the first real-motor run of any change.
4. **Link tests use motor-safe lines** (`PING <n>`, which the firmware answers
   "Unknown command").
5. **Never flash the MCU, change router units or drive GPIO 37/70 on the board** without his
   word. Those steps are his.
6. **Calibration pulses start from the closed position.** Not on the hat's cam, which has none
   (his word, 2026-10-17: no home position for now).
7. **During the fair, ask before restarting `fish-brain` or rebooting the board.**
8. **The debug view's motor tests, speaker test and restart are Alexander's to press** (ADR 0009:
   armed on the page for 60 s; a test is a validated timed stroke and its return, run by the
   turn loop; STOP is never armed). Claude tests them on the mock link only and never calls
   `/debug/motor`, `/debug/say`, `/debug/loop`, `/debug/voice` or `/debug/restart` against the
   board or the laptop fish (the loop makes sound; the voice render with `loq` is Wine here).

## What is in use

```
[hold on the phone page] → mic (the board's, or the phone's own over HTTPS) → speech-to-text
   → LLM (persona + history) → text-to-speech → WAV
   → loudness envelope → mouth pulses  +  text-driven neck/tail gestures
   → play audio and stream commands on one clock → the fish speaks → listen again
[typed name on the phone] → "¿Tú eres X?" → the answer is a turn   (ADR 0007; the badge photo left the page 2026-10-27)
[Fortune on the phone] → date, dream, card, cup, animal by voice → suspense → the reading from clips or the model   (ADR 0019)
```

The whole command schedule is computed from the finished WAV, then audio and commands run
together.

| Part | What it does | Where |
|---|---|---|
| Push-to-talk | Keyboard key, the page's hold button, or a remote's button; a fresh press starts a recording, `FISH_PTT_MAX_S` ends a long one and the LLM is told the visitor was still talking. With `FISH_MIC_CAPTURE=browser` the page records with its own microphone and uploads a 16 kHz WAV (`POST /utterance`), taken by the loop through one inbox like a board recording; a remote's press is relayed to the page in browser mode | [`ptt.py`](fish_brain/ptt.py), [`evdev_button.py`](fish_brain/evdev_button.py), [`viz.py`](fish_brain/viz.py) |
| Speech-to-text | `local` faster-whisper (optionally on an encoder window that follows the clip), `canary` (NVIDIA Canary through sherpa-onnx, for recordings up to 6 s; longer ones go to the services in `FISH_STT_LONG` while online, else to the local model), or the recording uploaded to `openai` / `groq`; the model loads in the background at start-up | [`stt.py`](fish_brain/stt.py) |
| LLM | Profiles `groq` (GPT-OSS-20B), `luna` (GPT-6 Luna), `claude` (Haiku 5.5) and `claude-sonnet` (Sonnet 5.5); each has a provider, and `make_conversation` picks the class; bounded history; fallback line on error. `reading.read_badge` turns a badge photo into a name with the first profile of `FISH_READING_PROFILE` that has a key and answers (empty = `claude`, then the LLM profile; `luna` and `claude` take images, `groq` does not) | [`llm.py`](fish_brain/llm.py), [`claude.py`](fish_brain/claude.py), [`ab.py`](fish_brain/ab.py) |
| Cloud plumbing | One client per service, short timeouts, a background "is the internet there" flag, two error types | [`cloud.py`](fish_brain/cloud.py) |
| Text-to-speech | `loq` (Loquendo "Jorge") or `openai`; always a WAV file, never played here | [`tts.py`](fish_brain/tts.py) |
| Canned phrases | welcome, goodbye, no_signal, no_mic, reading_wait, reading_fail, and the fillers and apologies of a waiting turn (`filler_first_*`, `filler_more_*`, `timeout_stt_*`); for the hat persona the show's `show_*` and the fortune's `fortune_*` lines too; cached by text and voice; an older rendering is used when a new one can't be made | [`canned.py`](fish_brain/canned.py) |
| Mouth | WAV → openness (0..1) → timed pulses through measured curves | [`envelope.py`](fish_brain/envelope.py) |
| Gestures | Head out on words, home on sentence ends; tail flaps | [`gestures.py`](fish_brain/gestures.py) |
| Conductor | Plays the audio and sends each command at its time | [`conductor.py`](fish_brain/conductor.py), [`speak.py`](fish_brain/speak.py) |
| Motor link | pyserial, or MessagePack-RPC through the UNO Q's router; a mock for `--dry-run`; a wrapper that keeps the fish talking without motors | [`serial_link.py`](fish_brain/serial_link.py), [`router_rpc.py`](fish_brain/router_rpc.py) |
| Turn loop | One turn in stages; no error inside a turn ends the loop. A recording the fish can use is answered at once with a burble (a synthesized bubble sound and one tail chain, never the mouth; no burble = not heard). While a voice turn waits the fish says short cached phrases (first after 2.5 s, then every 2 s of silence) and at 12 s it apologizes and listens again; each waiting stage runs in a worker, the loop's thread does the talking and the records (ADR 0010; `FISH_BURBLE=false` and `FISH_FILLER=false` = as before) | [`conversation.py`](fish_brain/conversation.py), [`burble.py`](fish_brain/burble.py) |
| The fortune act | The second act for adults (ADR 0019): `fortune.py` is the data and the parsers (the birth date to a sign, element and lucky number, never the year; 21 dream themes; the tarot's 22 major arcana as `DECKS`; the cup's shapes; the animal; the moon; the magic words; the `[ADIVINACIÓN: …]` tag; `BANNED` and `clean_reading`), `fortune_bank.py` its `fortune_*` lines and the model's adult rules, `fortune_run.py` the act itself (`FortuneRun`: one question at a time by voice, a narrower re-ask with a budget of two, Skip and End from the page; the ending from the clips, or from the model started before the suspense clip and dropped to the clips on any failure; its own `fortune.json`). The place (`FISH_PLACE`) is a setting | [`fortune.py`](fish_brain/fortune.py), [`fortune_bank.py`](fish_brain/fortune_bank.py), [`fortune_run.py`](fish_brain/fortune_run.py) |
| The page | `/` is the operator's page on his phone or a PC (ADR 0011, 0017): the debug view with the drawn hat showing what the fish does (pose and colour per state, the acts' stage and verdict, a shake where a turn died, the lamps of the lines sent) and three tabs first, Visit (the acts: New visitor, Fortune, the cue chips, the typed name; below them the place and the fortune's deck and cup) · Status (default on a phone) · Settings (mode, hardware, volume, phone speaker, network), a thumb bar (New visitor, hold to talk), the phone's microphone behind a switch. HTTPS as a second listener behind `FISH_VIZ_TLS_CERT` keeps the phone's screen on. The old visitor face is at `/face` until after the fair | [`viz.py`](fish_brain/viz.py), [`web/`](fish_brain/web/), [`docs/debug.md`](docs/debug.md), [`docs/viz.md`](docs/viz.md) |
| The debug view | `/debug` on a desktop: the bring-up checks (speaker, sink, microphone, remote, link, service), what each model is sent and answers, the log, every key of the remote, one record per turn, the lines sent and the bytes back, the board, hints; tests, switches for the running fish (echo or LLM, backends, gestures, motors muted; nothing survives a restart), and armed motor pulses and restart (ADR 0009) | [`debug.py`](fish_brain/debug.py), [`debug_state.py`](fish_brain/debug_state.py), [`debug_actions.py`](fish_brain/debug_actions.py), [`web/debug.*`](fish_brain/web/), [`docs/debug.md`](docs/debug.md) |
| Entry point | Flags, start-up checks, one-shots | [`app.py`](fish_brain/app.py) |

Other repos. **They stay untouched; this repo only calls them.**

| Repo | Role | Touched via |
|---|---|---|
| `~/Development/Big_mouth` | Firmware: executes motor commands. `main` = Uno R4 WiFi; branch `braintip` adds the UNO Q build (`unoq/BigMouthQ`), edited from here by his word of 2026-10-11, protocol unchanged. Pins: its `include/Config.h` | Serial, 115200 baud; flashed with `deploy/unoq_fw.sh` |
| `~/Development/loquen_hack` (laptop), `loq_winer` (board) | `loq`, the Loquendo voice | `loq -o FILE.wav -- "texto"` |

## Targets and hosts (measured 2026-10-10)

| | Desktop (Linux Mint, NVIDIA) | lapG7, the fair laptop (`ssh 192.168.1.66` at home; 2026-10-17) | UNO Q `segunda` (`ssh arduino@segunda.local`) |
|---|---|---|---|
| Python | 3.12 in `.venv` | Mint 22.3, 3.12.3 in `.venv`, pinned to the desktop's set | 3.13.5; needs `python3-venv python3-dev gcc libportaudio2` from apt |
| Motor board | Uno R4 WiFi on `/dev/ttyACM0` | none: the fallback is voice only (`FISH_SERIAL_PORT=/dev/null-no-motors`, always `--dry-run`) | STM32U585 on `/dev/ttyHS1` (`root:dialout`), owned by `arduino-router` 0.10.0 |
| MCU core | — | — | `arduino:zephyr` 0.55.2: the Linux link is `Serial2` |
| Audio | PipeWire with `pactl` | PipeWire with `pactl` and `wpctl` | PipeWire as user services, no `pactl` (`wpctl`, `pw-dump`); own sound card besides USB |
| Voice | `loq` under Wine. **Wine does not work on this desktop (NVIDIA): never run `loq` or any `.exe` here** | Intel GPU; `loq` works (2.4 s daemon start, 0.42 s a phrase), needs `LOQ_LTTS` (Loquendo under `Program Files`) | Hangover Wine + Loquendo: works, 0.75 s warm. Running `loq` on the board is fine |
| USB | — | not measured | Power bank into a hub, hub into the board. Speaker: Jieli "UACDemoV1.0". Microphone: RedOctane. PipeWire makes them the defaults |

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
| Debugging | A desktop view at `/debug` that shows the whole fish and may act: tests, and armed for 60 s motor pulses and a restart; with an empty token it is open to the whole hotspot (ADR 0009, proposed) | 2026-10-12 |
| The page at the fair | One page at `/` for the operator's phone, built from the debug view, with the hat as the at-a-glance display; visitors see no screen; the old face at `/face` until after the fair (ADR 0011, proposed, replaces 0008) | 2026-10-16 |
| The reading's model | `gpt-6-luna` through the board, strict JSON, the photo in memory only; measured 2026-10-11 | 2026-10-11 |
| The reading | A badge photo read by a vision model through the board (`luna`, or `claude` first when its key is set: ADR 0018, proposed); the fish asks the name by voice before telling the future; the photo lives in memory only; badge-only by default, a look line only with a consent tick (ADR 0007, proposed; superseded on the page 2026-10-27, the server side parked, the typed name stays) | 2026-10-11 |
| The fortune act | A separate act for adults from the Visit tab: every answer by voice with one narrower re-ask and a budget of two per act; day and month, never the year; 21 dream themes and mentalist vision lines; the Rider-Waite major arcana as data (a lotería deck later), the cup optional, the animal question, the moon and a magic word; the reading from the clips, or from the model started before the suspense clip and dropped to the clips on any failure; the adult register with `BANNED` and `clean_reading`; the place as a setting; `fortune_*` clips for the hat persona whatever `FISH_SHOW` says; its own state file (ADR 0019, proposed) | 2026-10-27 |
| Motor port | One holder at a time: a lock taken before the router is asked for anything | 2026-10-11 |
| Speech backends | By environment; laptop defaults are local STT and `loq` (ADR 0003) | 2026-10-10 |
| A waiting turn | A burble (sound and tail, never the mouth) at the release; short cached phrases while it waits, the first at 2.5 s; a turn dropped at 12 s with an apology (ADR 0010, proposed) | 2026-10-13 |
| LLM | Profiles; `groq` in code, `luna` on the board (ADR 0004); `claude` and `claude-sonnet` selectable through the Anthropic SDK, not the default (ADR 0018, proposed) | 2026-10-10 |
| `master` | Untouched. On `braintip` the laptop must still run with no environment set | 2026-10-10 |

Not decided: which cloud speech-to-text; local STT when offline; whether the LightDM session
stays installed with no display (to be measured). Decided 2026-10-10: the board's voice is
Loquendo (`FISH_TTS_BACKEND=loq`). Decided 2026-10-11: tamer welcome and goodbye for the fair.
Since 2026-10-27 the audience is adults (parties, spooky places, his parents' house, the
university); the house act's lines keep the kid register until his pass.

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
| [`tools/`](tools/) | yes | `sprite_clean.py` (clears a cut-out's leftovers from the on-screen sprites), `fw_check.py` (firmware checker: replies, timing, soak, one-line send), `stt_bench.py` (speech-to-text routes, local and online, timed and scored on a folder of clips; records clips from a terminal or from the remote), `uart_check.py` (link soak test), `unoq_checks.sh` (board checks), `unoq_bringup.sh` (board tests with PASS/FAIL), `sketches/` (MCU test sketches: two echo sketches and the pin probe; the fish firmware is in Big_mouth) |
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
- The page's drawing is original: nothing copied from the cartoon that inspired its look.
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
  `FISH_MIC_CAPTURE` (`host` on the laptop), `FISH_READING_PROFILE` (a list; empty = `claude`, then the LLM profile), `ANTHROPIC_API_KEY`,
  `FISH_READING_LOOK`, `FISH_SAY_ADDRESS`. Since 2026-10-12: `FISH_STT_MODEL_DIR`,
  `FISH_STT_WINDOW_S`, `FISH_STT_BEAM`, `FISH_STT_LONG`. Since 2026-10-13: `FISH_FILLER`,
  `FISH_FILLER_DELAY_S`, `FISH_FILLER_GAP_S`, `FISH_TURN_TIMEOUT_S`, `FISH_BURBLE`. Since
  2026-10-27 (ADR 0019): `FISH_FORTUNE_DECK` (`tarot`, `off`), `FISH_FORTUNE_CUP`,
  `FISH_FORTUNE_STATE`, `FISH_PLACE` (`casa`, `fiesta`, `universidad`, `otro`),
  `FISH_PLACE_TEXT`.

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
.venv/bin/python tools/stt_bench.py --self-test                          # expect all passed

# laptop, no hardware (cloud voice, so Wine is not involved)
.venv/bin/python -m fish_brain.app --dry-run --text --no-audio --tts openai   # type a turn; expect TX lines and a [turn] line
.venv/bin/python -m fish_brain.app --dry-run --echo --viz --tts openai        # hold the button in the browser, it repeats you; the fish's face is the default view; ?debug=1 the developer page
FISH_MIC_CAPTURE=browser .venv/bin/python -m fish_brain.app --dry-run --echo --viz --tts openai   # the browser's own microphone (localhost is a secure context)
FISH_READING_PROFILE=luna .venv/bin/python -m fish_brain.app --dry-run --text --no-audio --tts openai --read-badge foto.jpg   # the badge call alone, prints the JSON (needs the key; `claude` or `claude-sonnet` to try Claude)
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
deploy/unoq_setup.sh stt          # board: fetch the Canary speech-to-text model; prints the .env lines
deploy/unoq_setup.sh kiosk on|off|pause|resume|status   # parked (ADR 0005, replaced by 0006): the page on the board's display
deploy/unoq_fw.sh push | compile [--trace] | upload --by <who> | status | log   # from the laptop: MCU sketches
tools/unoq_checks.sh              # the Braintip Phase 1 table (what the board sees)
tools/unoq_bringup.sh             # usb, voice, speaker-to-mic loop, MCU link; expect "all tests passed"
.venv/bin/python tools/fw_check.py check --release-router   # firmware flashed, fish stopped; expect RESULT PASS
.venv/bin/python tools/fw_check.py send "MOUTH 120 50" --release-router   # one line, prints the reply
.venv/bin/python tools/uart_check.py --release-router      # needs the uart_echo sketch; expect 0 lost
.venv/bin/python tools/stt_bench.py run --clips DIR --cand fw:model=small --cand fw-window:model=small,window=10   # fish stopped; a table of seconds and word errors
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
| Anything | **`http://<fish>:8723/debug` first**: its hints name most of the rows below, the pipeline shows where the last turn died, Inputs shows every key the remote sends |
| Fish does not move | The board's LEDs first: LED4 green must blink (MCU alive), the matrix must move with speech (MCU got the commands: then look after the MCU, at drivers and power). The `[turn]` line's `link=` and any `[link] MCU silent`. With the service stopped: `--check-link` (says whether the MCU answers) and `tools/fw_check.py check --release-router`. These tools refuse while a fish holds the port |
| Mouth out of sync | The `[turn]` line (`play_start`); `sync_offset_ms` |
| "No te escuché bien" | The turn passed `FISH_TURN_TIMEOUT_S` while it was being transcribed: the `[turn] timeout: stt` line (in the LLM or the voice it is the lost-signal line and `timeout: llm` / `tts`); offline, a recording over about 10 s does. Or a filler was said and the transcript came back empty: `you> … (no te entendí…)`, outcome `not understood` |
| No burble after releasing the button | The fish did not take the recording: a tap, a silent recording (the `silence` outcome on `/debug`), or the microphone did not open. `FISH_BURBLE`; the `[turn]` line's `burble=` is the time from release to the sound |
| No phrase while it thinks | `FISH_FILLER`; the phrases must be rendered (`--prerender-canned`, the canned check on `/debug`): a missing one is skipped |
| "no te entendí" every time | The level meter in the page; the selected source (`wpctl status`); `silence_rms`. With the phone's microphone: the `[utt]` line (rate, seconds, bytes) and the ring on the target; `?mic=host` brings the board microphone back |
| No "Activar micrófono" button on the phone | The page is not a secure context: plain http, or the certificate warning not accepted; the hold still records with the board microphone |
| The phone's page says "no connection" while the desktop reaches the board | The phone and the board on one access point asking each other for a TDLS link: `journalctl -b \| grep TDLS`, and `fish-net` must have printed `tdls off on wlan0: OK`. Or the board between two access points: `journalctl -b -k \| grep -E "change mode\|BEACON-LOSS"`, `/usr/sbin/wpa_cli -i wlan0 status` for the BSSID (`docs/results/2026-10-27-home-wifi-drops.md`) |
| The badge is never read | The `[reading]` lines: `offline`, `misconfigured` (no profile with image input and a key; each skipped one is named once), `unavailable … trying luna` (Claude failed, luna took over); the line that answers ends `profile=`; type the name in the field |
| The fortune never starts | The `[fortune]` line: `lines not ready` (its question clips are still rendering, about 10 min at the first boot, estimate; Fortune is greyed and the canned check on `/debug` counts them), `visit open` (a house act is at its questions: finish it or force a house). `503 no fortune` from `POST /fortune` means the persona has no visit |
| Remote does nothing | `python -m fish_brain.evdev_button --list` and `--watch`; the start-up line `ptt=`. No burble and no line in the journal after `Unable to create stream: Timeout`: the fish is stuck on the microphone (2026-10-13), restart it |
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

**Claude** (2026-10-26, `anthropic` 2.3.0, API version 2026-10-21; checked offline, no key yet: no call, latency or accuracy is measured)

- **The SDK has no `temperature`, `top_p` or `top_k`**, and the API answers 400 to them: no profile sends one.
- **`anthropic.transform_schema` asserts on `{"type": ["string", "null"]}`**; the badge schema is rewritten to `anyOf` for Claude only (`claude.anthropic_schema`).
- **A client built with `api_key=` holds one credential and an explicit `base_url` beats `ANTHROPIC_BASE_URL`**; the key goes as `Authorization: Bearer`.
- **`import anthropic` takes 0.78 s on the desktop, `openai` 0.35 s**; the first Claude call logs `[claude] sdk imported in …` (the board's figure is not measured).
- **The SDK sleeps for any `Retry-After` (a 429 with 3600 asked for a 3600 s sleep) and `openai`'s stops at 60 s**: Claude clients run with `max_retries=0`. Both: [`docs/results/2026-10-26-anthropic-sdk-offline-checks.md`](docs/results/2026-10-26-anthropic-sdk-offline-checks.md).
- **Haiku 5.5 accepts `thinking: disabled` at effort `high` or below; Sonnet 5.5 answers 400 and takes `between_tools`.** A 400 that names `thinking` or `effort` is retried once without it.

**UNO Q** (2026-10-10, router 0.10.0, core 0.55.2)

- **The USB-C cable decides whether the board becomes the USB host.** With one cable it
  stayed in device mode and `lsusb` was empty; with a newer one it worked at once. Check
  `/sys/class/typec/port0/data_role`.
- **Loquendo runs under Hangover Wine**: 8 s one-shot, 0.75 s with the daemon warm.
- **Loquendo checks its licence against the adapter list the prefix's wineserver saw at its
  start** (2026-10-25). NetworkManager scans with a random MAC on `wlan0` (`ath10k_snoc` is not
  exempt), so a fish started before Wi-Fi connected spoke only "la licencia que posee no es
  válida para este ordenador" (4.52 s, replacing the phrase) until the wineserver ended.
  `loq --restart` alone does not clear it; `wineserver -k` does.
- **`arduino-cli upload` on the board needs no port and no password**, with the router up.
- **An unpinned `pip install` pulled PyAV 19, which breaks faster-whisper 1.2.1**, and the
  OpenAI SDK 3.x; both are now bounded in `pyproject.toml`.
- **Local speech-to-text takes the same time for a 3 s and a 6 s recording** (fixed 30 s
  window): `tiny` about 4 s, `base` 8 s, `small` 20 s or more.
- **The tested speaker at 40 % was inaudible to the microphone; at 100 % it was loud.**
- **faster-whisper's time on the board is its encoder over a fixed 30 s window** (2026-10-12):
  13.8 of about 17 s for `small`. `chunk_length` does not shorten it (each piece is padded
  back to 30 s); CTranslate2 takes shorter input when the encoder is called directly
  (`stt.transcribe_window`). `float32` is slower than `int8` on this CPU.
- **One decoding pass with beam 1 on a short window can loop** (2026-10-12): "No, nel." came
  back as "no, no, no, ..." for 34 s; a reply that compresses too well goes the stock way.
- **Canary and Moonshine lose one-word answers when the clip is cut tight** (2026-10-12):
  with a second of silence each side they come back. Parakeet guesses the language and
  answered short Spanish in English or with nothing.
- **The remote's OK button sends `BTN_LEFT` in its mouse mode and `KEY_ENTER` otherwise**
  (2026-10-13): a tool that listens for one of them hears nothing in the other mode.
- **Groq's free tier refuses a call every half second and none at one every 4 s**
  (2026-10-13, 192 calls); a bench must pace itself (`tools/stt_bench.py --gap`).
- **Takes under 1 s ("No, nel.") are 44 to 88 % word errors on every route**, online or
  local (2026-10-13).
- **`*.wav` is ignored by git and left out by `deploy/unoq_setup.sh sync`** (2026-10-13): a
  sound the fish needs is made on the machine that plays it (the burbles are synthesized
  into the cache), never shipped as a file.
- **A filler must be short** (2026-10-13): a 3 s phrase that started half a second before the
  transcript was ready held the reply back 3 s (echo at 6.5 s where 3.7 s was possible).
  The phrases are 0.9 to 1.9 s since, and each stage gets the delay of its own.
- **Loquendo speech does not tell speech models apart** (2026-10-12): 1.5 to 8 % word errors
  for nine candidates; the owner's voice spread them from 18 to 40 %.

- **Router 0.11 needs the `arduino-router` group** (2026-10-26): `apt dist-upgrade` brought
  0.10.0 → 0.11.0, the socket became `root:arduino-router` 0660, and the fish could no longer
  ask the router to release the port (motors silently off). Fix: `usermod -aG arduino-router
  arduino`, reboot.
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
- **The XING WEI remote's voice key is a fixed 0.12 s tap on every node**, however long it is
  held (2026-10-12); its OK button (`KEY_ENTER`), arrows and mute report real press and release,
  so the OK button is the hold-to-talk key. Its microphone mostly streams all the time (room
  floor 0.01 to 0.03 RMS, speech 0.10 and up) and sometimes goes to exact zeros (for a
  whole 164 s take and a 29-clip loop on 2026-10-12).
- **When the remote's microphone does not start, the fish hangs and cannot be stopped**
  (2026-10-13): PipeWire logged `set_hw_params: Connection timed out` on the XING WEI source
  40 minutes after its last use; the fish printed `PulseAudio: Unable to create stream:
  Timeout`, took no press for 90 minutes while `/status` said `listening: true`, and at the
  next restart ignored the stop signal until systemd killed it after 15 s: no `STOP` was
  sent. Not traced, not fixed. Look for `State 'stop-sigterm' timed out` in the journal.
- **The kiosk browser is the whole cost of the display** (2026-10-11): with it closed the board
  idles at under 2 % CPU, Xorg at 0.4 %, and the hottest zone drops from 68 C to 48 C in four
  minutes; the LightDM session and the supervisor are below the noise.
- **The home network's two access points share channel 149 and the board bounced between
  them** (2026-10-27): 14 "appears to change mode (expected VHT, found HT)" disconnects from the
  main router and 10 beacon losses on the weaker extender in one day, a few seconds offline
  each. The profile is held on the main router's BSSID since 2026-10-27 (`deploy/README.md`);
  `nmcli connection modify` needs no sudo on this image (`auth-polkit=false`).
- **A phone on the same access point asks the board for a TDLS direct link, `ath10k_snoc`
  cannot key it, and the phone's page says "no connection" while each attempt fails**
  (2026-10-27, every 10 to 30 s). `wpa_cli -i wlan0 set tdls_disabled 1` makes the supplicant
  discard the frames; its socket is open to `netdev`, so `fish-net` sets it after every client
  link (`docs/results/2026-10-27-home-wifi-drops.md`).

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
| Local STT fallback when offline | Idea only (the board's speech-to-text is local since 2026-10-12) |
| Moonshine, Parakeet as speech-to-text | Measured 2026-10-12, not chosen: Moonshine's Spanish models print a non-commercial licence; Parakeet fails short answers |
| Replacing OpenAI speech | After the fair, before 2027-01-06 |

## Quick reference

- **Before any `braintip` change:** [`docs/BRAINTIP.md`](docs/BRAINTIP.md)
- **Before touching the link or the router:** [`docs/UNOQ_BRIDGE_RPC_EXPLAINED.md`](docs/UNOQ_BRIDGE_RPC_EXPLAINED.md), [ADR 0001](docs/adr/0001-release-the-uart-through-the-router.md)
- **Before touching the page, the phone or the reading:** [`docs/viz.md`](docs/viz.md), [ADR 0006](docs/adr/0006-the-phone-is-the-interface.md), [ADR 0007](docs/adr/0007-the-reading.md), [ADR 0008](docs/adr/0008-the-phone-is-the-fishs-face.md)
- **Board set-up:** [`deploy/README.md`](deploy/README.md) · **Sketches:** [`tools/sketches/README.md`](tools/sketches/README.md)
- **Before touching the acts (the visit, the show, the fortune):** [ADR 0015](docs/adr/0015-the-scripted-visit.md), [ADR 0019](docs/adr/0019-the-fortune-act.md)
- **Before touching the debug view:** [`docs/debug.md`](docs/debug.md), [ADR 0009](docs/adr/0009-a-debug-view-that-acts.md), [ADR 0017](docs/adr/0017-the-show-tab.md)
- **Decisions:** [`docs/adr/`](docs/adr/) · **Measurements:** [`docs/results/`](docs/results/)
- **User guide:** [`README.md`](README.md)
