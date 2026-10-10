# UNO Q: raw UART link with `uart_echo` — 2026-10-10

Host: the board `segunda`; core `arduino:zephyr` 0.55.2, router 0.10.0. Sketch from commit
`3f8bc0d`. Pass line set beforehand: every line acknowledged.

| Step | Command (on the board) | Result |
|---|---|---|
| Compile | `arduino-cli compile -b arduino:zephyr:unoq uart_echo` | 59 s; 20,860 bytes |
| Upload | `arduino-cli upload -b arduino:zephyr:unoq uart_echo` | OpenOCD over SWD; no port, no password, router running |
| Release the port | `arduino-router-cli '$/serial/close' /dev/ttyHS1` | `true` |
| 100 lines, one at a time | `stty -F /dev/ttyHS1 115200 raw -echo -crtscts clocal`, then `PING n` and wait for the reply | 100 of 100 answered `ACK PING n`; 3.75 ms average per round trip |
| Hand the port back | `arduino-router-cli '$/serial/open' /dev/ttyHS1` | `true` |

Pass. This confirms on the board: the Linux link is `Serial2`; `$/serial/close` frees the
port while the router keeps running and the sketch keeps running; uploading works with the
router up.

Not done: the 33-lines-per-second soak with `tools/uart_check.py` (it needs the Python
environment on the board), a router restart in the middle of a run, and the LED behaviour,
which nobody has looked at yet.
