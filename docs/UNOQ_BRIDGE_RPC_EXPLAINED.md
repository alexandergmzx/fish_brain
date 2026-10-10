# Arduino UNO Q — Bridge RPC explained, and how to get out of it

Investigation notes from a live board (`arduino@segunda`), August 2026.
Companion to `UNOQ_PORT_ROADMAP.md` — this document covers the *transport* axis only.

---

## 0. TL;DR

| Question | Answer |
|---|---|
| Is Bridge RPC a replacement for serial? | No. It runs **on top of** a normal 115200 UART. |
| Is it like ROS 2 / DDS? | Same layer, different paradigm. Closest match is **ROS 2 services**, not DDS topics. |
| Is it slower? | Only `Bridge.call()` is, because it blocks. `Bridge.notify()` does not. |
| Is `Serial.println` debug gone? | No. It's on **TCP 127.0.0.1:7500**. `nc 127.0.0.1 7500`. |
| Can I get the naked UART? | Probably yes. Mask 4 systemd units, then `/dev/ttyHS1` is free. One test decides it. |
| Will that brick the board? | No held GPIO lines, and stop pulses MCU reset gracefully. See §5. |

---

## 1. The layer confusion (why this felt worse than it is)

The single most useful reframe: **Bridge RPC is not a peer of I²C or SPI.** Comparing them is a
category error. The honest comparison is *Bridge RPC vs. the text protocol you hand-rolled in
`CommandProcessor.h`* — both are application-layer protocols, one of which you owned.

| Layer | UART / I²C / SPI | UNO Q Bridge | ROS 2 |
|---|---|---|---|
| Physical | TTL pins, clock+data | internal UART pins | Ethernet / shared memory |
| Framing | you invent it (`\n`) | MessagePack frames | RTPS |
| Addressing | none (point-to-point) | named endpoints via broker | topic/service names + discovery |
| Semantics | you invent it (`MOUTH 238 14`) | typed RPC methods | msg / srv types |
| Your API | `Serial.write()` | `Bridge.call()` | `rclpy` |

I²C and SPI occupy the top two rows only. Everything below row two, you were already writing
yourself — Arduino just took it away and gave you theirs.

### Physical reality of the "bridge"

| Side | Peripheral | Device |
|---|---|---|
| MPU (QRB2210, Linux) | UART2 | `/dev/ttyHS1` |
| MCU (STM32U585, Zephyr) | LPUART1 | `Serial2` |
| Baud | | 115200 |

That's it. One UART. Everything else is software.

---

## 2. Is it DDS-like? Partly.

| Property | `fish_brain` pyserial | UNO Q Bridge RPC | ROS 2 service | DDS topic |
|---|---|---|---|---|
| Paradigm | byte stream | request/reply + fire-and-forget | request/reply | pub/sub |
| Who owns the wire | your process | `arduino-router` daemon | DDS participant | DDS participant |
| Broker | none | **yes** — star topology | none (peer-to-peer) | none (peer-to-peer) |
| Participants | exactly 2 | many | many | many |
| Discovery | none | registration with router | DDS discovery | DDS discovery |
| Serialization | ASCII you wrote | MessagePack (binary) | CDR | CDR |
| Blocking | no | `call()` yes / `notify()` no | client choice | never |

Two corrections to the DDS intuition:

- **DDS is data-centric and brokerless.** Bridge is function-centric with a central daemon.
  Architecturally it's closer to **gRPC or JSON-RPC** than to DDS.
- MessagePack-RPC is a **published open spec**, not an Arduino invention.

Nearest true peers: **Firmata** (classic Arduino RPC-over-serial) below it, **micro-ROS**
(DDS-XRCE with an agent) above it. Bridge sits between them.

### Mental-model mapping

| ROS 2 concept | UNO Q equivalent |
|---|---|
| service client | `Bridge.call("mouth", 238, 14)` |
| service server | `Bridge.provide_safe("mouth", mouth)` |
| publisher (fire-and-forget) | `Bridge.notify(...)` |
| `/rosout` | `Monitor.println()` → TCP 7500 |
| `ros2 node list` | router registration log lines |

---

## 3. Why Arduino built it this way — and where the reasoning fails

