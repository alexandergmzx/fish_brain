# 2026-10-27 — The fortune act on the board: a scripted act and a model act

The first two fortunes (ADR 0019) on the UNO Q, driven through the page's own routes
(`POST /fortune start` with a typed name, then one `POST /utterance` per question with the
Loquendo-voiced answer clips of `2026-10-27-fortune-answers-canary.md`, padded 0.8 s each side),
the USB speaker marked failed so the audio went to a stand-in phone page and nothing played
aloud at 06:30. Commit `69c2e1a`; the parser fixes below are `f87d5d8`.

- Board: `segunda`, `fish-brain.service`, `stt=canary llm=luna tts=loq`, place `fiesta`, deck
  `tarot`, cup on, online on the home Wi-Fi.
- Driver: `/tmp/fortune_test.py` (in the session's scratchpad, not in the repo); a copy of the
  house act's `route_test.py` with the fortune's view instead of the show's.

## Start-up

| Step | Measured |
|---|---|
| Licence probe | `[voice] CLEAN (3.01 s)` at 12:24:20 UTC |
| The 139 fortune clips rendered (first boot after the deploy) | `[fish] link=` at 12:27:42: **3 min 22 s**, not the 10 min estimated from 2026-10-26's 4.1 s a clip (the daemon stayed warm) |
| `GET /debug/state` | 1.1 to 1.3 s, 59 KB (0.5 s on 2026-10-26): the page's Status tab reads "Waiting for the hat…" for the first seconds after a load |

## The two acts

| | Script (`show=script`) | Model (`show=auto`, online) |
|---|---|---|
| Questions | fecha, sueno, carta, taza, animal | same |
| fecha: "Veintitrés de octubre." | heard `XII de octubre.` twice → no sign | same |
| sueno: "Soñé que se me caían los dientes…" | theme `dientes` (the dream's cap lifted to 10 s, the long route to Groq) | same |
| carta: "La muerte." | card 13 | same |
| taza: "Una estrella." | heard `uña extraída.` twice → no shape | same |
| animal: "Un gato negro." | `gato` | same |
| The ending | clips: suspense, luna (llena), magic (Ofrendilla), cierre_fiesta | the model (`gpt-6-luna`, **7.18 s**), rendered live, then cierre_fiesta |
| Clips to the stand-in page (fillers and burbles included) | 31 in 181 s | 30 in 197 s |
| Record | `[fortune] act #1 reading=clips mode=script (forced)` | `[fortune] act #2 reading=llm mode=llm (online)` |

The model's reading, as said: "Ana, bajo tu signo y tu elemento, veo dientes que se caen en la
boda de tu prima: se abre paso una nueva seguridad, y hasta el miedo se pone sus mejores galas.
La Muerte anuncia un cierre elegante y un comienzo con buen pulso. Tu gato negro te traerá
fortuna en la fiesta: pronto…" (clean; it named a sign it did not have, which the rules forbid:
one line to tighten).

## What changed because of this run

- Canary wrote the spoken date as a Roman numeral in the live turn (`XII de octubre`), where
  the bench on the same clip wrote `Veintitrés de octubre` (not explained). `parse_birth` now
  reads a Roman numeral that stands right before "de <mes>" or next to a month word as the day
  (`vi` alone stays a word).
- `uña extraída` is now an alias of the star in the cup.
- Checked live after the fix (act #4 on `f87d5d8`): `fecha heard='XII de octubre.' -> sign libra`,
  the page's data `Libra · aire · 4`.
- Not changed: the taza reprompt and the bridge covered the miss as designed; no error line was
  said in either act.
