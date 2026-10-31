# 0026 — The reading roasts: the wish, the hat's own card, seeds from the code

**Status:** proposed · **Date:** 2026-10-29

## Context

His word, 2026-10-29: the fortune's readings are "too innocent and maybe dumb" and "too canned
on repetitive scripts"; he asked how popular readings are made. The research
([results](../results/2026-10-29-reading-research.md)) and the act's own text gave three causes:

1. No stakes: every clip a blessing, 73 of 141 saying "esta noche", the dark cards softened on the
   spot; the rules asked for "un sentido bueno".
2. The act never asked what the visitor came for, so every prediction was general. Every popular
   format (a tarot question, a party reader's topic pile, the market's love, health and money)
   starts there.
3. In model mode each answer had its reaction clip, then the model recited the same 8 to 9 data
   in a fixed four-sentence order in about 70 words. Haiku takes no temperature, so the readings
   could vary only by what the code sent.

His answers the same day: tarot as one question, "¿Quieres que te lea una carta de tarot?", a card
named from his deck or, on a plain yes, one the hat draws; roast hard, a reading may end on the
sting; model mode only; the wish replaces the animal; no colour question; short beats in model
mode with the meaning read once.

## Decision

1. **The wish replaces the animal.** "¿Qué le vienes a pedir a la Muerte: amor, dinero, salud o
   venganza?" after the dream; four wishes by keywords (`fortune.WISHES`, venganza weighs 2), any
   other answer is `otro` with the visitor's words (up to 80 characters to the model). The order is
   sign, dream, wish, card, cup: the card answers the wish.
2. **The card is a question.** "¿Quieres que te lea una carta de tarot?": a card named is the
   visitor's draw from his deck ("de cabeza", "invertida" heard as reversed); a yes and the hat
   shuffles ("No traigo baraja: la traigo cosida en el forro…") and draws itself; a no is a short
   line and no card; an unclear answer is asked once more, then no card (a card only on a clear
   yes). `FISH_FORTUNE_DECK=off` still skips the question.
3. **The hat's deck**: the 22 major arcana and a second copy of La Muerte, El Diablo, La Torre, La
   Luna and Los Enamorados (dealt before repeat from the act's state file; the weighting is a
   choice, not measured). One draw in three comes reversed, and only in model mode, because the
   clips read upright.
4. **Model mode: beats, and the meaning once.** When the act's mode at an answer is the model's,
   the answer gets a short beat (12 lines, "Uy. Eso lo apunto en el forro.") and a card its name
   beat ("La Torre. Uy.", 22 lines, plus "Y salió de cabeza. Peor tantito."). The reaction the
   answer would have had is held; if the reading falls to the clips, the held reactions are said
   first (a reversed draw's upright line is dropped). Clip mode is the act as before, the wish's
   lines in the animal's place.
5. **Seeds from the code**, dealt before repeat, in the tag: `tema=` when no wish was heard;
   `visión=` one of 24 high-probability specifics (a chat kept muted, a key that opens nothing
   known, a tóper that is not yours), the only invented detail the model may say, with an out;
   `forma=` how the first sentence goes, of six that fit the data; `hoy=` the weekday and date;
   `evita=` the first eight words of the last six readings (`recent` in `fortune.json`). One angle
   (the wish) and two seeds: no ingredient bank (ADR 0022).
6. **The rules are a roast.** One story about the wish, two or three data as its evidence; the
   sign mocked for its famous flaw; the dream as one image from the visitor's words; the card read
   on the wish and not softened; one uncomfortable truth that may stay stinging; a concrete task
   with a day; the magic word last. Stale phrases are named as such ("esta noche" more than once,
   "algo viejo se va", "no te asustes", "energía", "nueva etapa"…), the parts never announced, the
   keys never said. These are bans on phrases, not on topics: ADR 0025 stands. Three examples,
   marked "no copies sus frases".
7. **The reading does not think.** `FortuneConfig.thinking = "disabled"`: the reading's call sets
   it over the profile's (`llm.thinking`, cleared at the next visitor's reset), so the visit keeps
   Haiku's thinking at effort low (ADR 0022). With thinking a reading took 5.1 to 7.6 s (median)
   and up to 4 of 11 hit the 8 s client timeout; without it 1.8 to 2.0 s
   ([results](../results/2026-10-29-roast-readings.md)).
8. **The ticket** prints the wish ("Pediste") in the animal's place, and a reversed card as
   "…, de cabeza" without its upright meaning.

## Alternatives

- **The favourite colour** (his first idea; the research's best new personality input): he
  declined it, "I don't think it helps on the future reading".
- **Thinking on and a longer wait**: the client's read timeout is 8 s and the voice is rendered
  inside the act's wait; a 6 to 8 s reading would fall to the clips most nights.
- **Rewriting the clip-mode lines**: his scope was the model; the clips gained only what the new
  questions and the beats need.
- **Spreads, court cards, pick-a-pile, the lotería, the year's numerology and Chinese animal**:
  each adds a question or a parser; left for later.

## Consequences

- The fortune's clips go from 141 to 181: 48 new (the wish's 2 prompts and 6 reactions, the card's
  new prompts, 12 beats, 22 name beats, the reversal line, 3 shuffles, 2 no-card lines), 8 gone
  with the animal; the card's two prompts are re-worded and render again. Rendered once at the
  first boot after the deploy: about 1 to 2 min (estimate, from 1.4 to 2.8 s a line on the board).
- The new lines, the gancho bank and the rules are drafts, his to edit.
- The model ignores the 75-word target (median 85 in the rehearsal); the act trims over 90.
  Once in 11 a card the hat drew was credited to the visitor; a missing name is sometimes filled
  with a guess. Not measured: a real act's reading with its voice, on the board, with his voice.
- Supersedes ADR 0019's decisions 5 (the card only from his deck) and 7 (the animal), and the
  animal part of ADR 0022's decision 4.

## Amendment, 2026-10-29 (ADR 0027)

The register is the old sorcerer's oracle, no longer a roast: the structure of decision 6 stands
(one story about the wish, the sting, the task), said gravely. The model mode's beats, shuffles
and suspense lines are re-worded to match ([0027](0027-the-oracles-voice.md)).
