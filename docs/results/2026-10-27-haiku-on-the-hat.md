# 2026-10-27 — Claude Haiku on the hat: thinking at effort low, his visit rehearsed, the SDK import

His pick of 2026-10-27: Claude Haiku 5.5 with thinking at effort low instead of `gpt-6-luna`,
no model comparison. Single runs of his own visit (visitor 1 of `tools/hat_visitors.txt`:
adulto, amigos, amarillo, sonriente, capa negra; "Hola, soy Albert.", "A mi novia.", "Toco
la puerta."; the fortune: "Diecisiete de junio.", the dream of his uncle and the sheep, "Un
perrito xoloitzcuintle."). One run each, so the seconds are single samples.

```bash
.venv/bin/python tools/hat_rehearse.py tools/hat_visitors.txt --profiles claude --only 1
```

| Run | Where, code | Thinking, cap | Visit replies, s | Reading, s | Outcome |
|---|---|---|---|---|---|
| 1 | desktop, `dda6228` with the profile edited | adaptive at effort low, 600 tokens | 3.5, 3.6, 3.6 | 1.9 | every visit reply empty (`stop_reason=max_tokens`): thinking used the cap |
| 2 | desktop, same | adaptive at effort low, 2000 tokens | 3.5, 4.8, 4.5 | 1.7 | a house; the old rules' ingredient bank still mashed into the verdict (75 words, a clock time) |
| 3 | board `segunda`, `318b216` (the new rules) | adaptive at effort low, 2000 tokens | 1.4, 1.1, 4.3 | 2.6 | a house; the verdict from his cues and answer; the reading 118 words |

Run 3's verdict: "Albert, das miedo por fuera, pero por dentro tienes una sonrisa de niño
travieso. ¡HUFFLEPUFF! Tu casa es la de los leales, la de quienes cuidan a los suyos. Esta
noche, cuando la vela de la ofrenda empiece a parpadear, toma la mano de tu novia antes de que
se apague." The xolo was taken as the animal; the dream reached the model as its theme only.

The act refused a reading over 6 sentences or 90 words and fell back to the clips; run 3's
reading would have been refused. Since `20e8fe7` a long reading is trimmed (its first
sentences and the last one, the magic word): run 3's comes to 81 words, the animal sentence
dropped.

The Anthropic SDK's first import on the board: 7.0 s (a runtime switch, 18:2x UTC) and 17.4 s
(at a start, with the speech models loading), from the fish's own `[claude] sdk imported in`
line. The page's switch answered "not picked up" the first time for that reason; the change
still applied.

Not measured: a real turn with Haiku on the board, his voice, the seconds over many visits.
