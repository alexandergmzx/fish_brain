# 2026-10-28 — Short questions in the castle: Haiku on the rewritten visit rules

His word after Mónica's visit (board, 2026-10-27 21:47 UTC, `lugar=universidad`): the questions
too long and forced on the place ("¿platicar con un libro, investigar algún misterio o
descubrir un hallazgo?"), not everyone at the university is a student, too little Hogwarts;
and the bans on the year, the age, the hour and named places were not his. Board `segunda`,
Claude Haiku 5.5 thinking at effort low, `tools/hat_rehearse.py` (cloud only, no voice):

```bash
set -a; . ./.env; set +a; .venv/bin/python tools/hat_rehearse.py --only N tools/hat_visitors.txt
```

| Code | Rules | Visitors, runs | Reading turn, words | Question, words | Verdict, words (sentences) | `años` said |
|---|---|---|---|---|---|---|
| `ce4cf24` | the old bank (2026-10-27) | Mónica, his real turns | 29, 37 | 15, 18 | 55 (4) | no |
| uncommitted, the first rewrite (castle, 25-word limit, 14-word question) | 11 and 1, once each | 36 to 47 | 10 to 16 | 56, 57 (3 to 4) | once ("años de pasillos", then banned) |
| `d937a88` (30-word turns, 10-word questions, 55-word verdicts; the year allowed) | 11, 1, 3, twice each | 34 to 47 | 9 to 11 | 60 to 83 (5 to 6) | once ("veinte años", allowed) |

What held in every run of `d937a88`: the question is one of the bank's, short, in the castle
("¿Qué clase: duelos, adivinación, criaturas mágicas o pociones?", "Una puerta cerrada: ¿la
abres, la estudias o buscas compañía?"); the verdicts are in the castle (the Gran Comedor, the
library, a lechuza, "una página olvidada en algún pasillo"); the professor is never taken for a
student; the season appears once or twice a visit. Visit replies 0.9 to 1.9 s; readings 1.9 to
7.6 s, 84 to 131 words (trimmed to 90 by the act). Visitor 3 answered the sign by name
("Escorpión" → `escorpio`, no lucky number, which the tag and the clips skip).

What did not hold: the word counts. Haiku writes two full lines and a question whatever the
stated limit; the rehearsal's `check()` flags every reading turn over 30 words and every
verdict over 55. Not changed here: a code trim of the visit replies (the fortune's
`trim_reading` is the pattern) is his call.
