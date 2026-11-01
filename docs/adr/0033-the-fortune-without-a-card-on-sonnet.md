# 0033 — The fortune without a card, on Sonnet

**Status:** proposed · **Date:** 2026-11-01

## Context

La consulta ([0032](0032-the-consulta.md)) gives one card its own act. His word: "cost is not an
issue, but time and quality are". 64 acts on 8 real visitors, scored blind
([results](../results/2026-11-01-fortune-arms.md)): Sonnet over Haiku by 1.49 of 5, 48 of 48; the
card within 0.01 of no card. Sonnet added about 1.3 s a reading and 0.9 s a question on the desktop.

## Decision

1. **The board's fortune has no card:** `FISH_FORTUNE_DECK=off`. Amends [0019](0019-the-fortune-act.md)
   and [0026](0026-the-reading-roasts.md). The code and the Visit tab's deck switch stay.
2. **The board's main model is Sonnet:** `FISH_LLM_PROFILE=claude-sonnet`. Amends
   [0029](0029-haiku-asks.md). Under `FISH_SHOW=script` that profile drives only the fortune.
3. **The fortune's thinking follows the profile:** `disabled` on Haiku, `between_tools` on Sonnet.
4. **La consulta starts under a scripted house** when `FISH_FORTUNE_MODEL=true`, on the same trust check.

## Alternatives

- **Keep the card:** no gain in the scores; the shuffle as a show was not judged. One switch brings it back.
- **Sonnet only in the consulta:** faster, 1.5 points lower.

## Consequences

The ticket prints no card picture. A model visit, if the board returns to one, is on Sonnet, untested.
