# The debug view (`/debug`)

A desktop page for the fish's owner: `http://<fish>:8723/debug` (or `https://…:8724/debug`;
`?token=<value>` when one is set). It exists whenever the fish runs with `--viz`. Decision and
its limits: [ADR 0009](adr/0009-a-debug-view-that-acts.md).

## What is on it

| Part | Shows |
|---|---|
| Bar | Host, uptime, commit, mode badges (`ECHO`, `DRY-RUN`, `WAIT`, `no token`, "code changed: restart"), a chip per part (link, internet, trigger, microphone, the three models, speaker, board), ARM and STOP |
| Hints | A sentence and the fix: a key that is not the configured one, no remote, a key that only taps, a recording of zeros or near silence, echo / dry-run / wait-to-speak, code on disk newer than the process, link off, MCU silent, offline, a missing key name, playback failed, a slow stage, the board in USB device mode |
| Checks | The bring-up checks as PASS / FAIL / WARN rows with the value found and the fix (`fish_brain/debug_checks.py`): USB host role and devices; a playback card, the sound server, the default sink, its volume and mute; a capture card, the default source, `FISH_MIC_SOURCE`; the remote's devices and readable input nodes; the port, the link, the router's socket; `loq`, canned phrases, key names, internet; service, linger, groups, `.env`; the last result of each test. Rows that do not apply on this machine read `skip` and are not counted. Three buttons: speaker → microphone loop, voice render, cloud round trip |
| Model | What each model is given and what it answers: the system prompt, the reading's rules and the kept history as they stand; every LLM call with its messages, parameters, reply, tokens and time (also the failed ones and the ones never sent while offline); speech-to-text's prompt, keywords, raw text and the filter that emptied it; the voice's text and settings; the badge call's question and parsed result, never the photo. A turn's detail opens its own records |
| Pipeline | The last (or the clicked) turn stage by stage; the stage it ended in reads `DIED HERE` |
| Turns | The last 200 with their timings and outcome; a click gives the detail and narrows the log to that turn |
| Inputs | The remote's devices and keys, every key as it arrives, the recorder's state; the last recording's numbers, a player, a 2 s microphone check |
| Voice | Backend, player, last playback; the text box, wait-to-speak, a speaker test per rendered phrase |
| Motors | Link, the lines sent, the bytes back from the MCU, the last performance; ping; the armed tests |
| Cloud, Board, Config, Clients | Models and key names; temperature, load, USB, the unit, restart; the configuration in effect with its `FISH_*` names; pages, dropped events, refused requests |
| Log | Every printed line with its time and tag; filter, search, pause, copy |

## Routes

All data and actions follow the token rule of the page server; the three static files are
open. POSTs must be `application/json`. Without `--viz` there is no hub and no route.

| Route | What |
|---|---|
| `GET /debug`, `/debug.js`, `/debug.css` | The page |
| `GET /debug/state` | The slow state as one JSON (`fish_brain/debug_state.py`) |
| `GET /debug/events?since=<boot>-<seq>` | Server-sent events: every record, replayed from the rings on connect, at most 200 per quarter second; `hello` first with the boot id |
| `GET /debug/rec.wav` | The newest recording |
| `POST /debug/ping`, `/debug/mic {seconds}`, `/debug/say {name}` | The harmless tests |
| `POST /debug/loop`, `/debug/voice`, `/debug/cloud` | The bring-up tests: audible loop (a rendered phrase or a tone, played while recording; never changes the volume); one phrase rendered with the configured voice, timed, not played; one small call to each cloud model in use (the LLM one through `Conversation.probe()`, which leaves the history alone) |
| `POST /debug/arm {on}`, `/debug/stop` | The arm (60 s), STOP |
| `POST /debug/motor {part}`, `/debug/restart {confirm: "restart"}` | Armed |

Refusals are `{"ok": false, "error": "<word>"}`: `not armed`, `busy`, `speaking`, `recording`,
`link off`, `test running`, `not picked up`, `not rendered`, `not a service…`, `a phone is the
microphone` (no test in browser-microphone mode while a phone is ready: it records by itself).
Every test, the ping included, runs in the turn loop, so each is refused with `busy` during a
turn. A fifth debug page is refused (503) rather than pushing an older one out.

## Records (`kind`)

`log {stream, tag, thread, text}` · `key {dev, name, key, code, value, configured, armed, held}`
· `press {source, key, held_s, outcome}` · `turn {id, trigger, times, rec, user, reply,
outcome, error, link, perf}` · `perf {pulses, gestures, player, late_max_ms, result, error}` ·
`tx {line, flag}` · `llm {model, messages, params, reply, tokens, seconds, error, sent}` · `stt {backend, model, prompt, keywords, raw, final, dropped}` · `tts {backend, voice, text, seconds}` · `vision {model, ask, prompt, tokens, found, confidence, name, look}` (these four are cleared when a reading starts: a new visitor) · `page {ev}` (what the phones got) · `level {rms}` · `action {what, lines,
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
- The phone page and `/status` are not this view's to change.

## Trying it without hardware

```bash
.venv/bin/python -m fish_brain.app --dry-run --text --echo --no-audio --tts openai --viz
# then http://127.0.0.1:8723/debug ; type a turn in the terminal
```
