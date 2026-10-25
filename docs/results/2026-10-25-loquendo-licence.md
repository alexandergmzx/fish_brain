# 2026-10-25: why Loquendo says "la licencia que posee no es válida para este ordenador"

Board `segunda`, tree `b44a540`. Read-only: no `loq` or Wine was run. The experiment that
settles the open point (L1) is below, not yet run.

## Findings

| Finding | Evidence |
|---|---|
| The sentence is Loquendo's own host-mismatch message, not an expiry | `strings LTTS7Spanish.dll`; `LoqTTS7.dll` has `This license is valid for host "%s" only`, separate from `This evaluation copy has expired` |
| The engine binds the licence to a network adapter's MAC | `LoqTTS7.dll` imports `GetAdaptersInfo` (iphlpapi) and `Netbios` (netapi32); no `GetVolumeInformation`, no `GetComputerName` |
| The dock's RTL8153 Ethernet is not the cause | It was on the board from 2026-10-10 23:21 UTC, same interface order (`wlan0` ifindex 3), while Loquendo worked |
| NetworkManager gives `wlan0` a random MAC while it scans | `journalctl -u NetworkManager`: `set-hw-addr: set MAC address to <random> (scanning)`, then `reset MAC address ... (preserve)` after connecting. Stock `no-mac-addr-change.conf` exempts only `eagle_sdio` and `wl`; this driver is `ath10k_snoc` |
| The loq daemon starts inside that window at every boot | Boot 0: fish-brain started, daemon launched 1.1 s later, random MAC at +2.1 s, daemon ready at +5.0 s, own MAC back at +7.7 s. Same race in all 4 kept boots |
| Where no known Wi-Fi exists the MAC stays random the whole time | Boots -3 and -2 (friend's / parents' house): random MAC, never reset |
| Clips rendered before are clean | [2026-10-25-canned-backup.md](2026-10-25-canned-backup.md); same text, same length at every render date; three transcribed clean with faster-whisper `small` |
| Nothing in fish_brain detects the warning | `tts.py` accepts any WAV with exit code 0; `canned.py` caches whatever was rendered |

The board's licence key (`HKLM\Software\Wow6432Node\Loquendo\LTTS7\LicenseCode`, `Name=arduino`)
was written 2026-08-25 00:50 UTC and not changed since.

## Fix

`deploy/nm/90-fish-wlan0-own-mac.conf`: scans keep `wlan0`'s own MAC. Then restart
`fish-brain` so the daemon starts again.

## Open: once per daemon start, or every phrase? (L1, not run)

Render the same phrase from a daemon started under a random MAC and with `loq --oneshot` under the
own MAC; repeat with the dock unplugged; then install the drop-in, cold-boot with no known
Wi-Fi, and render again. Pass line: after the drop-in, a cold boot with no known Wi-Fi renders
the phrase clean (length within 0.05 s of the clean length).