Stated/inferable rationale, graded honestly:

| Claimed constraint | Verdict |
|---|---|
| **Two OSes, one wire.** Linux has many processes, the MCU has one program; the router multiplexes so Python vision + C++ motors + App Lab can share the link. | ✅ Legitimate. Multipoint is genuinely impossible over raw point-to-point serial. |
| **Non-programmers shouldn't write framing protocols.** | ❌ Weak. Anyone writing `Bridge.provide_safe()` is programming, against a *less*-documented abstraction than `Serial.read()`. |
| **Debug must coexist with data on one wire.** | 🟡 True in principle, but the multiplexed monitor is so poorly documented it reads as removed. |

**The real complaint, correctly stated:** port arbitration is a solved problem in embedded
(advisory locks, `flock`, a small mux). And the elegant solution *is* a daemon that owns the port
— which is what `arduino-router` is. So the daemon isn't the sin. The sin is that its protocol
is heavier than necessary and its escape hatches are undocumented. For a two-process project
like `fish_brain`, all the multipoint benefits are irrelevant and you pay the tax anyway.

### Where the latency actually is

| Cost | Real? |
|---|---|
| MessagePack serialization | Small — binary, ~10–20 bytes framing per call. Not JSON. |
| The 115200 wire | Same wire you'd have raw. Unchanged. |
| **Synchronous round-trip on `call()`** | ✅ **This is the whole problem.** Kills a streaming lip-sync clock. |
| Unix-socket hop through the daemon | Microseconds. Noise next to the UART. |

So the cheapest fix for speed is not escaping RPC — it's `notify()`.

---

## 4. Router anatomy (as observed on this board)

Effective command line, after the runtime drop-in:

```
/usr/bin/arduino-router \
  --unix-port      /var/run/arduino-router.sock \
  --serial-port    /dev/ttyHS1 \
  --serial-baudrate 115200 \
  --after-ready    '/usr/bin/gpioset -c /dev/gpiochip1 -t0 70=1'
```

| Interface | Address | Purpose |
|---|---|---|
| Unix socket | `/var/run/arduino-router.sock` | RPC clients (Python, C++, n8n, `qmon.py`) |
| TCP listener | `127.0.0.1:7500` | **Monitor stream** — this is your `Serial.println` |
| UART | `/dev/ttyHS1` @ 115200 | the actual MPU↔MCU link |

Internal methods seen registered at startup:

| Method | Meaning |
|---|---|
| `mon/write` | MCU `Monitor.println()` arrives here |
| `mon/reset` | clear monitor state |
| `$/serial/open` | **undocumented** — router-mediated serial access |
| `$/serial/close` | ditto |

`$/serial/open` is worth probing with `qmon.py` in probe mode. If it can hand out `ttyHS1`
itself, it's a sanctioned raw-wire escape hatch and §6 becomes unnecessary. Zero risk to test.

### Sketch-side API

| Call | Behaviour | Use for |
|---|---|---|
| `Bridge.begin()` | init transport, register with router | always, if using Bridge at all |
| `Bridge.call(m, args)` | **synchronous** round-trip, returns value | commands where you need the ACK |
| `Bridge.notify(m, args)` | fire-and-forget, no wait | **streaming telemetry / lip-sync** |
| `Bridge.provide(n, fn)` | handler runs in background RPC thread | pure computation only |
| `Bridge.provide_safe(n, fn)` | handler runs in `loop()` context | **anything touching GPIO/PWM/servo** |

> ⚠️ `provide()` for motor or PWM work will fail intermittently — Arduino hardware APIs are not
> safe in the RPC thread. Use `provide_safe()`. This is the single sharpest undocumented edge.

---

## 5. The GPIO lines (and why stopping the router is safe)

From the generated drop-in `/run/systemd/generator/arduino-router.service.d/10-imola.conf`:

| Line | Driven when | Value | Reading |
|---|---|---|---|
| 37 | `ExecStartPre` (prefixed `-`, failure ignored) | 0 | "put the micro in a ready state" — reset-release or BOOT0-low, latched |
| 70 | `--after-ready`, only once UART link is live | 1 | "router is up" flag; boot animation gate |
| 38 | `ExecStopPost` only | 0 → 1 | **momentary MCU reset pulse** |

