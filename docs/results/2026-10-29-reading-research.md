# 2026-10-29 — How popular readings are made: the research behind ADR 0026

His question (2026-10-29): the fortune's readings are "too innocent and maybe dumb" and "too
canned on repetitive scripts"; how are readings made online and on other systems? A web sweep in
five lenses, each followed by a checker that opened the cited pages and marked every claim
`yes`, `partly`, `no` or `unreachable`. The checkers of two lenses (cold reading, LLM variety)
did not run (the account's usage limit): their sources are listed as **not checked** and no
number here rests on them alone.

## What the lenses found, as used by ADR 0026

| Finding | Lens | Checked | Used as |
|---|---|---|---|
| Every popular reading starts with what the person came for: Biddy's "a targeted question produces a targeted answer"; party readers' topic pile; love, health and money at the Mercado de Sonora | tarot, quick questions | yes ([Biddy, questions](https://biddytarot.com/blog/the-art-of-asking-powerful-questions/)); the Mercado's: VICE, "health is the third reason", partly | The wish question, replacing the animal |
| Virtual draws are normal: "Pick your own cards or let the app pick for you" | tarot | yes ([Labyrinthos app](https://apps.apple.com/us/app/-/id1155180220)) | The hat draws its own card on a yes |
| Reversals are the cheapest shadow: internal, too much or too little, blocked, upside-down image | tarot | yes ([Biddy, reversals](https://biddytarot.com/blog/how-to-interpret-reversed-tarot-cards/)) | One hat draw in three reversed, in model mode |
| A good reading tells one story: describe the card, make up a story, proverbs and song lines | tarot | yes ([Aeclectic, 21 ways](https://www.aeclectic.net/tarot/books/21-ways-to-read/)); the "arc first" order attributed to Biddy: **no** (the page says each card's story first) | "Una sola historia sobre su deseo" |
| Users of AI fortune-telling call it templated; "ChatGPT can be a little bit of a yes man" | tarot | partly (CSCW 2026 is about Chinese BaZi and I Ching communities; CHI 2026's "yes man" is one participant, friction tied to critical engagement, not to resonance) | The sting, with its caveat |
| People share the sting, not the comfort: Co-Star's blunt lines went viral where newspaper horoscopes are vague and positive | oracle voice, quick questions | partly (the viral quotes are real; "kinda mean to me" is one user; "Check your ego" not on the cited pages) | Roast hard (his pick) |
| Favourable claims are accepted more readily overall; a high-status speaker softens the cost of unfavourable ones | oracle voice | yes, as corrected by the checker ([skepdic, Forer](https://skepdic.com/forer.html)) | One sting in an otherwise warm read, then a task |
| Specific means a fuzzy fact the visitor completes (a letter, a day, an odd object), with a time revision ("if it hasn't happened yet…") | oracle voice, cold reading | partly ([Rowland](https://www.ianrowland.com/cold-reading-techniques): Fuzzy Fact and Time Revision named; the Jacques Statement not on that page) | `visión=`, said with an out; a weekday from `hoy=` |
| Mexican specifics: the vitrina of recuerditos from bodas and quince años, the butcher's calendar; Juan, María, José, Guadalupe as the century's names | cold reading | **not checked** ([Matador](https://matadornetwork.com/es/13-cosas-que-nunca-faltan-tipica-casa-mexicana/), [Mediotiempo](https://www.mediotiempo.com/otros-mundos/juan-maria-lupita-jose-dejaron-nombres-comunes-mexico)) | Two of the 24 `GANCHOS` |
| Hyman's tested recipe: about three in four desirable-specific statements, one in four undesirable-general | cold reading | **not checked** ([Hyman, Zetetic](https://www.deceptionary.com/ftp/Hyman-Zetetic.pdf)) | Background for "one uncomfortable truth"; no number from it in the rules |
| LLMs repeat the idea, not only the words; the model must never be the dice; name the defaults to avoid, with diverse examples | LLM variety | **not checked** (Anthropic's prompting guide, IFG, Artificial Hivemind) | Code deals the seeds; `evita=`; three examples marked "no copies" |
| The double reading: in model mode each datum had its clip and then the model read it again | LLM variety | the code (`fortune_run.answer`), not a source | Beats and held reactions |
| The repo's own numbers: 141 clips, 73 with "esta noche", whole-word "amor" 0, "dinero" 1, no weekday | oracle voice, quick questions | yes (counted against `FORTUNE_PHRASES`) | The diagnosis |

## Dropped by the checkers

The colour → suit mapping attributed to Aeclectic and Greer (neither page has it), Lüscher's
"the favourite colour is the desire" (not on the cited pages), "hilos = chismes" in the egg
limpia, the number-7 miss line (impossible as scripted), Melate with three numbers (it draws
six), the calaverita's date of origin (disputed), Walter Mercado's lucky-number wording (the
2026 columns are his niece's), lines that copied Co-Star or Brezsny nearly word for word. None of
them reached the code.

## Considered and not taken

His word decided these, or ADR 0026 left them for later: the favourite colour (he declined it:
"I don't think it helps on the future reading"), the year folded into the date (numerology,
the Chinese animal), three-card spreads and court cards, pick-a-pile objects, the lotería as a
second deck, the egg limpia, the calaverita literaria on the ticket, a Zoltar-style block of
lucky numbers and colour, a rewrite of the clip-mode lines (he chose model mode only).
