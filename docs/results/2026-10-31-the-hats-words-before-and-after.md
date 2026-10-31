# 2026-10-31 — The hat's words, before and after: rehearsal on his real visitors

Level 1 only: text, no voice, no board. His 4 visitors of 2026-10-31, 3 repeats, 12 acts. "Before"
is his folder with his own edits of the day, kept at `rehearsals/prompts-before-voice-20261031/`;
the conversations are in `rehearsals/compare-20261031/` (ignored by git: real visitors' words).

```bash
.venv/bin/python tools/hat_rehearse.py --log rehearsals/compare-20261031/before --repeat 3 --prompts rehearsals/prompts-before-voice-20261031 rehearsals/real_20261031.txt
.venv/bin/python tools/hat_rehearse.py --log rehearsals/compare-20261031/after --repeat 3 rehearsals/real_20261031.txt
```

Commit `a5751bd` plus uncommitted changes. Counts are regex over each whole run's log, including
visitors' words, the old "then" lines (same in both) and the tickets, so read them as a direction.

| In the log | Before | After |
|---|---|---|
| "esta noche" | 22 | 3 |
| Diminutives | 9 | 3 |
| uy, ay, ajá, mmm, híjole | 3 | 1 |
| Season words | 2 | 0 |
| Castle words | 14 | 3 |
| [H] question lines | 32 | 34 |
| Refused, clip said | 10 | 8 |

"el sombrero" went from 1 to 12: "Soy el Sombrero Seleccionador" in the new greeting, once per act.

**Refusals:** most name the tarot. His `ask.md` of today says "una carta de tarot" and "nunca
tarot" on one line; Haiku says "carta de tarot" and `fortune.ask_result` refuses it. Before his edit
the same check refused 1 of 33 (`2026-10-31-haiku-asks.md`).

**Still wrong in the after run:** Haiku parrots the cues ("Veo a un hombre adulto, solo, de ropa
blanca") and the visit's "Antes del domingo" repeats; the verdict can say the house last, after the
prediction; the mockery lives mostly in the fixed lines, the model's lines stay milder.

Not measured: how it sounds; the wait on the board.
