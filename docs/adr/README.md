# Decisions

One non-trivial decision per record, kept short. A record is changed while it is `proposed`;
once `accepted` it gets a dated amendment or is replaced by a new record.

Format: **Status** (proposed, accepted, replaced by NNNN) · **Date** · **Context** ·
**Decision** · **Alternatives** · **Consequences**.

| No. | Decision | Status | Date |
|---|---|---|---|
| [0001](0001-release-the-uart-through-the-router.md) | On the UNO Q, ask the router to release `/dev/ttyHS1`; Bridge RPC is the alternative | accepted | 2026-10-10 |
| [0002](0002-user-service-with-linger.md) | Run on the board as a systemd user service with linger | accepted | 2026-10-10 |
| [0003](0003-speech-backends-behind-env.md) | Speech-to-text and text-to-speech backends are chosen by environment | accepted | 2026-10-10 |
| [0004](0004-llm-profiles.md) | LLM profiles: Groq GPT-OSS and GPT-6 Luna | accepted | 2026-10-10 |
| [0005](0005-kiosk-on-the-board-display.md) | The page on the board's own display in a bare X session; the screen starts a turn at the fair | replaced by 0006 | 2026-10-11 |
| [0006](0006-the-phone-is-the-interface.md) | The operator's phone is the fair's interface: trigger, microphone and badge camera over HTTPS; the board's display parked | proposed | 2026-10-11 |
| [0007](0007-the-reading.md) | The reading: a badge photo becomes a name through a vision model on the board; the fish asks before telling the future; memory only | proposed; superseded on the page 2026-10-27 (0019) | 2026-10-11 |
| [0008](0008-the-phone-is-the-fishs-face.md) | The phone is the fish's face in the visitor's hands; the remote is the control; the operator's controls are a sheet behind a held shell | replaced by 0011 | 2026-10-12 |
| [0009](0009-a-debug-view-that-acts.md) | A desktop debug view fed by a hub in the process; it may act: tests, and armed for 60 s motor pulses and a restart | proposed | 2026-10-12 |
| [0010](0010-fillers-while-the-fish-thinks.md) | The fish says short cached phrases while a turn waits and drops a turn at 12 s with an apology; waiting stages run in workers, the loop's thread talks | proposed | 2026-10-13 |
| [0011](0011-one-page-for-the-operator.md) | One page at `/` for the operator's phone: the debug view with the drawn hat showing what the fish does, the visit's tools and a hold-to-talk; the old face at `/face` until after the fair | proposed | 2026-10-16 |
| [0012](0012-the-fish-always-comes-up-and-stops.md) | A bad certificate leaves the page on http; the page before the voice; a watcher sends STOP when the main thread is stuck; motor tests never stop the fish (bench mode) | proposed | 2026-10-26 |
| [0013](0013-the-loquendo-licence-guard.md) | `wlan0` scans with its own MAC; a start-up probe catches Loquendo's licence warning, restarts the voice on a fresh wineserver, else no live render; the warning is never cached | proposed | 2026-10-26 |
| [0014](0014-evidence-that-survives-a-pulled-plug.md) | A journald drop-in, the fish's own fsynced record, and his power logger from every boot | proposed | 2026-10-26 |
| [0015](0015-the-scripted-visit.md) | `FISH_SHOW`: a scripted visit with no model and no live voice: the cross questions, a deterministic house, re-ask then move on, operator buttons, no error line | proposed | 2026-10-26 |
| [0016](0016-speaker-and-microphone-routes.md) | Speaker routes USB, Bluetooth, the phone, by PipeWire node, never the onboard codec; motors follow each route's start; a pw-record capture that cannot hang; the phone's microphone when the board's is dead | proposed | 2026-10-26 |
| [0017](0017-the-show-tab.md) | The Show tab: go / no-go rows, volume, the visit's mode, the network pin, the phone speaker; the Visit tab folded into it (amends 0011) | proposed | 2026-10-26 |
| [0018](0018-claude-through-its-own-sdk.md) | Claude through the Anthropic SDK: profiles `claude` and `claude-sonnet`, and the reading's first reader when its key is set; the chat default and a fish without the key are unchanged | proposed | 2026-10-26 |
| [0019](0019-the-fortune-act.md) | The fortune act: a second act for adults from the Visit tab, every answer by voice with one re-ask, day and month never the year, the open dream and the mentalist lines, the tarot as data, the cup, the animal, the moon and a magic word; the reading from the clips or from the model; the adult register and the place | proposed | 2026-10-27 |
| [0020](0020-online-first-speech-and-the-uncut-hold.md) | Every recording to `gpt-transcribe` first while online, Canary offline, the routes read at every recording; no act clamps the hold (`FISH_PTT_MAX_S` alone); a hold ends after `FISH_PTT_SILENCE_END_S` of silence | proposed | 2026-10-27 |
| [0021](0021-one-device-table.md) | One device table (`devices.py`): whether each part is there, marked, dead or in use, decided once and read by the Status rows, chips, hints, checks and the acts; one connection record and one sentence per refusal on the page | proposed | 2026-10-27 |
| [0022](0022-the-visit-for-adults.md) | The visit for adults: cues last the visit and its fortune, the adult cue set and register, a verdict from the visitor with no ingredient bank, the fortune's fixes, Claude Haiku thinking at effort low | proposed | 2026-10-27 |
| [0023](0023-the-old-hat-voice.md) | The old hat's voice: `gpt-4o-mini-tts` ash with the old-hat instruction replaces Loquendo on the board, reshaped 2 semitones lower at 0.72 tempo through `rubberband` (first at `FISH_TTS_RATE_FACTOR=0.88`); canned phrases rendered once and kept; until 2027-01-06 | replaced by 0028 | 2026-10-28 |
| [0024](0024-the-fortunes-ticket.md) | The fortune's ticket: the reading printed on the MP210 over the stdlib RFCOMM socket, handed over as the closing line starts, one an act, connect per ticket, no resend, Reprint on the Visit tab; the printer row warns at worst; `FISH_PRINTER` empty = off | proposed | 2026-10-28 |
| [0025](0025-no-censoring.md) | No censoring: no word list, no forbidden topics in the model's rules; only length and privacy limits stay | proposed | 2026-10-29 |
| [0026](0026-the-reading-roasts.md) | The reading roasts: the wish replaces the animal, the card is a question (named from his deck, or drawn by the hat on a yes), short beats in model mode with the meaning read once, seeds from the code (visión, forma, hoy, the last openings), the roast rules, the reading without thinking | proposed | 2026-10-29 |
| [0027](0027-the-oracles-voice.md) | The oracle's voice: the reading as an old sorcerer's omen over the roast's structure (the head as the instrument, emblems, one equivocation, a warning, a small rite, no percentages); the model's call and the reading's wait at 15 s, one more suspense line at 7 s | proposed | 2026-10-29 |
| [0028](0028-jorge-in-a-stone-room.md) | The hat's voice: Loquendo Jorge 2 semitones lower with the formants moved too, in a stone room, as one sox pass after the render in fish_brain (`FISH_TTS_FORMANTS=shift`, `FISH_TTS_ROOM=stone`); `loq_winer` unchanged | proposed | 2026-10-31 |
