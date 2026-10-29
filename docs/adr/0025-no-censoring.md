# 0025 — No censoring

**Status:** proposed · **Date:** 2026-10-29

## Context

ADR 0019 (decision 10) gave the fortune a word filter, `fortune.BANNED`, checked by
`banned_in` against every clip in the tests and by `clean_reading` against the model's reading,
and the model's rules for the reading and the visit carried a list of forbidden topics: illness,
accidents, real misfortune, a death said as an event, explicit or crude sex, cruelty about the
body, politics, religion as doctrine, prizes. La Muerte was allowed by name, but "muere",
"morir", "muerto" or "funeral" in a reading threw the reading away for the clips. His word,
2026-10-29: no censoring; he does not want Death, or anything else, prohibited.

## Decision

1. **No word list.** `BANNED`, `EXEMPT` and `banned_in` are gone. `clean_reading` drops a reading
   only when it is empty or still over 6 sentences and 90 words after the trim.
2. **No forbidden topics in the model's rules.** The lines that forbade illness, accidents,
   misfortune, a death said plainly, explicit or crude language, remarks on the body, politics,
   religion and prizes are gone from `fortune_bank.FORTUNE_RULES` and the visit's rules
   (`config.py`).
3. **The free animal** is whatever the visitor said (up to three words), no word refused.
4. **The rehearsal** (`tools/hat_rehearse.py`) checks the shape of a reply only: tags, sentences,
   words, question length, the house, the time.

What stays, because it is not about content: the length limits; the privacy rules (the first
name only, never surnames, age, address or phone; a cue naming a school, company or person used
by its theme); never repeating the bracket tags; the parked badge look's consent rules (ADR 0007).

## Consequences

- A model reading that names a death, an illness or a swear word is said and printed as written.
  What the hat says is the model's and the rules' tone, with nothing behind it to catch it.
- The clips are his texts; no test checks their words any more, only their shape.
- Supersedes ADR 0019's decision 10 as far as it bans; its register (spooky and cheeky, the
  season's guests) stays as the rules describe it.
