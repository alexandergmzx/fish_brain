# 2026-10-26: the scripted visit on the board, and the season's lines

Board `segunda`, `sorting-hat` up to `915ea2c`. The hat's 3xAA pack was disconnected (no motion
possible). From the middle of the run the speaker was at 5 % (his request).

## 21 visits with Jorge as the visitor (FISH_SHOW=script, temporary drop-in)

Driver: a script on the board posts `/visit`, then for each open question uploads a Loquendo
render of an answer through `/utterance` (padded with 0.8 s of silence), or taps `/show`.
The 132 lines of the first draft were rendered after `[voice] CLEAN`.

| Visits | Scenario | Result |
|---|---|---|
| 1–6 | heard answers, varied | 6 verdicts `by=answers` (Hufflepuff 3, Ravenclaw, Gryffindor, Slytherin) |
| 7 | silence throughout | re-ask, bridge; verdict `by=bag` |
| 8 | "mmm, no sé" throughout | `not_sure` each time; verdict `by=bag` |
| 9 | off-list ("me gusta mucho la pizza") | re-ask, bridge; verdict `by=bag` |
| 10 | "yo quiero ser de Ravenclaw" | Ravenclaw `by=preference` at once |
| 11 | "no quiero Slytherin", then answers | Gryffindor `by=answers`; the veto was **not** recognised (Canary wrote "esliterín"; fixed since) |
| 12 | silence and answers alternating | Ravenclaw `by=answers` |
| 13–15 | three silent visits | Slytherin, Gryffindor, Slytherin `by=bag` |
| 16 | operator taps | Hufflepuff `by=answers` |
| 17 | operator skips | Ravenclaw `by=bag` |
| 18 | operator "Forzar casa" G | Gryffindor `by=operator` |
| 19 | mixed | Ravenclaw `by=answers` |
| 20–21 | the fish killed (`SIGKILL`) mid-visit, then a whole visit | restarted by systemd; visit 21 Ravenclaw `by=answers` |

Hearing on clean Jorge takes: 27 of 31 first answers matched; the 4 misses ("Un Doctor gón",
"Unbolkan", "Que Anasta", "Él mata") were heard after the re-ask; **0 wrong accepts**. No error
line was said in any visit. Since: the matcher also tries a word without a glued article
("unbolkan" → "bolkan") and knows "esli…" as Slytherin. False accepts on his 61 recorded take
texts against all 9 questions: 0 of 549 (before and after the fix).

Not measured: real visitors' voices through the remote's microphone; children; hall noise.

## The season's lines (Halloween and Día de Muertos, the neighbourhood calaverita rounds)

143 show lines and the hat's welcome, greeting, goodbye and 14 fillers, researched and reviewed
line by line (gender-neutral, never scary, no venue, no clock times). Rendered at start-up after
`[voice] CLEAN (3.01 s, clean 3.01 s)`: 166 new clips, 681 s, every one transcribed with
faster-whisper `small`: 0 with the licence warning, 0 missing their words. Backed up to
`~/.local/share/fish_brain/canned-season-2026-10-26` on the board and
`~/fish_brain_backups/segunda/2026-10-26/` on the desktop.

## English words: spelled right in the text, respelled for Jorge

Each candidate rendered alone with Jorge, transcribed with faster-whisper `small` in English:

| Word | As written | Respelling chosen (transcript) |
|---|---|---|
| Gryffindor | "Gryffindor." | none needed |
| Ravenclaw | "Ravenclaw." | none needed |
| Slytherin | "It's littering." | **Slízerin** ("Slytherin") |
| Hufflepuff | "oof le poof" | **Jófl paf** ("Hufflepuff"; in Spanish "¡Jofipaf!") |
| Halloween | "I do work in." | **Jálouin** ("Halloween.") |
| Happy | "Happy." | none needed |
| trick or treat | "trick or treat" | none needed |

These are defaults in `PERSONAS["hat"]["say_as"]` until he picks by ear on the page's
Pronunciation list; the shown text keeps the correct spelling.
