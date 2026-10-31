# 2026-10-31 — Three fortunes on the board with the new voice, and their replay

His session on the board (`segunda`, `fish-brain.service`, `stt=canary llm=claude tts=loq`, the
Jorge stone voice of ADR 0028, the oracle's rules of ADR 0027 as synced, byte-identical to
`33b5f97`): 4 visitors, 06:42 to 07:32 UTC, 3 of them through the fortune (acts #10 to #12, all
in model mode, all on the phone's microphone after the remote's sent zeros). Visitors are named
by act number only; their words are in `rehearsals/` (ignored by git).

```bash
scp arduino@segunda.local:.local/state/fish_brain/records/b15503fa-774856.jsonl rehearsals/records/
.venv/bin/python tools/hat_records.py rehearsals/records/b15503fa-774856.jsonl --since 2026-10-31T07:18 > rehearsals/real_20261031.txt
.venv/bin/python tools/hat_rehearse.py --log rehearsals --repeat 6 rehearsals/real_20261031.txt   # 18 readings, desktop, HEAD 33b5f97
```

The night's three were also read by three independent reviewers (the act as heard, the readings
against `FORTUNE_RULES`, the Spanish and the register), each checked by a second reader; none of
the findings below was refuted.

## On the night

| Act | What happened | Cause |
|---|---|---|
| #10 | Answered the wish "¿Cómo? Dinero."; at the card, a 26 s protest out of role ("antes de decir la muerte… tenías que haber dicho que si me sacabas una carta… Sí, saco una carta") was taken as naming La Muerte from his deck; the reading said "La Muerte la sacaste con tu mano, no yo" | The wish question is "¿qué le vienes a pedir **a la Muerte**…?" (`fortune_bank.py:42`), heard as the card. `parse_card` runs before `parse_yes_no` (`fortune_run.py:92`) and "muerte" is a card alias; `parse_yes_no` alone would have said "no" (a no wins), not the draw |
| #11 | Said no to the card; the reading said "Tu carta no salió: el sombrero no te la quiso mostrar" | The tag still carries `carta=ninguna (no quiso tarot)`; the hat in the third person also comes from the tag's own `otro sueño (el sombrero se lo guarda)` |
| #12 | Answered the wish "¿Y cómo que muerte?"; stored as the wish (`parse_wish` gives `otro` to any words); the reading: "No hay deseo que me hayas pedido, así que lo leo en tu rostro: una sonrisa que llega rosa" | The same question; a question back is taken as data; the colour cue said as a word |
| all 3 | No first name in any fortune (`first` empty), though every visitor said theirs in the visit | Only a typed name reaches `visit.first_name` |
| 2 of 3 | "No." to "¿Has tenido sueños interesantes últimamente?" re-asked as if unheard | A yes/no question whose "no" is not a parse |
| 2 of 3 | A beat that does not fit: "La carta lo sabía antes que tú." after a dream, before any card | One beat pool for every question |
| 4 of 4 visits | The verdict's secret-kept trait ("lo guardas bajo llave", "cuando nadie mira") and "Esta noche, cuando veas una vela encendida…" in 3 of 4 | Close to the visit rules' own example; `lugar=otro` gave no scene |

## The replay (6 × the 3 fortunes, same answers, fresh seeds)

| Check | Count |
|---|---|
| A card mentioned when none was taken | 0 of 12 |
| Card credited as the tag says (the tag itself wrong for #10, see above) | 6 of 6 |
| The hat speaks of itself as "el sombrero" | 8 of 18 |
| The magic word used as the visitor's name ("Tenebrumba, ven acá") | 3 of 18 |
| #12's protest read as her wish or as a question about death | 3 of 6 |
| Over the trim (6 sentences or 90 words) | 3 of 18 |
| Spanish slips (e.g. "si sigues patear", "sópalo", "quema tres granos de sal en la lengua") | 3 of 18 |

Not measured: how visitors take the voice itself; a reading with the hat's own draw on the board.

## After the change (same replay, uncommitted on `33b5f97`)

The wish asked by the hat, the question back, the card's deciding sentence, the tag from the
hat's side (no declined card, "la saqué yo", no vague dream, "color de su ropa"), the
first-person and magic-word rule lines, the name the hat echoed at the greeting
(`docs/adr/0019`, `0026` amendments of 2026-10-31). The same command and script; the parsers on
the night's own answers first:

| Act | Heard | Before | After |
|---|---|---|---|
| #10 | "¿Cómo? Dinero." | wish dinero, words "¿Cómo? Dinero." | wish dinero, words "Dinero." |
| #10 | the 26 s protest ending "Sí, saco una carta de tarot." | card 13 named by the visitor | the hat's draw |
| #11 | "Me tiene que trabajar mucho." (after a re-ask) | `sueño=otro (otro sueño (el sombrero se lo guarda))` in the tag | out of the tag |
| #12 | "¿Y cómo que muerte?" | wish `otro` with those words | asked again |

| Check, 18 readings | Before | After |
|---|---|---|
| A card mentioned when none was taken | 0 of 12 | 0 of 12 |
| The hat's draw said in the first person (#10, 6 readings) | — (the tag said the visitor drew) | 6 of 6 |
| The hat speaks of itself as "el sombrero" | 8 of 18 | 0 of 18 |
| The magic word used outside its closing | 3 of 18 | 0 of 18 |
| A name in the tag (none was typed: the one the hat echoed) | 0 of 18 | 18 of 18 |
| Over the trim (6 sentences or 90 words) | 3 of 18 | 3 of 18 |
| Distinct openings | — | 16 of 18 |

Still wrong in this replay: one reading gave Cáncer the goat's emblem (Capricornio's, from
the rules' list); one told a dealt tema as "aunque no lo dijiste", against the rule.
