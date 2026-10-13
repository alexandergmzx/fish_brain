# 0010 — The fish talks while it thinks, and gives up on a turn that takes too long

**Status:** proposed · **Date:** 2026-10-13

## Context

After the visitor releases the button the fish said nothing until its reply started. With
the board's routes that is 2.3 s (takes under 3 s) to 4.9 s (the longest under 5 s) of
transcription on Canary ([results](../results/2026-10-13-unoq-stt-his-takes.md)), then 1.5 to 3 s of LLM (7 s for a
prophecy) and about 1 s of voice ([first conversation](../results/2026-10-11-unoq-first-conversation.md),
[reading](../results/2026-10-11-board-reading-and-upload.md)): 4 to 10 s of silence. Offline
with a recording over 6 s it is about 10 s at 7 s of recording and 16 to 42 s over 10 s. Only the cloud calls had a time limit; Canary,
faster-whisper and Loquendo had none, so a turn could hold the fish as long as it liked.

A turn ran on one thread, stage after stage, and the speaker refuses a second phrase while
one plays instead of queueing it. A phrase said during a stage needed the stage to run
somewhere else, and the reply must never be lost to a phrase still playing.

## Decision

1. While a voice turn waits, the fish says short canned phrases: the first after
   `FISH_FILLER_DELAY_S` (1.5 s at first, 2.5 s since the amendment below) of silence from the end of the recording, the next ones
   `FISH_FILLER_GAP_S` (2 s) after the previous phrase ended, until the reply starts. One
   chain per turn, across transcription, LLM and voice. No phrase twice in a turn, and the
   last three said are avoided.
2. Past `FISH_TURN_TIMEOUT_S` (12 s; his word: tighter) with a stage still running the fish
   apologizes ("no te escuché bien, ¿me lo repites?" during transcription, the lost-signal
   line after it), drops the turn and listens again at once. This is the first limit the
   local routes have. A stage that starts after a filler ran past the budget still gets
   3 s of its own, so a reply that was ready in time is not dropped for the filler. A
   transcript that comes back empty after a filler gets the same apology: the fish had
   promised an answer.
3. Each waiting stage runs in a worker thread; the turn loop's own thread keeps everything
   that is said and recorded about the turn (the debug hub counts a turn's fields only on
   that thread) and says the phrases through the speaker's lock. A stage a turn gave up on
   ends by itself and its result is discarded; the next turn waits for it before starting
   the same stage, so one model is never asked twice at once.
4. The reply follows the phrase: its voice is rendered without the speaker's lock while a
   filler may still play, then performed. A filler is never cut.
5. Only phrases already rendered are said; a missing one is skipped, never rendered in the
   middle of a turn. The phrases are entries of `CannedConfig.phrases` (`filler_first_*`,
   `filler_more_*`, `timeout_stt_*`), rendered at start like the others. Their register is
   a mix: mind reading, a call centre turned into mind reading, and plain ones. They were
   2.6 to 4.4 s each at first and are 0.9 to 1.9 s since the first turns on the board (his
   word, 2026-10-13): a 3 s phrase that started half a second before the transcript was
   ready held the reply back by 3 s.
6. The page gets the filler as a `speak` event marked `filler`: the mouth moves, the words
   are the fish's bubble, the sign stays on "Déjame pensar…" and a press stays refused. It
   is never the event replayed to a page that connects later.
7. `FISH_FILLER=false` removes the phrases and the limit; with the burble off too (point
   11), and always in text mode, every stage is called directly as before: no thread. `/debug` has a switch for it.

Amendment, 2026-10-13 (his idea, the same day): the fish also answers the release of the
button with a burble, as a voice assistant beeps when it stops listening.

8. A recording that passes the two checks (not a tap, not silence) is answered at once,
   while it is being transcribed, with one of four short synthesized bubble sounds
   (`fish_brain/burble.py`, written into the cache at first use; never the same twice
   running) and one chain of the tail. The mouth does not move: the fish is not talking.
   The close pulse still ends it, as after every performance. No burble for a reading (no
   recording), nor while something else has the speaker.
9. No burble therefore means "not heard": a press that recorded nothing is no longer
   indistinguishable from a slow turn.
10. With the burble as the acknowledgement the first filler moves from 1.5 s to 2.5 s, so a
    short local turn (about 2.3 s on Canary) is burble, then reply.
11. `FISH_BURBLE=false` removes it. With the fillers off and the burble on there is no turn
    budget. With both off every stage runs directly, as before either.

12. Until a filler has been said in a turn, each stage gets the whole delay of its own (his
    word, the same day): a transcript that arrives under the delay is not followed by a
    phrase only because the voice render crossed it. A slow stage after a quick one still
    gets its phrase, the delay later. Once a filler is said the chain goes on as in 1.

## Consequences

- After the burble the fish is silent for at most the 2.5 s a stage is given before the
  first phrase (again for each stage until a phrase is said), then 2 s at a time. A turn is
  given up at 12 s plus the phrase being said, plus the 3 s every stage is given from its
  own start.
- Offline on the board a recording over about 10 s (`small` on the window: 16 to 42 s; about
  10 s for a 7 s recording, which can still fit) ends in the apology, and its leftover work is waited for by the next turn inside that turn's
  budget. A longer budget or a shorter recording limit when offline is not decided.
- An LLM answer that arrives after the apology still enters the history, unspoken.
- A phrase from the page's text box or a badge read that takes the speaker between a filler
  and the reply still drops the reply, as it did before.
- `play_start` in the `[turn]` line now includes a filler that was still playing when the
  voice was ready; `fill=` is the time spent saying fillers; `stt=` and `llm=` stay the
  stage's own seconds.
- Loquendo's render now has a 30 s limit, so a voice that hangs ends and the next turn is
  not held by it. Canary and faster-whisper cannot be stopped: one that never returns holds
  every later turn to its budget until the service is restarted.
- Measured on the board the same day
  ([results](../results/2026-10-13-unoq-burble-and-fillers.md)): the burble 0.1 to 0.2 s
  after the end of the recording; a short turn is burble, then the reply 2.3 to 2.8 s after
  release, with no filler. Not measured yet: a filler since they were shortened, the
  apology, and the conductor's lateness while an abandoned transcription still uses the CPU.
- A burble still ends with the close pulse, which drives the closed mouth shut for 74 ms.
  Whether that stays once drivers are wired is his to decide on the real fish.
