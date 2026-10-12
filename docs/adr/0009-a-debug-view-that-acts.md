# 0009 — A desktop debug view that shows the whole fish, and may act on it

**Status:** proposed · **Date:** 2026-10-12

## Context

On 2026-10-12 the remote's OK button began to arrive as `BTN_LEFT` (its mouse mode) while the
fish listened for `KEY_ENTER`. The running fish read every one of those presses and dropped
them without a word; it took an ssh session and `evdev_button --watch` to see it. The same day:
a recording of pure silence, a 10 s speech-to-text call, a goodbye that failed with an ALSA
error, a board left in echo mode. Of the failure modes written down in the docs, a dozen left
no trace a page could show: turn timings lived only in a printed line, a tap left nothing, a
failed playback still animated the phone, what the MCU answered was thrown away.

## Decision

1. `GET /debug` is a desktop page (`web/debug.{html,js,css}`, plain JavaScript) fed by a hub
   inside the process (`fish_brain/debug.py`): a tee on stdout and stderr, rings of records
   (every key of the remote, one record per turn, each performance, the lines sent to the
   motors and the bytes that came back, the page's own events), the state of the fish, and
   hints that turn a signal into a sentence with its fix. The hub exists only with `--viz`.
2. The hooks in the other modules do nothing without a hub and can never raise into their
   caller; the tee writes to the real stream first. Debug code never breaks a turn or a print.
3. The debug page has its own event stream (`/debug/events`, at most four), fed from the
   rings by its own thread: a debug tab never takes one of the phones' eight places and a
   phone never receives a debug record. `/status` and `/events` are unchanged.
4. The newest microphone recording is kept in memory, replaced by the next one, and served
   only at `/debug/rec.wav`.
5. The view may act (the owner's choice): the bring-up checks read by the fish itself, with
   three tests (a speaker-to-microphone loop, a voice render, a cloud round trip; added
   2026-10-12), a link ping with the motor-safe `PING <n>`, a
   microphone check, a speaker test with a phrase that is already rendered (never a
   synthesis, nothing to the motors), and, **armed on the page for 60 s**, motor test pulses
   and a restart of the service.
6. A motor test takes no number from the page. Its lines are built from the configuration and
   validated before they are sent: `MOUTH`, `NECK` or `TAIL` with one or two `<pwm> <ms>`
   pairs, 1.5 s at most, never a single integer (a held drive). The mouth test is the open
   pulse and then, always, the conductor's close pulse. It runs **in the turn loop**, offered
   through the page's inbox like a typed name, so the thread that drives the motors during
   speech stays the only one that writes a motor line, and a test starts only while the fish
   waits. It is refused while the fish speaks, records or is busy, and dropped if not picked
   up within half a second.
7. STOP is not armed and never refused: it aborts a running test, drops the arm and sends
   `STOP` at once (the link serialises the write). After it a test sends nothing more.
8. Restart only where the process is a systemd service: `SIGINT` to the main thread, the
   unit's own stop signal, so the goodbye and STOP run and `Restart=always` starts the fish
   again; if it has not ended after 12 s, STOP and a hard exit.
9. Never to a page: key values, the token, the certificate paths, the badge photo.
   *Amended 2026-10-12 (the owner's word):* the view shows what the models are given and
   what they answer, in full: the LLM's messages with its kept history, speech-to-text's raw
   text, the voice's text, the badge call's parsed name and look. These records hold
   visitors' words and full names; they travel only on the guarded debug routes, are scrubbed
   like every record, and are cleared when a reading starts (a new visitor). Every record is scrubbed where it enters a ring. Letters and digits typed on an
   adopted keyboard are counted, never named. All data and actions follow the token rule;
   POSTs must be JSON, so another web page in the same browser cannot fire them.

## Alternatives

- **Show only**: safer, but the motor and restart checks would stay ssh work at the stand.
- **A switch in `.env` before the arm, or the token for the armed actions**: a stronger lock;
  the owner chose the arm alone.
- **Motor tests from the request's thread under the speaker's lock**: simpler, but a second
  writer on a link that has no lock of its own, and a check-then-act race with speech.
- **Parse the journal for timings**: no new hooks, but brittle, and nothing for keys or taps.
- **Debug records on the phones' stream**: one stream, but every phone would carry the load
  and a burst could push a `speak` event out of a phone's queue.

## Consequences

- **With the token empty (the board on the owner's hotspot), anyone who has the hotspot
  password can open `/debug`, read the log and the transcripts, play the last visitor's
  recording, arm and pulse the motors and restart the fish.** `FISH_VIZ_TOKEN` closes it.
- During speech STOP ends the current pulse only; the phrase's next pulse moves the mouth
  again. Holding the motors still for the rest of a phrase would drop its close pulse and is
  not done.
- PortAudio's own messages and crash traces never pass through Python: they stay in the
  journal, and the page says so. History does not survive a restart.
- Cost on the board is not measured yet (`docs/results/` when it is): each hook is one append
  under one lock; the board is sampled every five seconds only while a debug page is open.
- The assistant tests on the mock link only and never calls the motor test, the speaker test
  or the restart against the board or the laptop fish. The first real pulse is the owner's.
