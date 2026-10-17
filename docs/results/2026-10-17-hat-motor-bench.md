# 2026-10-17: the hat's motor on the bench, gate mode

Commit `f3e8286` (`sorting-hat`), firmware Big_mouth `braintip` 6a7b2d5. The mechanism out of
the hat on a TB6612FNG, channel A (D12/D11/~D6, STBY D9), VM from the toy's 3 AA box.
Service stopped. Alexander watching the mechanism.

| Command | Result |
|---|---|
| `tools/fw_check.py send "MOUTH <p> <ms>" --release-router` for 120/300, 160/500, 200/500, 255/500, -200/500 | Every line answered `MOUTH -> 1 step`; he saw it move |
| `FISH_PERSONA=hat FISH_MOUTH_MODE=gate FISH_LINK_LOG=… python -m fish_brain.app --say "Hola. Dime tu nombre, por favor, y te diré tu casa."` | "I see it moving well" (his words) |

From the link log of the `--say` run:

- Run 1 ("Hola."): 530.50 to 530.80 s, `MOUTH 238 150` every 60 ms, then `MOUTH 0 1`.
- Pause: 0.58 s with no line.
- Run 2 (the whole second sentence): 531.38 to 533.99 s with no stop at the commas, as
  expected (Loquendo's comma pauses are shorter than the 300 ms gap), then `MOUTH 0 1`.
- The end of the utterance: `MOUTH 0 1`, then `STOP` on exit. No negative MOUTH line.
- No `ERROR` or `Unknown` reply from the MCU.

Not measured: the current, the start PWM, the flap period, coast against brake, the motor's lag.