`gpioinfo -c /dev/gpiochip1` on a running board:

```
line 37: output          (no consumer)
line 38: input           (no consumer)
line 70: output          (no consumer)
```

**No `consumer=` on any of them.** `gpioset -t0` sets and exits, releasing the line — nothing is
being held. Line 38 sitting as `input` confirms it's pulsed, not held.

Consequence: **stopping the router does not strand the MCU.** The stop path deliberately clears
the ready flag and pulses reset so the boot animation reclaims the LED matrix. The STM32 comes
back running whatever is in flash. You do not need to take over any GPIO.

> Unverified: line 38 = nRST and line 37 = BOOT0 are inferred from timing and the drop-in's
> own comment, not from a schematic. Confirm against the UNO Q schematic on the Arduino product
> page if you need certainty.

libgpiod is **v2** on this image — `gpioinfo gpiochip1` fails; use `gpioinfo -c /dev/gpiochip1`.

---

## 6. Why `systemctl stop` keeps losing

```
$ sudo systemctl stop arduino-router
Job for arduino-router.service canceled.
$ systemctl is-active arduino-router
active
```

The dependency graph:

| Unit | Relationship |
|---|---|
| `arduino-router.service` | `Restart=always`, `RestartSec=3` |
| `arduino-app-cli.service` | `Wants=` router (daemon on :8800) |
| `arduino-router-serial.service` | **`Requires=` router** (hard) |
| `arduino-router-serial.path` | **triggers** the above on `/dev/ttyGS0` appearing |

Loop: the `.path` unit fires → starts `arduino-router-serial.service` → which `Requires=` the
router → a start job supersedes your stop job → *"canceled"*. Stopping the service without the
`.path` gives the explicit warning: *"but its triggering units are still active."*

`arduino-router-serial.service` is just:

```
socat file:/dev/ttyGS0,raw,echo=0,b9600,crtscts=0 tcp:127.0.0.1:7500
```

i.e. it bridges the **USB gadget serial port to the Monitor TCP stream**. Plug the board into a
laptop by USB, open the CDC port, and you get `Monitor.println()` output. That is the "serial
monitor" you expected — implemented as a proxy rather than a real UART.

### Bringing it down

```bash
sudo systemctl mask --now \
  arduino-router-serial.path \
  arduino-router-serial.service \
  arduino-app-cli.service
sudo systemctl stop arduino-router.service
systemctl is-active arduino-router          # want: inactive
```

Or short-circuit the whole graph:

```bash
sudo systemctl mask --now arduino-router.service
```

Masking beats `disable` — it makes the dependency *unsatisfiable* rather than a race you can lose.

**Recovery:** `sudo systemctl unmask --now` on all four. A router restart re-runs `ExecStartPre`
and re-sequences the MCU, so you return to a clean state without a power cycle.

---

## 7. The three escape routes, ranked

| Route | What it is | Cost | Verdict |
|---|---|---|---|
| **A. `notify()` instead of `call()`** | Stay on Bridge, drop the blocking round-trip | ~1 hour | 🟢 **Do this first.** Removes most of the pain for free. |
| **B. FTDI on D0/D1** | USB-TTL dongle, MCU `Serial1`, pyserial over USB | a dongle + a USB port | 🟡 Known-good fallback. Already scoped in the roadmap. |
| **C. Mask the router, own `/dev/ttyHS1`** | True naked UART | systemd wrangling + one test | 🟢 Now viable — see §5. Gated on the flash test below. |
| **D. Device-tree overlay for a second MPU UART** | QUP/SE0 reconfiguration | days | 🔴 Not worth it. Overlay work on a Qualcomm SoC to dodge a library you've half-ported. |

### Route C — order of operations

The whole thing hinges on **step 3**. Do not build on top of it until it passes.

1. Mask the four units (§6). Confirm `systemctl is-active arduino-router` → `inactive`.
2. `sudo fuser -v /dev/ttyHS1` — confirm nothing holds the port.
3. **`arduino-cli upload` a blink sketch with the router down.**
   Flashing goes through `arduino-debug.service` / OpenOCD over the SPI programming link, which
   is independent of the router's UART. **Confirmed by precedent** — see §8, mominux flashed
   Zephyr with the router stopped and disabled. Still verify once on your own board.
