# 0015 — The scripted visit: a deterministic floor with no model and no live voice

**Status:** proposed · **Date:** 2026-10-26

## Context

At the fair and at the house tests the hat depended on the cloud (speech-to-text for long
answers, the model) and on a live Loquendo render for every reply; any of them failing showed
the visitor an error line or silence. No existing Sorting Hat project solved offline voice for
fixed answers: about 30 were read; they pick at random, let an operator pick, or used online
speech and fell back to typed answers. Children's speech recognition is poor everywhere (20 to
28 % correct at ages 5 to 6; 44 to 88 % word errors on this board's takes under 1 s).

## Decision

1. `FISH_SHOW=off|auto|script`. `off` (the default, the laptop) is today's visit. `script`
   always runs the scripted visit; `auto` runs it whenever the model cannot be trusted now
   (offline, a key missing, the voice tainted, a model failure in the last 2 minutes) and the
   model's visit otherwise. A model failure inside a model visit hands over to the script in the
   same voice; its fallback line is never said.
2. The questions are a "cross": two either/or questions whose answers split the houses in
   pairs, so the 16 answer paths give exactly 4 per house and never tie, plus one four-trait
   question worth more than one axis answer and less than two, which moves a visitor at most to
   a neighbouring house. Three sets rotate by visit number; small children (the age chip) get
   the two either/or questions only.
3. The house: the operator's "Forzar casa", then a stated house ("quiero Ravenclaw"; a house
   with a negation before it is ruled out), then the answers plus the colour chip (half an
   answer's weight, so it only breaks ties), then the latest four-way answer among the tied
   houses, then a persisted house bag. Every choice comes from sha256, never from Python's
   `hash()` or `random`; the seed, the visit counter and the line bags survive reboots.
4. Hearing: Canary's transcript matched against each option's words with accent folding and a
   Spanish sound key; conservative (a wrong callback is worse than a generic line). Nothing
   heard: the question once more, narrower, then a bridge line and the next question; at most
   two re-asks per visit. The operator's answer buttons count as an answer. There is no error
   line among the show's clips; a failed turn counts as no answer.
5. Every line is a canned phrase `show_*` (132 at first, drafted, original, gender-neutral),
   rendered at start-up only after the licence probe passed, played from the cache, backed up.
6. With the show on: "salir" does not quit, recordings stay under Canary's 6 s limit, the
   start-up welcome, the spoken address and the goodbye are not said.

## Alternatives

- **Vosk grammar mode as a second listener:** measured feasible on paper (39 MB Spanish model,
  Apache-2.0); not now (his word, 2026-10-26). `fuse` leaves room for it.
- **Three four-option questions with 2 + 1 points:** harder to hear, and 8 of 64 paths tie.
- **Operator-only:** the buttons are there, but the hat should still listen.

## Consequences

Visitors who give the same answers with the same chips get the same house; the lines vary by
visit. Unclear answers are common, so the default paths (re-ask, bridge, chips, bag, buttons)
carry many visits. Reviewing the 132 lines is his.
