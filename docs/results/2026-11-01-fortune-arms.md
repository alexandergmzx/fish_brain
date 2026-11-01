# 2026-11-01 — The fortune with or without a card, on Haiku or Sonnet

Level 1: real models and the act's own steps, no voice, no board, from the desktop. 8 real fortune
visitors, 2 takes, 4 arms, 64 acts. Code frozen at `rehearsals/snap-20261101/` (base `aab3dc4` plus
the uncommitted consulta tree). The script is `tools/fortune_arms.py`; rows with visitors' words are
in `rehearsals/arms-20261101/arms.json` (ignored by git).

```bash
cd rehearsals/snap-20261101 && ../../.venv/bin/python tools/fortune_arms.py --out ../arms-20261101 --takes 2 ../real_20261031.txt ../real_visitors.txt
```

The reading's thinking: `disabled` on Haiku, `between_tools` on Sonnet (it answers a 400 to `disabled`).

| Arm | Reading s, median (max) | Question s, median (max) | Words, median (max) | Over the length check | Questions refused |
|---|---|---|---|---|---|
| Haiku, card | 1.58 (1.99) | 1.08 (1.46) | 71 (86) | 3 of 16 | 3 of 46 |
| Haiku, no card | 1.51 (2.16) | 1.08 (1.44) | 64 (89) | 1 of 16 | 3 of 42 |
| Sonnet, card | 2.94 (4.47) | 1.96 (5.40) | 76 (88) | 6 of 16 | 0 of 46 |
| Sonnet, no card | 2.76 (3.14) | 1.98 (5.55) | 77 (87) | 0 of 16 | 0 of 42 |

Over the length check means 7 sentences or over 90 words; the act trims those, it does not refuse them.

## Blind scoring

Three readers scored all 64 acts from 1 to 5, each as one role: a party guest, a tarot reader and
mentalist, a Mexican Spanish editor. Letters were shuffled per visitor and take, the arms unnamed.
A reading with a card shows it, so that factor is not truly blind. The set, the key and the scores
are in `rehearsals/arms-20261101/` (`blind.json`, `blind_key.json`, `scores.jsonl`). Text only: no
voice, no room, no visitor.

| Arm | Specific | Oracle | Coherent | Spanish | Questions | Overall |
|---|---|---|---|---|---|---|
| Haiku, card | 3.04 | 2.85 | 2.89 | 3.41 | 2.46 | 2.70 |
| Haiku, no card | 2.96 | 2.77 | 2.96 | 3.48 | 2.40 | 2.65 |
| Sonnet, card | 3.88 | 4.06 | 3.53 | 3.95 | 4.27 | 4.14 |
| Sonnet, no card | 4.05 | 4.06 | 3.61 | 3.98 | 4.12 | 4.20 |

Paired within each visitor, take and reader (48 comparisons), on Overall:

| Effect | Mean difference | Standard error | Better / worse |
|---|---|---|---|
| Sonnet over Haiku | +1.49 | 0.06 | 48 / 0 |
| Card over no card | -0.01 | 0.08 | 23 / 18 |

Named as errors in the arms' rows: Haiku 43 and 39, Sonnet 27 and 20. Haiku said "Cuánguanse dinero
llega" and "el poder te quedó chico, Dinero."; Sonnet said "jovencito" to an unknown visitor and
flipped "solo" and "sola" in one act. A plain "Sí" to the dream question was answered "No me diste
nada" on both models.

Not measured: Sonnet on the board, the shuffle and the card's name as theatre, Sonnet in the visit.
