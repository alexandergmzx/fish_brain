# 2026-10-29 — The roast readings: old rules and new, with and without thinking

The fortune's model reading before and after ADR 0026 (the wish, the hat's own card draw, the
code's seeds, the roast rules), rehearsed against the model with no voice, no microphone and no
motors. Desktop, branch `sorting-hat`, HEAD `fe7d319` with this change uncommitted; the old rules
are `fe7d319` itself (ADR 0025's, no censoring), run from a temporary worktree.

- Model: Claude Haiku 5.5, the `claude` profile (thinking `adaptive` at effort `low` unless the
  row says otherwise), from the desktop on the home network.
- Visitors: `tools/hat_visitors.txt`, 11 scripted visitors, each a visit and a fortune (the
  old file has the animal, the new one the wish and the card's yes or no).
- What counts: the time of the reading call alone (the visit's turns are not in it); "slow" is a
  reading that hit the 8 s client timeout or took longer than the act's 8 s wait; words are the
  model's own (the act trims anything over 6 sentences or 90 words, keeping the magic word);
  openings are the first three words, folded.

```bash
.venv/bin/python tools/hat_rehearse.py tools/hat_visitors.txt                      # new rules
.venv/bin/python tools/hat_rehearse.py --only 3 --repeat 20 tools/hat_visitors.txt   # one visitor 20 times
# old rules: a worktree at fe7d319, its own tool and visitors, the main .env loaded by path
```

## The table

| Run | Rules | Reading thinking | Said of 11 | Slow | Seconds, median (max) | Words, median (range) | "esta noche" | Distinct openings | Other stale phrases |
|---|---|---|---|---|---|---|---|---|---|
| old 1 | `fe7d319` | adaptive, low | 9 | 2 | 6.3 (7.7) | 70 (60–118) | 1 | 9 of 9 | — |
| old 2 | `fe7d319` | adaptive, low | 10 | 1 | 5.1 (6.8) | 94 (67–119) | 4 | 10 of 10 | — |
| old, no thinking | `fe7d319` | disabled (the visit's too) | 11 | 0 | 2.5 (4.0) | 122 (80–170) | 3 | 11 of 11 | "no te asustes" 2, "transformación" 1 |
| new, first draft | ADR 0026, first draft | adaptive, low | 7 | 4 (`APITimeoutError` at 8 s) | 7.6 (8.0) | 91 (77–104) | 0 | 7 of 7 | "salió derecha" 3, "gancho" said 1 |
| new 5 | ADR 0026 less the last two rule lines | disabled | 11 | 0 | 2.0 (3.3) | 86 (62–116) | 0 | 10 of 11 | "la verdad que pica" 1, "tu verdad incómoda" 1 |
| **new 6** | **ADR 0026 as committed** | **disabled** | **11** | **0** | **2.0 (3.4)** | **85 (69–107)** | **0** | **10 of 11** | "salió derech…" 1 |
| collapse | ADR 0026 less the last two rule lines; visitor 3 × 20 | disabled | 20 of 20 | 0 | 1.8 (2.8) | 80 (57–121) | 0 | 11 of 20 | "abundancia" 1, "el universo" 1 |

Single runs of 11 visitors (two for the old rules); the spread between runs is not measured
beyond that.

## What the runs say

- **The speed is the thinking, not the rules.** With thinking the old rules took 5.1 to 6.3 s
  (median) and the first draft of the new ones 7.6 s, 4 of 11 timing out; without it the old
  rules took 2.5 s and the new 1.8 to 2.0 s. The act's wait is 8 s after the suspense line, and
  in a voice turn the reading's voice is rendered inside that wait as well (1.4 to 2.8 s a line,
  `2026-10-28-openai-voice-on-the-board.md`), so a 6 to 8 s reading falls to the clips. Hence
  `FortuneConfig.thinking = "disabled"` for the reading only; the visit keeps his thinking-low
  pick of ADR 0022.
- **The content is the rules.** Without thinking the old rules still wrote 122-word blessings
  that recite every datum ("La Muerte, no te asustes, que aquí no significa final sino paso y
  transformación"); the new ones write one story about the wish with a sting and a task.
- **Variety:** across 11 different visitors the new rules gave 10 and 11 different openings in
  runs 5 and 6, and no "esta noche". The same visitor 20 times gave 11 openings, the `forma` seed
  rotating them; the content repeats with identical answers ("Escorpio, tú no soñaste nada y lo
  sabes" in 6 of 20), which no real night has.
- **Fixed on the way**, each seen in a run: the key `gancho` said aloud (now `visión=`); "la sacó
  el visitante" read as "visitante" (now "tú la sacaste" / "la saqué yo"); "salió derecha" in 3 of
  11 and then 6 of 20 while the rules named it (the rules now never mention an upright card: 1 of
  20, then 1 of 11); the sceptic example copied word for word in 3 of 20 ("o sea que vienes a
  auditar al sombrero"; the example lost its sceptic); the `forma` instruction read out as a label
  ("Orden corta: …"; the instructions are now about the first sentence); parts announced ("Tu
  visión:", "La verdad que pica:") and the visitor in the third person once (one rule line: none
  in run 6).
- **Known limits, not fixed:** the model ignores the 75-word target (median 85, the act trims
  over 90); once in run 6 a card the hat drew was credited to the visitor; "Tu visión es…" once;
  a missing name is sometimes filled with the magic word or a guessed gender ("maestra" for a
  professor with no name in the tag).

## The same visitor, old and new

Visitor 4 (Piscis, a dream over a pantheon, El Diablo drawn from the deck; old: the bat, new: a
wish for revenge on the ex):

> **Old, with thinking (3.6 s, 118 words):** Ah, Piscis, hijo del agua, tu sueño trae a un ser
> querido que ya cruzó el puente, y eso es buena señal, pues los que se fueron nos cuidan desde el
> otro lado. Veo tu carta, El Diablo, que no es maldición sino el sabor picante de la vida, pues tu
> corazón morado y tu sonrisa pícara anuncian que tomas las cosas con gusto. El murciélago, que
> escogiste, te guía de noche, y el número cuatro te trae una pequeña fortuna que llegará pronto,
> cerca del altar o de la mesa de algún amigo. Esta noche la luna gibosa menguante te susurra que
> sueltes lo que ya no te sirve, y para cerrar, tu palabra mágica es Murcielumbra.

> **New, run 6 (2.0 s, 85 words):** Suelta esa venganza, que ya te pesa más que el disfraz.
> Piscis, tú no te ahogas en un vaso: te ahogas en el chat de tu ex, y eso sí es nadar en
> desgracia. El Diablo lo sacaste tú, no me eches la culpa: esa cadena la traes puesta por gusto.
> La foto que no te atreves a borrar ya te está mirando desde el celular. Bórrala el sábado, antes
> de la ofrenda, y pon ahí una vela para cerrar. Tu palabra mágica es Murcielumbra.

More from run 6 (said as written; the act would trim none of these):

> **Visitor 3** (Escorpio, no dream remembered, money, a yes and the hat drew La Estrella):
> Escorpio, tú no olvidas nada, pero dices que no te acuerdas. Eso también es picadura de alacrán.
> Pediste dinero "ya que estamos", como quien pide el postre después de la cuenta. La Estrella
> salió con tu mano: esperanza, pero con los pies bien en la tierra. Esa deuda chiquita con alguien
> de confianza, págala tú antes de que te la cobren. Mañana, antes de que se te enfríe el café,
> manda ese mensaje. Tu palabra mágica es Murcielumbra.

> **Visitor 11** (a professor, Virgo, "que mis alumnos lean", the hat drew Los Enamorados reversed):
> Ay, Virgo, tú dando clase en un salón vacío, qué drama tan bonito. Tu deseo es que tus alumnos
> lean, y eso te late bien porque eres de los que corrigen hasta el silencio. Los Enamorados
> salieron de cabeza: el amor ya te cansó, o tú ya cansaste a alguien con tus correcciones. Ese
> audio largo que no has escuchado trae justo lo que pides, así que ponlo el lunes antes del café.
> Tu palabra mágica es Tenebrumba.

Not measured: a reading in a real act (the voice rendered in the same worker, his voice through
speech-to-text), on the board's network, or how visitors take a roast.
