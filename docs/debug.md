# The operator's page (`/`, also `/debug`)

The owner's page, on a desktop or on his phone: `http://<fish>:8723/` (on the phone
`https://<ip>:8724/`, which keeps the screen on and allows the phone's microphone;
`?token=<value>` when one is set). It exists whenever the fish runs with `--viz`. Decisions and
their limits: [ADR 0009](adr/0009-a-debug-view-that-acts.md),
[ADR 0011](adr/0011-one-page-for-the-operator.md), [ADR 0017](adr/0017-the-show-tab.md) (the
phone as the console, three tabs since 2026-10-27), [ADR 0019](adr/0019-the-fortune-act.md)
(the fortune act), [ADR 0021](adr/0021-one-device-table.md) (one device table, one connection
record, one sentence per refusal). The old visitor face is at `/face` until after the fair.

## What is on it

| Part | Shows |
|---|---|
| Hat | Top left (on a phone: on top, always), in the study from `/face` (window and moon, books, candle, stool, the sign "El Sombrero Adivino"; `scene.css`, `?lite=1` stops its loops); the state word is its bubble under the sign. The drawn hat follows the reply being spoken (the mouth track lifts the mouth and brows, NECK bends the tip, TAIL wags the brim, the burble perks it). Its pose and the band under it say what the fish is doing: WAITING, LISTENING, THINKING with the seconds against the turn's budget and "hearing" or "model", SPEAKING; a grey slump when the stream is down; NO INTERNET. Through a visit its face grows surer, and a verdict shows the house's colour and name for 10 s. A turn that died shakes it and names the stage. Three lamps (MOUTH, NECK, TAIL) light for every line the link really sent (hollow when muted or dropped), and after each phrase "motor: N lines" (or "no lines"). The last heard and said lines. On a live edge into the fortune's reading the study turns violet and the candle's halo swells (transform and opacity; off under `lite` and still), and the house slot shows the sign for 12 s. `?hat=<state>&mouth=0..1&stage=n&house=<House>` shows a still; `?fortune=<q>` a still of the fortune row at question q |
| Visit | The acts (ADR 0015, ADR 0019), in English: the heading with the visit's state; the **fortune row** while a fortune is open ("Question 2 of 5 · dreams (asked again)", "heard: …", the data so far as chips "Escorpio · 6 · dientes · La Muerte", **Skip question**, **End act**; "Reading the future…" during the ending); the **scripted visit's row** while a house act is open (the open question's answers, force a house, skip, what was heard); the **🔮 Fortune** button (hidden unless `page.fortune_enabled`, greyed while its clips are still rendering (`ready < lines`), disabled while a fortune is open, "🔮 Fortune for Ana" after a verdict) and the last fortune's line; the **cue chips** (Age: Child, Teen, Adult; With: Alone, Friends, Family; Colour; Impression: Shy, Smiling, Curious; "Wearing…", "Note…"), whose values go to the server in Spanish; the **typed name** with "Tell the hat" (the hat asks "¿Tú eres…?"); below the acts, **Place** (Home, Party, University, Other, with a text field for Other: the text reaches the web model only) and **Fortune** (Tarot deck, No deck, Lotería later and disabled; "☕ Read the cup"), which post `/debug/set` like the switches (`place`, `place_text`, `fortune_deck`, `fortune_cup`; a restart brings back `.env`) and write a refusal under them. "New visitor" and "Hold to talk" sit in the thumb bar; both act buttons jump to this tab after a 200, and the band chip ("Fortune 2/5 · Ana") taps to it. A fortune over a live house act is refused with a toast ("finish the visit first (or Force a house)") |
| Status | The default tab on a phone (ADR 0017): a summary line ("Waiting for the hat…" until the state arrives; "No answer from the hat for N s: check the Wi-Fi" when the last good state is older than 15 s, the rows kept and dimmed; else "Check: …" for a red row, "Ready, with a warning: …" for an amber one, "Ready for visitors"); first the **device rows** in the table's order (`devices`, ADR 0021: USB port and USB devices on the board only, speaker, microphone, remote, motors, internet, phone speaker, phone microphone; a part that does not apply here is hidden), each with its state, reason and fix; then voice, mode, lines (the house act's), fortune (`show_tab.fortune`), the act in progress and start at boot |
| Settings | What changes during an evening: **Mode** (Auto, Model, Script, Echo); **Hardware** he marks failed (USB speaker, USB microphone, remote button, motors, internet: kept in `~/.local/state/fish_brain/hw.json` across reboots; the pressed state is the table's `marked`; a tap waits for the board's answer and stays as it was on a refusal; marking the speaker or the microphone also turns on this phone's speaker or microphone, and clearing it turns them off only when that tap turned them on; `#hwNote` lists what is detected failed but not marked); volume; network; the phone speaker. A restart brings back `.env`; only the network pin and the hardware marks are files. Place and Fortune moved to the Visit tab on 2026-10-27 |
| Phone | Voice: the phone's microphone switch (off by default; on asks for permission and sets `mic=browser`). System: this phone's screen, secure context, screen lock and stream; vibrate and still toggles. The band: seconds since the last record, the visit, "secure" and "screen on" chips |
| Bar | Host, uptime, commit, mode badges (`ECHO`, `DRY-RUN`, `WAIT`, `no token`, "code changed: restart"), a chip per part (LINK, NET, TRIG, MIC and SPK from the device table's `motors`, `internet`, `remote`, `mic` and `speaker` rows; the three models; board), ARM and STOP |
| Hints | A sentence and the fix: one per red device row, on its tab (`devices.hints_for`: the board in USB device mode, no speaker left, no microphone left, the link off or the MCU silent, offline with a cloud stage in the turn); and the rest from the records: a key that is not the configured one, a key that only taps, a recording of zeros or near silence, echo / dry-run / wait-to-speak, bench mode, muted motors, code on disk newer than the process, a missing key name, playback failed, a slow stage, a failed speaker or microphone check |
| Checks | The bring-up checks as PASS / FAIL / WARN rows with the value found and the fix (`fish_brain/debug_checks.py`): USB host role and devices; a playback card, the sound server, the default sink, its volume and mute; a capture card, the default source, `FISH_MIC_SOURCE`; the remote's devices and readable input nodes; the port, the link, the router's socket; `loq`, canned phrases, key names, internet; service, linger, groups, `.env`; the last result of each test. Rows that do not apply on this machine read `skip` and are not counted. The rows about a part's presence (USB host role, devices on USB, the remote's devices read, the link attached and the MCU answering, internet) take their status from the device table (`devices.check_status`: ok → PASS, warn → WARN, bad → FAIL, off → skip), so a marked remote or the bench reads WARN, not FAIL; the file facts (the port node, the router's socket, the sound rows) are read here. The ALSA cards and the sound server's cached answer are read once per state, for the table and the checks. Three buttons: speaker → microphone loop, voice render, cloud round trip |
| Switches | The running fish, changed from the page: echo or LLM, the LLM profile, the speech-to-text and voice backends, where Canary sends every recording first (`stt_online`: `openai`, `groq`, `off`; read at the next recording, nothing rebuilt; refused without the service's key), gestures, the reading's look line, the voice quit word, the burble at release, the fillers while it thinks and the delay of the first one, the recording limit, the silence end (`silence_end_s`, 0 to 30 s, 0 = off; the board's recorder and the phone's microphone read it at the next hold), board or phone microphone, the fortune's deck (`tarot`, `off`) and cup, the place and its text (at most 60 characters), and (armed) the motors muted. Each row shows the value at start-up and marks a difference. Nothing is written anywhere: a restart brings back what `.env` and the unit say |
| Model | What each model is given and what it answers: the system prompt, the rules of the act in progress (the reading's, the fortune's) and the kept history as they stand; every LLM call with its messages, parameters, reply, tokens and time (also the failed ones and the ones never sent while offline; the fortune's call carries the `[ADIVINACIÓN: …]` tag as its message); speech-to-text's prompt, keywords, raw text and the filter that emptied it; the voice's text and settings. The badge rows left the page 2026-10-27 with the badge photo. A turn's detail opens its own records |
| Pipeline | The last (or the clicked) turn stage by stage; the stage it ended in reads `DIED HERE` |
| Turns | The last 200 with their timings and outcome; a click gives the detail and narrows the log to that turn |
| Inputs | The remote's devices and keys, every key as it arrives, the recorder's state; the last recording's numbers, a player, a 2 s microphone check |
| Voice | Backend, player, last playback; the text box, wait-to-speak, a speaker test per rendered phrase |
| Motors | Link, the lines sent, the bytes back from the MCU, the last performance; ping; the armed tests |
| Cloud, Board, Config, Clients | Models and key names (a key reads as needed when its service is in Canary's routes, `backends.stt_keys`); the speech-to-text routes (`backends.stt_online`, `stt_long`) and the last recording's route and seconds (`backends.stt_last`); the Model tab's speech rows carry a route column (the backend and `route`: `online first`, `long`, `canary`, `long: local …`; what was passed over in its tooltip, the record's `skipped`); temperature, load, USB, the unit, restart; the configuration in effect with its `FISH_*` names; pages, dropped events, refused requests |
| Log | Every printed line with its time and tag; filter, search, pause, copy |

The middle column has nine tabs: **Visit** (the acts), **Status**, **Settings**, **Checks**,
**Live** (inputs and motors), **Model** (with the cloud facts), **Voice**, **Switches**,
**System** (board, service, configuration, pages, this phone). On a phone (≤ 700 px) the hat
and the tabs stay on top, one column shows at a time and two more tabs open the **Turns** and
**Log** columns. The page opens on Status on a phone and on Checks on a desktop; `?tab=<name>`
opens a named one (`show` is kept as an alias of `status`), and the chosen tab is remembered in
the browser. Hints fold into one line; every action answers in one toast at the bottom.

## Routes

All data and actions follow the token rule of the page server; the three static files are
open. POSTs must be `application/json`. Without `--viz` there is no hub and no route.

| Route | What |
|---|---|
| `GET /`, `/debug`, `/debug.js`, `/debug.css` | The page |
| `GET /debug/state` | The slow state as one JSON (`fish_brain/debug_state.py`); `page` carries what the tools need (the visit's view with the scripted visit's `show` and the fortune's `fortune` blocks, `fortune_enabled`, whether a typed name can be taken, the recording limit, the silence end and its level, the TLS port); `show_tab` the voice, audio, network, show and `show_tab.fortune` (`deck`, `cup`, `place`, `ready`, `lines`, `open`); `devices` the device table (ADR 0021: `{id, label, present, marked, dead, in_use, level, state, reason, fix, tab}` per part; `mic` also `capture`, `recorder`, `out`, `last_rec`; the phone rows `pages`), `summary` (`{level, bad, warn, text}`), `timing` (milliseconds per section, `sound` for the cards and the sound server, `total`; shown on System). Gone since 2026-10-27 (the table says them): `show_tab.hw`, `mic_dead`, `phone_mics`, `capture`, `page.capture`, `backends.capture`, `clients.mic_pages`; a page left open across that update must be reloaded |
| `GET /debug/events?since=<boot>-<seq>&page=<id>&tail=<n>` | Server-sent events: every record, replayed from the rings on connect (`tail`: only the last n on a first connection), at most 200 per quarter second; `hello` first with the boot id. A stream that names its page replaces that page's earlier one |
| `GET /debug/rec.wav` | The newest recording |
| `POST /debug/ping`, `/debug/mic {seconds}`, `/debug/say {name}` | The harmless tests |
| `POST /debug/loop`, `/debug/voice`, `/debug/cloud` | The bring-up tests: audible loop (a rendered phrase or a tone, played while recording; never changes the volume); one phrase rendered with the configured voice, timed, not played; one small call to each cloud model in use (with Canary, its first `stt_online` service: the warm-up for the first turn; the LLM one through `Conversation.probe()`, which leaves the history alone) |
| `POST /debug/set {name, value}` | One switch (`debug_actions.SWITCHES`). Applied by the turn loop between turns, so `busy` during one; `motors` needs the arm; refused with the reason when a key or `loq` is missing |
| `POST /fortune {action, value}` | The fortune act (ADR 0019), beside `/visit`, `/cues` and `/show` on the page server's token rule: `start` (`value`: the typed name, at most 20 characters, or empty), `skip` (the open question: a bridge line and the next one), `end` (the ending now). Handed to the turn loop like the scripted visit's taps. `400` bad input; `409 {"busy": true}` when the loop is not listening; `409 {"busy": true, "why": "visit open"}` while a house act is at its questions (finish it or force a house); `503 {"error": "no fortune"}` when the persona has none; `200 {"ok": true}`. The `visit` event on the stream then carries the act (`docs/viz.md`) |
| `POST /debug/hw {part, failed}` | Mark a part failed or working (`speaker`, `mic`, `remote`, `motors`, `internet`; `hw.py`): kept across reboots, followed at once; `200 {ok, hw}`, `400` for another part |
| `POST /debug/volume {value}` | The live speaker's volume, 0 to 100 (the routed sink, else the default); no sound is made; `500` when `wpctl` fails |
| `POST /debug/net {pin}` | `ap` pins the board's own Wi-Fi, `auto` lets fish-net decide (a file, kept across reboots) |
| `POST /debug/pron {i}` | One pronunciation candidate (an index into `say_as.CANDIDATES`) rendered with `loq` and played, audio only; `409` when the voice is not `loq` |
| `POST /debug/arm {on}`, `/debug/stop` | The arm (60 s), STOP |
| `POST /debug/motor {part}`, `/debug/restart {confirm: "restart"}` | Armed |

Refusals are `{"ok": false, "error": "<word>"}`: `not armed`, `busy`, `speaking`, `recording`,
`link off`, `test running`, `not picked up`, `not rendered`, `not a service…`, `a phone is the
microphone` (no test while a phone records the next hold, `devices.recorder`: it records by
itself; a switch is still allowed, so the page can turn its microphone off).
The page turns every answer into one sentence in one place, `explain(out, what)` in `debug.js`:

| Answer | The page says |
|---|---|
| no answer at all (status 0) | no connection |
| `403` `not armed` | arm first (60 s) |
| `403` otherwise | no permission (token) |
| `409` with `why` | refused: the reason (`visit open` → "finish the visit first (or Force a house)") |
| `409` `recording`, `speaking`, `a phone is the microphone`, `link off`, `test running` | the hat is recording, the hat is speaking, a phone is the microphone, the motor link is off, a test is running |
| `409` `busy` or no word | the hat is busy: try again when it waits |
| `503` | `<what>` is off (the fortune, the visit) |
| `504` | the hat did not pick it up |
| anything else | refused: the error word |

Every test, the ping included, runs in the turn loop, so each is refused with `busy` during a
turn. A fifth debug page is refused (503) rather than pushing an older one out.

## Records (`kind`)

`log {stream, tag, thread, text}` · `key {dev, name, key, code, value, configured, armed, held}`
· `press {source, key, held_s, outcome}` · `turn {id, trigger, ended, times, rec, user, reply,
outcome, error, link, perf, fillers}` (`ended` is how the recording ended: `release`, `silence` (`FISH_PTT_SILENCE_END_S`), `limit` (`FISH_PTT_MAX_S`) or `dead stream` (`FISH_PTT_DEAD_S`) on the board; a phone upload's `X-Fish-End`, `release`, `silence` or `limit`, empty from a page that does not send it; `outcome` is `timeout: stt|llm|tts` when the turn passed its budget; `times.fill` is the time spent saying fillers, `times.burble` the time from the end of the recording to the burble's first sample) · `perf {pulses, gestures, player, late_max_ms, result, error}` ·
`tx {line, flag}` · `llm {model, messages, params, reply, tokens, seconds, error, sent}` (a Claude call also has `stop_reason`) · `stt {backend, model, prompt, keywords, raw, final, dropped}` · `tts {backend, voice, text, seconds}` · `vision {profile, model, ask, prompt, tokens, found, confidence, name, look}` (these four are cleared when a reading starts: a new visitor; the `vision` record is still written by the parked badge route, the page no longer shows it) · `fortune {n, mode, why, place, data, heard, clips, reading, house, first, seconds}` (one per act, when it ends or is dropped; `data` the said forms, never the year; a turn started by it has `trigger` `fortune` or `operator` and the outcome `fortune: reading (llm|clips)` or `dropped (why)`) · `page {ev}` (what the phones got) · `level {rms}` · `action {what, lines,
result}` · `http {method, path, status, error}`. Sizes of the rings: `RINGS` in `debug.py`.

## Rules for anyone changing it

- A hook is a call to a function in `fish_brain/debug.py`: it does nothing without a hub and
  never raises (it catches `Exception`, never more). Nothing in the hub prints.
- Nothing secret enters a ring or the state: see `NOT_SHOWN` and the classification test.
- A model hook is `debug.model(kind, request, resp=…, error=…, seconds=…)`: the hub takes the
  fields out of the caller's objects itself, so a strange response cannot fail in the caller.
  Never pass an image or a data URL, and never print what a hook records.
- **Presence and failure are decided once, in `fish_brain/devices.py`** (ADR 0021): the Status
  rows, the chips, the hat's NO INTERNET, the hints, the presence checks, who records the next
  hold (`recorder`), which speaker plays (`speaker_routes`) and whether the model is asked
  (`internet`) all read the table or its functions. A new part or rule goes there, with its
  test in `tests/test_devices.py`, never in a caller.
- **One connection record on the page**: `CONN = {QUIET_S: 15, DOWN_S: 25, STALE_S: 15}` and
  `connState()` (`stream` live, quiet or down; the state's age). The watchdog, the hat, the
  Status tab, the band, a resume and the phone's microphone read it, never their own clock.
  **One `explain()`** for every refusal (the table above).
- The sound server is only ever asked from the one-shot `debug-sound` thread (2 s timeouts,
  a 10 s cache); a check is a row, never a call that can wait.
- No motor line is ever composed from a request: `debug_actions.build_lines` and `check_line`.
- The page takes text only through `textContent`; `debug.css` animates only `transform` and
  `opacity`; every id `debug.js` looks up exists in `debug.html` (tests hold all three).
- A switch changes objects the turn loop reads (`convo.echo`, `cfg.*`, the cached clients) and
  only from inside that loop; it never writes `.env` or a unit file.
- Muted motors (`BaseLink.mute`): every line but `STOP` is dropped at the link and recorded
  with the flag `muted`.
- `/status` is not this page's to change (`/status` reads the mode and the backends when asked,
  so it follows a switch). The old face at `/face` is left as it is until it is removed.
- Records replayed on connect only set state; what moves the hat, buzzes the phone or starts a
  recording runs only for records that arrive live (`S.caughtUp`). Each tool block starts in
  `guard()`, after ARM and STOP are wired.

## Trying it without hardware

```bash
.venv/bin/python -m fish_brain.app --dry-run --text --echo --no-audio --tts openai --viz
# then http://127.0.0.1:8723/debug ; type a turn in the terminal
```
