# Running fish_brain on the Arduino UNO Q

Always run `sudo apt update` before any `sudo apt install` on the board.

Everything needed to run the fish standalone on the board (`segunda`, `arduino@segunda.local`):
no laptop, phone hotspot, USB speaker, USB voice remote.

| File | What it is |
|---|---|
| `unoq_setup.sh` | One script for the whole setup. Never calls `sudo`; it prints root steps for you. |
| `env.unoq.example` | The board's `.env`. Copied to `~/fish_brain/.env` by `install` if none exists. |
| `fish-brain.service` | systemd **user** unit that runs the fish at boot. |
| `fish-mcu-ready.service` | systemd **system** unit, only for the optional "router off" setup. |

Every subcommand can be run again safely. `deploy/unoq_setup.sh` with no argument prints the list.

## The sequence

"You" = a step that needs your password, your API key or your hands. Everything else the script does.

| # | Where | Who | Command | What happens |
|---|---|---|---|---|
| 1 | laptop | script | `deploy/unoq_setup.sh sync` | Copies the repo to `arduino@segunda.local:fish_brain/` (not `.venv`, `.env`, `__pycache__`, `*.wav`). |
| 2 | board | script | `cd ~/fish_brain && deploy/unoq_setup.sh install` | First run stops and prints the `apt` line (and a `usermod` line if a group is missing). |
| 3 | board | **you** | `sudo apt update && sudo apt install -y …` (the printed line) | Installs `python3-venv`, `gcc`, `libportaudio2` and friends. |
| 4 | board | script | `deploy/unoq_setup.sh install` | Creates `.venv`, `pip install -e ".[unoq]"`, creates `.env`, then stops at the key gate (exit 2). |
| 5 | board | **you** | `nano ~/fish_brain/.env` | Set `OPENAI_API_KEY` and `FISH_VIZ_TOKEN`. |
| 6 | board | script | `deploy/unoq_setup.sh install` | Checks the internet, renders the canned phrases and checks the WAV files exist, runs the link check. |
| 7 | board | **you** | `sudo loginctl enable-linger arduino` | The user session (and so the fish) starts at boot with nobody logged in. Once. |
| 8 | board | script | `deploy/unoq_setup.sh service` | Installs the unit in `~/.config/systemd/user/`, enables it, starts or restarts it. |
| 9 | board | script | `deploy/unoq_setup.sh hotspot "<SSID>" "<password>"` | Saves the phone hotspot so the board joins it by itself. |
| 10 | board | **you** | `wpctl set-default <id>` (see Audio) | Picks the USB speaker and the remote's microphone. |
| 11 | laptop | script, **you** for the upload once drivers are wired | `deploy/unoq_fw.sh push`, `compile`, `upload --by <name>` | Puts the fish firmware (Big_mouth, branch `braintip`) on the MCU. Stop the fish first. |
| 12 | board | script, then **you** | `deploy/unoq_setup.sh kiosk on`, then the two printed `sudo` lines | The page on the board's own display (see the kiosk section). Optional. |

Step 1 without rsync on the board (it is not on the stock image) falls back to tar over ssh; that
copy does not remove files you deleted on the laptop. `rsync` is in the `apt` line of step 3.
Alternative to step 1 once the branch is pushed:
`git clone https://github.com/alexandergmzx/fish_brain ~/fish_brain && git -C ~/fish_brain checkout braintip`,
later `git -C ~/fish_brain pull --ff-only`.

After a code change: `sync` on the laptop, then `deploy/unoq_setup.sh service` on the board
(it restarts the fish). Re-run `install` only when dependencies, `.env` backends or the canned
phrases change.

Notes on `install`:

- It reads the backends from `.env` and asks only for the keys they need
  (`OPENAI_API_KEY` for `openai` STT/TTS and the `luna` profile, `GROQ_API_KEY` for `groq`).
- After `--prerender-canned` the script also checks the files themselves: one
  `~/.cache/fish_brain/canned/<name>-*.wav` for every name printed by `--list-canned`.
