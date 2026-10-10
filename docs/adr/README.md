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
