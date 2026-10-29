# 0019 — The fortune act: a second act for adults, answered by voice, read from clips or by the model

**Status:** proposed · **Date:** 2026-10-27

## Context

The audience changed (his word, 2026-10-27): adults at his parents' house, a Halloween party,
curious people at the university, "somewhere I define". The fair's pieces were made for school
children with badges: a badge photo and the reading of a name ([0007](0007-the-reading.md)) have
no use at a party, and the house act's lines keep a kid's register. He asked for a new act that
asks the birth date (the sign), the dreams and "esoteric stuff", and predicts the future, "be
creative"; the dream question is open ("¿Has tenido sueños interesantes últimamente?") so the
visitor hands the hat material to read a mind with. The scripted visit
([0015](0015-the-scripted-visit.md)) already has the floor any act needs: clips rendered at
start-up, a matcher for Canary's transcripts, re-ask then move on, operator buttons, no error
line.

## Decision

1. **A separate act.** "Fortune" sits on the Visit tab beside "New visitor" (the house act);
   either may follow the other for the same visitor. After a verdict the fortune knows the
   house and the first name for ten minutes (`carry_s`). Over a live house act it is refused
   (`409 visit open`: finish it or force a house); "New visitor" or a typed name drops an open
   fortune silently, and so do 90 s of silence.
2. **Every answer by voice**, no answer chips. A miss gets the narrower re-ask once, with a
   budget of two per act; "no sé" moves on at once; the page has Skip question and End act.
   Every datum is optional: the act always reaches the closing.
3. **Day and month, never the year** (the prompt says so, and a year in the answer is ignored).
   The sign, its element and a lucky number (the digits summed to 1..9) come from the date; a
   sign said directly counts.
