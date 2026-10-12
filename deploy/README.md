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
| 12 | board | script, then **you** | `deploy/unoq_setup.sh kiosk on`, then the two printed `sudo` lines | Parked ([ADR 0006](../docs/adr/0006-the-phone-is-the-interface.md)): the page on the board's own display. At the fair the page is on the operator's phone instead. |

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

On the hotspot, open the page from the phone at `http://segunda.local:8723/?token=<FISH_VIZ_TOKEN>`
or, where `.local` does not resolve, at `http://<board ip>:8723/?token=<FISH_VIZ_TOKEN>`.
An Android phone that is itself the hotspot most likely cannot resolve `.local` (its own network is
mobile data) and hands out a different `192.168.x.0/24` each time the hotspot is enabled: use the IP
form there. The board can say its address after the welcome (`FISH_SAY_ADDRESS=true`, once it lands);
from the laptop on the same hotspot, `ssh arduino@segunda.local hostname -I` prints it.
First measured hotspot turn: not yet (see the fair-day matrix, row 3).

Checks: `nmcli -f NAME,AUTOCONNECT-PRIORITY,DEVICE connection show`, `nmcli device wifi list`.

## HTTPS for the phone

A browser gives a page its microphone only in a secure context: `https://`, or `localhost`.
The console page over plain http can still drive the board's microphone (hold-to-talk), but
the phone's own microphone needs the HTTPS listener. Both listeners serve the same page; the
http one stays for the ssh tunnel, the parked kiosk and as the restart-free fallback.

```bash
deploy/unoq_setup.sh tls <hotspot ip>          # on the board: writes ~/.config/fish_brain/tls/segunda.{crt,key}
deploy/unoq_setup.sh tls --force <ip> [<ip>]   # a new certificate (the phone asks again)
deploy/unoq_setup.sh tls --local <ip>          # on the laptop instead; prints the scp line
```

It makes a self-signed certificate (RSA 2048, SHA-256, 820 days, `CN=segunda.local`, SAN
`segunda.local`, `localhost`, `127.0.0.1` and every IP given) with the board's own OpenSSL,
outside the synced tree (`sync` runs `rsync --delete`), directory 700 and files 600, and
refuses to overwrite one without `--force`. It never edits `.env`: it prints the three lines
(`FISH_VIZ_TLS_CERT`, `FISH_VIZ_TLS_KEY`, `FISH_VIZ_TLS_PORT`) for you to add, then
`systemctl --user restart fish-brain`. The journal then shows the `https://` address first,
and `/status` reports `"tls": true`. A certificate path that does not load makes the service
exit 78 (no restart loop): `deploy/unoq_setup.sh status` shows the path it looked at.

Per device, once (Chrome, Android or desktop; remembered 7 days, so accept again on fair
morning):

1. Open `https://<board ip>:8724/?token=<FISH_VIZ_TOKEN>`.
2. "Your connection is not private" → Advanced → Proceed (unsafe).
3. `Activar micrófono` → Allow.

Plan B without a certificate: `chrome://flags/#unsafely-treat-insecure-origin-as-secure` with
`http://<board ip>:8723`, then Relaunch. Plan C: the http page with the board's microphone.

The board's IP changes with every hotspot session (Android picks a new `192.168.x.0/24`), and
the hotspot phone cannot resolve `segunda.local`: an IP that is not in the certificate only
means the warning again, the page still works. With `FISH_SAY_ADDRESS=true` the fish says the
last two octets after the welcome. The laptop does resolve `segunda.local`, so there
`segunda.crt` can be installed as a trusted authority (it carries `CA:TRUE` for that) and the
warning goes away for good.

## Parked: the fish page on the board's own display (kiosk)

Not used at the fair since [ADR 0006](../docs/adr/0006-the-phone-is-the-interface.md): the
browser on the board costs 1.1 to 1.3 cores and about 13 C ([results](../docs/results/2026-10-11-kiosk-display.md)).
With no display attached nothing of it runs. Kept for a stand with mains power.

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
| The fish in the sea and a blue button | Working | — |
| "El pez está despertando…" with a counter | The display works, `fish-brain` does not answer on port 8723 | `systemctl --user status fish-brain`, the journal; exit status 78 = a wrong line in `.env` |
| Solid dark blue | The session runs, the browser has not started | `deploy/unoq_setup.sh kiosk status`, `journalctl -t fish-kiosk` |
| The login screen | The kiosk session ended | `sudo systemctl restart lightdm` |
| "No signal" | The board does not see the display | Power the display first, then the board; `FISH_KIOSK_MODE=1280x720` in `.env` if it is seen but dark |

The button is grey ("Ahorita vuelvo…") while the page has no connection to the fish, lilac
for the instant before the host records, coral while it records, amber while the fish thinks,
green while it speaks; each state also has its words and its drawing. A press that cannot be
taken (the fish is speaking, a tap that was too short) makes the button shake.

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

Run it on battery, on the phone hotspot, with the speaker, the microphone and the phone the
fair will use; no display. Keep
`journalctl --user -u fish-brain -f` open in an ssh session. "Board LEDs" are the MCU's
matrix (three lanes: mouth nearest the USB-C connector, neck, tail) and LED4 (green
heartbeat, blue per command).

