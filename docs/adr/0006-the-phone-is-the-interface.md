# 0006 — The operator's phone is the fair's interface; the board's display is parked

**Status:** proposed · **Date:** 2026-10-11

## Context

ADR 0005 put the page on an HDMI touch display driven by the board itself. Measured on 2026-10-11
([results](../results/2026-10-11-kiosk-display.md)): the browser on the board costs 1.1 to 1.3 of
its four cores whatever the resolution, frame rate or animation switch; the hottest zone goes from
42 C to 54 to 56 C with the page idle; a local speech-to-text turn that took 3.5 to 4.8 s without
the page took 12.4 s with it. The display needs its own power bank and must be on before the board
boots. The same page already opens on a phone over plain http with a token (the spare of 0005).

What the phone cannot do over plain http is record: a browser exposes `navigator.mediaDevices`
only in a secure context (https, or localhost). Chrome, Firefox and Safari all hide it on
`http://<ip>:8723` and `http://segunda.local:8723`. A photo through `<input type=file capture>`
needs no secure context. The board runs Python 3.13, which has no `http.server.HTTPSServer`
(that is 3.14); wrapping the listening socket would run every TLS handshake in the single
`serve_forever` thread, where one stalled phone blocks every other connection.

The fair network is the operator's Android phone as the hotspot and the console. Android 11+
hotspots pick a random `192.168.x.0/24` per enable, and the phone that hosts the hotspot most
likely cannot resolve `segunda.local` (its default network is mobile data, where `.local` is
excluded). Chrome on Android and on the laptop treats an origin whose certificate warning the
user clicked through as a secure context; the bypass is remembered seven days per host.

The turn loop needs a WAV path (`ptt.wav_duration_s`, `ptt.wav_rms`, `conversation._transcribe`,
both cloud speech-to-text backends).

## Decision

1. At the fair a turn starts from the page opened on the operator's phone (or the laptop) on the
   hotspot, in an operator console view (`/?console=1&token=…`). No display is connected to the
   board. The kiosk of ADR 0005 is parked: `fish_brain/kiosk.py`, `deploy/kiosk/` and their tests
   stay in the tree; with no display nothing of them runs.
2. `viz.py` listens twice when `FISH_VIZ_TLS_CERT` and `FISH_VIZ_TLS_KEY` are set: plain http on
   `FISH_VIZ_PORT` as today (the kiosk probe, the ssh tunnel, the fallback page) and https on
   `FISH_VIZ_TLS_PORT` (8724), the same handler. TLS is wrapped per connection inside the worker
   thread with a handshake timeout, never on the listening socket. The laptop default stays plain
   http. A bad certificate path exits with status 78, never a restart loop.
3. The certificate is self-signed (SAN with `segunda.local`, `localhost`, `127.0.0.1` and the
   addresses seen in rehearsal; EKU serverAuth; at most 825 days), made by `deploy/unoq_setup.sh
   tls`, kept under `~/.config/fish_brain/tls/` on the board, outside the synced tree and the
   repo. On Chrome the operator proceeds past the warning once per device; the Chrome flag
   `unsafely-treat-insecure-origin-as-secure` is plan B; installing the same file as a user root is
   an option where `segunda.local` resolves (the laptop).
4. `FISH_MIC_CAPTURE=browser` (the board; the laptop keeps `host`) lets the page record with the
   phone's microphone: PCM from an AudioWorklet at the device's own rate, downsampled in the page
   to 16 kHz mono int16 WAV, uploaded at release as one `POST /utterance`. The host loop takes an
   uploaded recording, a held button (board microphone, remote) or a queued reading, whichever
   comes first, through one inbox checked inside `ptt.record_multi`. A page without a secure
   context or with the microphone denied keeps sending `/ptt` edges and the board's microphone
   records as today: the fallback is per device and needs no restart.
5. Once a token is set, `GET /events` and `GET /audio/<n>.wav` need it too (`?token=`), because
   visitor names will travel there. `/status` stays public and leak-free.
6. With `FISH_SAY_ADDRESS=true` the fish says the last two octets of its address after the
   welcome, so the operator can type the URL on a phone that cannot resolve `.local`.

## Alternatives

- Keep the display and make the page lighter: the cost was the same at 2 frames a second and with
  the idle animation off, and the display still needs its own power and a boot order.
- A private root installed on the phone: cleaner, but Android installs roots only from Settings
  with a screen lock, and with a changing hotspot address the name still mismatches; kept as an
  option for the laptop.
- MediaRecorder blobs (webm/opus, fragmented mp4) decoded on the board with PyAV: three
  containers and known Safari quirks; the documented plan B if the worklet misbehaves.
- A WebSocket: the standard library has no server; SSE plus POST is enough.
- One listener switched to https: the kiosk probe and the tunnel would break, and going back to
  http would need a restart during the fair.

## Consequences

- The page's cost moves to the phone: keep it charging, auto-lock off. The board runs no browser;
  the gain is measured in a dated results file, not assumed.
- Visitor speech travels phone → board over TLS, then to the cloud speech-to-text as before
  (ADR 0003). The token sits in the URL and the browser history; the page moves it out of the
  address bar.
- The hotspot can hand the board a new address per session: the fish says it, the card carries
  the IP form, and the warning is accepted again on fair morning.
- The service unit is unchanged (`--viz` already). If the kiosk is ever revived it keeps using the
  http listener.
- ADR 0005 is replaced by this record; its files stay as parked code and docs.
