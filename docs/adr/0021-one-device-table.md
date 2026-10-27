# 0021 — One device table: presence and failure decided once, read everywhere

**Status:** proposed · **Date:** 2026-10-27

## Context

On 2026-10-27, with the board driven from the phone alone, the page's failures ("no
connection", the microphone switch resetting itself, the Remote row reading "connected" with
zero devices, nothing on the Status tab about the USB port being a device) came from one
cause: whether a part is there, failed or in use was decided in four places (the Status rows,
the chips, the hints, the bring-up checks) plus the acts' own tests, with six vocabularies.
Found wrong in the code that day:

- the Remote row read "connected" for an empty device list (`!rem.devices` is false for `[]`);
- "No answer from the hat for Infinity s" after a failed poll;
- five disconnect thresholds on the page (8, 15, 15, 12 and 25 s), the 8 s one under the 10 s
  heartbeat, so it flickered;
- `hw.internet` (the mark) never reached the chip or the hat;
- "busy" written seven ways and "no connection" six;
- `hw.apply` rewrote `cfg.ptt.capture` before the switches were built, so after a boot with the
  microphone marked the `mic` switch's start value was `browser` and turning the phone's
  microphone off restored `browser`;
- the hardware taps were optimistic (pressed before the board answered) and asymmetric.

`GET /debug/state` took 1.1 to 1.3 s on the board that day, 0.5 s on 2026-10-26
([results](../results/2026-10-27-fortune-on-the-board.md)).

## Decision

1. **One table on the server**, `fish_brain/devices.py`: pure functions over a `Facts` record
   whose defaults are a laptop with nothing set; `debug_state._facts(hub)` reads the machine
   once per state build. One record per part, in a fixed order: `usb_port`, `usb_devices`,
   `speaker`, `mic`, `remote`, `motors`, `internet`, `phone_speaker`, `phone_mic`:

   `{id, label, present, marked, dead, in_use, level, state, reason, fix, tab}`

   `level` is `ok`, `warn`, `bad` or `off` (not applicable here: the page hides the row);
   `present` is `None` when it cannot be known here. `mic` also carries `capture` (as
   configured), `recorder` (who records the next hold), `out` and `last_rec`; the phone rows
   `pages`. The derivation of every row is the table in the module's docstring, pinned by
   `tests/test_devices.py`.
2. **Precedence, the same for every part**:
   1. marked beats present: a part he marked failed is out even when it is detected;
   2. dead beats present: a part that is there but sends nothing is out;
   3. `in_use` only while a phone page is the thing playing or recording;
   4. **the level follows the fallback in use**: a fault with a working fallback is `warn`, a
      fault with none is `bad` (the microphone marked with a phone recording: warn; with no
      phone: bad; offline while the script covers the visit: warn; offline with a cloud stage
      in the turn: bad; the bench: warn; the link off or the MCU silent: bad).
3. **The acts call the same functions**: `recorder()` (conversation's relay, the debug tests'
   refusal), `speaker_routes()` (`audio_route`), `internet()` (`show_run.model_trusted`, the
   speech-to-text's online check), `usb_host()`. A mark is read where the decision is made;
   `hw.apply` no longer rewrites the configuration (the motors' mute stays). A marked remote's
   presses are ignored (`ButtonSource.off`), as `hw.py` always said.
4. **Every reader takes the table**: the Status rows (the USB rows first, board only), the
   summary (`summary`: "Check: …", "Ready, with a warning: …", "Ready for visitors"), the chips,
   the hat's NO INTERNET, the Settings tab's marks, one hint per bad row (`hints_for`, on the
   row's tab) and the presence checks (`check_status`: ok → pass, warn → warn, bad → fail,
   off → skip; the USB host role, the devices on USB, the remote's devices, the link attached
   and the MCU answering, internet). The file facts (the port node, the router's socket, the
   sound rows) stay in the checks. The old keys (`show_tab.hw`, `mic_dead`, `phone_mics`,
   `capture`, `page.capture`, `backends.capture`, `clients.mic_pages`) are removed.
5. **On the page, one connection record and one sentence per refusal**: `CONN = {QUIET_S: 15,
   DOWN_S: 25, STALE_S: 15}` with `connState()`, read by the watchdog, the hat, the Status tab,
   the band, a resume and the phone's microphone; the last good state keeps its time, so the
   Status tab says "No answer from the hat for N s" with the rows dimmed. `explain(out, what)`
   turns every POST's answer into one sentence ([`debug.md`](../debug.md)). The hardware taps
   wait for the board's answer and stay as they were on a refusal; clearing a mark turns the
   phone's speaker or microphone off only when the tap turned it on.
6. **The cost is measured in the state itself**: `timing` (milliseconds per section and the
   total, on the System tab). The ALSA cards and the sound server's cached answer are read once
   per build for the table and the checks; the volume is read in the background (a 5 s cache,
   seeded after a set), the rendered phrases with one directory listing (10 s), the `FISH_*`
   names once per process.

## Alternatives

- **Per caller, as before**: each place keeps its own test. Every bug above came from two
  places answering the same question differently; a fix in one left the other wrong.
- **A table built on the page**: the page has the facts too, but the acts (who records, which
  speaker plays, whether the model is asked) run on the board and must decide the same way
  without a page open.

## Consequences

- A page left open across the update that removed the old keys must be reloaded: it reads
  the table only.
- `/status` is unchanged (the old face reads `mic_capture` and `mic_pages` there); with
  `hw.apply` no longer rewriting the capture, `/status.mic_capture` is the configured value
  whatever is marked, and the `mic` switch's start value is the boot value.
- A forgotten remote mark leaves the remote dead; its row, its hint and its chip say "marked
  failed", and the page's hold still works.
- The first state after a restart has no volume (the slider waits one poll).
- A remote that is not found is now `warn` (the page's hold remains), so it no longer raises a
  hint; its row and the Devices read check say it.
- The laptop with no environment: the USB, remote and phone rows are `off`, the speaker is the
  desktop's card, `motors` is the real link or the mock under `--dry-run`, `internet` is online
  until the probe says otherwise; no row is `bad` (`build(Facts())`, tested).
- The state's build time on the board went from a median of 0.99 s to 0.06 s (53 ms in
  `timing`), ten requests each, 2026-10-27
  ([results](../results/2026-10-27-debug-state-cost.md)).
