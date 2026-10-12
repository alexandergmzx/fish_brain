# The debug view (`/debug`)

A desktop page for the fish's owner: `http://<fish>:8723/debug` (or `https://…:8724/debug`;
`?token=<value>` when one is set). It exists whenever the fish runs with `--viz`. Decision and
its limits: [ADR 0009](adr/0009-a-debug-view-that-acts.md).

## What is on it

| Part | Shows |
|---|---|
| Bar | Host, uptime, commit, mode badges (`ECHO`, `DRY-RUN`, `WAIT`, `no token`, "code changed: restart"), a chip per part (link, internet, trigger, microphone, the three models, speaker, board), ARM and STOP |
| Hints | A sentence and the fix: a key that is not the configured one, no remote, a key that only taps, a recording of zeros or near silence, echo / dry-run / wait-to-speak, code on disk newer than the process, link off, MCU silent, offline, a missing key name, playback failed, a slow stage, the board in USB device mode |
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
| `POST /debug/arm {on}`, `/debug/stop` | The arm (60 s), STOP |
| `POST /debug/motor {part}`, `/debug/restart {confirm: "restart"}` | Armed |

Refusals are `{"ok": false, "error": "<word>"}`: `not armed`, `busy`, `speaking`, `recording`,
`link off`, `test running`, `not picked up`, `not rendered`, `not a service…`.

## Records (`kind`)

`log {stream, tag, thread, text}` · `key {dev, name, key, code, value, configured, armed, held}`
· `press {source, key, held_s, outcome}` · `turn {id, trigger, times, rec, user, reply,
outcome, error, link, perf}` · `perf {pulses, gestures, player, late_max_ms, result, error}` ·
`tx {line, flag}` · `page {ev}` (what the phones got) · `level {rms}` · `action {what, lines,
result}` · `http {method, path, status, error}`. Sizes of the rings: `RINGS` in `debug.py`.

## Rules for anyone changing it

- A hook is a call to a function in `fish_brain/debug.py`: it does nothing without a hub and
  never raises (it catches `Exception`, never more). Nothing in the hub prints.
- Nothing secret enters a ring or the state: see `NOT_SHOWN` and the classification test.
- No motor line is ever composed from a request: `debug_actions.build_lines` and `check_line`.
- The page takes text only through `textContent`; `debug.css` animates only `transform` and
  `opacity`; every id `debug.js` looks up exists in `debug.html` (tests hold all three).
- The phone page and `/status` are not this view's to change.

## Trying it without hardware

```bash
.venv/bin/python -m fish_brain.app --dry-run --text --echo --no-audio --tts openai --viz
# then http://127.0.0.1:8723/debug ; type a turn in the terminal
```
