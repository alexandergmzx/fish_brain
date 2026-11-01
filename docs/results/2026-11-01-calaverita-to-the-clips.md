# 2026-11-01 — A calaverita that gave way to the clips, and its replay

His run on the board: calaverita #4 (`records/6be742c2-105718.jsonl`), `how=clips`, "only 2 of 3 stanzas rhymed in 12 versions", 33.0 s, model 9.68 s. The tag had his name, house, three answers and the cues. The verses he never heard are not recorded: only the clip's text is.

The replay: his tag, level 1, desktop, real Sonnet, 3 clients, 4 passes, 12 s, commit `e34dcf7` plus uncommitted `TEAR_FEED`.

```bash
.venv/bin/python tools/calaverita_replay.py '[CALAVERITA: nombre=...]' --takes 8
```

| Result | Takes |
|---|---|
| Every stanza rhymed | 7 of 8 (1 to 3 passes) |
| To the clips | 1 of 8: 2 of 3 rhymed after 12 versions |

The take refused ended on "por él" and "usted" (`el`, `ed`): assonant, so the check was right by its rule, and the verse had his name, his cat and his bag of sweets. The rhyme key's known misses (quiero/dinero, quien/bien) were not the cause here.

Not measured: how often this happens across visitors; the same on the board.

## Printed from the board

`tools/calaverita_print.py` on `segunda`, the same tag: every stanza rhymed; the MP210 took 893 bytes in 1.1 s (connect 0.4 s). Several lines ran past the paper's 32 columns and folded.

## With the fortune's answers

The same `tools/calaverita_replay.py`, 6 takes, his six answers from house act #36 and fortune #16 (output: `rehearsals/calaverita-all-answers.txt`). Across the takes 34 of 36 answers appear in the verse, counted by word. Fully rhymed 4 of 6, to the clips 2 of 6: more material makes the rhyme harder. One refusal was the check's own bug, pedir and conseguir, fixed after this run; the other was a real miss (Géminis, cima).
