# UNO Q: first conversation under the service — 2026-10-11

Host: the board `segunda` on the home Wi-Fi and a power bank, display on its own power bank.
fish_brain `b26d2a1` under `fish-brain.service` (user unit, linger on), settings from the
board's `.env`: `stt=openai llm=luna:gpt-6-luna tts=loq`, page on `0.0.0.0` with a token,
`FISH_VIZ_TRUST_LOCAL=true`. MCU: Big_mouth `25b72a9` (no banner at start-up), no drivers
attached. Turns were started by the owner with the hold-to-talk target on the touch display.

Level 5 without motors: boot, service, cloud, voice, display and link, with the board's LEDs
in place of the drivers. Not on the hotspot, and nothing here shows motion.

| Check | Result |
|---|---|
| `deploy/unoq_setup.sh install` | 7 of 7 steps; canned phrases rendered with the local voice; `link ok: serial /dev/ttyHS1, MCU answered` |
| `deploy/unoq_setup.sh service` | Unit enabled and active; summary line `link=serial /dev/ttyHS1 stt=openai llm=luna:gpt-6-luna tts=loq ptt=web+evdev(1 device, KEY_VOICECOMMAND, hold)` |
| Router journal at MCU start, banner-free build | 0 error lines in the 5 s after the reset (about 1,000 with the banner) |
| Turn 1, first after the service start | `[turn] rec=5.2s stt=10.1s llm=2.4s tts=1.3s play_start=1.4s link=ok` |
| Turn 2 | `[turn] … stt=1.3s llm=1.8s tts=1.1s play_start=1.2s link=ok` |
| Reboot by the owner | Kiosk and service came back by themselves; the welcome was heard; the log shows `[cloud] offline`, the link attached, then `[cloud] online`; `NRestarts=0` |
| Load with the page open | About 55 % of the four cores busy; hottest zone 65 C |

Open: `FISH_PTT_DEVICE=auto` adopted the board's headset-jack input device as a second
trigger; the first turn after a start waits about 10 s on speech-to-text; the same turns on
the phone hotspot; the 2-hour firmware soak (lost to a reboot).