- The link check runs with `FISH_SERIAL_REQUIRED=true` for that one command, so a port that
  cannot open shows as a failure and not as "degraded". For `install` it is still only a
  warning: the service runs with `FISH_SERIAL_REQUIRED=false`, talks without motors and
  keeps retrying the link.
- No udev rule is needed: `/dev/ttyHS1` is `root:dialout 0660` and `arduino` is in `dialout`.
- `install`, `service`, `router release|restore` and `hotspot` refuse to run on a machine
  that is not the board (override: `FISH_FORCE=1`; even then `install` and `service` refuse
  unless `FISH_TTS_BACKEND=openai`, so the Wine voice never starts on the laptop).

## The service

`fish-brain.service` is a user unit, not a system unit, because the audio lives in the user
session: PipeWire and WirePlumber run as user services on this image, and the mic/speaker
defaults you set with `wpctl` belong to that session. Linger starts the session at boot.

| Setting | Why |
|---|---|
| `Type=exec` | A wrong path fails the start right away. |
| `Restart=always`, `RestartSec=3` | A clean exit must not leave the fish off (`on-failure` would). |
| `StartLimitIntervalSec=0` | Never give up restarting. |
| `RestartPreventExitStatus=78` | 78 = configuration error (no push-to-talk source). A restart would not fix it. |
| `KillSignal=SIGINT`, `TimeoutStopSec=15` | Stop = Ctrl-C: the goodbye phrase plays and `STOP` reaches the motors. |
| `PYTHONUNBUFFERED=1`, `PYTHONFAULTHANDLER=1` | Log lines appear at once; a native crash leaves a traceback. |
| no `EnvironmentFile=` | The app reads `.env` itself. systemd would reject `export` lines and keep inline comments in values. |
| `After=pipewire.service wireplumber.service` | Audio first. A user unit cannot wait for the network; the app handles being offline. |

The unit expects the repo at `~/fish_brain`. If it is somewhere else, `service` rewrites the two
paths while installing.

```bash
systemctl --user status fish-brain
systemctl --user restart fish-brain
systemctl --user stop fish-brain          # says goodbye, sends STOP
journalctl --user -u fish-brain -f        # live log
journalctl --user -u fish-brain -b        # everything since boot
deploy/unoq_setup.sh status               # units, router, who holds the port, groups, linger
```

In the log: one startup summary line (`[fish] link=serial /dev/ttyHS1 stt=… llm=… tts=… ptt=…`;
the link reads `serial /dev/ttyHS1 (degraded)` when the port could not open), one
`[turn] rec=… stt=… llm=… tts=… play_start=…` line per turn, `[link]` lines when the motor link
comes and goes, `[cloud] offline` / `[cloud] online`.

If the service will not stay up and the status shows exit code 78: no push-to-talk source was
found. Set `FISH_PTT_DEVICE` (see `python -m fish_brain.evdev_button --list`) or keep `--viz` in the
unit, then `systemctl --user restart fish-brain`.

Alternative, not shipped: a **system** unit with `User=arduino` and pure ALSA
(`FISH_MIC_DEVICE` / `FISH_SPEAKER_DEVICE` naming the ALSA devices). It needs no linger but loses
the PipeWire source selection, resampling and gain, and it fights the user session for the sound
card. Use it only if PipeWire under linger turns out unreliable.

## The router: release or off

`arduino-router` owns `/dev/ttyHS1`, the UART to the STM32. fish_brain needs that port for the
motor commands. Two ways to get it.

### Release (default, nothing to do)

fish_brain asks the router to let go of the port (`$/serial/close`) when it starts, watches for
router restarts and asks again, and hands the port back (`$/serial/open`) when it stops. The
router keeps running, so the MCU keeps running, flashing works, and no root is needed.

By hand:

```bash
deploy/unoq_setup.sh router release    # arduino-router-cli '$/serial/close' /dev/ttyHS1
deploy/unoq_setup.sh router restore    # arduino-router-cli '$/serial/open'  /dev/ttyHS1
```

The port argument is mandatory; the router rejects the call without it.

