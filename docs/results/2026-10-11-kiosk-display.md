# UNO Q: the fish page on the board's own display — 2026-10-11

Host: the board `segunda`, Chromium 154.0.8037.92, LightDM with
`deploy/kiosk/50-fish-kiosk.conf` installed by the owner, fish_brain at the commit of this
file. The fish was started by hand in echo mode (`app --echo --viz`, local `tiny`
speech-to-text, local voice, no keys); the unit is not installed yet. MCU: Big_mouth
`772ef54`, no drivers attached. Level 2 for the page and touch, on the board.

## Display

| Case | Result |
|---|---|
| HDMI in, display fed from the hub's power bank | `DP-1 disconnected`, "no signal" |
| Display on its own power bank, attached at power-up | `connected`, 1920x1080 at 60 Hz, on 2 cold boots of 2. One boot logged `Fail to read EDID: -22` once before succeeding |
| USB audio with the display attached | USB speaker and microphone stayed the PipeWire defaults |

Not done: plugging the display into a running board; the display back on the shared bank
after a cold boot.

## Kiosk session

| Check | Result |
|---|---|
| Autologin into the bare session | `arduino` on seat0, `Xorg -s 0 -dpms`, session script and supervisor running, no greeter |
| Blanking | `xset q`: timeout 0, DPMS disabled |
| No fish running | Waiting page shown (`[kiosk] wait on DP-1 1920x1080`) |
| Fish started | Supervisor switched to the page by itself (`[kiosk] fish on DP-1 1920x1080`) |
| Mode changed with `xrandr` to 1280x720 | Supervisor restarted the browser at the new size |
| Hold-to-talk from the touch panel | One turn by the owner: `[turn] rec=8.3s stt=12.4s tts=0.9s play_start=1.1s link=ok`; the fish repeated the sentence |

## Cost (read with `top -b`, 4 to 5 s samples, percent of one core; the board has four)

| On the display | Chromium (two busiest processes) | Xorg |
|---|---|---|
| `about:blank` | 5 | — |
| Visitor view, 1920x1080 | 83 + 52 | 5 |
| Visitor view, 1280x720 | 76 + 46 | — |
| Same, animation capped at 24 frames a second, meter not drawn | 74 + 60 | 5.5 |
| Same, talk target's idle animation off (`&lite=1`) | 67 + 47 | 17.5 |
| Same, canvas at 2 frames a second (`&fps=2`) | 61 + 52 | 20.7 |
| Same as `lite`, `--disable-gpu` | 67 + 64 | 6 |

Hottest thermal zone: 42 C before, 54 to 56 C with the page idle, 64 C during a local
speech-to-text turn. Local `tiny` speech-to-text took 12.4 s for an 8.3 s recording with the
page open, against 3.5 to 4.8 s measured without it on 2026-10-10.

Reading: the page costs about 1.1 to 1.3 cores whatever the resolution, the frame rate of
the fish canvas, the talk target's animation or the GPU setting. Something else in the page
animates on every frame. Not found; not pursued (a lighter interface is planned separately).
`kiosk pause` closes the browser if the cores are needed.
