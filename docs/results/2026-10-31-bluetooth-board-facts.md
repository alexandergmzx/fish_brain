# 2026-10-31 — The board's Bluetooth before a speaker, and how other interfaces pair one

Read only: nothing was paired, connected, scanned or restarted. Board `segunda`, branch
`sorting-hat`, commit `a5751bd` (the board's `config.py`, `fortune_run.py` and `audio_route.py`
match that commit by sha256). No audio has been played over Bluetooth yet: every statement on
sound below comes from reading scripts and sources, not from a measurement.

## The board

Commands run over `ssh arduino@segunda.local`.

| Fact | Value | Command |
|---|---|---|
| Stack | BlueZ 5.82-1.1, `libspa-0.2-bluetooth` 1.4.2, PipeWire 1.4.2, WirePlumber 0.5.8 | `dpkg -l`, `wpctl status` |
| Controller | hci0 `14:B5:CD:E9:56:6D`, UART, Qualcomm, HCI and LMP 5.1, `qcom,wcn3988-bt`, driver `hci_uart_qca` | `hciconfig -a`, `/sys/class/bluetooth/hci0/device/uevent` |
| Controller state | Powered, pairable, not discoverable, `PSCAN` on, no experimental features | `bluetoothctl show`, `busctl introspect org.bluez /org/bluez/hci0` |
| `main.conf` | Section headers only: all defaults | `grep -vE "^\s*(#|$)" /etc/bluetooth/main.conf` |
| D-Bus | `context="default"` may send to `org.bluez`; `arduino` reads the tree | `/usr/share/dbus-1/system.d/bluetooth.conf`, `busctl tree org.bluez` |
| Known devices | `DC:0D:51:92:74:DA` MP210, icon `printer`: paired, bonded, trusted, not connected | `bluetoothctl info` |
| Codecs | sbc, ldac, lc3, opus, opus-g, faststream, g722; no aac, no aptx | `ls /usr/lib/*/spa-0.2/bluez5/` |
| A2DP endpoints | 11 registered by WirePlumber at the boot's start | `journalctl -u bluetooth -b` |
| Audio sinks | Only the Jieli USB sink, id 54, volume 0.80 | `wpctl status` |
| Routes | `alsa_output.usb-*,bluez_output.*,phone`; next is USB | `GET /debug/state` |
| Token | Empty | `GET /debug/state` |
| Python in `.venv` | 3.13.5; `AF_BLUETOOTH` yes; `dbus`, `dbus_fast`, `dbus_next`, `pydbus`, `gi` missing | `.venv/bin/python -c` |
| Wi-Fi | `IZZI_5053.5`, channel 149, 5745 MHz. `fish-hotspot` has no band set; `fish-ap` is `bg` | `nmcli` |

**The seat.** `bluez.lua:543-561` creates the BlueZ monitor only while logind says `active`. The
state comes from `lightdm-autologin`'s x11 session 2 on `seat0` (`loginctl`), with no monitor
attached (`/sys/class/drm/card0-DP-1` disconnected). From WirePlumber 0.5.8's `module-logind.c`, a
user active with no active seat reads `online`, so an ssh session would not hold it up. Read from
source, not run.

**Sink name.** `bluez.lua:276-279`: `bluez_output.<address>.<id>`, `:` turned into `_`. Not yet seen
on a real device.

**Settings.** `bluetooth.autoswitch-to-headset-profile` is true; `wpctl settings`. The board's
schema has no `bluetooth.profile-preference` (0.5.15) or `autoswitch-*-timeout` (0.5.19).

## How other interfaces do it

Pages came through a summarizing fetch, so code quotes are not line-exact. Marked (snippet): only a
search snippet was readable.

| System | Lists | Scan | One tap | Forget | Unnamed | PIN |
|---|---|---|---|---|---|---|
| GNOME Settings | One, sorted | While the panel is open; also makes the host discoverable | New: pair, trust, connect | Details, then an alert | Hidden | `DisplayYesNo`; pairing failure shows no dialog |
| Blueman | One | `StartDiscovery` with no filter | Double-click toggles connect | Menu | "Unnamed device" | `KeyboardDisplay`, always prompts |
| Android | Paired, and a separate new-device screen | While open; stops on tap, restarts on failure | Next sensible step; row disabled while busy | Gear icon | Hidden | System dialog |
| iOS | My Devices, Other Devices (from memory) | While open | Tap the name | More Info | Not verified | "You might need to enter your PIN" |
| Volumio plugin | Labelled | "Search for speakers", about 12 s | "Select and connect" pairs, trusts, connects, saves | "Forget pairing" | Stays visible: some speakers show audio only after pairing | Sent to `bluetoothctl` |
| moOde | Devices (snippet) | SCAN button (snippet) | PAIR, CONNECT | Not verified | Not verified | Not verified |
| Home Assistant | No official audio pairing page; a proposal asks for this flow | | | | | |

Sources: [GNOME widget](https://raw.githubusercontent.com/GNOME/gnome-bluetooth/master/lib/bluetooth-settings-widget.c),
[GNOME agent](https://raw.githubusercontent.com/GNOME/gnome-bluetooth/master/lib/bluetooth-agent.c),
[Blueman agent](https://raw.githubusercontent.com/blueman-project/blueman/main/blueman/main/applet/BluezAgent.py),
[Android pairing](https://raw.githubusercontent.com/aosp-mirror/platform_packages_apps_settings/main/src/com/android/settings/bluetooth/BluetoothDevicePairingDetailBase.java),
[Apple](https://support.apple.com/en-mide/HT204091),
[Volumio plugin](https://community.volumio.com/t/experimental-plugin-wireless-bluetooth-airplay-output-manager-for-volumio-4/77180),
[moOde forum](https://moodeaudio.org/forum/showthread.php?tid=5647),
[Home Assistant proposal](https://community.home-assistant.io/t/native-bluetooth-pairing-page-for-audio-devices/1030201).

## BlueZ and WirePlumber, from their sources

- A device's agent: `Pair()` uses the caller's own, and it dies with its D-Bus connection
  ([agent.c](https://raw.githubusercontent.com/bluez/bluez/5.82/src/agent.c)).
- `autopair` tries 0000, 1234, 1111 for some A/V classes, not "loudspeaker"
  ([autopair.c](https://raw.githubusercontent.com/bluez/bluez/5.82/plugins/autopair.c)).
- An unpaired device object lasts 30 s after it stops being seen
  ([main.conf](https://raw.githubusercontent.com/bluez/bluez/5.82/src/main.conf)).
- The policy plugin retries only after link loss, 7 attempts over about 127 s
  ([policy.c](https://raw.githubusercontent.com/bluez/bluez/5.82/plugins/policy.c)).
- `monitor.bluez.seat-monitoring = disabled` is the documented fragment
  ([WirePlumber](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/bluetooth.html)).
- A pulled sink under `node.dont-reconnect` should end `pw-play` with an error, not a hang
  (`prepare-link.lua:71-75,112-118`, `pw-cat.c`).

## Not known

Audio on this radio, its latency and idle clipping; which real failure gives which BlueZ error;
coexistence with Wi-Fi on 2.4 GHz (nothing found for this chip); whether the seat fragment holds
with LightDM stopped.
