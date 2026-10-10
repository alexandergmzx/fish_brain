# Test sketches for the UNO Q link

Two small MCU sketches that prove the Linux <-> STM32 link before the real firmware is
ported. They move no motors. Each one pairs with one fish_brain transport:

| Sketch | Transport | Linux side | Reply |
|---|---|---|---|
| `uart_echo` | `FISH_SERIAL_TRANSPORT=serial` (raw UART) | `/dev/ttyHS1`, released by the router | `ACK <line>` on the UART |
| `bridge_echo` | `FISH_SERIAL_TRANSPORT=bridge` (router RPC) | `fish_cmd` / `fish_ping` through `/var/run/arduino-router.sock` | `ACK <line>` on the Monitor, TCP `127.0.0.1:7500` |

Status (2026-10-10): **both sketches are uncompiled and unflashed.** They were written
against core `arduino:zephyr` 0.55.2, `Arduino_RouterBridge` 0.4.3 and the files on the
board, but nothing was built. The upload recipe below is taken from the core's
`platform.txt` and was not run either. Compiling and flashing are the owner's steps.

## Rules

1. **Default FQBN only: `arduino:zephyr:unoq`** (startup mode "Wait for Linux").
   `wait_linux_boot=no` ("Immediate") is allowed only for a raw-UART sketch on a board
   where the router is permanently off and nothing raises GPIO line 70. A Bridge sketch
   built that way calls `Bridge.begin()` a few milliseconds after power-up, sends
   `$/reset` into a UART nobody reads yet, and blocks forever.
2. **The link is `Serial2`** on cores 0.55.0 to 1.0.0 (0.55.2 is installed). Cores 0.51
   to 0.54 had it on `Serial1`. On current cores `Serial1` is USART1 on D0/D1, where the
   Zephyr console and boot banner go.
3. **A raw-UART sketch never touches `Serial`, `Monitor` or `Bridge`.** `Serial` is the
   router Monitor: a blocking RPC with no timeout. With the router away it hangs the
   sketch.
4. **A Bridge sketch never begins a second hardware UART** (`Serial1.begin()`,
   `Serial2.begin()`): the Bridge already owns the link.
5. **Thread helpers: only `k_sched_current_thread_query()` and `k_thread_name_copy()`.**
   Never `k_current_get()` or `k_thread_name_get()`. The default dynamic link mode
   resolves only the symbols listed in the core's
   `variants/arduino_uno_q_stm32u585xx/syms-dynamic.ld`, and those two are not in it.
   Check that file before using any other Zephyr kernel call.
6. **Bridge handlers only copy.** A handler may run on the Bridge library's own thread,
   which has a 500-byte stack. Copy the line into a mailbox and do the work in `loop()`
   (see `bridge_echo.ino`).
7. Both ends tolerate a stray byte or line around an MCU reset.

## Compile

On the board (`ssh arduino@segunda.local`, from the repo). `arduino-cli` 1.5.1 and the
core are already installed there:

```bash
arduino-cli compile -b arduino:zephyr:unoq tools/sketches/uart_echo
arduino-cli compile -b arduino:zephyr:unoq tools/sketches/bridge_echo
```

`bridge_echo` needs `Arduino_RouterBridge` (0.4.3 is in `~/Arduino/libraries`).
To point `uart_echo` at another UART, edit `#define LINK` at the top of the sketch.

## Upload (owner's step)

Flashing is OpenOCD over SWD, run by `remoteocd` on the board. It does not use the UART
and does not need the router. It resets the MCU when done.

```bash
arduino-cli board list          # the board lists itself: 192.168.1.114, protocol "network"
arduino-cli upload -b arduino:zephyr:unoq -p 192.168.1.114 -l network \
    --upload-field password=<board password> tools/sketches/uart_echo
```

Flashing a sketch replaces whatever runs on the MCU (an App Lab sketch, the firmware).

## Verify `uart_echo` (raw UART)

The router owns `/dev/ttyHS1`, so release it first. `uart_check.py` does that and hands
the port back when it ends:

```bash
.venv/bin/python tools/uart_check.py --release-router
# expect: sent 1000, acked 1000, lost 0, RESULT PASS
```

By hand:

```bash
arduino-router-cli '$/serial/close' /dev/ttyHS1      # the port argument is required
stty -F /dev/ttyHS1 115200 raw -echo -crtscts clocal
cat /dev/ttyHS1 &
echo "PING 1" > /dev/ttyHS1                          # prints: ACK PING 1
kill %1
arduino-router-cli '$/serial/open' /dev/ttyHS1       # hand the port back
```

While the port is released every Bridge method is unregistered and App Lab cannot reach
the MCU. Always hand it back.

## Verify `bridge_echo` (router RPC)

Order matters: the router must own the port **before** the sketch boots. Hand the port
back first (see above), then flash. The flash resets the MCU, so `Bridge.begin()`
registers against a listening router.

```bash
arduino-router-cli fish_ping                     # prints 1
nc 127.0.0.1 7500 &                              # the Monitor
arduino-router-cli -n fish_cmd "PING 1"          # nc prints: ACK PING 1
kill %1
.venv/bin/python tools/uart_check.py --transport bridge
```

Expected extra Monitor lines, counted by `uart_check.py` as "garbage" but not as loss:

- `THREADS handler=<name> loop=<name>` once, after the first command. `handler=bridge`
  means handlers run on the library's small thread (rule 6).
- `DROPPED <n>` if the 8-line mailbox overflowed. That is real loss.

If `fish_ping` fails with router error 2 ("method not available"), the sketch is not
registered: it is not flashed, or it booted while the port was released. Run
`arduino-router-cli '$/serial/open' /dev/ttyHS1`, then reset or reflash the MCU.

Not checked yet: `arduino-router-serial.service` (socat, USB gadget serial) keeps its
own connection to port 7500. If `nc` or `uart_check.py` see no replies while `fish_ping`
answers, the Monitor may serve one client at a time; look at `journalctl -u arduino-router`.

## From the laptop

The router socket and the Monitor can be reached through ssh tunnels, without copying
anything to the board:

```bash
ssh -N -L 127.0.0.1:7600:/var/run/arduino-router.sock \
       -L 127.0.0.1:7500:127.0.0.1:7500 arduino@segunda.local &
.venv/bin/python tools/uart_check.py --transport bridge --router-socket tcp://127.0.0.1:7600
```

`uart_check.py --self-test` checks the tool itself against a pty pair and a fake router,
with no board at all.