4. **The dream, open.** Twenty-one themes matched by keywords, ordered by how common each is in
   the research ([results](../results/2026-10-27-dream-themes.md)): `nada` for "no me acuerdo",
   `otro` for the rest and for the deflected subjects (sex, violence, pregnancy, religion), and
   three the research had dropped that come back with adults: `ex`, `desnudo`, `fortuna`. In
   script mode the theme's omen line, then one **vision** line from a mentalist pool, lines
   that need no content ("Y en ese sueño había alguien que no esperabas. No me lo digas: ya lo
   vi."). In model mode the tag carries the theme and the visitor's own words (at most 120
   characters) and the rules teach the moves: the echo, the rainbow, the hit boost, a miss
   turned into the future. For this question only the recording cap rises from 5.5 s to 10 s
   (`dream_record_s`) while the long speech route is online; offline it stays and the re-ask
   lists themes. *Amended 2026-10-27 ([0020](0020-online-first-speech-and-the-uncut-hold.md)): no
   cap is lifted or restored; every answer, the dream's too, is capped by `FISH_PTT_MAX_S`
   alone.* Every keyword (the themes', the cup's, the cards' aliases) is written as
   `visit._fold` leaves a word, without accents and with ñ as n, and a stem ends in `*`.
5. **The deck as data.** `DECKS["tarot"]` holds the 22 Rider-Waite major arcana as `Card` rows
   (Spanish and English names, the number, aliases for a Spanish ear, a meaning). The visitor
   draws from his deck and says the name or the number; La Muerte and El Diablo are named.
   `FISH_FORTUNE_DECK=off` skips the question; a lotería deck is one more entry and its clips,
   later.
6. **The cup**, optional (`FISH_FORTUNE_CUP`, off by default): "¿Qué figura ves en tu taza?",
   eleven shapes by keywords.
7. **The animal**: gato negro, búho, murciélago or sapo, a four-way question through the
   scripted visit's matcher.
8. **Without input**: the moon tonight (eight phases from the clock, skipped when the clock is
   not sane) and a magic word of the night (twelve invented words, a deal-before-repeat bag).
9. **The reading in two modes.** The mode is the show's (`mode_now`; echo is script). Script:
   the suspense clip, the number, the moon, the magic word and the closing, from the clips.
   Model: the model job starts first, then the suspense clip is said on the loop's thread, and
   the reply gets `reading_s` (8 s) from the end of the clip; a clean reply is rendered live and
   remembered, then the closing clip. Any failure (timeout, error, a reply empty or too long)
   ends on the script's clips and marks the show as the house act does. No error line, ever.
10. **The adult register.** Spooky and cheeky: death and the calaveras as the season's guests,
    the Death and the Devil cards by name, romance and the ex, money as "fortuna" (never a
    prize), dark humour, light albures ("picarones, nunca groseros"), the naked-in-public dream
    as comedy, a drink or a song. `clean_reading` drops a model reply past six sentences or
    90 words. *Amended 2026-10-29 ([0025](0025-no-censoring.md)): no filter, no content bans.*
11. **The place is a setting**, not a per-visitor cue: `FISH_PLACE=casa|fiesta|universidad|otro`
    and `FISH_PLACE_TEXT` (free text, read by the model only), both on the Settings tab (on the
    Visit tab since 2026-10-27, see the amendment). The intro and the closing pools have a
    variant per place; a toast or a song only at a party; the model gets `lugar=` in the tag and
    one rule line.
12. **The clips are `fortune_*`**, joined to the canned phrases whenever the persona is the hat
    and not gated on `FISH_SHOW`: the act lives when the page's Model or Echo buttons turn the
    show off, and the show's own tests ("no `show_` names with the show off") hold. The deck's
    and the cup's clips render even when the toggles are off. On the page Fortune is greyed
    until the question clips are cached (`lines_ready`).
13. **Its own state file** (`FISH_FORTUNE_STATE`, `fortune.json`): the counter and the bags,
    beside the show's; every choice from sha256, never `random`.

The act, as the visitor hears it:

```
intro_<place>   (intro_<house> when the house act just ran)
Q1 fecha   "¿Qué día y de qué mes naciste?"               → sign, element, number  → re_fecha_<sign>
Q2 sueño   "¿Has tenido sueños interesantes últimamente?" → a theme                → re_sueno_<theme> + vision_<i>
Q3 carta   (deck on) "Saca una carta… ¿cuál?"             → one of 22              → re_carta_tarot_<n>
Q4 taza    (cup on)  "¿Qué figura ves en tu taza?"        → a shape                → re_taza_<shape>
Q5 animal  "¿gato negro, búho, murciélago o sapo?"        → one of 4               → re_animal_<id>
suspense → script: num_<n> · luna_<phase> · magic_<i> · cierre_<place>
         → model:  four sentences from [ADIVINACIÓN: …] (live render) · cierre_<place>
                   any failure → the script's ending
```

A miss is the narrower re-ask, then a bridge line and the next question. The reaction clip
**is** the datum's line, said when it lands.

## Alternatives

- **Answer chips on the page** (the date, the card, the theme): the operator would type while
  the visitor talks; he chose voice with the re-ask.
- **The fortune after the house inside one visit**: one long act with the house's kid lines in
  it; two acts let either run without the other.
- **Whole-sentence combinations** (a clip per sign × theme × card): thousands of clips to
  render and to review; instead one clip per datum, said when it lands, and the model for the
  woven reading.

## Consequences

- About 140 clips (`fortune_*`), rendered once after the licence probe at the first boot after
  the deploy: about 10 min (estimate, from 166 clips in 681 s on 2026-10-26,
  [results](../results/2026-10-26-hat-offline-visit.md)). Fortune is greyed until then.
- The lines are drafts, his to edit: the omens, the vision pool, the cards' meanings, the magic
  words, the moon and number lines.
- The house act's 143 kid lines keep their register until his later pass, and its model rules
  get the `lugar` line then.
- Canary writes a spoken date as words, never digits (Loquendo-voiced clips, `../results/2026-10-27-fortune-answers-canary.md`); his voice is not yet measured; a miss costs one re-ask and the sign and
  number lines are skipped. English card names through Spanish speech-to-text are a risk; the
  number is the safe path. A party is loud: Skip and End matter.
- The badge photo and the look tick leave the operator page; the server side of
  [0007](0007-the-reading.md) is parked and the typed name stays.

## Amendment, 2026-10-27: the place and the fortune's extras on the Visit tab

- The place, its text, the deck and the cup sit on the Visit tab below the acts
  ([0017](0017-the-show-tab.md), amendment of the same date), not on Settings. Same switches,
  same reset at a restart.

## Amendment, 2026-10-27 (ADR 0022)

The cues reach the reading; any animal is taken as said; the dream's words are left out for a loved one and an unthemed dream; a long reading is trimmed, not refused.

## Amendment, 2026-10-28: the sign asked first, the year and the hour allowed

His word: adults will not mind the year, the age or a clock time, and the hat may ask the
zodiac sign outright. `fortune_q_fecha` asks "¿De qué signo eres?", the re-ask is the day and
month as the fallback; a sign alone gives no lucky number (the tag and the clips skip it).
The fortune's rules name the castle as
the world and the season as a pinch ([results](../results/2026-10-28-short-turns-in-the-castle.md)).

## Amendment, 2026-10-28 (ADR 0024)

With `FISH_PRINTER` set, the reading also goes home on a ticket, handed to the printer as the
closing line starts, one an act; `FISH_FORTUNE_TICKET` and the Visit tab's switch turn it off
([0024](0024-the-fortunes-ticket.md)).

## Amendment, 2026-10-29 (ADR 0025)

No censoring: the word list, its checks and the forbidden topics in the rules are gone
([0025](0025-no-censoring.md)).
