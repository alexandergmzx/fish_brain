# braintip — fish_brain on the Arduino UNO Q

> Context for the `braintip` branch. Read this before changing code on this branch.
> As of 2026-10-10. Target date: the fair on **2026-10-17**.

## Goal

Run fish_brain **standalone on an Arduino UNO Q**: no laptop, on batteries, with the phone
hotspot as the only internet. The UNO Q's Linux side is the brain; its STM32U585 is the motor
executor, linked by a **native UART** (not the Arduino RPC Bridge).

Two bodies use this branch, in this order:

1. **Billy Bass #2** — the safe target for the fair.
2. **Spin Master Talking Sorting Hat** — only if it arrives in time. Hat build plan:
   [Talking Sorting Hat — Build Plan](https://claude.ai/code/artifact/c89fbc5e-f034-42ec-a0ea-ff3bd0394d16).

Work order: **software and firmware first, motors last.**

## Rules for this branch

- Keep `master` behavior working: laptop + Uno R4 over `/dev/ttyACM0` must still run.
  Put every UNO Q difference behind config / env vars, not hard-coded paths.
- The serial protocol stays the contract (see README "Serial protocol"). Same commands,
  same `\n` lines, 115200 baud. Only the port changes.
- Safety stays: `STOP` on exit/error, `MOUTH 0` after each utterance, 5 s firmware watchdog.
- Secrets only in `.env` (gitignored).

## Target hardware

| Part | Role | Notes |
|---|---|---|
| Arduino UNO Q (4 GB) | Brain + motor executor | Linux (Qualcomm QRB2210, Debian, aarch64) + STM32U585 (Zephyr core) |
| Powered USB-C dongle/hub with PD input | Power in, USB devices out | The UNO Q does **not** power the dongle; the dongle powers the board |
| USB-C power bank with PD + 3 A cable | Powers dongle → UNO Q | Separate from the motor pack |
| USB speaker | Audio out | On the dongle |
| USB remote with microphone | Guest mic + push-to-talk button | On the dongle |
| Phone hotspot | Internet for the OpenAI API | No laptop at the fair |
| TB6612FNG ×2 (later) | Motor driver | VM from AA pack, VCC 3.3 V, STBY high |
| AA pack (later) | Motor power | 3 AA ≈ 4.5 V or 4 AA ≈ 6 V |

Do **not** power the UNO Q from VIN or the 5 V pin: its USB-C port may stay in device mode and
the speaker/remote are not recognized. Arduino staff called that setup unsupported.

## What changes vs master

| Area | master (laptop) | braintip (UNO Q) | Status |
|---|---|---|---|
| Motor link | `/dev/ttyACM0`, USB-CDC to Uno R4 | `/dev/ttyHS1`, internal UART to the STM32 (LPUART1), 115200 | Phase 2 |
| `serial_link.py` | pyserial | Same code; set `FISH_SERIAL_PORT=/dev/ttyHS1`. Inbound is already ignored, so any boot text from the MCU is harmless | Phase 2 |
| Push-to-talk | `pynput` (needs a display) | Headless: `pynput` falls back to Enter. Add an **evdev** backend that reads the remote's button | Phase 3 |
| Mic | PipeWire source via `FISH_MIC_SOURCE` | Same if PipeWire/Pulse exists on the image; else ALSA default (code already falls back) | Phase 1 check |
| Playback | sounddevice → paplay/aplay | Same; default ALSA device = USB speaker | Phase 1 check |
| STT | faster-whisper `small`, local | Measure on the Cortex-A53; else OpenAI transcription | Phase 3 decision |
| TTS | `loq` (Loquendo under Wine, x86) | ARM64 port of `loq` not confirmed. Fallback: OpenAI TTS to WAV | Phase 3 decision |
| LLM | OpenAI chat | Same, over the hotspot | No change |
| `--viz` | `127.0.0.1:8723` | Required at the fair: the unit passes it and the page on the operator's phone is the interface (ADR 0006) | Phase 6 |
| Startup | Manual in a terminal | systemd service at boot | Phase 3 |
| Firmware | Big_mouth, PlatformIO, Uno R4 (`renesas-ra`) | Port to `arduino:zephyr:unoq` via arduino-cli; read commands from the internal UART | Phase 4 |

Doc drift to fix on the way: README says "ESP32-S3 firmware"; Big_mouth now targets the Uno R4 WiFi.

## Phase 1 — bring-up checks (mic, speaker, power)

Goal: prove the UNO Q sees the speaker and the remote's mic, and stays stable on battery.
Run on the UNO Q (ssh/adb shell). Fill in the results table at the end.

**1.1 Board basics**

```bash
uname -m                 # expect aarch64
cat /etc/os-release
python3 --version
free -h; df -h /
sudo usermod -aG audio,input,dialout "$USER"   # log out/in after
```

**1.2 USB devices appear**

```bash
lsusb                    # speaker, remote, hub should be listed
sudo dmesg -w            # in a 2nd terminal; replug each device and watch
```

Nothing in `lsusb` → the power path is wrong (board not powered through the PD dongle).

**1.3 Speaker**

```bash
sudo apt update && sudo apt install alsa-utils
aplay -l                                   # note the speaker's card id, e.g. [Speaker]
speaker-test -D plughw:CARD=<id>,DEV=0 -c 2 -t wav -l 1
alsamixer -c <id>                          # set a sane volume
```

**1.4 Mic (remote)**

```bash
arecord -l                                 # note the remote's card id
arecord -D plughw:CARD=<mic_id>,DEV=0 -f S16_LE -r 16000 -c 1 -d 5 /tmp/mic.wav
aplay -D plughw:CARD=<id>,DEV=0 /tmp/mic.wav
```

Some voice remotes only send audio while the voice button is held. Test both ways.

**1.5 Default devices** — `~/.asoundrc`, using card ids (numbers can change between boots):

```
pcm.!default {
  type asym
  playback.pcm "plughw:CARD=<id>,DEV=0"
  capture.pcm  "plughw:CARD=<mic_id>,DEV=0"
}
ctl.!default { type hw card <id> }
```

**1.6 Remote button (for push-to-talk)**

```bash
sudo apt update && sudo apt install evtest
ls -l /dev/input/by-id/        # stable path for the remote's keyboard device
sudo evtest                    # pick the remote, press the voice/mic button
```

Write down the device path and the `KEY_...` code. Phase 3 needs both.

**1.7 Sound server?**

```bash
pactl info || wpctl status     # PipeWire/Pulse present?
```

If neither exists, stay on plain ALSA. fish_brain already falls back to the default device.

**1.8 Power under load**

Use an inline USB-C meter between the power bank and the dongle.

```bash
uptime -s                                  # boot time before
sudo apt update && sudo apt install stress-ng
stress-ng --cpu 4 --timeout 600s &         # 10 min CPU load
# meanwhile, loop audio out + in:
for i in $(seq 1 60); do aplay /tmp/mic.wav; arecord -d 5 -f S16_LE -r 16000 -c 1 /tmp/loop.wav; done
uptime -s                                  # must match the first value (no reboot)
sudo dmesg | grep -iE "usb disconnect|reset|over-current|under-?voltage"
cat /sys/class/thermal/thermal_zone*/temp  # millidegrees C
ls /sys/class/typec/ 2>/dev/null           # PD info, if this board exposes it
```

Pass: same boot time, no USB disconnects/resets, audio never drops, meter voltage stays near 5 V.
Then time a full battery run with the loop above to estimate fair runtime.

**Results** (fill in)

| Check | Result | Notes |
|---|---|---|
| Speaker card id | `UACDemoV10` | Jieli "UACDemoV1.0", playback only, 48 kHz stereo (2026-10-10) |
| Mic card id | `Microphone` | RedOctane USB Microphone, mono 48 kHz. Not a remote: it has no button |
| Mic works without holding the button? | yes | It is a plain microphone, always live |
| Remote input device + KEY code | no remote | The speaker has media keys on `/dev/input/by-id/usb-Jieli_Technology_UACDemoV1.0_...-event-if02`; which button sends which key is not checked |
| PipeWire/Pulse present? | yes | PipeWire 1.4.2; `pactl` after installing `pulseaudio-utils` |
| 10 min load test passed? | not run | `tools/unoq_checks.sh --stress` |
| Voltage at meter under load | not measured | |
| Battery runtime (power bank model) | not measured | |

## Phase 2 — native UART, Linux ↔ STM32

Goal: raw `\n`-terminated lines between `/dev/ttyHS1` and the MCU, no RPC Bridge.

**2.1 Free `/dev/ttyHS1`** — the Arduino router owns it by default. Service names below are from
the Arduino forum; check yours first with `systemctl list-units | grep -i arduino`.

```bash
sudo systemctl stop    arduino-router.service arduino-router-serial.service arduino-r.service
sudo systemctl disable arduino-router.service arduino-router-serial.service arduino-r.service
sudo systemctl mask    arduino-router.service arduino-router-serial.service arduino-r.service
sudo lsof /dev/ttyHS1          # must print nothing
```

This disables App Lab and the Bridge. Undo with `unmask` + `enable`. Board/OS updates may re-enable it.
Port permissions: `/etc/udev/rules.d/99-arduino-hs1.rules`:

```
KERNEL=="ttyHS1", OWNER="arduino", GROUP="arduino", MODE="0660"
```

then `sudo udevadm control --reload && sudo udevadm trigger`.

**2.2 Which MCU serial object is the link** — LPUART1 (PG7/PG8), but its Arduino name depends on
the core version: `Serial1` on current releases, `Serial2` on newer ones (per the Arduino forum).
Users report a Zephyr boot banner on a UART at MCU reset (reports differ on which one), so both
ends must tolerate one garbage line after a reset.

**2.3 Echo sketch (MCU)**

```cpp
// LINK = MCU UART wired to Linux /dev/ttyHS1 (LPUART1).
// Serial1 on current core releases, Serial2 on newer ones — try both.
#define LINK Serial1

void setup() { LINK.begin(115200); }

void loop() {
  if (LINK.available()) {
    String line = LINK.readStringUntil('\n');
    line.trim();
    LINK.print("ACK ");
    LINK.println(line);
  }
}
```

Build and flash on the board (uses SWD via `remoteocd`, not the UART; confirm it still works with
the router masked):

```bash
arduino-cli compile -b arduino:zephyr:unoq uart_echo
arduino-cli upload  -b arduino:zephyr:unoq uart_echo
```

**2.4 Linux side test**

```bash
stty -F /dev/ttyHS1 115200 raw -echo
cat /dev/ttyHS1 &
echo "MOUTH 120 50" > /dev/ttyHS1      # expect: ACK MOUTH 120 50
```

Then a pyserial loop: 1000 lines at 33 Hz (fish_brain's max rate), count ACKs, measure round trip.
Keep it as `tools/uart_check.py`.

Notes from the developer's approach: _(fill in)_

## Phase 3 — fish_brain running on the UNO Q

**3.1 Install**

```bash
sudo apt update && sudo apt install python3-venv libportaudio2 alsa-utils git
git clone <repo> ~/fish_brain && cd ~/fish_brain && git checkout braintip
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env    # OPENAI_API_KEY, FISH_SERIAL_PORT=/dev/ttyHS1
python -m fish_brain.app --dry-run --text --no-audio    # first smoke test
```

faster-whisper's engine (ctranslate2) ships aarch64 wheels, so pip should not need to build it.

**3.2 Decide STT** — time a 5 s clip on the A53:

```bash
time python -c "from faster_whisper import WhisperModel as W; m=W('base',device='cpu',compute_type='int8'); print(' '.join(s.text for s in m.transcribe('/tmp/mic.wav',language='es')[0]))"
```

Try `tiny`, `base`, `small`. If too slow for a conversation, use OpenAI transcription
(`gpt-transcribe` is the current recommended model; `gpt-4o-mini-transcribe` also works).
Make it switchable: `FISH_STT_BACKEND=local|openai`.

**3.3 Decide TTS** — `loq` on ARM64 is unproven (see `loq_winer`). If it is not running by Phase 3:
OpenAI `gpt-4o-mini-tts` with `response_format="wav"`, saved to a file, so `envelope.py` and the
conductor work unchanged. Switch: `FISH_TTS_BACKEND=loq|openai`. Pre-render canned phrases while
online; they cache by text hash. OpenAI's policy asks to disclose that the voice is AI-generated.

**3.4 Push-to-talk from the remote** — new evdev backend: open `FISH_PTT_DEVICE`
(`/dev/input/by-id/...`), record while `FISH_PTT_KEY` is held. User must be in `input`.
Keep `--viz` hold-to-talk as the fallback.

**3.5 Offline behavior** — if the API call fails (hotspot drop), play a canned "no signal" phrase
and re-listen. Never crash the loop.

**3.6 Autostart** — `/etc/systemd/system/fish-brain.service`:

```ini
[Unit]
Description=fish_brain
After=network-online.target sound.target
Wants=network-online.target

[Service]
User=arduino
WorkingDirectory=/home/arduino/fish_brain
EnvironmentFile=/home/arduino/fish_brain/.env
ExecStart=/home/arduino/fish_brain/.venv/bin/python -m fish_brain.app
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

A system service does not see a user's PipeWire session; use ALSA defaults, or a user service
with lingering. Save the phone hotspot as a known WiFi network and confirm it reconnects on boot.

Pass: press the remote button, ask, hear the answer — laptop unplugged, on battery, via hotspot.
Log the time per stage (record, STT, LLM, TTS, playback start).

## Phase 4 — firmware port (Big_mouth → UNO Q MCU)

Use a `braintip` branch in Big_mouth too.

| Change | Detail |
|---|---|
| Build | arduino-cli `arduino:zephyr:unoq` instead of the PlatformIO `uno_r4_wifi` env |
| Command input | `main.cpp` reads from the link object (`Serial1`/`Serial2`, see 2.2), not USB `Serial` |
| `MotorControl.h` | Same IN1/IN2 + PWM model fits the TB6612FNG. **Remove `pinMode()` on PWM pins**: on the UNO Q it can break `analogWrite()` |
| PWM pins | Device tree enables PWM on D2, D3, D5–D13 (D20/D21 clash with I2C). Default ≈ 500 Hz. Pin 9 confirmed by a forum user; reports of trouble on 5 and 6. Test each pin before wiring |
| `Config.h` | New pin map for 3 channels: AIN1/AIN2/PWMA etc. Make it the only pin table |
| Watchdog | Keep `MAX_RUN_TIME` 5 s |

Pass: commands typed over `/dev/ttyHS1` (`MOUTH 150 100`, `STATUS`) get the firmware's normal
replies, and each PWM pin shows output on an LED or meter. No motors yet.

## Phase 5 — motors (later)

Billy Bass #2 first, then the hat. TB6612FNG: VM from the AA pack, VCC 3.3 V, STBY high,
common ground with the UNO Q, motor pack separate from the power bank. Before trusting the
TB6612FNG, measure each motor: under 1 A running and 3 A stall. Then the README calibration
(open/close curves, `sync_offset_ms`).

## Phase 6 — the phone as the interface; the reading (ADR 0006, 0007)

Decided 2026-10-11 after the display was measured (`docs/results/2026-10-11-kiosk-display.md`).
The board drives no display at the fair; the operator's phone is trigger, microphone and badge
camera. Stages, in order; each leaves the fish working with the board microphone through the
page, which works today:

| Stage | What | Evidence |
|---|---|---|
| 1 | The display unplugged and the board measured; a hotspot smoke test with today's code; token on `/events` and `/audio`, body caps, heartbeat, the inbox in `record_multi`; the console view `?console=1` | results files; level 0 and 2 |
| 2 | HTTPS listener behind `FISH_VIZ_TLS_*`; `deploy/unoq_setup.sh tls`; the owner's phone passes `isSecureContext` (the go/no-go for the phone microphone); the fish says its address | level 0, 2, 5 |
| 3 | The reading: `POST /badge` → `gpt-6-luna` → "¿Tú eres X?" → the answer is a turn; `reading_wait`, `reading_fail`; tamer welcome and goodbye | level 0, 1, 2, 5 |
| 4 | The phone's microphone: AudioWorklet → 16 kHz WAV → `POST /utterance` (`FISH_MIC_CAPTURE=browser`); dropped first if time runs out | level 0, 2, 5 |
| 5 | Rehearsal on battery on the hotspot with the fair phone; results; the fair matrix rewritten | level 5 |

Pass line: a cold boot with no display; a phone turn over the hotspot; a reading from a badge
photo to the fish asking the name; the phone's microphone over HTTPS.

## Phase 7 — board + phone only, a show that survives everything (2026-10-25)

After the fair failed ([post-mortem](results/2026-10-25-fair-postmortem.md)): only the UNO Q
and the phone at a show, failures hidden from visitors, a deterministic offline visit when
everything else is gone. His decisions (2026-10-25): audio USB, then a Bluetooth speaker on the
board, then the phone's speaker; the phone opens a subdomain of `alexander-gomez.com` with a
real certificate; keep Loquendo and fix the licence race; no show date, measurements first.

| Step | What | State |
|---|---|---|
| 0 | Protect and measure: the clean clips backed up; journald drop-in; licence experiment; his power plan E1–E6; the board's own Wi-Fi and Android on it; the name; a Bluetooth speaker; audio and mic failure measurements | clips, journald and licence done 2026-10-25/26; the rest open |
| 1 | The fish always comes up, stops, never speaks a bad render, leaves a record (ADR 0012–0014) | done on the board 2026-10-26; S1 and R1 open |
| 2 | The board's own Wi-Fi when no known network appears; the http paths | built 2026-10-26: fish-net, `fish-ap` on 2.4 GHz channel 6, his phone loaded the page; the certificate covers 10.42.0.1 |
| 3 | The scripted offline visit (`FISH_SHOW`), the clip library, nothing said about errors | on the board 2026-10-26 (ADR 0015), the Halloween season's lines |
| 4 | Sound always comes out: USB, Bluetooth, the phone | on the board 2026-10-26 (ADR 0016); a real USB pull and a real phone not yet |
| 5 | The visitor's voice always gets in: microphone failover to the phone | built 2026-10-26 (`pw-record`, `FISH_MIC_CAPTURE=auto`); with his press not yet |
| 6 | One name and a real certificate | open |
| 7 | The phone as the console; the everything-fails drill | the Show tab on the board 2026-10-26 (ADR 0017); the drill open |
| 8 | The fortune act for adults (ADR 0019): the birth date → the sign, the open dream, a tarot card, the cup, the animal, the moon and a magic word; the reading from the clips or from the model; the place as a setting; the adult register | built 2026-10-27 (`fortune.py`, `fortune_bank.py`, `fortune_run.py`, about 140 `fortune_*` clips); his look open; the house act's lines keep the kid register until his pass |
| 9 | Three tabs on the phone: Visit (the acts; the place and the fortune's deck and cup below them, moved from Settings 2026-10-27), Status (default), Settings (mode, hardware, volume, phone speaker, network); the badge photo off the page (ADR 0017 amended, ADR 0007 superseded on the page) | built 2026-10-27; his look open |

## Proposed config / env (not implemented yet)

| Variable | Example | Purpose |
|---|---|---|
| `FISH_SERIAL_PORT` | `/dev/ttyHS1` | Exists. Internal UART to the STM32 |
| `FISH_STT_BACKEND` | `local` / `openai` | STT choice |
| `FISH_TTS_BACKEND` | `loq` / `openai` | TTS choice |
| `FISH_PTT_DEVICE` | `/dev/input/by-id/...-event-kbd` | Remote input device |
| `FISH_PTT_KEY` | `KEY_...` | Remote button code from `evtest` |
| `FISH_VIZ_HOST` | `0.0.0.0` | Open `--viz` from the phone |

## Open questions

- Does `loq` run on the UNO Q yet?
- Does the remote's mic stream only while its button is held? Which key code?
- Is PipeWire/Pulse on the UNO Q image?
- `Serial1` or `Serial2` for the link on the installed core?
- Does `arduino-cli upload` still work with the router masked?
- Battery runtime of the power bank under load?

## References

- [UNO Q user manual](https://docs.arduino.cc/tutorials/uno-q/user-manual/)
- [Forum: manual control of ttyHS1 + router services](https://forum.arduino.cc/t/uno-q-how-to-achieve-manual-control-over-router-bridge-formed-using-uart2-ttyhs1-mpu-lpuart1-serial2-mcu-devices/1426989)
- [Forum: Serial / Serial1 / Serial2 / Monitor mapping](https://forum.arduino.cc/t/uno-q-serial-as-monitor-alias/1435776)
- [LPUART1 on PG7/PG8 ↔ /dev/ttyHS1 at 115200](https://github.com/ormastes/simple/pull/1654)
- [remoteocd (MCU flashing)](https://github.com/arduino/remoteocd)
- [Forum: USB port dead when powered from 5 V / VIN](https://forum.arduino.cc/t/uno-q-usb-port-not-working-if-board-powered-from-5v/1442207)
- [Forum: UNO Q power consumption](https://forum.arduino.cc/t/what-is-the-power-consumption-of-the-arduino-uno-q/1408753)
- [Forum: USB audio / ALSA on UNO Q](https://forum.arduino.cc/t/audio-output-support-in-arduino-app-lab-usb-sound-cards-alsa-on-uno-q/1424680)
- [Forum: pinMode vs analogWrite](https://forum.arduino.cc/t/uno-q-interaction-between-pinmode-and-analogwrite/1444761)
- [Forum: UNO Q PWM pins and frequency](https://forum.arduino.cc/t/arduino-uno-q-very-poor-pwm/1445321)
- [ctranslate2 aarch64 wheels](https://pypi.org/project/ctranslate2/#files)
- [OpenAI speech-to-text](https://developers.openai.com/docs/guides/speech-to-text)
- [OpenAI text-to-speech](https://developers.openai.com/docs/guides/text-to-speech)
- [TB6612FNG carrier specs](https://shop.pimoroni.com/en-nz/products/tb6612fng-dual-motor-driver-carrier)

## Corrections (2026-10-10)

Checked on the board (`arduino@segunda`) and against current sources. Where this section and
the text above disagree, this section is right.

| Topic | Above says | What is true |
|---|---|---|
| Branch | "the `braintip` branch" exists | Created 2026-10-10 from `text-driven-gestures` |
| Serial protocol pointer | README "Serial protocol" | That section does not exist; the contract is in `CLAUDE.md` |
| After each utterance | `MOUTH 0` | A full close pulse (`MOUTH <close_pwm> <ms>`), sent by the conductor |
| Router units (2.1) | `arduino-router.service arduino-router-serial.service arduino-r.service` | `arduino-router.service`, `arduino-router-serial.service`, `arduino-router-serial.path`; `arduino-app-cli.service` only `Wants=` the router. There is no `arduino-r.service` |
| `systemctl mask` (2.1) | Works | Fails on arduino-router 0.10.0: its units are real files in `/etc/systemd/system`. Works from 0.11 |
| Freeing `/dev/ttyHS1` | Stop and mask the router | Ask the router to let go: `arduino-router-cli '$/serial/close' /dev/ttyHS1` (undo: `'$/serial/open' /dev/ttyHS1`). fish_brain does this itself. The router keeps running, so the MCU keeps its "Linux is ready" signal |
| Stopping the router | Harmless | Its stop action drives GPIO line 70 low and resets the MCU; the sketch then waits in the boot animation until line 70 is high again |
| udev rule (2.1) | Needed | Not needed: `/dev/ttyHS1` is `root:dialout 0660` and `arduino` is in `dialout` |
| Link object (2.2, 2.3, Phase 4) | `Serial1` now, `Serial2` on newer cores | `Serial2` on every core from 0.55.0 (the board has 0.55.2). `Serial1` is D0/D1. `Serial` is the Bridge monitor: never use it in a raw-UART sketch |
| Boot banner (2.2) | May appear on the link | Zephyr's console is USART1 (D0/D1), not the Linux link. Still tolerate a stray byte around resets |
| Firmware replies (2.4, Phase 4) | `ACK ...` | The firmware echoes each character, prints a `> ` prompt, and has no ACK. Only the echo sketch answers `ACK <line>` |
| Groups (1.1) | `usermod -aG audio,input,dialout` | `arduino` is already in all three |
| `alsa-utils`, `evtest` (1.3, 1.6) | Install them | Already installed. Missing instead: `python3-venv python3-pip python3-dev gcc libportaudio2` |
| Sound server (1.7) | `pactl info` decides | PipeWire 1.4.2 + WirePlumber run as user services; `pactl` is not installed. Check with `wpctl status` |
| Default audio device | The USB speaker | The board has its own sound card. Pick the USB devices with `wpctl set-default` |
| Headless push-to-talk | `pynput` falls back to Enter | Without a display `pynput` cannot load, and without a terminal the Enter fallback cannot work. Use the remote (`FISH_PTT_DEVICE`) or `--viz` |
| Remote device path | `/dev/input/by-id/...-event-kbd` | The voice key is often on a separate node (`...-event-ifNN`). `FISH_PTT_DEVICE=auto` finds it by key code |
| STT model (3.2) | `gpt-4o-mini-transcribe` also works | Deprecated 2026-08-26, shut down 2027-02-26, with `whisper-1`, `gpt-4o-transcribe` and `gpt-4o-transcribe-diarize`. Use `gpt-transcribe`; it takes `languages=["es"]` (a list) |
| Local STT speed (3.2) | Try `small` | Measured: `small` 20 to 23 s, `base` 8 s, `tiny` 3.5 to 4.8 s per turn. A cloud backend, or `tiny` |
| TTS as WAV (3.3) | Save `response_format="wav"` | Ask for `pcm` and write the WAV header locally: the streamed WAV can carry a placeholder length |
| TTS model (3.3) | `gpt-4o-mini-tts` | Fine for the fair. All `/v1/audio/speech` models shut down 2027-01-06 |
| `loq` on the board (3.3) | Unknown | Works under Hangover Wine 11.9: 0.75 s per short sentence with the daemon warm, 8 s without |
| Power (target hardware) | A PD dongle and a 3 A cable | Confirmed the hard way: with one cable the port stayed in device mode; a newer cable fixed it |
| Flashing (2.3) | May need the router down | `arduino-cli upload -b arduino:zephyr:unoq <sketch>` on the board works with the router up, no password |
| Echo test (2.4) | To do | Done: 100 of 100 lines answered, 3.75 ms each |
| Install (3.1) | `pip install -e .` | Works after `apt update` and the apt line; PyAV and the OpenAI SDK are bounded in `pyproject.toml` because the newest versions break it |
| Unit (3.6) | System unit, `Restart=on-failure` | User unit with linger (PipeWire is per user), `Restart=always`, `KillSignal=SIGINT`; see `deploy/` |
| LLM | OpenAI chat, no change | Profiles: `groq` (GPT-OSS-20B) or `luna` (GPT-6 Luna); `FISH_LLM_PROFILE` |

## Corrections (2026-10-11)

| Topic | Above says | What is true |
|---|---|---|
| Motor driver (target hardware, Phases 4 and 5) | TB6612FNG ×2 at 3.3 V | L298N boards, as on Billy Bass #1, on the same pin numbers (owner, 2026-10-11). Inputs are driven at 3.3 V |
| Firmware home (Phase 4) | "Use a `braintip` branch in Big_mouth too" | Done: `unoq/BigMouthQ` there, one `main.cpp` for both boards, built on the board with `deploy/unoq_fw.sh` |
| `pinMode()` on PWM pins | Can break `analogWrite()` | Not on core 0.55.2 (measured on D9, D10). The firmware still gives the enables no `pinMode` |
| PWM pins | "reports of trouble on 5 and 6" | D3, D5 and D6 measured good: 500 Hz, duty right to 0.1 point; enables and direction pins do not disturb each other |
| Phase 4 pass line | Each PWM pin shows output on an LED or meter | Measured from the MCU by reading the pins back; see `docs/results/2026-10-11-unoq-firmware-leds.md` |
| Push-to-talk | A remote | The touch display on the board (ADR 0005) |
| Push-to-talk (2026-10-11, ADR 0006) | The touch display (ADR 0005) | The page on the operator's phone; the display parked |
| Mic (row above) | The board's PipeWire source | The remote's own microphone (2026-10-12): the RedOctane draws too much current and the phone's browser microphone is built but off |
| Push-to-talk key (2026-10-12) | The remote's voice key | The remote's OK button held (`KEY_ENTER`): the voice key reports only a 0.12 s tap on every node |