4. Sanity-check the free wire before writing any code:
   ```bash
   stty -F /dev/ttyHS1 115200 raw -echo
   hexdump -C /dev/ttyHS1
   ```
5. Flash a sketch with **no `Bridge.begin()`**, talking the plain MCU-side UART object
   (`Serial2` on older cores, `Serial` on Zephyr core 0.90.0+ — verify, see §8).
6. Open `/dev/ttyHS1` from Python at 115200 with pyserial. You are back to `fish_brain`'s
   original `serial_link.py` with a different device path.

If step 3 fails → unmask everything, go to route B.

### What route C costs you

| Lost | Replacement |
|---|---|
| `Monitor.println` on TCP 7500 | your own `Serial2` prints — you own the wire now |
| Multipoint (several Linux processes) | irrelevant for `fish_brain` |
| App Lab, `arduino-app-cli` | already not using it |
| Boot animation on the LED matrix | your sketch owns the matrix |

---

## 8. Prior art — people who already did this

### mominux: Zephyr on the UNO Q (Nov 2025)

The closest precedent. He flashed upstream Zephyr onto the STM32U585, which made the Arduino
runtime — and therefore the router — incompatible. Same problem, same solution path.

| Step | What he did |
|---|---|
| Find the Linux device node | Read `ExecStart` in `arduino-router.service`; confirmed via `dmesg \| grep -i tty` → `4a88000.serial: ttyHS1 at MMIO` |
| Find the MCU peripheral | `grep -n "lpuart1" build/zephyr/zephyr.dts` → LPUART1, `current-speed = <115200>` |
| Free the port | `systemctl stop arduino-router && systemctl disable arduino-router` — UART free immediately |
| Flash with router down | ADB pushes the hex, `arduino-debug.service` runs OpenOCD over the **SPI programming link** ✅ |
| Verify the wire | `stty -F /dev/ttyHS1 115200 raw -echo` then `hexdump -C /dev/ttyHS1` |

**Key takeaway: flashing is independent of the router.** This resolves the route C gate by
precedent. Note he used `disable`, not `mask` — he was on adb; with `arduino-router-serial.path`
watching `/dev/ttyGS0` on this board, mask remains the safer choice (§6).

Also worth knowing: `arduino_uno_q` is an officially supported Zephyr board, so the DTS work is
already upstream if you ever want to drop the Arduino core entirely.

https://mominux.com/weekend-project-zephyr-on-the-uno-q-like-bumping-into-an-old-friend/

### Tips gathered from forums and comments

| Tip | Detail |
|---|---|
| **`Serial3` on D20/D21** | Reported alongside `Serial1` (D0/D1) as responding near-instantly. A *second* free MCU UART — more headroom for route B than assumed. |
| ⚠️ **Bridge object renamed** | On Zephyr core **0.90.0+** the bridge moved from `Serial2` to plain `Serial`, and `Serial.available()` on it **hangs the MCU**. Verify your core version before trusting object names anywhere in this document. |
| **`--verbose` router flag** | Arduino's own docs show adding it to the ExecStart drop-in. Free RPC-level tracing before deciding to leave. |
| ⚠️ **Bare-metal LPUART1 fails** | A forum report (Tock OS port): LED blink works, but clock init and serial fail outside the Zephyr bootloader. A known wall below the core level. |
| **`Monitor` is one-way** | Confirmed by multiple people asking for a response path. Reinforces `notify()` as the streaming answer. |

Relevant threads:
- https://forum.arduino.cc/t/uno-q-serial-communication-between-linux-and-stm32-beside-arduino-router-bridge/1444094
- https://forum.arduino.cc/t/uno-q-how-to-achieve-manual-control-over-router-bridge-formed-using-uart2-ttyhs1-mpu-lpuart1-serial2-mcu-devices/1426989
- https://forum.arduino.cc/t/arduino-uno-q-serial-dev-ttyhs1-mpu-mcu-communication/1443235

---

## 9. Reference

