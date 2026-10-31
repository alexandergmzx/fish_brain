# 0024 — The fortune's ticket: the reading on paper from a Bluetooth printer

**Status:** proposed · **Date:** 2026-10-28

## Context

His word, 2026-10-28: the fortune act's reading ([0019](0019-the-fortune-act.md)) goes home with
the visitor on a ticket from the MP210, a 58 mm Bluetooth thermal printer (ESC/POS, 384 dots a
line, no cutter, one connection at a time; from its manual). Printing starts while the hat says
its closing line; a Reprint button sits on the Visit tab; a setting turns printing off; a failed
print never holds up the act. Not the house act.

The machines offer the stdlib RFCOMM socket and the printer's serial port on channel 1
([results](../results/2026-10-28-bluetooth-facts.md); the board's values are from the plan, not
re-read that night). No library on the board decodes images, and python-escpos would pull Pillow
and eight more packages.

## Decision

1. **Transport:** the stdlib `socket(AF_BLUETOOTH, SOCK_STREAM, BTPROTO_RFCOMM)` to
   `(FISH_PRINTER, FISH_PRINTER_CHANNEL)`, paced `sendall`. No `rfcomm bind`, python-escpos,
   bleak or Pillow at runtime.
2. **Connect per ticket, never hold the link between acts**, so a phone or the laptop can still
   reach the printer and it can go to standby.
3. **The gate:** the ticket is handed to the printer just before the closing clip plays
   (`Speaker.say_sequence(..., at=(name, fn))`), in the model ending and the clips ending;
   `_close` hands it over when the closing line never started. One ticket an act, from every
   path into `_close` (model, clips, End from the page, a fault mid-reading); a drop prints
   nothing. Nothing reaches paper before the hat has said it.
4. **Two modules:** `ticket.py` is pure (content, layout, ESC/POS bytes, the plates, a text
   preview); `printer.py` is one daemon worker that owns the socket, a queue of two, `submit`
   never blocks, `close()` joins for 1 s at most. The act never imports socket code.
5. **Failure policy:** each connect bounded, retried until a deadline after the hand-over; a
   stall or a drop mid-ticket fails with no automatic resend (no cutter: the paper would come
   out twice); Reprint is the human retry and is refused while a ticket runs.
6. **Configuration:** `FISH_PRINTER` empty (off, the laptop), `mock` (the stand-in: logs the
   ticket as text) or the printer's MAC; `FISH_PRINTER_CHANNEL` (1); `FISH_FORTUNE_TICKET`
   (true). A malformed `FISH_PRINTER` turns the printer off with one `[printer]` line and a
   warning row; the service never exits 78 for it. Code page, columns, band height, pacing and
   timeouts are constants in the modules, each marked "(estimate)" until the desk results.
7. **The page:** `POST /fortune {"action":"reprint"}` (taken while the hat speaks; 409
   `printing` / `no ticket yet`, 503 `no printer`), the Reprint button and the ticket's line on
   the Visit tab, the "🎫 Print the ticket" switch beside the cup's. The device row `printer`
   ([0021](0021-one-device-table.md)) is ok, warn or off, **never bad**, and no hardware mark:
   the spoken reading plus Reprint is the working fallback. One probe (connect and close) at an
   act's start, none periodic.
8. **Records:** a `ticket` record (`queued → connecting → printing → printed | failed`), the
   `fortune` record's `ticket=`, `printer=` in the `[fish]` start-up line.
9. **Encoding:** every ticket starts with init, Chinese mode off, the USA set and one code page;
   `ticket.printable` drops every control character (no ESC from the model or a typed name
   reaches the printer) and maps what the page lacks. The page is `ESC t 19` / cp858: on the desk it
   prints ñ á ¿ ¡ right and 16 prints black blocks, so cp1252 is not on this firmware.
10. **Content:** the title, `para <name>`, the visitor's card (picture, numeral, name, meaning),
    the reading (the model's text, or the said texts of the number, moon and magic clips),
    leader lines for the number, the moon, the animal and the magic word, and a footer with the
    folio, the date in words when the clock is sane, the place and the plate's credit. Left off:
    the dream (private), the cup, the house, the mode. The Spanish labels are drafts, his to
    edit.
11. **The picture:** the 22 major arcana from the 1909 plates (Pamela Colman Smith), dithered
    once on the laptop and committed as 1-bit PBM files, read with the stdlib. A missing or bad
    file means no picture, never an error. Not yet committed: see Consequences.
12. **Tools:** `--print-test [CARD]` prints a sample ticket from bank texts through the real
    worker (exits 78 with no printer set); `tools/printer_check.py` does the desk experiments
    and has a socket-pair self-test.

## Alternatives

- **Hold the link between acts:** a ready printer at once, but nobody else can connect and the
  printer never sleeps. The fallback, if the board shows the ticket late: connect at the start
  of the ending and hold only until the gate.
- **python-escpos:** Pillow and eight packages on the board, not declared for Python 3.13.
- **BLE through bleak:** a new dependency; only if the serial port fails on the desk.
- **Print after the closing line:** the visitor would wait at the hat for the paper.
- **Resend after a drop:** duplicate paper with no cutter.

## Consequences

- Built on mocks and `socket.socketpair()`; paired with the laptop and printing from it, not
  paired on the board. The code page is measured: `ESC t 19` / cp858 prints the Spanish letters,
  16 is not cp1252 on this firmware; a text-only sample of 1117 bytes printed in 1.6 s with a
  0.9 s connect ([desk results](../results/2026-10-28-mp210-on-the-desk.md)). The columns, the
  band height, the pacing and the tail wait on a picture are still estimates.
- The plates are not in the repo yet (`fish_brain/ticket_art/` does not exist): tickets print
  the card's numeral, name and meaning with no picture until they are. The plates' licence in
  Mexico (life+100; Smith died 1951) is his call before they are committed.
- The laptop with nothing set is unchanged: `printer=off`, no thread, no row.
- `--print-test` and Reprint on the board make paper: his to press.
- Pairing is his, as `arduino` on the board (`deploy/README.md`); a printer that shows up as an
  audio sink would join `FISH_AUDIO_ROUTES`' `bluez_output.*` (check `wpctl status`).
- Whether the ticket is late against the closing line, and whether the act's time changes, is
  measured on the board (`docs/results/<date>-mp210-on-the-board.md`, not written yet).

## Amendment, 2026-10-29

The footer loses the folio and the plate's credit, to save paper (his word): the date and the
place stay. The credit for the plates (Pamela Colman Smith, 1909) belongs on the page instead.
