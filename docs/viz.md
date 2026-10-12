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
  the page as `/?token=<value>`: the POST endpoints (`/speak`, `/ptt`, `/mic`, `/wait`), the
  event stream (`/events`) and the audio files (`/audio/<n>.wav`) then refuse requests without
  it (`?token=` in the query or the `X-Fish-Token` header; loopback passes with
  `FISH_VIZ_TRUST_LOCAL`). The page itself, `/status` and `/mics` stay open. Without a token
  anyone on the network can make the fish talk.
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
  `deploy/README.md` (parked since ADR 0006: the page runs on the operator's phone).

## Console view (2026-10-11)

- **`/?console=1&token=<value>`** is the operator's view on a phone in portrait (ADR 0006): the
  fish at about 30 vh, the round hold target under it, and a strip along the bottom that is
  always visible. The console implies the kiosk layout and shares its pointer handlers, its
  state machine and the operator sheet; the laptop in landscape gets the same three rows.
- **The strip** shows, in words: the link (`pez conectado` / `pez callado` / `sin pez`), the
  internet, the microphone source (`mic del tablero` or `mic del teléfono`, with the ptt
  summary and `espera activada` when wait-to-speak is on), and `escuchando` while
  `/status.listening` is true (polled every 3 s) or while `level` events arrive; then the
  two transcript lines (heard, reply) in readable type and a gear that opens the sheet in one
  tap. The five corner taps still work. An unreachable `/status` reads `sin respuesta del
  cerebro`.
- **Hidden in the console**: the mic picker row (with the meter), the sensitivity slider, the
  WAV test row, the bubbles toggle and `Sonido en navegador`. The console is muted and draws
  no bubbles: the fish speaks on the board, the phone shows. `Esperar para hablar` and the
  text box stay in the sheet.
- **The token leaves the address bar.** A `?token=` in the URL is stored in `sessionStorage`
  (`fishToken`) and removed with `history.replaceState`, the other parameters kept; a reload
  keeps it, a new tab needs the link again. With a token set, `GET /events` and
  `GET /audio/<n>.wav` need it too: the stream opens as `/events?token=…`, the audio fetch
  sends `X-Fish-Token`, the release beacon keeps the query form (a beacon has no headers).
- **Heartbeat and watchdog.** The stream sends `retry: 2000` and then `{"type":"hb"}` every
  10 s of silence. The page notes the time of the last message (heartbeats count); when
  nothing arrived for 25 s it closes the `EventSource` and opens a new one, and does the same
  on `pageshow` and on becoming visible when the stream is stale or closed. A phone that slept
  or changed network comes back without a reload: the dot goes red, then green. The 25 s
  rule arms only after the stream has sent one `hb`: a host whose stream carries only SSE
  comments (which never reach the page's handler) is reconnected only when the browser
  reports the stream closed, never on a timer.
- **`age_ms` on a replayed `speak`.** A `speak` replayed to a page that connects within 30 s
  carries `age_ms`, the milliseconds since it was announced (`0` when live). The mouth track
  and the gestures start that far in, so a mid-phrase reconnect animates the remainder; a
  reply older than its `duration_ms` neither enters `speaking` nor plays, so a reconnecting
  page never refuses presses for a reply that has already ended. Each reply's audio URL is
  unique, so a `speak` whose URL the page has already seen is a replay even when the host
  sends no `age_ms`: the page then takes the age from its own clock.
- **Lightness.** The connection dot breathes on `opacity` and `transform`, never on
  `box-shadow`. The console draws at 20 frames a second and, while nothing moves (no mouth
  track, mouth closed, no gesture, no bubbles), draws the resting pose once and then polls
  every 250 ms instead of asking for animation frames; a `speak`, a `level` or a gesture wakes
  it. The hold target keeps its breathing and its spring states throughout.
- In kiosk and console a non-passive `touchstart` cancels the touch default on the target
  (the iOS loupe on a long press); the pointer handlers are untouched.

## The reading (2026-10-11)

- **What it is** ([ADR 0007](adr/0007-the-reading.md)): the operator photographs a visitor's
  fair badge on the console; the board reads the name with the vision model of
  `FISH_READING_PROFILE` (empty = the LLM profile; `luna` is the one with image input);
  the fish asks "¿Tú eres X?" by voice and the visitor's spoken answer is a normal turn,
  with the question seeded into the LLM history and the per-visitor rules
  (`ReadingConfig.rules`) attached to the persona for that visitor. A name typed on the
  console skips the question: the fish tells the future at once.
- **The row on the strip**: `Foto del gafete` (the camera, through a hidden file input with
  `capture="environment"`), `Galería` (the same input without `capture`: Android Chrome
  shows the camera tile with it and the gallery without), the name field with `Leer el
  futuro`, and, only when `/status.reading_look` is true, the tick `Describir su look (con
  permiso)`, cleared after every reading. The photo buttons are disabled when `/status.reading`
  is false (no reader registered: the page was started without the reading).
- **The photo** is decoded once in the page (`createImageBitmap` with the EXIF orientation,
  resized to a 1024 px long edge; an `Image` and a canvas when the options are refused),
  re-encoded as JPEG at 0.8 and posted as `POST /badge` (token, `Content-Type: image/jpeg`,
  `X-Fish-Look: 1` when the tick is on, at most 1.5 MiB). The host says `reading_wait`
  from the canned cache while the call runs, keeps the bytes only in the handler's local
  variable, and answers `{ok, found, name, first_name, confidence}` (a `Reading` goes into
  the inbox), `{ok, found: false}` (the fish says `reading_fail`), `409 busy` when the turn
  loop is not listening, `503 offline` / `503 misconfigured` for cloud errors, `503 no
  reader`, `400` for a non-JPEG. The page shows the name with its confidence colour (green
  high, amber medium or low) and `el pez pregunta`, or `No se pudo leer: escribe el nombre`,
  `El pez está ocupado`, `Sin internet para leer el gafete`.
- **A typed name**: `POST /reading {"name"}` (cleaned on the server: letters, spaces,
  hyphens and apostrophes, Title Case, at most 40 characters; `400` when nothing is left)
  queues a confirmed `Reading`; `409 busy` as above.
- **Events**: `{"type": "reading", "stage": "ask" | "speaking"}` (never replayed, never the
  photo). On `ask` the hold target enters `k-reading` (a slow sway, transform only) and reads
  `¿Tú eres…?`; the following `speak` event takes over as usual. Presses are refused while
  reading, as while thinking. The page also enters `k-reading` with `Leyendo tu gafete…`
  while a photo is on its way.
- **Journal lines**: `[reading] badge <seconds>s tokens=<prompt tokens> found=<bool>
  confidence=<high|medium|low>` (never the name), `fish> (lectura: pregunta por el nombre)` or `fish> (lectura)`, and a `[turn]
  read=ask|tell …` line. The `fish>` and `you>` lines of the following turns carry the name
  as any turn does.
- **One-shot**: `python -m fish_brain.app --tts openai --llm luna --read-badge foto.jpg`
  prints the result as JSON before any voice warm-up.

## Rule for anyone changing the page

Animation must feel alive: spring easing with overshoot, idle motion, secondary motion.
Nothing meter-like or mechanical.

