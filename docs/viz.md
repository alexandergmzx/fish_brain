# On-screen fish (`--viz`)
A browser fallback/debug view of what the fish is saying — useful when the physical fish
misbehaves. `viz.py` runs a stdlib `ThreadingHTTPServer` (daemon thread): it serves `web/`,
streams a `speak` event per reply over **Server-Sent Events** (`/events`) carrying the audio
URL + the precomputed **mouth loudness envelope** + NECK/TAIL gesture timing, and serves the
spoken WAV bytes at `/audio/<token>`. The browser (`fish.js`) runs a **sprite state machine**:
each frame it picks one whole-fish composite PNG for the current `(neck, mouth, tail)` state —
**mouth** `0..3` played from the sent envelope on the browser's own clock (spring-smoothed),
**neck** `Rest|Out` and **tail** `Rest|Flap` from whether a NECK/TAIL gesture is firing. Driving
the mouth from the envelope (not live audio analysis) means it animates even with browser sound
off / autoplay blocked — including the startup greeting; the manual "probar con un WAV" test
falls back to a live `AnalyserNode`. The **Sensibilidad** slider scales the envelope level (how
wide/easily the mouth opens); mouth smoothing is a fixed critically-damped spring (`mouth.k`).
Whole-fish composites (not stacked layers) because an open
mouth looks different when the neck is also out; sprites are named
`neck{Rest|Out}_mouth{0..3}_tail{Rest|Flap}.png` and missing ones fall back to a simpler pose
(see `web/img/README.md`). Bubbles draw on top. Because the greeting plays before any browser
connects, `viz.py` **replays the last `speak` event to a browser that connects within 30 s**, so
the on-screen fish still performs the greeting. The host plays the audio; the page's own sound
is the "Sonido en navegador" toggle, off by default (on a phone next to the fish a second voice
would only echo it). The fish animates from the envelope either way, even in `--dry-run`.

The page also has a **mic picker + level meter**. Recording is host-side, so the browser can't use
its own devices; instead `GET /mics` enumerates the host's input devices and `POST /mic
{"device": <id|null>}` selects one in the shared `Config`. The picker prefers **PipeWire/Pulse
sources** (via `pactl`): the id is the stable source NAME → `PTTConfig.source`, recorded through the
`pulse` PCM with `PULSE_SOURCE` set (proper gain + 16 kHz resampling, and stable across reboots/USB
re-enumeration). On systems without PipeWire/Pulse it falls back to raw `sounddevice` indices →
`PTTConfig.device` (note: those indices are **unstable** and a raw `hw:` device can capture silence
— prefer the PipeWire source). Silent recordings (RMS < `PTTConfig.silence_rms`) are skipped before
STT, and `stt.py` runs Whisper with `vad_filter=True` plus a small phrase blocklist, so it no
longer emits the silence-hallucination "Subtítulos por la comunidad de Amara.org". A **transcript
panel** under the meter shows the last STT (`🗣️`) and reply (`🐟`): `conversation` calls
`viz.push_transcript(text, role)`, sent as `stt` SSE events that `fish.js` renders with a flash. While recording, the recorder streams per-chunk RMS to
`viz.push_level`, sent as `level` SSE events; `fish.js` draws them as a scrolling waveform + peak
bar that decays to flat when released (the meter is live **only while recording**).

With `--viz` the turn is triggered by an on-screen **hold-to-talk** button (or the browser
spacebar) instead of the keyboard: press/release POST `/ptt {"down": bool}` to `viz.set_ptt`, and
`conversation` records via `ptt.record_multi` (the web button is one `ButtonSource` polling
`viz.ptt_held`; the viz inbox can hand it an input item instead) rather than `record_hold`.
This avoids terminal focus / `pynput` issues and makes debugging easy. An empty transcription
(silence / too-short hold) **re-listens** instead of ending the loop — only `salir`/`quit`/`exit`,
EOF (`--text`), or Ctrl-C quit.

## Added on the `braintip` branch

- **Reachable from a phone.** `FISH_VIZ_HOST=0.0.0.0` (or `--viz-host`) makes the page reachable
  from other devices; the start-up line prints the address. Set `FISH_VIZ_TOKEN` with it and open
  the page as `/?token=<value>`: the POST endpoints (`/speak`, `/ptt`, `/mic`, `/wait`) then
  refuse requests without it. Without a token anyone on the network can make the fish talk.
- **A press can end from the host.** A recording is cut at `FISH_PTT_MAX_S`; the host then
  ends the press and sends a `ptt` event (`{"type": "ptt", "held": false}`) so the button
  follows. A press older than the limit is treated as a lost release. The page also releases
  when it is hidden or loses focus, with a beacon, because a normal request can be cancelled
  while the page goes away.
- **The button and a remote work together.** With `FISH_PTT_DEVICE` set, a turn starts on a
  fresh press of either.
- **Mic list without `pactl`.** On systems with PipeWire but no `pactl` the list comes from
  `pw-dump`.

## Visitor view and status (2026-10-11)

- **`/?kiosk=1`** is the visitor view for a touch display: the fish at full height and one
  round hold-to-talk target. The states are derived in the page from events it already
  gets: `level` events mean the host is really recording (listening), the release starts
  "thinking", a `speak` event with `duration_ms` means speaking, the event stream's own
  open/error means online or not. A hold lasts from the first finger down to the last finger
  up. Context menu, selection, drag and zoom are switched off. Five taps in the top-right
  corner open the normal controls and a status block for 45 s.
- **`GET /status`** returns host, IP, uptime, link description and health (`ok`, `silent`,
  `off`), internet, backends, and whether the speaker is registered. Never a key or a token.
- **`FISH_VIZ_TRUST_LOCAL=true`** lets POSTs from 127.0.0.1 through without the token.
- `fish_brain/kiosk.py` and `web/wait.html` put the page on the board's display; see
  `deploy/README.md`.

## Rule for anyone changing the page

Animation must feel alive: spring easing with overshoot, idle motion, secondary motion.
Nothing meter-like or mechanical.

