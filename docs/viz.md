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

- **`/` (the default view; `/?console=1` is accepted too; `?token=<value>` when one is set)** is the operator's view on a phone in portrait (ADR 0006): the
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

## The phone's microphone (2026-10-11)

- **What it is**: with `FISH_MIC_CAPTURE=browser` (default `host`, the laptop's behaviour)
  the page records the turn with the phone's own microphone and uploads it; the board's
  microphone is no longer opened for a turn. It needs `--viz` (the program exits 78
  without it) and a secure context on the phone: the HTTPS listener (`FISH_VIZ_TLS_*`), or
  `localhost` on the laptop. `/status.mic_capture` tells the page which mode is on.
- **The gate**: a button `Activar micrófono` (`#micGate`: on the strip in the console, under
  the target in the plain and kiosk views) appears only in browser mode and only when
  `window.isSecureContext` and `navigator.mediaDevices` exist. Its `click` handler (a tap
  grants user activation; a touch `pointerdown` does not) asks `getUserMedia` for one
  channel with echo cancellation, noise suppression and automatic gain, creates an
  `AudioContext` with no `sampleRate` option, loads `/rec.js` into its `audioWorklet` and
  connects source → `fish-rec` → a `GainNode` at 0 → destination (the graph must reach the
  destination to run). It also requests `navigator.wakeLock` for the screen (errors ignored)
  and re-acquires it when the page becomes visible. On `NotAllowedError` or any failure the
  gate reads `micrófono del pez` and every hold keeps the `/ptt` path: the fallback is per
  device and needs no restart. The target shows a thin teal rim while this device records.
- **The worklet** (`web/rec.js`): an `AudioWorkletProcessor` named `fish-rec` whose
  `process()` posts a copy of its mono input block (Float32, the context's rate) to the page
  and returns true. The page keeps a 300 ms ring of recent chunks while idle, so the first
  syllable of a hold is not lost. During the first hold of at least a second it counts the
  samples received per wall-clock second; under 90 % of `ctx.sampleRate` it rebuilds the
  graph on a `ScriptProcessorNode(4096)` and the strip reads `mic rate anomaly`.
- **A hold in browser mode**: `pointerdown` → `ctx.resume()`, the ring is prepended and the
  chunks collected; the RMS of each chunk feeds the level meter, the kiosk `listening` state
  and the target's `--lvl` ring locally through a slightly under-damped spring (no `level`
  events come from the host in this mode); `/ptt` is never POSTed. `pointerup` →
  `ctx.resume()` again, 250 ms more are collected, then the clip is judged: a hold under
  350 ms or a clip whose peak chunk RMS is under 0.003 is dropped with a nudge; otherwise the
  samples are downsampled from the context's rate to 16 kHz by linear interpolation (44.1 and
  48 kHz both), clamped to Int16 and prefixed with a 44-byte RIFF/WAVE header (PCM, mono,
  16-bit, 16 kHz). A hold longer than `/status.max_record_s` ends itself and uploads, like
  a host recording. The page hidden (lock screen, another app) drops the clip, stops the
  tracks and shows the gate again; a track that reports `ended` or `muted` at the next
  `pointerdown` does the same, and that hold goes to the host.
- **The upload**: `fetch("POST /utterance")` (a beacon caps its body at 64 KiB) with
  `X-Fish-Token`, `Content-Type: audio/wav` and `X-Fish-Hold-Ms` (the hold's length). The
  host answers `403` without the token, `413` over 1 MiB, `400` with a short reason when
  the body is not a WAV, is not mono 16-bit, is outside 8 to 48 kHz or is longer than
  `FISH_PTT_MAX_S + 1`, `409 busy` when the turn loop is not listening (the file is
  removed), `200 {ok}` when the `Utterance(path, hold_s, upload_s)` entered the inbox. The
  WAV is written with `tempfile.mkstemp(suffix=".wav", prefix="fish_in_")`, exactly as a
  host recording, and the turn loop transcribes it on the same path and unlinks it. The
  journal shows `[utt] 16000 Hz 4.9 s 160044 B upload=0.21s` (never the audio) and a
  `[turn] rec=… stt=…` line where `rec` is the hold plus the upload. The page shows
  `thinking` on 200, a nudge on 409 or a dropped clip, and `Sin conexión con el pez…` on a
  network error. The start-up line says `ptt=web+browser-mic`.
- **The `listen` event**: `{"type": "listen", "ready": bool}` is published whenever the
  turn loop starts or stops waiting for input (the same flag as `/status.listening`). In
  browser mode a press while the host is not ready is nudged with the finger still down
  instead of after the upload; a page that missed the event learns from the 409.
- **A remote relayed to the page**: in browser mode a press on the board's remote
  (`FISH_PTT_DEVICE`) must not open the board's microphone while the phone has one. The
  page says when its microphone is ready: `POST /micstate {"ready": true|false, "page":
  <id>}` (on the guarded list; `200 {ok}`), with a random id the page keeps in
  `sessionStorage` (`fishPage`). `ready: true` goes after the gate succeeds and again
  every 20 s as a keep-alive; `ready: false` when the microphone is dropped, on
  `visibilitychange` hidden and on `pagehide` (a beacon, so the query form of the token).
  The host keeps the ready pages with their last time (`VizServer.mic_pages()`; an entry
  older than 45 s is dropped; `/status.mic_pages`). Before every wait the turn loop checks
  `mic_pages() > 0`: if so the remote's source is marked `relay` and `ptt.record_multi`
  only polls it, handing each edge to `viz.relay_ptt`, which publishes
  `{"type": "ptt", "held": true, "source": "remote"}` and `{"type": "ptt", "held": false,
  "source": "remote"}`; the board's microphone is never opened for it. The page, with its
  microphone ready, starts the same local hold a `pointerdown` starts (no `/ptt` POST,
  the listening state shown) and ends it like a `pointerup` (the 250 ms tail, the discard
  rules, the upload, which arrives through the inbox as an `Utterance`); the on-screen
  target keeps working beside it and a finger during a relayed hold is nudged. A page in
  host mode, or with no microphone, ignores sourced `ptt` events. The sourceless
  `{"type": "ptt", "held": false}` of `reset_ptt` keeps its meaning (the host ended the
  page's own press). A relayed hold longer than `FISH_PTT_MAX_S` is ended by the host with
  `held: false` and the remote reset (the page also enforces its own limit), and one still
  held when the wait ends is ended the same way, so the page never records forever. With
  no page ready (none open, the gate not tapped, the microphone denied) the remote records
  with the board's microphone as before; the choice is made at every wait, so a phone that
  comes or goes needs no restart. The start-up line reads
  `ptt=web+browser-mic+evdev(…)→page`.
- **`?mic=`**: `?mic=host` forces the `/ptt` path on that device (the board's microphone
  through the page, for a test or when the phone's is unusable); `?mic=browser` shows the
  gate even when `/status` says `host`, for a laptop test on `http://127.0.0.1:8723`, which
  is a secure context.

## Rule for anyone changing the page

Animation must feel alive: spring easing with overshoot, idle motion, secondary motion.
Nothing meter-like or mechanical.