While the port is released:

- Bridge sketches and App Lab cannot reach the MCU (calls return error 2, notifications vanish).
- A Bridge sketch that boots during that time hangs in `Bridge.begin()`. After `router restore`,
  reset or reflash the MCU.
- The release is only in the router's memory. A router restart takes the port back without any
  error on our side; fish_brain notices over the router socket and releases it again.

### Off (optional, root)

Use it only if the release path misbehaves on fair day. `deploy/unoq_setup.sh router off` prints
the commands; it runs none of them. In order:

1. Create the flag file `/etc/fish_brain/router-off`.
2. Add the drop-in `90-fish-off.conf` (`ConditionPathExists=!/etc/fish_brain/router-off`) to
   `arduino-router.service`, `arduino-router-serial.service` **and**
   `arduino-router-serial.path`. Without the third one the path unit keeps starting the others.
3. `daemon-reload`, then stop the three units. This resets the MCU and it shows the boot
   animation.
4. Install and start `fish-mcu-ready.service`, which raises the "Linux is ready" line
   (gpiochip1 line 70) now and at every boot, so the sketch runs.

Then set `FISH_ROUTER_RELEASE=false` in `.env` and restart the fish. `router on` prints the exact
reverse.

Why not `systemctl mask`: arduino-router 0.10.0 installs its unit files in
`/etc/systemd/system/`. Masking works by putting a link to `/dev/null` at that same path, so it
fails with "File … already exists". Only router 0.11 and later (units in `/usr/lib`) can be
masked. `systemctl disable` is not enough either: the package turns the units back on at every
upgrade. The flag file plus drop-ins survives upgrades. Undo it with the commands that
`router on` prints, all of them: `fish-mcu-ready.service` conflicts with the router, so while it
stays enabled the router does not start at boot even with the flag file gone.

Why `fish-mcu-ready` is needed: when the router stops it drives line 70 low and pulses the MCU
reset. The MCU loader (default "Wait for Linux" mode) then loops the boot animation until line 70
is high again. With the router off, nobody else raises it.

| | Release | Off |
|---|---|---|
| Root needed | no | yes |
| Survives a router restart or upgrade | yes (watchdog re-releases) | yes |
| App Lab / Bridge sketches | work again after the fish stops | do not work |
| `FISH_SERIAL_TRANSPORT=bridge` | possible | not possible |
| Risk | a short overlap after a router restart | none from the router |

Router 0.11 and later: the socket becomes `0660 root:arduino-router`. `install` and `status` print
`sudo usermod -aG arduino-router arduino` when that group exists and you are not in it (takes
effect after a reboot).

## Audio: pick the speaker and the microphone

fish_brain plays and records through the session's default devices unless `.env` says otherwise.
Set the defaults once, with the USB speaker and the remote's dongle plugged in:

```bash
wpctl status                              # Sinks = outputs, Sources = microphones; * marks the default
wpctl set-default <sink id>               # the USB speaker
wpctl set-default <source id>             # the remote's microphone
wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.9
wpctl set-volume @DEFAULT_AUDIO_SOURCE@ 1.0
```

WirePlumber remembers the choice by device name, so it survives reboots and replugging; the ids
themselves change, so read them from `wpctl status` each time. Test without the fish:

```bash
pw-record --rate 16000 --channels 1 /tmp/mic.wav     # speak, Ctrl-C
pw-play /tmp/mic.wav
```

