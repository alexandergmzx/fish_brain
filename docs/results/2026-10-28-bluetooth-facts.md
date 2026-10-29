# 2026-10-28 — Bluetooth on the desktop, the laptop and the board, before the MP210

What each machine offers a Bluetooth ticket printer (the MP210, `DC:0D:51:92:74:DA`) before any
printer code exists. Read only: nothing was paired, connected or printed. Branch `sorting-hat`,
commit `79fbc36`.

## Desktop (Linux Mint, NVIDIA), read earlier on 2026-10-28

The outputs were not saved to a file; the values are the ones written into the printer plan
that day, with the commands that give them.

| Fact | Value | Command |
|---|---|---|
| The printer | `MP210` at `DC:0D:51:92:74:DA`, paired and bonded, Class `0x040680` | `bluetoothctl info DC:0D:51:92:74:DA` |
| Its radio | Dual mode: bonded over BR/EDR, and BLE services `0x18F0`, `e7810a71-…`, `ffcacade-…` advertised; manufacturer data key `0x434B` with the MAC as value | `bluetoothctl info DC:0D:51:92:74:DA` |
| Serial port | SDP "Serial Port" on **RFCOMM channel 1** | `sdptool records DC:0D:51:92:74:DA` |
| Python | 3.12.3 in `.venv`: `socket.AF_BLUETOOTH` and `socket.BTPROTO_RFCOMM` present | `.venv/bin/python -c "import socket; print(socket.AF_BLUETOOTH, socket.BTPROTO_RFCOMM)"` |
| Imaging | No Pillow in `.venv`; numpy 2.4.6 | `.venv/bin/python -c "import PIL"`; `.venv/bin/python -c "import numpy; print(numpy.__version__)"` |

## Laptop (lapG7, Mint 22.3, kernel 6.8.0-147), read 2026-10-28 18:30 CST

Earlier that evening the controller was rfkill soft-blocked. It was unblocked and powered on
without sudo (`rfkill unblock bluetooth`, `bluetoothctl power on`): `/dev/rfkill` carries the
ACL `user:alexmint:rw-`. The values below are after that.

| Fact | Value | Command |
|---|---|---|
| BlueZ | 5.72, `bluetooth.service` active | `bluetoothctl --version`; `systemctl is-active bluetooth` |
| Controller | `94:E7:0B:CB:31:20` "lapG7", **Powered: yes**, Pairable: no, Discoverable: no | `bluetoothctl show` |
| rfkill | `hci0` soft and hard blocked: no | `rfkill list` |
| `/dev/rfkill` | `crw-rw-r--+ root root`, ACL `user:alexmint:rw-` | `ls -l /dev/rfkill`; `getfacl /dev/rfkill` |
| Paired devices | BT5.0-Audio, MX Master 3, soundcore Space Q45, G915 TKL. **The MP210 is not paired** | `bluetoothctl devices`; `bluetoothctl devices Paired` |
| Groups | `bluetooth` exists (gid 109); `alexmint` is not in it (in `dialout`, `input`, `plugdev`) | `getent group bluetooth`; `id` |
| Tools | `/usr/bin/rfcomm`, `/usr/bin/sdptool` | `which rfcomm sdptool` |
| Python | 3.12.3 in `.venv` and `/usr/bin/python3`: `AF_BLUETOOTH` = 31, `BTPROTO_RFCOMM` = 3 in both | `<python> -c "import socket; print(socket.AF_BLUETOOTH, socket.BTPROTO_RFCOMM)"` |
| Imaging | `/usr/bin/python3` has Pillow 10.2.0; `.venv` has no Pillow, numpy 2.4.6 | `/usr/bin/python3 -c "import PIL; print(PIL.__version__)"`; `.venv/bin/python -c "import PIL"` |
| netpbm, ImageMagick | `/usr/bin/pamditherbw` (netpbm 11.05.02), `/usr/bin/convert` (ImageMagick 6.9.12.98) | `which pamditherbw convert`; `dpkg -l netpbm imagemagick` |

## Board `segunda` (UNO Q), not re-read

`ssh arduino@segunda.local` failed at 18:30 CST: `Could not resolve hostname segunda.local`
(the laptop was on another network, `10.48.96.0/20`). The values are from the printer plan,
read from the desktop earlier on 2026-10-28; only the unit file was checked again, in the repo.

| Fact | Value | Command |
|---|---|---|
| BlueZ | 5.82, active; controller powered; nothing paired (from the plan) | `bluetoothctl --version`; `bluetoothctl show`; `bluetoothctl devices` |
| Groups | `arduino` in `bluetooth` (from the plan) | `groups` |
| Tools | `rfcomm` and `sdptool` present (from the plan) | `which rfcomm sdptool` |
| Python | 3.13.5 venv: `AF_BLUETOOTH` and `BTPROTO_RFCOMM` present (from the plan) | `~/fish_brain/.venv/bin/python -c "import socket; print(socket.AF_BLUETOOTH, socket.BTPROTO_RFCOMM)"` |
| Libraries | No `bleak`, `python-escpos` or Pillow in the venv (from the plan) | `~/fish_brain/.venv/bin/python -m pip list` |
| The unit | No sandboxing: no `RestrictAddressFamilies`, `PrivateNetwork`, `Protect*`, `NoNewPrivileges` or `SupplementaryGroups` in `deploy/fish-brain.service` (or any `deploy/*.service`), so nothing blocks `AF_BLUETOOTH` | the `grep` below (no match) |

```bash
grep -n -i -E "Restrict|Private|Protect|NoNewPriv|Supplementary" deploy/*.service   # no output
```

To re-read the board when it is reachable:

```bash
ssh arduino@segunda.local 'bluetoothctl --version; bluetoothctl show; bluetoothctl devices Paired; groups; which rfcomm sdptool;
  ~/fish_brain/.venv/bin/python -c "import socket; print(socket.AF_BLUETOOTH, socket.BTPROTO_RFCOMM)";
  ~/fish_brain/.venv/bin/python -m pip list | grep -i -E "^(bleak|python-escpos|pillow) "'
```

## What it means

- The stdlib RFCOMM socket exists on all three machines; no library is needed to reach channel 1.
- The laptop needs his pairing step before any paper (`bluetoothctl`: `power on`, `agent on`,
  `default-agent`, `scan on`, `pair DC:0D:51:92:74:DA` with PIN 0000, `trust`, `info`).
- Whether an outgoing RFCOMM connect needs the `bluetooth` group is not measured: the laptop's
  user is not in it, the board's is.
- The plates can be dithered on the laptop with `/usr/bin/python3` (Pillow) or netpbm; the
  board needs neither.