| # | Test | How | Pass |
|---|---|---|---|
| 1 | Cold boot | Hotspot on, then power the board; touch nothing | The welcome plays; `[fish] link=serial /dev/ttyHS1 …` in the log; the phone opens the page and the pearl in the corner shell is green. Note the seconds from power to voice |
| 2 | Remote turn | Hold the remote's OK button, talk into the remote, release | The sign on the phone page reads "Te escucho…" then "Déjame pensar…" then "¡Escúchame!", and what was heard and the reply appear as speech bubbles; a `[turn]` line with five timings and `link=ok`; the mouth lane of the matrix moves with the voice |
| 2b | Phone turn, remote microphone | `?talk=1` on the page: hold the blue button, ask into the remote, release | Same as 2; no restart needed to fall back to this row from any other |
| 3 | Phone turn, phone microphone | `Activar micrófono` once, then as 2 with the phone held toward the visitor | Same as 2, plus an `[utt]` line; `?mic=host` brings row 2 back without a restart |
| 3d | The debug view | On the laptop: `http://<board>:8723/debug`; press OK on the remote; switch the remote to its mouse mode and press again | Each press shows in Inputs with its key; in mouse mode a red hint names `BTN_LEFT` (unless it is already in `FISH_PTT_KEY`); a turn fills the pipeline and the Turns table |
| 3b | The reading from the shell | Hold the corner shell until the sheet opens, `Foto del gafete`, photograph a badge | A tap on the shell only wobbles it; the sheet closes by itself; the fish asks "¿Tú eres X?" and the question shows as a bubble. With a failed read the sheet stays open on the name field |
| 3c | Small hands | A minute of tapping, dragging, pinching and long presses on the page | Nothing opens, scrolls, zooms or is selected; the sheet opens only on a held shell |
| 4 | Page without token | From a phone: `http://segunda.local:8723/` and press | Nothing is recorded or spoken |
| 5 | Turn time | Read five `[turn]` lines | Release-to-voice mostly under about 5 s |
| 6 | Hotspot data off | Mobile data off, ask something | "Se me fue la señal…" within about 10 s, about 2 s on the next tries |
| 7 | Hotspot back | Data on, ask something | `[cloud] online`, a normal answer, no restart |
| 8 | Hotspot gone at boot | Boot with the hotspot off, then turn it on | The fish starts anyway; answers once the board joins |
| 9 | Stuck press | `?talk=1`: hold the button for 20 s | One recording of at most 15 s; the button returns by itself |
| 10 | Press while it speaks | `?talk=1`: press during an answer | The button shakes; nothing is recorded |
| 11 | Service restart | `systemctl --user restart fish-brain` | Goodbye; the sign goes grey ("Ahorita vuelvo…") and the pearl red, then both come back by themselves; **no** second welcome |
| 12 | Clean stop | `systemctl --user stop fish-brain` | Goodbye; matrix dark except the ticks; the display shows the waiting page; `start` it again |
| 13 | Crash recovery | `systemctl --user kill -s KILL fish-brain` | Matrix dark within a second; back by itself; the first line of the new process is `STOP` |
| 14 | Router restart | `sudo systemctl restart arduino-router` mid-answer | The voice continues; the matrix shows the boot animation, then the ticks; `[link] router is back; released /dev/ttyHS1 again`; the matrix moves on the next answer |
| 15 | Tools under a running fish | `python -m fish_brain.app --check-link`, `tools/fw_check.py check --release-router` | Both refuse and name the holder; the matrix still moves on the next answer |
| 16 | Link missing | `systemctl --user set-environment FISH_SERIAL_PORT=/dev/ttyNOPE`, restart | The fish talks; `(degraded)` in the summary line; `[turn] … link=off`. Then `unset-environment FISH_SERIAL_PORT`, restart |
| 17 | Remote unplugged | Pull the remote's dongle, hold the page target and speak, replug | Noted: with the board's own input as fallback the recording is silence and the fish says nothing; the remote key is gone until the replug. Works again after the replug |
| 18 | Speaker replug | Pull and replug the speaker, ask | Sound returns without a restart (if not: restart, and note it) |
| 19 | Display attached by mistake | Boot with a display plugged in | The fish is the same; `deploy/unoq_setup.sh kiosk status`: the parked kiosk may start a browser, `kiosk pause` closes it |
| 20 | Phone stays on | Leave the phone untouched for 30 minutes (auto-lock off, on a power bank) | The pearl still green, the scene still moving; a turn works |
| 21 | "salir" | Say "salir" | Answered like any phrase; the fish stays on (`FISH_VOICE_QUIT=false`) |
| 22 | Soak | 30 minutes, a turn every minute or two | No restart, no growing delay, temperature steady |
| 23 | Battery | Full charge, a turn now and then | Runtime noted; longer than the fair shift |

If a row fails on the day: 3 → row 2 (`?mic=host`, no restart). The phone → the laptop on the
hotspot, or `ssh -L 8723:127.0.0.1:8723 arduino@segunda.local` and `http://localhost:8723/`.
14/16 → the fish still talks without motors. 6–8 → move the phone closer. Anything else →
`deploy/unoq_setup.sh status` and the log. Restarting `fish-brain` during the fair: ask first.

Measured so far, without motors: rows 13 and 15 by hand on 2026-10-11
(`docs/results/2026-10-11-unoq-firmware-leds.md`), row 2 once in echo mode
(`docs/results/2026-10-11-kiosk-display.md`). Everything else is open.
