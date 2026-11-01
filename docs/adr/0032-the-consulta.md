# 0032 — La consulta, and the mockery out of the fortune

Status: proposed, 2026-11-01. Reverses ADR 0030 decision 2 and ADR 0026 decision 6 **for the fortune only**; `visit.md` and `house.toml` are not touched.

## Context

A 2023 chat read one Thoth card for one real question, and the person asking was happy with it. He wants that on the hat as a feature to play with. Reading the rules for it, he found that the fortune tells the hat to mock the wish: "awful, I don't like it".

## Decisions

1. **A new act, not the wish's slot.** One question, one card, one reading, then it closes; started again for another question. It shares the fortune's one slot (`FortuneRun.v`, `v["act"] == "consulta"`), so the two exclude each other, with its own reading loop in `consulta.py`.
2. **The tone of the 2023 chat.** Warm, explains the card, then what it may mean for the question. The card "may indicate"; it never predicts. `prompts/consulta.md`.
3. **Sonnet 5.5** (`FISH_CONSULTA_PROFILE=claude-sonnet`), his word: cost is not an issue. On five sentences: median 145 words (121 to 158) and 3.73 s, against Haiku's 129 (103 to 193) and about 2.1 s; desktop ([results](../results/2026-11-01-consulta-trial.md)). Length is set by sentences: asking for words did nothing.
4. **The 22 major cards, Rider-Waite.** Thoth's names (Arte, Ajuste, Lujuria, Eón, Universo, La Fortuna) reach their cards only in this act: as deck aliases "Quiero saber mi fortuna" would be card 10 in the fortune. A minor card is told it is not in the deck. No table of pictures: the model describes them from the name.
5. **The hat draws fair and upright**, from a bag of its own. The fortune's weighted draw stays there.
6. **No clip can answer a question.** Offline, without a key or in a scripted show the act does not start; a reading that fails says so, and does not count against the show.
7. **Saved like any other turn, no ticket** (his word).
8. **No mockery in the fortune.** `LA BURLA` out of `reading.md`, its examples rewritten, 64 clips reworded. The dark-card weighting stays: it serves the ominous tone.
9. **Self-harm: no reading, no card named**, the Línea de la Vida named and no phone number spoken. Illness, death or danger: no prediction, and it points to a doctor or someone trusted.

## Not measured

The model and a reading over 63 words through Jorge on the board; `WAIT_S` (20 s), `QUIET_S` (300 s), `AFTER_S` (60 s) and `MAX_WORDS` (180) are estimates. How speech-to-text hears "Eón" or "Ajuste". About 50 s of mouth motion. A reading cannot be stopped once speaking.

## Amendment, 2026-11-01

His word: after the consulta "print the results". Decision 7 changes: a reading goes on paper as the closing line starts, with the card's plate, the question and the reading (`ticket.consulta_ticket`). A failed reading prints nothing.
