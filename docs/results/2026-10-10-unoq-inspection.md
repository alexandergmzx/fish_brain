# UNO Q inspection — 2026-10-10

Host: the board `segunda` (`ssh arduino@segunda.local`), read-only commands over ssh
(`uname`, `lsusb`, `aplay -l`, `systemctl cat`, `dpkg-query`, `arduino-cli core list`, files under
`~/.arduino15` and `~/Arduino/libraries`). Nothing was changed on the board. No USB hub was
attached, so there is no speaker, microphone or remote in these results.

| Item | Found on `segunda` |
|---|---|
| OS / CPU / RAM | Debian 13 trixie, kernel 7.0, aarch64, 4× Kryo-V2 @ 2.0 GHz, 3.6 GiB RAM + 1.8 GiB swap, 9 GB free |
| Python | **3.13.5**; no `pip`, no `ensurepip`, no `python3-venv`, no `python3-dev`, no `gcc`, no `libportaudio2` → apt step required |
| User `arduino` | already in `dialout`, `audio`, `input`, `sudo` (password needed), `docker`, `gpiod` |
| `/dev/ttyHS1` | `crw-rw---- root dialout` → **no udev rule needed** (Braintip 2.1 rule is redundant) |
| Router stack | `arduino-router.service` in `/etc/systemd/system` (Restart=always; the base `ExecStart` has only `--unix-port /var/run/arduino-router.sock`). The serial wiring lives in the **generator drop-in** `/run/systemd/generator/arduino-router.service.d/10-imola.conf` (copied from `/var/lib/arduino-router/config/` at boot and on every `daemon-reload`): `ExecStartPre=-gpioset 37=0`, an `ExecStart=` reset + `--serial-port /dev/ttyHS1 --serial-baudrate 115200 --after-ready 'gpioset … 70=1'`, `ExecStopPost` 70=0 then a reset pulse on 38. Also `arduino-router-serial.service` (**Requires** router, socat ttyGS0→:7500, Restart=always), `arduino-router-serial.path` (PathExists=/dev/ttyGS0, enabled, ttyGS0 present), `arduino-app-cli.service` (Wants router). **No `arduino-r.service`**, no `arduino-debug.service` (Braintip 2.1 names are wrong). Package arduino-router **0.10.0** |
| Router socket | `/var/run/arduino-router.sock` is `srw-rw-rw-` → any user can connect (Route A needs no root) |
| Router internals | methods `$/version $/reset $/register $/setMaxMsgSize $/serial/open $/serial/close mon/* hci/*`; `--verbose` flag exists; monitor TCP 127.0.0.1:7500 |
| Zephyr core | `arduino:zephyr` **0.55.2 installed** (0.90.0 latest). Overlay: `serials = <&usart1>, <&lpuart1>`, `arduino,router-serial = <&lpuart1>`, `zephyr,console = usart1` (boot logs go to **usart1/D0-D1, not the Linux link**). Core rule: with a router-serial node index 0→`Serial1`, index 1→`Serial2` ⇒ **raw Linux link = `Serial2`** on 0.55.2; `Serial` is a stub unless Arduino_RouterBridge supplies the Monitor |
| Bridge lib | `Arduino_RouterBridge` 0.4.3 + `Arduino_RPClite` 0.3.0 in `~/Arduino/libraries`. `Bridge.begin()` → `$/reset`; `provide_safe(name, fn)` → `$/register` + local bind tagged `__safe__`, dispatched from loop context; `provide()` dispatched in the "bridge" thread; `notify(method, args…)` fire-and-forget |
| Flashing | `arduino-cli` 1.5.1 on the board; `board list` shows the board itself as a **network port 192.168.1.114**; upload = OpenOCD via `remoteocd` (independent of the router; see below) |
| GPIO 37/38/70 | as in the bridge doc (37 out, 38 in, 70 out; none held) |
| Audio | **PipeWire 1.4.2 + WirePlumber** as user services (`pipewire-pulse` installed, **`pactl` missing** → `viz._pulse_sources()` falls back; `wpctl` present). Only the built-in qcm2290 codec card (`Arduino-Imola-HPH-LOUT`, "Headphones playback" UCM profile, currently Dummy Output sink, no sources). No USB audio yet |
| USB | type-C port0 is in **device mode** (`data_role: host [device]`, UDC not attached) → no PD hub connected right now, so **no speaker/remote/`/dev/input/by-id`** to test. Phase 1 USB checks wait for the dongle |
| Input | only `gpio-keys`, `pm8941_pwrkey`, headset-jack event nodes |
| Network | NetworkManager; wlan0 on home Wi-Fi `IZZI_5053.5` (autoconnect). Hotspot not saved yet. `Linger=no` for user `arduino` |
| Wine / loq | **Hangover wine-11.9** (`hangover-wine`, `-libwow64fex`, `-libarm64ecfex`, `-wowbox64`) + `gcc-mingw-w64-i686` installed; `~/loq-portable/loq_winer` is a clean clone of github.com/alexandergmzx/loq_winer (4 commits, incl. a macOS/portable-paths port). **Loquendo TTS 7 is installed** in `~/.wine/drive_c/Program Files (x86)/Loquendo/LTTS7`; `~/.local/bin/loq` is on PATH; `.bashrc` exports `WINEPREFIX` and `LOQ_LTTS`. `loqd.exe` is present in the engine folder (built 2026-08-25). Whether synthesis works under Hangover is untested |
| Flash tooling | `remoteocd` 0.1.1 (OpenOCD on the board, SRST via GPIO; adb tunnel from a PC), recipe `flash_sketch.cfg` writes at `0x8100000`; `remoteocd_network` upload asks for the board password. Independent of the router |
| Bridge library details | `singletons.cpp`: `BridgeClass Bridge(ARDUINO_ROUTER_SERIAL)` (= `Serial2` via the core macro; falls back to `Serial1`); `Monitor` aliases `Serial`. `__loopHook()` (weak, in bridge.h) calls `safeUpdate()` every loop → **`provide_safe` handlers run without any `Bridge.update()` in the sketch**. `Bridge.begin()` writes the literal text "MCU starting RPC Bridge communication" on the UART before RPC (expected junk for a raw-UART listener if a Bridge sketch is flashed). README: `Bridge.provide_safe("greet", greet)`, `Bridge.notify("signal", 200)` when no result is expected. Examples: client, server, monitor, hci, udp_ntp_client |
| apt | all needed packages available: `python3-venv python3-pip python3-dev gcc libportaudio2 pulseaudio-utils python3-evdev(1.9.1) python3-msgpack(1.0.3)`; `libasound2t64` installed; Debian + Arduino + Qualcomm repos |
| App Lab | docker images `app-bricks/python-apps-base:0.10.1` etc.; no Python bridge module installed outside containers |

Not measured yet: USB audio devices, the remote's key and device node, battery runtime, the
load test, `loq` under Hangover, speech-to-text timings.
