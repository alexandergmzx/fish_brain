# 0033 — La calaverita: a verse after the House

**Status:** proposed · **Date:** 2026-11-01

## Context

His word, 2026-11-01: a new act that composes a calaverita literaria from what the visit knows, just
after a House, "family friendly but very funny", using La burla, which leaves the fortune. His
answers: a button, voice and ticket, three stanzas.

## Decision

1. **A button after the verdict.** 💀 Calaverita on the Visit tab, lit for `carry_s` (600 s) from the
   verdict; the window does not slide. Another tap in the window composes a new verse and a new
   ticket. It asks the visitor nothing.
2. **One blocking call on the turn loop's thread**, with nothing open between turns. It never calls
   `close`, `next_act` or `delivered`, so a fortune afterwards carries as before.
3. **What it knows:** the name, the house, the place, the cues the verdict filed and the visitor's own
   answers. `Visit.heard` is new (cleaned, the last 6): nothing else holds the answers after a verdict.
4. **The words are one file he edits**, `prompts/calaverita.toml`: the rules, La burla for this act,
   the pools, the word list, the fallback verses by house.
5. **The family rule is for this act only.** Its rules and `nunca`, a short list that refuses a verse:
   paper can't be unsaid. [ADR 0025](0025-no-censoring.md) stands for the other acts.
6. **Any failure ends in the house's rhymed clip, never an error line.** Fallback verses carry no name,
   because clips are pre-rendered.
7. **Only "not asked", a timeout before the reply and a real model error call `show.model_failed()`.** A
   refusal, an empty reply, a bad poem, a slow voice or a busy speaker say nothing about the next visit.
   This act quotes rude visitors, so refusals will happen.
8. **The running act refuses on shape, never on scansion:** 12 lines, each short, 40 to 90 words, no
   tag, no `nunca`. Meter and rhyme are measured by `tools/hat_rehearse.py` only.
9. **The pause is punctuation:** a comma at each line, a period at each stanza. Tags only if the lines
   run together by ear.
10. **The ticket has its own layout**, so the fortune's paper does not change. Reprint stays one slot,
    so a later fortune replaces the verse.

11. **Sonnet writes it, his word 2026-11-01** (`FISH_CALAVERITA_PROFILE`, default `claude-sonnet`), on a client of its own, built in the worker on first use; the rest of the hat stays on its model. `main` or a missing key uses the visit's. Its failures never call `show.model_failed()`: they say nothing about the visit's model. Its rhyme is still below the bar set beforehand: 38 % of stanzas.

## Alternatives

- **Automatic after the verdict:** a longer visit for someone who may be leaving; his choice was the button.
- **One verse per verdict:** nothing asked for it, and it caused most of the design's edge cases.
- **Haiku, the visit's model:** 67 % of lines within one of 8 against Sonnet's 97 % ([rehearsal](../results/2026-11-01-calaverita-arms.md)).
- **Scansion as a refusal:** a crude counter must not reject a good poem.

## Consequences

The first start renders its 19 clips. A `--prompts` folder without the file uses the package's. Not
measured: the length said aloud, the lines in Jorge's voice, `calaverita_s` on the board, paper on the MP210.
