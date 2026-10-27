# The operator's page (`/`, also `/debug`)

The owner's page, on a desktop or on his phone: `http://<fish>:8723/` (on the phone
`https://<ip>:8724/`, which keeps the screen on and allows the phone's microphone;
`?token=<value>` when one is set). It exists whenever the fish runs with `--viz`. Decisions and
their limits: [ADR 0009](adr/0009-a-debug-view-that-acts.md),
[ADR 0011](adr/0011-one-page-for-the-operator.md), [ADR 0017](adr/0017-the-show-tab.md) (the
phone as the console, three tabs since 2026-10-27), [ADR 0019](adr/0019-the-fortune-act.md)
(the fortune act). The old visitor face is at `/face` until after the fair.

## What is on it

| Part | Shows |
|---|---|
| Hat | Top left (on a phone: on top, always), in the study from `/face` (window and moon, books, candle, stool, the sign "El Sombrero Adivino"; `scene.css`, `?lite=1` stops its loops); the state word is its bubble under the sign. The drawn hat follows the reply being spoken (the mouth track lifts the mouth and brows, NECK bends the tip, TAIL wags the brim, the burble perks it). Its pose and the band under it say what the fish is doing: WAITING, LISTENING, THINKING with the seconds against the turn's budget and "hearing" or "model", SPEAKING; a grey slump when the stream is down; NO INTERNET. Through a visit its face grows surer, and a verdict shows the house's colour and name for 10 s. A turn that died shakes it and names the stage. Three lamps (MOUTH, NECK, TAIL) light for every line the link really sent (hollow when muted or dropped), and after each phrase "motor: N lines" (or "no lines"). The last heard and said lines. On a live edge into the fortune's reading the study turns violet and the candle's halo swells (transform and opacity; off under `lite` and still), and the house slot shows the sign for 12 s. `?hat=<state>&mouth=0..1&stage=n&house=<House>` shows a still; `?fortune=<q>` a still of the fortune row at question q |
| Visit | The acts (ADR 0015, ADR 0019), in English: the heading with the visit's state; the **fortune row** while a fortune is open ("Question 2 of 5 · dreams (asked again)", "heard: …", the data so far as chips "Escorpio · 6 · dientes · La Muerte", **Skip question**, **End act**; "Reading the future…" during the ending); the **scripted visit's row** while a house act is open (the open question's answers, force a house, skip, what was heard); the **🔮 Fortune** button (hidden unless `page.fortune_enabled`, greyed while its clips are still rendering (`ready < lines`), disabled while a fortune is open, "🔮 Fortune for Ana" after a verdict) and the last fortune's line; the **cue chips** (Age: Child, Teen, Adult; With: Alone, Friends, Family; Colour; Impression: Shy, Smiling, Curious; "Wearing…", "Note…"), whose values go to the server in Spanish; the **typed name** with "Tell the hat" (the hat asks "¿Tú eres…?"); below the acts, **Place** (Home, Party, University, Other, with a text field for Other: the text reaches the web model only) and **Fortune** (Tarot deck, No deck, Lotería later and disabled; "☕ Read the cup"), which post `/debug/set` like the switches (`place`, `place_text`, `fortune_deck`, `fortune_cup`; a restart brings back `.env`) and write a refusal under them. "New visitor" and "Hold to talk" sit in the thumb bar; both act buttons jump to this tab after a 200, and the band chip ("Fortune 2/5 · Ana") taps to it. A fortune over a live house act is refused with a toast ("finish the visit first (or Force a house)") |
| Status | The default tab on a phone (ADR 0017): a summary line ("Waiting for the hat…" until the state arrives, "No answer from the hat for N s" when it is older than 15 s, then "Ready for visitors" or "Check: …"); rows for voice, speaker, microphone, remote, motors, network, mode, lines (the house act's and the fortune's: `show_tab.fortune`) and start at boot, each with what to do |
| Settings | What changes during an evening: **Mode** (Auto, Model, Script, Echo); **Hardware** he marks failed (USB speaker, USB microphone, remote button, motors, internet: kept in `~/.local/state/fish_brain/hw.json` across reboots; marking the speaker or the microphone also turns on this phone's speaker or microphone); volume; network; the phone speaker. A restart brings back `.env`; only the network pin and the hardware marks are files. Place and Fortune moved to the Visit tab on 2026-10-27 |
| Phone | Voice: the phone's microphone switch (off by default; on asks for permission and sets `mic=browser`). System: this phone's screen, secure context, screen lock and stream; vibrate and still toggles. The band: seconds since the last record, the visit, "secure" and "screen on" chips |
| Bar | Host, uptime, commit, mode badges (`ECHO`, `DRY-RUN`, `WAIT`, `no token`, "code changed: restart"), a chip per part (link, internet, trigger, microphone, the three models, speaker, board), ARM and STOP |
| Hints | A sentence and the fix: a key that is not the configured one, no remote, a key that only taps, a recording of zeros or near silence, echo / dry-run / wait-to-speak, code on disk newer than the process, link off, MCU silent, offline, a missing key name, playback failed, a slow stage, the board in USB device mode |
| Checks | The bring-up checks as PASS / FAIL / WARN rows with the value found and the fix (`fish_brain/debug_checks.py`): USB host role and devices; a playback card, the sound server, the default sink, its volume and mute; a capture card, the default source, `FISH_MIC_SOURCE`; the remote's devices and readable input nodes; the port, the link, the router's socket; `loq`, canned phrases, key names, internet; service, linger, groups, `.env`; the last result of each test. Rows that do not apply on this machine read `skip` and are not counted. Three buttons: speaker → microphone loop, voice render, cloud round trip |
| Switches | The running fish, changed from the page: echo or LLM, the LLM profile, the speech-to-text and voice backends, where Canary sends every recording first (`stt_online`: `openai`, `groq`, `off`; read at the next recording, nothing rebuilt; refused without the service's key), gestures, the reading's look line, the voice quit word, the burble at release, the fillers while it thinks and the delay of the first one, the recording limit, board or phone microphone, the fortune's deck (`tarot`, `off`) and cup, the place and its text (at most 60 characters), and (armed) the motors muted. Each row shows the value at start-up and marks a difference. Nothing is written anywhere: a restart brings back what `.env` and the unit say |
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
| `GET /debug/state` | The slow state as one JSON (`fish_brain/debug_state.py`); `page` carries what the tools need (the visit's view with the scripted visit's `show` and the fortune's `fortune` blocks, `fortune_enabled`, whether a typed name can be taken, the capture, the TLS port); `show_tab` the Status rows and `show_tab.fortune` (`deck`, `cup`, `place`, `ready`, `lines`, `open`) |
| `GET /debug/events?since=<boot>-<seq>&page=<id>&tail=<n>` | Server-sent events: every record, replayed from the rings on connect (`tail`: only the last n on a first connection), at most 200 per quarter second; `hello` first with the boot id. A stream that names its page replaces that page's earlier one |
| `GET /debug/rec.wav` | The newest recording |
| `POST /debug/ping`, `/debug/mic {seconds}`, `/debug/say {name}` | The harmless tests |
| `POST /debug/loop`, `/debug/voice`, `/debug/cloud` | The bring-up tests: audible loop (a rendered phrase or a tone, played while recording; never changes the volume); one phrase rendered with the configured voice, timed, not played; one small call to each cloud model in use (with Canary, its first `stt_online` service: the warm-up for the first turn; the LLM one through `Conversation.probe()`, which leaves the history alone) |
| `POST /debug/set {name, value}` | One switch (`debug_actions.SWITCHES`). Applied by the turn loop between turns, so `busy` during one; `motors` needs the arm; refused with the reason when a key or `loq` is missing |
| `POST /fortune {action, value}` | The fortune act (ADR 0019), beside `/visit`, `/cues` and `/show` on the page server's token rule: `start` (`value`: the typed name, at most 20 characters, or empty), `skip` (the open question: a bridge line and the next one), `end` (the ending now). Handed to the turn loop like the scripted visit's taps. `400` bad input; `409 {"busy": true}` when the loop is not listening; `409 {"busy": true, "why": "visit open"}` while a house act is at its questions (finish it or force a house); `503 {"error": "no fortune"}` when the persona has none; `200 {"ok": true}`. The `visit` event on the stream then carries the act (`docs/viz.md`) |
| `POST /debug/arm {on}`, `/debug/stop` | The arm (60 s), STOP |
| `POST /debug/motor {part}`, `/debug/restart {confirm: "restart"}` | Armed |

Refusals are `{"ok": false, "error": "<word>"}`: `not armed`, `busy`, `speaking`, `recording`,
`link off`, `test running`, `not picked up`, `not rendered`, `not a service…`, `a phone is the
microphone` (no test in browser-microphone mode while a phone is ready: it records by itself; a
switch is still allowed, so the page can turn its microphone off).
Every test, the ping included, runs in the turn loop, so each is refused with `busy` during a
turn. A fifth debug page is refused (503) rather than pushing an older one out.

## Records (`kind`)

`log {stream, tag, thread, text}` · `key {dev, name, key, code, value, configured, armed, held}`
· `press {source, key, held_s, outcome}` · `turn {id, trigger, times, rec, user, reply,
outcome, error, link, perf, fillers}` (`outcome` is `timeout: stt|llm|tts` when the turn passed its budget; `times.fill` is the time spent saying fillers, `times.burble` the time from the end of the recording to the burble's first sample) · `perf {pulses, gestures, player, late_max_ms, result, error}` ·
`tx {line, flag}` · `llm {model, messages, params, reply, tokens, seconds, error, sent}` (a Claude call also has `stop_reason`) · `stt {backend, model, prompt, keywords, raw, final, dropped}` · `tts {backend, voice, text, seconds}` · `vision {profile, model, ask, prompt, tokens, found, confidence, name, look}` (these four are cleared when a reading starts: a new visitor; the `vision` record is still written by the parked badge route, the page no longer shows it) · `fortune {n, mode, why, place, data, heard, clips, reading, house, first, seconds}` (one per act, when it ends or is dropped; `data` the said forms, never the year; a turn started by it has `trigger` `fortune` or `operator` and the outcome `fortune: reading (llm|clips)` or `dropped (why)`) · `page {ev}` (what the phones got) · `level {rms}` · `action {what, lines,
result}` · `http {method, path, status, error}`. Sizes of the rings: `RINGS` in `debug.py`.

## Rules for anyone changing it

- A hook is a call to a function in `fish_brain/debug.py`: it does nothing without a hub and
  never raises (it catches `Exception`, never more). Nothing in the hub prints.
- Nothing secret enters a ring or the state: see `NOT_SHOWN` and the classification test.
- A model hook is `debug.model(kind, request, resp=…, error=…, seconds=…)`: the hub takes the
  fields out of the caller's objects itself, so a strange response cannot fail in the caller.
  Never pass an image or a data URL, and never print what a hook records.
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
