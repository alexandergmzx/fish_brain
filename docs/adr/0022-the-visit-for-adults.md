# 0022 — The visit for adults: cues for the whole visit, a verdict from the visitor, Haiku

**Status:** proposed · **Date:** 2026-10-27

## Context

His test on the board, 2026-10-27 18:07-18:12 UTC (the journal and the record
`156feadb-6329.jsonl`): a house visit with the cues adulto, amigos, amarillo, sonriente and a
costume note, then a fortune with the cues set again. The cues reached the model once, on the
first model turn, and were consumed (`Visit.delivered`); the rules allowed one cue per reply,
disguised. The verdict's prediction was built from a random bank of six or seven ingredients
and came out mashed ("una vela de colores hará bailar una sombra de rana … pan de muerto …
¡Dulce o truco!"), his main complaint: "something more organic and related to the cues I give".
The visit's rules still addressed families with children while the fortune spoke to adults.
The fortune ignored the cues, refused "un perrito xoloitzcuintle" twice, matched no theme for
"soñé con unos borreguitos" and retold "veo a tu tío que se murió".

## Decision

1. **The cues last the visitor's visit and its fortune.** Every turn carries every lit cue and
   the place (`[PISTAS: lugar=…; …]`); turns never consume them; the act's close files them and
   clears the row; the next visitor keeps only the cues set after that close; a fortune that
   follows the same visitor's verdict gets them back, any other prunes them (`visit.py`).
2. **The adult cue set**: age Young · Adult · Older; With adds Couple; Impression adds Sceptic and
   Party animal; a new row Costume: Spooky · Funny · Elegant. The impression reaches the model as
   a noun, so no gendered adjective is echoed.
3. **The visit's rules in the fortune's adult register**; every cue is material, the hat need
   not name each; the verdict's prediction is one image from the visitor's words, a cue and the
   place, with no ingredient bank, no hour and no named venue.
4. **The fortune**: the cues in its tag; any animal (the four offered, then an animal word kept as
   said, then the sound-alike match); the dream's words left out for a loved one and for an
   unthemed dream; more animals in the dream themes; a long reading trimmed to fit, keeping its
   first sentences and the magic word, instead of falling to the clips.
5. **The model is Claude Haiku 5.5 with thinking at effort low** (his word, 2026-10-27, no
   comparison asked for): the `claude` profile thinks (`adaptive`, effort `low`) with a
   2000-token cap, because thinking shares the cap. On the board it is `FISH_LLM_PROFILE=claude`.
   The badge reading already tries Claude first (ADR 0018). Speech-to-text and the voice have no
   Anthropic model and stay as they are (ADR 0020, Loquendo).

## Consequences

- His visit rehearsed on the board: a verdict from his cues and answer, the xolo taken
  ([results](../results/2026-10-27-haiku-on-the-hat.md)). Visit replies 1.1 to 4.8 s in three
  runs, against 2.5 to 3.3 s for luna in his turns of the day (single samples).
- The rules, the two new animal clips and the chip labels are drafts, his to edit.
- The first Claude call after a start waits for the SDK import (7.0 and 17.4 s measured on the
  board).

## Known limits

- The scripted house act (offline, or Script mode) keeps the children's register until his pass;
  in Auto, going offline changes the register.
- A fortune within 10 min of a verdict inherits that visitor's house, name and cues; time is the
  only test.
- Without the bank the model may settle on similar predictions; not measured.
- Script visits that never reach a verdict pass their cues to the next visitor, as before.

## Amendment, 2026-10-28: short questions in the castle, nobody assumed a student

His word after Mónica's visit at the university: the questions too long and forced on the
place, too little Hogwarts, not everyone there is a student; and the bans on the year, the
age, the hour and named places were not his. The rules get EL CASTILLO (the Gran Comedor, the
ghosts, the Forbidden Forest, potions, quidditch) as the world, the season and the place as "la
sazón, no el plato"; the university as corridors and coffee, "no des por hecho que estudia";
a bank of questions of 10 words or fewer; two short lines and a question (30 words) per
reading turn, 55 words for the verdict; the age may be said, a named place only when the
visitor said it. Haiku keeps the short questions and the castle and ignores the word counts
(34 to 47 words a turn: [results](../results/2026-10-28-short-turns-in-the-castle.md)).

## Amendment, 2026-10-29 (ADR 0026)

The fortune has no animal any more (decision 4's animal part is superseded). The fortune's
reading runs with thinking disabled; the visit's turns keep thinking at effort low
([0026](0026-the-reading-roasts.md)).
