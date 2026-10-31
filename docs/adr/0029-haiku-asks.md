# 0029. Haiku asks the questions; the words live in files

**Status:** proposed · **Date:** 2026-10-31

## Context

After his fortunes on the board he found the questioning "a little too dumb", and said Haiku is not.
The rules were the cause: the visit imposed a template and a list of multiple-choice questions of 10
words, with no following up on an answer ("Una duda." → "Una puerta cerrada: ¿la abres…?"); in the
fortune the model wrote no question, only fixed clips and a random beat ("Capricornio." → "Silencio.
Eso pesa."). He wants to polish the words himself, more ominous and on theme.

## Decision

1. **The words are files**: `fish_brain/prompts/visit.md`, `ask.md`, `reading.md` (sent to the model
   whole) and `lines.toml` (every fortune line, the seeds, the visit's greeting), read by
   `fish_brain/texts.py`. A broken file stops the start-up, naming itself. The house act's lines stay in code.
2. **The visit follows the answer**: each question comes from the last reply; the list became what
   each house reveals, with examples of tone. Grave and ominous rather than cheeky.
3. **The fortune's questions are the model's in model mode**: after an answer it reacts and asks the
   next thing (`[PREGUNTA: pide=…; modo=…; dijo="…"; …]`, thinking disabled, one history an act), and
   in a re-ask it can answer a question back in character. `parse_answer` and `reask` still decide
   what is asked and when.
4. **The clips stay the fallback**: a failure, a timeout or a line `ask_result` refuses (no question at
   its end, not the topic, a tag, "tarot", a card with no deck) is the clip, and the rest of the act
   stays on clips. A line over 40 words is cut to its first sentence and its question. Clip mode is
   unchanged, as are the intro, the first question, a card's name, the shuffle, no card, suspense and
   the closing. `FISH_FORTUNE_ASK=false` turns it off.
5. **Privacy holds**: the words of a dream in `DREAM_NO_WORDS` never reach the question turn.

## Alternatives

Fixed clips rewritten by him: instant, but they can never react. Rules kept in Python: no new file, but
words mixed with code.

## Consequences

- Each fortune answer now waits for the model and a live render, covered by the burble and the
  fillers within the 12 s limit. That wait is not measured on the board.
- The rehearsal marks each line [S], [H] or [H → clip]; the records gain `asked`.
- Amends 0019 (re-ask lines), 0022 (the visit's question bank) and 0026 (the beats are now the fallback).