| Thing | Where |
|---|---|
| Star-topology architecture diagram | https://docs.arduino.cc/tutorials/uno-q/user-manual/ |
| Byte-level MessagePack frame decode (logic analyzer) | https://myembeddedstuff.com/arduino-uno-q-rpc-explained |
| `Arduino_RouterBridge` internals | https://deepwiki.com/arduino-libraries/Arduino_RouterBridge |
| Router source | https://github.com/arduino/arduino-router |
| MessagePack-RPC spec | https://github.com/msgpack-rpc/msgpack-rpc |

### Quick commands

```bash
nc 127.0.0.1 7500                       # Monitor / Serial.println stream
sudo ss -ltnp | grep arduino-router     # confirm the listener
gpioinfo -c /dev/gpiochip1              # libgpiod v2 syntax
systemctl list-dependencies --reverse arduino-router.service
sudo fuser -v /dev/ttyHS1
```

---

## 10. Open questions

- [x] ~~Does flashing survive the router being down?~~ **Yes** — precedent in §8; confirm locally.
- [ ] Does `$/serial/open` expose `ttyHS1`, or only auxiliary ports? (`qmon.py` probe — no risk)
- [ ] Which Zephyr core version is on this board? Decides `Serial` vs `Serial2` (§8)
- [ ] Schematic confirmation that line 38 = STM32 nRST, line 37 = BOOT0 —
      `ABX00162-schematics.pdf` on docs.arduino.cc
- [ ] Measured round-trip latency of `call()` vs `notify()` at 115200, to quantify §3

---

## 11. Corrections (2026-10-10)

Checked on the board and against arduino-router 0.10.0, ArduinoCore-zephyr 0.55.2 and
Arduino_RouterBridge 0.4.3. Where this section and the text above disagree, this one is right.

| Section | Above says | What is true |
|---|---|---|
| Header | Companion to `UNOQ_PORT_ROADMAP.md` | That file is not in this repo |
| §1, §7, §8 | Link object is `Serial2` on older cores, `Serial` on 0.90.0+ | The raw link is `Serial2` on every core from 0.55.0. Since 0.55.0 `Serial` is an alias of the Bridge `Monitor`; its calls wait for the router with no timeout, which is the "hang" |
| §4 | Router command line | The unit's own `ExecStart` has only `--unix-port`. The serial arguments, the GPIO 37 step and `--after-ready ... 70=1` come from a generated drop-in, `/run/systemd/generator/arduino-router.service.d/10-imola.conf`. A drop-in that adds `--verbose` must repeat that full line and sort after it |
| §4, §10 | `$/serial/open` and `$/serial/close` are undocumented | Both are in the router's README. `$/serial/close ["/dev/ttyHS1"]` releases the port and returns once it is free; the daemon keeps running |
| §5 | Stopping the router does not strand the MCU | It does for a default build: the stop action sets line 70 low and resets the MCU, and the loader waits for line 70 before starting the sketch. Line 38 is the MCU reset (confirmed by the OpenOCD config) |
| §6 | Mask the units | `mask` fails on router 0.10.0 because the units are real files in `/etc/systemd/system`. From 0.11 they move to `/usr/lib` and can be masked |
| §7 route C | Mask, then own the port | Release the port with `$/serial/close` instead. While it is released, methods the MCU provides are unregistered, and a Bridge sketch that starts meanwhile waits forever in `Bridge.begin()`; `$/serial/open` plus an MCU reset brings them back |
| §7 route C | — | A router restart reopens the port while another process holds it, and the other process sees no error. Watch the router socket, not the writes |
| §7 step 3, §8 | Flashing uses `arduino-debug.service` over SPI | `remoteocd` runs OpenOCD on the board, bit-banging SWD on gpiochip1 lines 25/26 with reset on 38. No such service exists. Flashing does work with the router down |
| §4 | `provide_safe` always runs in `loop()` | With Arduino_RPClite 0.3.0 the background thread can also run it, on a 500-byte stack. Keep handlers to "copy and return" |
| §7 route A | — | A notification to a method nobody registered is dropped without an error; a call returns error code 2. Bridge sketches must use the default "Wait for Linux" start mode |
| §4 | Socket is world-writable | True for 0.10.0. From 0.11 it is `0660 root:arduino-router` |
