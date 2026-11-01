# 2026-11-01 — La consulta and the fortune's arms on the board, silent

Level 5 without sound: `segunda`, commit `e390181`, the service running with `FISH_SHOW=script`,
`FISH_FORTUNE_MODEL=true`, `FISH_LLM_PROFILE=claude-sonnet`, `FISH_FORTUNE_DECK=off`. Real Sonnet, real
Jorge render, typed words for the microphone, a mock link, no audio played. His voice is not measured.
Outputs: `rehearsals/board-20261101/`.

```bash
.venv/bin/python tools/consulta_live.py --clips /tmp/cl/clips --tts loq --out /tmp/cl/live.md
.venv/bin/python tools/fortune_arms.py --out /tmp/cl/arms --takes 1 rehearsals/real_20261031.txt
```

La consulta: 7 of 7 sittings as expected, under the scripted house. 14 clips rendered in 14.9 s.

- Reading: [40.0 s of audio, render 7.1 s]
- Reading: [43.9 s of audio, render 7.6 s]
- Reading: [35.8 s of audio, render 6.3 s]
- Reading: [39.0 s of audio, render 6.8 s]
- Reading: [37.6 s of audio, render 6.6 s]

The fortune's arms, 3 visitors, 1 take (3 acts an arm):

| Arm | Reading s, median (max) | Question s, median (max) | Words, median |
|---|---|---|---|
| Haiku, card | 1.61 (3.81) | 1.20 (1.48) | 73 |
| Haiku, no card | 1.60 (1.88) | 1.20 (3.15) | 62 |
| Sonnet, card | 2.73 (2.85) | 1.97 (2.35) | 71 |
| Sonnet, no card | 2.79 (2.99) | 2.25 (2.62) | 73 |

Seen: with the hat's own draw a reading said "esta carta que sacaste tú".