To pin a device in `.env` instead: `FISH_MIC_SOURCE=<PipeWire source name>` (shown by
`wpctl inspect <source id>` as `node.name`, or pick it in the web page's mic list) and
`FISH_SPEAKER_DEVICE=<part of the device name>`. `pactl` is not on the stock image; it comes with
`pulseaudio-utils` in the `apt` line.

## The phone hotspot

```bash
deploy/unoq_setup.sh hotspot "<SSID>" "<password>"           # save only
deploy/unoq_setup.sh hotspot "<SSID>" "<password>" connect   # save and switch now
```

It saves a NetworkManager profile named `fish-hotspot` with autoconnect priority 100 (preferred
over the home Wi-Fi), endless retries, and the password stored system-wide so it works at boot
with nobody logged in. No `sudo` on this image. Saving does not need the phone to be on and does
not drop your ssh session; `connect` (or `nmcli connection up fish-hotspot`) does drop it if you
came in over the home Wi-Fi.

On the hotspot, find the board from the phone at `http://segunda.local:8723/?token=<FISH_VIZ_TOKEN>`
(iPhone resolves `.local`; on Android use the board's IP from the hotspot's client list).

Checks: `nmcli -f NAME,AUTOCONNECT-PRIORITY,DEVICE connection show`, `nmcli device wifi list`.

## The fish page on the board's own display (kiosk)

An HDMI touch display on the hub shows the visitor view of the page (`/?kiosk=1`): the fish
at full height and one hold-to-talk target. Record: [ADR 0005](../docs/adr/0005-kiosk-on-the-board-display.md).

**Display first.** Give the display its own power (not the hub's power bank) and switch it on
**before** the board. Measured 2026-10-11: with the display fed from the shared bank the board
saw no display at all (`DP-1 disconnected`); on its own bank, attached at power-up, it came up
at 1920x1080 on two cold boots out of two. Plugging the display into a running board is not
reliable on this kernel.

**Set up, once.**

```bash
deploy/unoq_setup.sh kiosk on        # installs ~/.xsession (no sudo) and prints the next two lines
sudo install -D -m 644 /home/arduino/fish_brain/deploy/kiosk/50-fish-kiosk.conf /etc/lightdm/lightdm.conf.d/50-fish-kiosk.conf
sudo systemctl restart lightdm
```

The two `sudo` lines are the owner's. They make the board log `arduino` in by itself into a
bare X session that runs only the page: no desktop, no App Lab, no screen locker, and an X
server that never blanks. Undo:

```bash
sudo rm /etc/lightdm/lightdm.conf.d/50-fish-kiosk.conf && sudo systemctl restart lightdm
deploy/unoq_setup.sh kiosk off       # removes ~/.xsession
```

**What the screen shows.**

| On the screen | Meaning | Do |
|---|---|---|
| The fish and a round blue button | Working | — |
| "El pez está despertando…" with a counter | The display works, `fish-brain` does not answer on port 8723 | `systemctl --user status fish-brain`, the journal; exit status 78 = a wrong line in `.env` |
| Solid dark blue | The session runs, the browser has not started | `deploy/unoq_setup.sh kiosk status`, `journalctl -t fish-kiosk` |
| The login screen | The kiosk session ended | `sudo systemctl restart lightdm` |
| "No signal" | The board does not see the display | Power the display first, then the board; `FISH_KIOSK_MODE=1280x720` in `.env` if it is seen but dark |

The button is grey while the page has no connection to the fish, purple for the instant
before the host records, red while it records, amber while the fish thinks, green while it
speaks. A press that cannot be taken (the fish is speaking, a tap that was too short) makes
the button shake.

**Operator corner.** Five taps in the top-right corner within three seconds open the
controls of the normal page plus a status block (host, IP, link and MCU, internet, backends).
It closes by itself after 45 s.

**Other commands.**

```bash
deploy/unoq_setup.sh kiosk status    # display, root file, session, supervisor, browser
deploy/unoq_setup.sh kiosk pause     # close the browser (the fish keeps running)
deploy/unoq_setup.sh kiosk resume
ssh -L 8723:127.0.0.1:8723 arduino@segunda.local   # the same page on the laptop, as a local client
```

The browser on the board needs no token: `FISH_VIZ_TRUST_LOCAL=true` in `.env` lets requests
from the board itself through. Everything else on the network still needs `FISH_VIZ_TOKEN`.
With no display attached nothing of the kiosk runs, and the fish is the same.

## Fair-day test matrix

Run it on battery, on the phone hotspot, with the speaker, the microphone and the display the
fair will use, the display on its own power and switched on first. Keep
`journalctl --user -u fish-brain -f` open in an ssh session. "Board LEDs" are the MCU's
matrix (three lanes: mouth nearest the USB-C connector, neck, tail) and LED4 (green
heartbeat, blue per command).

| # | Test | How | Pass |
|---|---|---|---|
| 1 | Cold boot | Display on, then power the board; touch nothing | Waiting page, then the fish page; the welcome plays; `[fish] link=serial /dev/ttyHS1 …` in the log. Note the seconds from power to voice |
| 2 | Touch turn | Hold the round button, ask, release | Button red while the host records, amber while it thinks, green while it speaks; a `[turn]` line with five timings and `link=ok`; the mouth lane of the matrix moves with the voice |
| 3 | Phone turn | Phone on the hotspot, page with the token, hold to talk | Same as 2 |
| 4 | Page without token | From a phone: `http://segunda.local:8723/` and press | Nothing is recorded or spoken |
| 5 | Turn time | Read five `[turn]` lines | Release-to-voice mostly under about 5 s |
| 6 | Hotspot data off | Mobile data off, ask something | "Se me fue la señal…" within about 10 s, about 2 s on the next tries |
| 7 | Hotspot back | Data on, ask something | `[cloud] online`, a normal answer, no restart |
| 8 | Hotspot gone at boot | Boot with the hotspot off, then turn it on | The fish starts anyway; answers once the board joins |
| 9 | Stuck press | Hold the button for 20 s | One recording of at most 15 s; the button returns by itself |
| 10 | Press while it speaks | Press during an answer | The button shakes; nothing is recorded |
| 11 | Service restart | `systemctl --user restart fish-brain` | Goodbye; the page shows grey, then comes back by itself; **no** second welcome |
| 12 | Clean stop | `systemctl --user stop fish-brain` | Goodbye; matrix dark except the ticks; the display shows the waiting page; `start` it again |
| 13 | Crash recovery | `systemctl --user kill -s KILL fish-brain` | Matrix dark within a second; back by itself; the first line of the new process is `STOP` |
| 14 | Router restart | `sudo systemctl restart arduino-router` mid-answer | The voice continues; the matrix shows the boot animation, then the ticks; `[link] router is back; released /dev/ttyHS1 again`; the matrix moves on the next answer |
| 15 | Tools under a running fish | `python -m fish_brain.app --check-link`, `tools/fw_check.py check --release-router` | Both refuse and name the holder; the matrix still moves on the next answer |
| 16 | Link missing | `systemctl --user set-environment FISH_SERIAL_PORT=/dev/ttyNOPE`, restart | The fish talks; `(degraded)` in the summary line; `[turn] … link=off`. Then `unset-environment FISH_SERIAL_PORT`, restart |
| 17 | Microphone unplugged | Pull the microphone, hold and speak, replug | Noted: with the board's own input as fallback the recording is silence and the fish says nothing. Works again after the replug |
| 18 | Speaker replug | Pull and replug the speaker, ask | Sound returns without a restart (if not: restart, and note it) |
| 19 | No display | Boot with the display unplugged | Same summary line; a phone turn works; `deploy/unoq_setup.sh kiosk status` shows no browser |
| 20 | Screen stays on | Leave it untouched for 30 minutes | Still lit and responsive |
| 21 | "salir" | Say "salir" | Answered like any phrase; the fish stays on (`FISH_VOICE_QUIT=false`) |
| 22 | Soak | 30 minutes, a turn every minute or two | No restart, no growing delay, temperature steady |
| 23 | Battery | Full charge, a turn now and then | Runtime noted; longer than the fair shift |

If a row fails on the day: 2 → the phone page (3). 14/16 → the fish still talks without
motors. 6–8 → move the phone closer. The display → see the kiosk table above; the fish does
not need it. Anything else → `deploy/unoq_setup.sh status` and the log.

Measured so far, without motors: rows 13 and 15 by hand on 2026-10-11
(`docs/results/2026-10-11-unoq-firmware-leds.md`), row 2 once in echo mode
(`docs/results/2026-10-11-kiosk-display.md`). Everything else is open.
