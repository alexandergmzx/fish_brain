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
| [0007](0007-the-reading.md) | The reading: a badge photo becomes a name through a vision model on the board; the fish asks before telling the future; memory only | proposed | 2026-10-11 |
| [0008](0008-the-phone-is-the-fishs-face.md) | The phone is the fish's face in the visitor's hands; the remote is the control; the operator's controls are a sheet behind a held shell | proposed | 2026-10-12 |
| [0009](0009-a-debug-view-that-acts.md) | A desktop debug view fed by a hub in the process; it may act: tests, and armed for 60 s motor pulses and a restart | proposed | 2026-10-12 |
