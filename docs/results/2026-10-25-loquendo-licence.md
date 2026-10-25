# 2026-10-25: why Loquendo says "la licencia que posee no es válida para este ordenador"

Board `segunda`, tree `b44a540`. The findings were read-only. L1 (renders to `/tmp`, no
restart, no motor line) is below.

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
`fish-brain`, so the daemon and the wineserver start again (see L1 below).

## L1, part 1: the wineserver keeps the adapter list it started with (2026-10-25 23:47 UTC)

Board up 4 h 41 min, `wlan0` on its own MAC for hours (no `permaddr` key), `fish-brain`
running; its Loquendo daemon and the prefix's wineserver both started 19:05:04 UTC, inside the
random-MAC window. No restart, no motor line: renders went to `/tmp` and were transcribed on
the desktop with faster-whisper `small`. Phrase: "Hola, esta es una prueba de la voz del
sombrero." MACs compared (`wine ipconfig /all` against `/sys/class/net/*/address`), never printed.

| Render | Wine sees `wlan0` as | Seconds | Transcript |
|---|---|---|---|
| `loq -o` (the warm daemon) | the boot's random scan MAC | 4.52 | "Atención, la licencia que posee no es válida para este ordenador." |
| `loq --oneshot` (new process, same prefix) | the boot's random scan MAC | 4.52 | the same warning |
| `TTSFileGenerator.exe` in a copy of the prefix (registry copied, `C:` linked; its own fresh wineserver) | the board's own MAC | 3.01 | "Hola, esta es una prueba de la voz del sombrero." |

What this shows:

- The warning **replaces** the phrase; it is not prepended. While the licence fails, every
  render is the same 4.52 s sentence.
- The adapter list is fixed when the prefix's **wineserver** starts, and every Wine process in
  the prefix gets it. Restarting only the Loquendo daemon (`loq --restart`) does not clear it
  while the wineserver lives. The wineserver runs in `fish-brain`'s cgroup, so restarting the
  service clears both.
- The licence itself is fine for the board's own MAC.

Fix, two parts: the NetworkManager drop-in, so the random MAC never exists; and a start-up probe
that renders this phrase, expects about 3.0 s, and on the warning stops the prefix's wineserver
(`wineserver -k`) and starts the daemon again.

## Open: does the drop-in hold at a cold boot with no known Wi-Fi?

Pass line: after the drop-in, a cold boot with no known Wi-Fi renders the phrase in
3.01 ± 0.05 s with a clean transcript.
