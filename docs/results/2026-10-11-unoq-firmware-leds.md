# UNO Q: the fish firmware on the MCU, no drivers attached — 2026-10-11

Host: the board `segunda`; core `arduino:zephyr` 0.55.2, router 0.10.0 (`NRestarts=0`
throughout). fish_brain `c6789ce` (tools), Big_mouth `braintip` `772ef54`. Nothing was wired
to the header (owner's word). Flashed with `deploy/unoq_fw.sh`; the MCU link was kept
released during the tests.

**Level 3: link and firmware execution, read back from the MCU. No driver, no motor, no fish
body: nothing here shows motion, sync or stall behaviour, or the driver inputs while the MCU
is in reset.** What a person saw on the LEDs is recorded separately when it has been looked at.

Pass lines set before measuring: every reply as in the Big_mouth source; pulses within
−1.0/+2.0 ms on the MCU clock; 0 lines lost; duty within 1.5 points; MCU clock within 0.1 %.

## Uploads (`~/.local/state/fish_fw/uploads.tsv`)

| # | Sketch | Commit | Seconds |
|---|---|---|---|
| 1 | `pwm_probe` | fish_brain `c6789ce` | 11 |
| 2 | `BigMouthQ`, trace build (`-DFISH_TRACE=1`) | Big_mouth `772ef54` | 10 |
| 3 | `BigMouthQ`, normal build (left on the MCU) | Big_mouth `772ef54` | 10 |

Compile on the board: probe 64 s, firmware 89 s (normal, 27,492 bytes) and 92 s (trace).
Uno R4 build of the same sources: `firmware.bin` sha256 `953f9f39…` before and after the
port (clean PlatformIO builds), 50,292 bytes.

## Pins (upload 1, `tools/fw_check.py listen --seconds 45 --release-router`)

| Check | Result |
|---|---|
| State at entry, before any `pinMode` | D12, D11, D6, D4, D3, D7, D5: analog mode, floating. D2 (PB3): alternate function 0, floating, low. **D8 (PB4): alternate function 0 with pull-up, reads high** |
| Direction pins D12, D11, D2, D4, D7, D8 | Write 1 and 0 read back on all six; no other pin moved |
| PWM on D3, D5, D6, `analogWrite` only | 499.9 to 500.0 Hz. Raw high fraction at 64/128/200/238/254: 23.3 / 47.7 / 76.7 / 92.7 / 99.6 %. The probe takes fewer samples while the pin is high (297,600 at 0 % against 269,376 at 100 %, ratio 1.105); corrected with that ratio: 25.1 / 50.2 / 78.4 / 93.3 %, against 25.1 / 50.2 / 78.4 / 93.3 % commanded. 0 gives no high sample, 255 gives 100 % |
| Enables together (D6, D3, D5), then D6 to 0 | Same values; D3 unmoved |
| Direction pins while the enables run PWM | 0 wrong samples; toggling each direction pin shifts no duty by more than 0.1 point |
| `pinMode(OUTPUT)` before `analogWrite` (D9, D10) | PWM present, same duty. The forum report is not reproduced on this core. (The probe prints `BROKEN` for these rows: its duty window does not allow for the sampling bias.) |
| Delay from `analogWrite` to the pin | Rising 0.01 to 2.0 ms, average 1.0 ms; falling 0 to 1.9 ms, average 0.85 ms: the duty changes at the next 500 Hz period |
| Cost of a call | `analogWrite` 10 µs average (24 max); `digitalRead` and `digitalWrite` 2 µs; a matrix draw 6 µs (16 max) |
| Clocks | `millis` and `micros` agree within 1 ms; empty loop 539,148 passes per second |
| UART | 57 bytes of transmit room when idle |
| Other PWM-capable pins | D2, D7, D8, D9, D10, D11, D13 give PWM; D12 does not |

The probe's own verdict line reads `ok=69 fail=12`. All twelve are duty rows that fail only
by the sampling bias described above.

LEDs as seen by the owner: the matrix's row 0 is the edge next to the USB-C connector; LED3
fades red, green, blue with `analogWrite`; LED4 lights with LOW.

## Firmware, trace build (upload 2)

| Check | Command | Result |
|---|---|---|
| Link, motor-safe | `fw_check.py check --release-router --count 300` | 3 of 3 probes, status all stopped, 300 of 300 echoed and answered; round trip 5.69 ms average, 5.74 at the 95th percentile, 9.63 maximum |
| Protocol transcript, motor-safe lines | `fw_check.py replay` | 81 of 81 as expected |
| Protocol transcript, all lines | `fw_check.py replay --drive --held` | 122 of 122 as expected |
| Pulses `MOUTH 238 n` and `MOUTH -200 n`, n = 1 to 104 ms | `fw_check.py timing --drive --held` | Every pulse between −0.99 and +0.01 ms of the commanded length; averages −0.23 to −0.79 ms |
| Chains | same | `NECK 230 650` −0.76 ms, `NECK -200 560` −0.58 ms, `TAIL 210 230 -210 210` 0.00 ms per step |
| Pre-emption | same | A second line 100.3 ms into a pulse replaces it at 100.3 ms |
| STOP | same | All outputs off within 1 ms of the line; status all stopped |
| Held PWM limit | same | Stopped at 5000.1 ms on the MCU clock, 5.013 s on the host's |
| Truth table | same | 279 pin records: `+` is IN1 high, `−` is IN2 high, stop is both low, duty = \\|pwm\\| |
| MCU clock | same | −547 ppm against the host over 12 s |
| Loop | same | Longest gap 13.2 ms (while a long reply was printed), no trace record dropped |
| Soak, the fish's own lines with bursts | `fw_check.py soak --seconds 300 --drive --bursts` | 9,999 sent, echoed and accepted, 0 lost; round trip 9.13 ms average, 21.75 maximum; longest loop gap 1.2 ms |
| One spoken sentence through the app | `python -m fish_brain.app --say "…"` with `FISH_LINK_LOG` | Voice from the USB speaker (heard by the owner on the earlier run with `uart_echo`). 185 lines in 8.1 s, 182 echoed and accepted, none rejected. The other three are the attach `STOP` and the last two lines, whose replies the log of that commit could not record (the log was fixed afterwards, commit `8d72d6e`) |

## Firmware, normal build (upload 3, the one left on the MCU)

| Check | Result |
|---|---|
| `fw_check.py check` | Pass; 300 of 300; round trip 5.75 ms average, 48.9 maximum |
| `fw_check.py replay --drive --held` | 122 of 122 |
| `fw_check.py soak --seconds 600 --drive --bursts` | 19,999 sent, echoed and accepted, 0 lost; round trip 5.10 ms average, 5.17 at the 95th percentile, 47.5 maximum |

Pulse timing was measured on the trace build of the same source and not again on this one.

## Rehearsals with the app talking (normal build, commit `993a742`)

The app was run by hand on the board (`python -m fish_brain.app --say "<23 s of text>"`,
local voice, `FISH_LINK_LOG` on). Pass lines: tools refuse and the fish loses no line; all
outputs off within 1 s of a hard kill; the voice continues through a reflash.

| Case | What was done | Result |
|---|---|---|
| Tools against a talking fish | 9 s into the sentence: `app --check-link`, `uart_check.py --release-router`, `fw_check.py check --release-router`, `unoq_setup.sh router restore`, `unoq_fw.sh upload` | All five refused, naming the holder (`pid … app.py`). The fish sent 626 lines in 23.2 s; 626 echoed by the MCU, none rejected |
| Hard kill | `kill -9` of the app 10 s into the sentence, then `fw_check.py send STATUS` | 0.99 s after the kill (the time the tool needs to start): MOUTH, NECK, TAIL all `stopped`. No STOP was sent; the last pulse ended by itself |
| Restart after the kill | `app --say "Ya volví."` | First line on the link: `STOP`, 0.9 s before the first mouth pulse |
| Reflash mid-sentence | `unoq_fw.sh upload BigMouthQ --force` 9 s into the sentence (upload 4, 11 s) | The voice went on. Journal: `[link] MCU silent` 15.0 s after attach, `[link] MCU answering again` 5.8 s later. 635 lines written. `fw_check.py check` afterwards: pass |

## Found on the way

- **Every byte the MCU sends while the router owns the port is one `ERROR … expected array`
  line in the router's journal.** The probe cost 1,474 lines every 20 s, the trace build
  about 20 lines a second. The normal build prints its banner (about 1 kB) once per MCU
  start and nothing else unprompted. The journal is capped at 50 MB.
- The core's `portInputRegister()` does not compile; the probe takes the port block from the
  GPIO device.

## Not done

- The owner has not yet watched the lamp walk or a spoken sentence on the matrix.
- A router restart in the middle of speech (the owner's `sudo`).
- An overnight soak.
- Anything with a driver or a motor.
