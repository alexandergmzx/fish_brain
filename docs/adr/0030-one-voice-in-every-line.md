# 0030 — One voice in every line: the open roast, the first film, the house act in his file

**Status:** proposed · **Date:** 2026-10-31

## Context

His word, 2026-10-31: "the toml lines suck… maybe the tone and theme can be perfected". The lines
were the fair's kid bank with words swapped: "esta noche" in 68 of 184, a diminutive in 20, the
castle in 2 ([research](../results/2026-10-31-the-hats-words-research.md)).

## Decision

1. **The voice:** an ancient magical object of Hogwarts that reads the head in front of it; short
   grave sentences, the future tense, no diminutives, noises or reassurances, the hat in the first
   person, Mexican Spanish. The style guide is section 3 of the research, with his answers on top.
2. **An open roast**, his answer: the hat mocks, dry, in most lines; the kindness stays underneath.
   This reverses "sin burla" of [0027](0027-the-oracles-voice.md); its sage's shapes stay.
3. **The castle is a pinch from the first film**, in its Latin American names; the visitor's own
   words carry the line. No English name in a spoken line unless `say_as` respells it.
4. **This pass:** the 80 fortune lines changed in `lines.toml` (what model mode says, plus the
   seeds' diminutives), `visit.md`, `reading.md`, and the house act's 143 clips. The fortune's banks
   (`signs`, `dreams`, `shapes`, `numbers`, `moons`, `cards.tarot`, `wishes`, `magic`, `vision`,
   `re_deseo_otro`) wait for a second pass. `ask.md` stays his.
5. **The house act's words move to `prompts/house.toml`**, amending
   [0029](0029-haiku-asks.md) decision 1 and ending the wait for the adult pass of 0015, 0019 and
   0022. Nine new questions for adults, by position in the cross; the scores stay in
   `show_bank.SHAPE`, so an edit cannot unbalance it. The option words sit beside their question,
   because the options are its nouns.
6. **`FISH_PROMPTS_DIR`** (default the package's folder) and `tools/hat_rehearse.py --prompts DIR`
   rehearse other words without touching his files.

## Alternatives

- **Every bank now:** his choice was the lines he hears first.
- **A dry sting with no open mockery:** he picked the open roast.
- **The whole saga as the castle:** he limited it to the first film, as a pinch.

## Consequences

Clip mode and the fallback mix the two registers until the second pass. Old rendered clips remain
the offline fallback by name (`canned.py`), so a first start offline can say an old line under a new
text: check `ready == lines` on Status before a visitor. Tests of the house act are positional, so
new nouns do not break them. Lines are drafts for his edit. Not measured: all of it by voice.

## Amendment, 2026-10-31: the house act's first words are back

His word: the new house lines are "too complex to understand for the majority". `house.toml` holds
the fair's 143 lines again (`show_bank.py` at `52cacd1^`, word for word), reversing the words of
decision 4's house act; the file stays his (decision 5). The rest of this record stands: the model's
visit, the fortune and `reading.md` keep the voice above, so the scripted house act and those two now
speak in different registers. The rewritten lines are in git at `aab3dc4`.

## Amendment, 2026-11-01: no burla in the fortune

His word: La burla is erased from the fortune and stays out. `reading.md` lost its section and the
fortune's clips in `lines.toml` were reworded, so decision 2 no longer holds for the fortune;
`visit.md` keeps it, heard only on the page's Auto or Model. The comments in `fortune_bank.py` name
ADR 0032, the consulta's record, which is not written yet. `visit_greeting` was shortened with the
restore of 2026-10-31; it is not said under script. Decision 5's nine new questions went with that
restore too.
