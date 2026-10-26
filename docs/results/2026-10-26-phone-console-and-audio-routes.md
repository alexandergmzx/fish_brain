# 2026-10-26: the Show tab, speaker routes, a capture that cannot hang

Board `segunda`, `sorting-hat` up to `c44085c`. Cell pack disconnected, speaker at 5 % throughout.

| Check | How | Result |
|---|---|---|
| Certificate for the board's own Wi-Fi | `deploy/unoq_setup.sh tls --force 10.42.0.1 192.168.1.114`, restart, `openssl s_client` | the listener serves SANs segunda.local, localhost, 127.0.0.1, 10.42.0.1, 192.168.1.114 |
| Onboard codec hidden | `deploy/wireplumber/51-fish.conf`, `wpctl status` | sinks: only `UACDemoV1.0`; the volume stayed 0.05 |
| USB route | a scripted visit through `/utterance` | `[audio] speaker route: alsa_output.usb-* (…UACDemoV1.0…)` |
| Phone route | drop-in `FISH_AUDIO_ROUTES=alsa_output.nothing-here-*,phone`; a stand-in page on the board (event stream, `/speakerstate`, fetch, `/speaker/started`) | `[audio] speaker route: phone`; 18 then 19 clips played by the stand-in; visits #23 and #24 (set C, "de puerta en puerta") reached a verdict |
| A bug the phone run found | the page view after the last question indexed past the end | fixed (`c20f501`), test added; the rerun ended with no traceback |
| Show tab data | `GET /debug/state` → `show_tab` | voice clean; route `alsa_output.usb-*`, sink 46, volume 0.05; net client IZZI; show auto (online), 143 of 143 lines ready; record and logger on |
| Volume action | `POST /debug/volume {"value": 5}` | `wpctl get-volume` 0.05 |
| Page listeners | curl | http 200, https 200 |
| `pw-record` capture | `POST /debug/mic`, and `pw-record` by hand | 1.79 s captured, **all zeros**; PortAudio on the same source: all zeros too. The remote's microphone did not stream without its key held (not a capture fault). With his press: not measured yet |
| Deaf fallback | desktop, `FISH_SHOW=script`, `FISH_STT_MODEL_DIR=/nonexistent` | `[show] speech-to-text unavailable …: visits by the page's buttons only`; no exit 78 |

Found on the way: **the motor link has not attached since 2026-10-26 01:41 UTC**. His
`apt dist-upgrade` that night upgraded `arduino-router` 0.10.0 → 0.11.0, whose socket is
`root:arduino-router` 0660; `arduino` is not in that group, so the router cannot be asked to
release the port (`[link] router did not release /dev/ttyHS1: no permission`). The fish talks
without motors meanwhile (`FISH_SERIAL_REQUIRED=false`). Fix (his): `sudo usermod -aG
arduino-router arduino`, then reboot.

Not measured: a real phone as the speaker (latency, the AudioContext over a long show); a real
USB speaker pulled mid-phrase; the remote's microphone through `pw-record` with the key held;
a Bluetooth speaker.
