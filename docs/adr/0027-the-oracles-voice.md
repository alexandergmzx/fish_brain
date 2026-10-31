# 0027 — The oracle's voice: the reading as an old sorcerer's omen, and 15 s for the model

**Status:** proposed · **Date:** 2026-10-29

## Context

His word, 2026-10-29: "an epic/elder tone in his prophecies, like an omenic sage on the TV". Not
Walter Mercado's pomp; the Brujo Mayor named only as the opposite of it, and then: "I don't want
to be a literal mexican shaman… I want to keep it being an occidental sorcerer magic hat" (a
limpia with herbs, the mal de ojo and such are fine). The roast of
[0026](0026-the-reading-roasts.md) read as cheek, not as a prophecy. And: "the limit for the
model, take it to 15 seconds".

The Western oracle's traits, from the texts themselves
([research](../results/2026-10-29-the-oracles-voice.md)): Delphi's equivocation (one answer,
two readings, never wrong), the witches' condition that comes true sideways, Merlin's emblems and
time marks, the Sorting Hat's own songs (the head is what it reads; it warns because it has seen
it before), Tolkien's sages (short declaratives, the senses as evidence).

His answers the same day: the sage's voice over the roast's bones; 15 s for the model call and
for the act's wait for the reading, not for the visit's turn; one more suspense line when the
reading is slow.

## Decision

1. **The reading speaks as an oracle** (`FORTUNE_RULES`): old, grave, solemn, few words, in the
   future tense, no mockery and no pomp. The structure of 0026 stays: one prophecy about the
   wish, two or three data as its evidence, the card not softened, an uncomfortable omen left
   standing, a concrete task, the magic word last.
2. **What changes in each part:** the instrument is the visitor's head, which the card confirms
   (never the stars or the universe); the sign is an emblem, read gravely; the dream is an omen;
   the sting is an omen said without flinching; at most one line with two readings; a time mark
   (a weekday, the moon, "antes de que…"), never a percentage; a warning, one "ay de ti si…" at
   most; the task a small rite with its day (a candle at the window, salt on the threshold, a
   coin in the left shoe, a limpia with ruda, something against the mal de ojo). The forma seed
   `orden` becomes `aviso`.
3. **The rite is a seed** (`rito=`, 18 in `fortune_bank.RITOS`, each with its time, dealt before
   repeat like `visión=`). With the rites listed in the rules, the rehearsal copied them: "una
   vela en la ventana" and "antes del domingo" each in 11 of 16 readings; dealt, 16 readings
   used 16 different rites. The rules also forbid naming the vision ("tu visión es…", 3 of 16)
   and saying that a tema was not said.
4. **Stale for the oracle:** los astros, las estrellas, el universo, todo está escrito, el
   destino te sonríe, mucho amor, any percentage. Phrases, not topics: ADR 0025 stands.
5. **The model mode's own clips** (the 12 beats, the 3 shuffles, the 2 suspense lines) are
   re-worded in the same voice. The clip-mode act is untouched (his scope of 0026).
6. **15 s:** every profile's call limit (`LLMConfig.timeout_s`) goes from 8 to 15 s, and the
   act's wait for the reading after the suspense line (`FortuneConfig.reading_s`) from 8 to 15 s.
   The visit's turn limit (`FISH_TURN_TIMEOUT_S`, 12 s) is unchanged.
7. **One more suspense line:** a reading still running `suspense_more_s` (7 s) after the suspense
   line gets one line from `suspense_mas` (2 new clips), then the wait goes on.

## Alternatives

- **The Brujo Mayor as the persona** (percentages, "por medio de las cartas", the title): he
  declined it; the hat is a Western sorcerer's hat.
- **Pure sage, no sting:** softer; he kept the roast's bones.
- **Silence until 15 s:** up to 15 s of nothing in a live act.

## Consequences

- Clips 181 → 183; 19 render again at the first boot after the deploy (about 1 min, estimate
  from 1.4 to 2.8 s a line on the board).
- A slow reading now waits up to 15 s instead of falling to the clips at 8 s; a visit's model
  call may take up to 15 s, but the turn is still dropped at 12 s.
- The rules and lines are drafts, his to edit. Not measured: the readings on the board, with his
  voice.
- Amends 0026 (the register; its structure stands) and 0019 (`reading_s`).
