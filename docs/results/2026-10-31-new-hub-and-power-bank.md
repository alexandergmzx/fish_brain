# 2026-10-31 — The board on the new hub and power bank: detection, idle

Read-only over ssh, 20:44 UTC, 17 min after boot, `fish-brain` running. No sound played, no motor.
`lsusb`, `wpctl status`, `/proc/asound/cards`, `journalctl -k -b`, `GET /debug/state`, and on the
microphone: `timeout 6 pw-record --target alsa_input.usb-XING_WEI_…mono-fallback --rate 16000
--channels 1 --format s16 take.wav`, RMS and the share of zero samples computed from the WAV.

| Part | Result |
|---|---|
| Hub | Genesys 05e3:0608, board in host role |
| Remote | XING WEI on port 1.1, five input nodes; a button press not tested here |
| Speaker | Jieli on port 1.3, default sink, volume 0.25; one `descriptor read/64, error -32` at boot, then enumerated. `hw.json` held `failed: speaker` from 18:08 UTC, so the page said no speaker |
| Microphone | Default source, capture 100 %; four takes, 3.8 s and three of 5.8 to 5.9 s, RMS 0.0, 100 % zero samples, nobody pressing or talking |
| Kernel | No USB disconnect, over-current or under-voltage since boot |

Not measured: USB under load on this power bank; whether the zeros go away during a hold.
