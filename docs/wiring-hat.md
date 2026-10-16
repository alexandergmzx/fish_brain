# The Sorting Hat on the UNO Q: one TB6612FNG module in the bell

The Spin Master Talking Sorting Hat replaces Billy Bass #2 for the fair of 2026-10-17 (the
owner's word, 2026-10-16). One DC motor moves the mouth and the tip together through a one-way
cam (his teardown, 2026-10-16), so the build is one TB6612FNG module, one firmware channel
(`MOUTH`) and one new firmware pin: the module's standby on D9. The UNO Q stays outside the
hat. This page is the wiring, the rules and the bring-up; the earlier plan for Billy Bass #2
(two modules, three channels) is kept in the chat of 2026-10-14 and is not needed here.

"You" = your hands, the meter, flashing, first motion. "Laptop" = compile, `fw_check`, the app.

## What the hat is

| Fact | Source | Consequence |
|---|---|---|
| One motor moves mouth and tip together; the stock drive turns it one way; more current = faster flapping | the owner's teardown, 2026-10-16 | A pulse is motion, not a position: the mouth runs in **gate mode** (below). Positions drift without feedback |
| Motor voltage read about 4.3 V peak, maybe more; the stock box takes 3 AA | the owner's meter, 2026-10-16; the build plan of 2026-10-10 | A DC meter averages a pulsed motor, so the pack voltage is the real ceiling. Cell count of the box: confirmed at step 0 |
| TB6612FNG: every input (IN1, IN2, PWM, STBY) has an internal 200 kΩ pull-down; STBY low = every output off whatever the inputs | [Toshiba datasheet](https://toshiba.semicon-storage.com/info/docget.jsp?did=10660) p.2, p.4 | STBY from D9, raised by the firmware only after the motor pins are driven low, keeps the driver off while the MCU is in reset (the Linux boot, a router restart, an upload). **No pull-down resistors** |
| VIH = 0.7 × VCC, VIL = 0.3 × VCC; VCC 2.7 to 5.5 V; Icc 1.1 mA typ; input clamp diodes to VCC | datasheet p.3, p.5 | VCC from the board's 3V3 OUT, the same rail as the GPIOs |
| IN1 = IN2 = L with PWM = H is stop (outputs high-Z); PWM low with IN1 ≠ IN2 is short brake; IN1 = IN2 = L with PWM = L is not in the table | datasheet p.4 | With AIN2 tied to the module's GND a negative `MOUTH` from the firmware can never reverse the motor: it stops |
| Output current rated 1.0 A only at VM ≥ 4.5 V; 0.4 A below that "without PWM operation"; 1.2 A absolute max per channel; thermal shutdown only, no over-current protection | datasheet p.3 | A 3 AA box (4.5 to 4.8 V fresh, less under load) sits at the bottom of the rated range: fresh cells for the fair, VM measured under a stall at step 6 |
| Application circuit: 10 µF + 0.1 µF on VM and on VCC close to the chip; regenerative current into VM when a pulse ends | datasheet p.7, p.10 | C1, a 470 µF 16 V electrolytic across the module's VM/GND, + on VM (the module's own capacitors are unconfirmed) |
| Generic module, likely: control header `PWMA AIN2 AIN1 STBY BIN1 BIN2 PWMB GND`, power header `VM VCC GND AO1 AO2 BO2 BO1 GND` (the SparkFun layout prints A01 A02 B02 B01, B reversed); three GNDs one net; no STBY pull-up; no reverse-polarity protection reported | ProtoSupplies; SparkFun v11 board file | AIN2 sits above AIN1. Check the silkscreen (photo) before wiring |
| The UNO Q header is 3.3 V logic; three GND pins; D9 is free GPIO; `analogWrite` is fixed at 500 Hz (the chip takes up to 100 kHz) | [Arduino UNO Q datasheet](https://docs.arduino.cc/resources/datasheets/ABX00162-datasheet.pdf), user manual | STBY on D9 (PB8: no debug function, expected to float in reset; **not measured**: the 2026-10-11 probe read the nine motor pins only; measured at steps 2 and 5). The pack never touches 5V or VIN |
| Hat motor running and stall current; VM under load; the module's temperature | not measured | Step 6 |

## The mouth: gate mode

The fish's mouth model turns loudness into a jaw *position*: a rise costs the difference of
the measured open curve in drive time, a fall the close curve. On the hat there is no
position: the motor runs only on rises, for a few to a hundred milliseconds, and a close is a
stop. The mouth would twitch at syllable onsets and stand still through a vowel.

`FISH_MOUTH_MODE=gate` runs the motor while the level is above a gate and stops it when the
level falls (`envelope.gate_pulses`): a pulse of 150 ms at `open_pwm`, re-sent every 100 ms
while the level holds (the MCU replaces a running pulse with the next line), so the motor runs
without a gap and never more than 150 ms past the last line the host managed to send; a fall
sends a 1 ms zero pulse, which stops it at once. Every line is a timed pulse, the firmware's
5 s limit still applies, nothing is held. `FISH_MOUTH_OPEN_PWM` is the flap speed (step 7).
The close pulse that ends every utterance and the neck and tail gestures still go out: on the
hat a close is a stop and `NECK`/`TAIL` drive pins with nothing on them.

Not built: a home sensor on the cam (a microswitch, or a magnet and a hall sensor) for
repeatable poses; after the fair.

## The wiring

One module, channel A only, on the same pin numbers as the fish's `MOUTH`. AIN2 is tied to
the module's GND, so the motor can only turn the way the stock drive turned it. Polarity is
fixed at first motion by swapping the two motor wires (pack off), never by pins.

| Firmware pin | Role | UNO Q (outside) | Module (inside the bell) |
|---|---|---|---|
| `MOUTH_IN1` | + flap | D12 | AIN1 |
| `MOUTH_IN2` | − (locked out) | D11, not connected | AIN2, short jumper to the module's GND |
| `MOUTH_ENA` | PWM, flap speed | ~D6 | PWMA |
| `DRIVER_STBY` | enable, high after `setup()` | D9 | STBY |
| logic supply | | 3V3 OUT | VCC |
| board ground | its own wire in the bundle | one GND pin | GND on the control header (after PWMB) |
| motor supply | hat pack + through its switch and a keyed 2-pin plug, red to VM | **never a board pin** | VM |
| motor return | hat pack −, shortest lead | **never a board pin** | GND next to VM |
| C1 | 470 µF 16 V electrolytic, + to VM, stripe to GND | | across VM/GND of the power header |
| motor | + = the wire the stock board drove + | | AO1 (+), AO2 |
| channel B | not used | | BIN1, BIN2, PWMB, BO1, BO2 open (the pull-downs hold them low; nothing jumpered to VCC) |

`NECK` and `TAIL` pins (D2, D4, ~D3, D7, D8, ~D5) stay unconnected.

```
Power (the hat pack never touches the board's 5V or VIN; pack - never a board pin)

  hat pack + --[switch]--[keyed plug]--+-- VM
                                       |
                                    C1 470 uF, + on VM
                                       |
  hat pack - ------------------------+-- GND (power header)
  UNO Q 3V3 OUT ----------------------- VCC
  UNO Q GND (own wire) ---------------- GND (control header)

  The two grounds meet only inside the module (its three GND pins are one net):
  motor current never crosses the board or a signal lead.

Signals (UNO Q outside -> module inside the bell)

  D12 -> AIN1     ~D6 -> PWMA     D9 -> STBY
  AIN2 -> GND on the module (reverse locked out)
  AO1 (+) / AO2 -> hat motor
```

### What crosses the bell

Seven wires through the pass-through: five signal wires in one bundle and the speaker pair.
Two more only if the hat's battery box ends up outside.

| # | Wire | Outside | Inside the bell |
|---|---|---|---|
| 1 | AIN1 | D12 | module AIN1 |
| 2 | PWMA | ~D6 | module PWMA |
| 3 | STBY | D9 | module STBY |
| 4 | VCC | 3V3 OUT | module VCC |
| 5 | signal GND | UNO Q GND | module control-header GND |
| 6, 7 | speaker, twisted pair | the USB speaker's amplifier output | the speaker's cone |
| 8, 9 | VM and pack −, twisted | the hat pack, only if its box is outside | module VM and power GND |

Tie the bundle on the inside of the pass-through, so a pull stops at the tie and never reaches
the module's pins (a lifted STBY = a hat that talks and does not move). Label both ends of
wires 1 to 5 before closing the hat. Keep the speaker pair apart from wires 1 to 5 along the
run.

### Rules

- Nothing is wired with the board or the pack powered. VCC only from 3V3 OUT. Loose jumpers
  never carry VM (a one-pin slip on the VM/VCC/GND header puts the pack on the 3V3 rail).
- The pack reaches VM and GND only through its keyed plug, red to VM, read once with the
  meter (switch on, module side unplugged: + on the VM lead, no VM-to-GND short). Any other
  pack gets the same reading before its first plug-in.
- The module is tied or glued where it sits; the pack switch sits where the operator can reach
  it; the hat travels with the pack off and the board unpowered.
- **From the first motor on, a boot, a service start and a service stop all move the hat**
  (the welcome, the goodbye). The pack switch is on only while you are at the hat, off between
  sessions. The service stays disabled from step 2 to step 9.
- The `/debug` motor tests send `config.py`'s mouth values: the fish's until step 7.

## Bring-up

Each step has a pass line; every reading goes into
`docs/results/2026-10-16-unoq-tb6612-hat-bringup.md` with its command and both repos' commits.

0. **You, before cutting anything:** mark which motor wire the stock board drove +; count the
   cells in the hat pack; photograph the module's header silkscreen.
1. **Laptop:** the firmware with `DRIVER_STBY` (Big_mouth `braintip`): the R4 build's
   `firmware.bin` hash unchanged before and after the edit (done 2026-10-16: `953f9f39…`,
   50,292 bytes, both builds); `deploy/unoq_fw.sh push && deploy/unoq_fw.sh compile`, the push
   printing the sha with `dirty=0`.
2. **Laptop, then you:** `ssh arduino@segunda.local systemctl --user disable --now fish-brain`
   with nothing wired (goodbye, STOP, nothing moves); it stays disabled until step 9. Your meter
   on D9 against GND, then `deploy/unoq_fw.sh upload --by owner --note "tb6612 stby on d9"`:
   D9 under 0.3 V on the bare pin while the MCU is silent during the flash (about 3.3 V there =
   a pull-up like D8's, STBY needs another pin), 3.3 V once LED4 blinks green. Laptop:
   `fw_check.py check --release-router` passes; `replay --drive --held` gives 122 of 122.
3. **You:** `sudo poweroff` on the board; when it is down, pull the hub's cable from the USB-C;
   the meter reads 0 V from 3V3 OUT to GND before any wire is touched.
4. **You, everything off:** the module inside the bell, the AIN2 jumper to the module's GND, C1,
   wires 1 to 7 through the pass-through, the pack through its switch and plug. Meter the plug
   once: + on VM, no VM-to-GND short. Motor not connected yet.
5. **Board on, pack off (you on the meter, laptop on the link):** during the Linux boot the STBY
   node reads under 0.3 V (the 200 kΩ pull-down against ≤ 1 µA of leakage gives ≤ 0.2 V; 0.3 to
   0.99 V still reads low to the chip but means something pulls the node: a fail); after LED4
   blinks green, 3.3 V ± 0.1. `systemctl --user is-enabled fish-brain` = disabled. Pack on,
   still no motor, one line at a time with `tools/fw_check.py send "…" --wait 4.5
   --release-router` (`send` never writes STOP; a timed line ends on the MCU; `--held` is never
   used here):
   - `MOUTH 255 4000`: AO1 against AO2 reads the voltage at the module's VM pin within 0.1 V
     (255 is a constant high, measured 2026-10-11).
   - `MOUTH 128 4000`: about half of it (the PWM-off phase is a short brake, both outputs low,
     so a DC meter reads duty × VM; this proves the PWM pin).
   - `MOUTH -255 4000`: about 0 V, floating (high-Z: a few hundred mV is still a pass). This is
     the lock working; anything near VM = stop and recheck the AIN2 jumper.
   - Rest state after `send STOP`: 10 k from AO1 to VM, meter AO1 to GND; then 10 k from AO1 to
     GND, meter AO1 to GND. About VM then about 0 V = high-Z; about 0 V both times = short
     brake. Recorded; neither changes code.
6. **First motion, you at the hat, pack switch in hand:** `send "MOUTH 120 50"`. Wrong
   direction = pack off, swap the two motor wires, pack on. Then the current check, in this
   order: (a) pack off, ohmmeter across the motor, turn the shaft, keep the lowest R, write
   I ≈ V/R as "(estimate)"; (b) meter across the module's VM and GND pins,
   `send "MOUTH 255 2000" --wait 3` with the cam held at a stop, write the lowest VM; (c) a
   second run with the meter on its 10 A jack in series with the pack lead (the mA range's
   burden adds sag), MAX-hold if it has one: that reading is the winding current (255 is DC).
   Pass: under 0.4 A, or VM ≥ 4.5 V and under 1.0 A. Fail = fresh cells, a larger pack, or a
   lower `FISH_MOUTH_OPEN_PWM`, then measure again (a pack-side reading below 255 is never
   compared with the limits: winding current = reading / duty). Let the chip cool between runs.
7. **Flap speed, you:** `send "MOUTH 150" --held --release-router`, then 200, then 255 (a held
   `MOUTH <n>` needs `--held` and ends only at the firmware's 5 s limit or the pack switch);
   pick the speed that reads as talking. It goes into the board's `.env` as
   `FISH_MOUTH_OPEN_PWM` and into the calibration file.
8. **The app, you at the hat, laptop watching the journal:** on the board, with
   `FISH_MOUTH_MODE=gate` and the chosen `FISH_MOUTH_OPEN_PWM` in `.env`,
   `cd ~/fish_brain && .venv/bin/python -m fish_brain.app --say "Hola"` (with `FISH_PERSONA=hat` in
   `.env` and the phrases rendered: `--prerender-canned` first); the voice comes from
   the cone in the bell and the flapping follows it; the `[turn]` line and the mouth lane
   agree. Pack voltage (switch on, hat idle) before and after the rehearsal sentences with
   the sentence count; the module's temperature by touch after a long sentence.
9. **Only then,** told first that every boot and stop will move the hat:
   `systemctl --user enable --now fish-brain`.

If the motion is not ready by the fair, the hat still talks: pack switch off, and the voice
runs unchanged with no motor.

## Open questions

| Question | Experiment or decision | Decides |
|---|---|---|
| Cells in the hat pack and VM under a stall | Steps 0 and 6 | Fresh cells, or a 4 AA holder with a lower `FISH_MOUTH_OPEN_PWM` |
| The hat's battery box inside or outside the bell | The owner, at assembly | Wires 8 and 9 |
| The speaker's amplifier inside or outside | The owner, at assembly | Only the cone is planned inside |
| The hat's words | `FISH_PERSONA=hat` on the board; the owner writes the texts in `PERSONAS["hat"]` in `config.py` (speakable placeholders until then), then `python -m fish_brain.app --prerender-canned` there | The persona, the welcome and goodbye, the reading's rules |
| D9's state in reset | Steps 2 and 5 | Whether STBY stays on D9 |
| Rest state IN1 = IN2 = L, PWM = L: brake or high-Z | Step 5 | Nothing in code; one line in the calibration notes |
| Can the motor run in reverse safely | After the fair (locked out now) | Whether AIN2 ever goes back to D11 |
