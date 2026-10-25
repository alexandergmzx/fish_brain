# 2026-10-25: what happened at the fair (2026-10-17/18) and after

Sources: the Claude Code sessions on `lapG7` and this desktop (`e842bf4d`, `6d4b87de`,
`a03c38d2`, `f2a94e08`), `lapG7`'s wtmp and NetworkManager journal, the board's journal (boots
-3 to 0; earlier boots were rotated away by `SystemMaxUse=50M`). Times are local (UTC-6). The
board has no RTC, so its journal times before an NTP sync are not real.

| When | What | Evidence |
|---|---|---|
| Sat 17, 12:09 | A bench session stopped and disabled `fish-brain`; still inactive at 21:41 | `systemctl --user disable --now fish-brain` in `6d4b87de`; `enable --now` in `e842bf4d` at 21:42 |
| Sat 17, 14:36–15:46 | The board rebooted and saw no hub; the hub came back once the RedOctane mic was unplugged. The speaker failed with `error -71` (its cable, fixed by him at 15:14). The board rebooted once when the motor was connected (15:36); cause not established | lsusb and kernel lines in `6d4b87de` |
| Sat 17, 21:41–21:51 | At the venue on the Ultron hotspot: `lsusb` showed only the root hubs. Two cable swaps each rebooted the board, which is powered through that same cable. The two markers then read as a charge-only cable (`usb_vbus: disabling`, no `port0-partner`) also appear today with every device working: the cause was not established | `e842bf4d` 21:42–21:47; board `journalctl -b -1 -k` |
| Sat 17, 21:51 | "give up, I will use this computer instead of the arduino q". `lapG7` had no dongle or speaker plugged in and had never run a voice turn; the relay plan was drafted only | `e842bf4d` 21:51–22:01; `lapG7` `journalctl -k`; `docs/results/2026-10-17-lapg7-setup.md` |
| Sat 17, 22:44 – Sat 24, 23:01 | `lapG7` off, including all of Sunday | `last -x` on `lapG7` |
| Unknown day, Oct 18–24 | Two board boots with no known Wi-Fi: `[cloud] offline`, no LAN address. In one, the dock's USB2 side disconnected and came back within 1 s | board boots -3, -2 |
| Sat 24, 23:22–23:44 | Parents' house: the board joined Ultron, then `Yes` (192.168.1.220). Profile order set to IZZI 30, Yes 20, Ultron 10. No voice turn logged | board boot -1; `f2a94e08` |

Not established: the cause of the venue USB failure (cable, hub, power bank or port) and of the
reboot when the motor was connected. His power plan (`UNO Q power experiments never lose the
hubs again.md`, E1–E9) tests exactly these; none of it has run yet.

The licence warning heard since is explained in
[2026-10-25-loquendo-licence.md](2026-10-25-loquendo-licence.md).
