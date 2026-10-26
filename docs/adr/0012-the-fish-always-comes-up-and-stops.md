# 0012 — The fish always comes up, and always stops

**Status:** proposed · **Date:** 2026-10-26

## Context

At the 2026-10-17 fair the fish had been stopped and disabled for a motor test and stayed off
for hours. A certificate that could not be loaded ended the process with 78, which the unit
does not restart, so there was no fish at all. The page started only after Loquendo warmed
and the canned phrases rendered. On 2026-10-13 a stop signal never reached the turn loop
(stuck in PortAudio) and no STOP was sent.

## Decision

1. A certificate that cannot be loaded leaves the page on http, with a warning and a hint;
   `/status` says `tls_error: certificate`. Never exit 78 for it.
2. The page starts before the voice warms.
3. A watcher thread on the signal wakeup fd sends STOP if the main thread has not reached its
   stop 1 s after SIGINT/SIGTERM, mutes the link, and exits `FISH_STOP_GRACE_S` (10 s) after
   the signal. The emergency STOP starts with a newline when another line may be half written;
   on the bridge transport it is a call, never raw bytes. The protocol is unchanged.
4. Motor tests never stop the fish: `deploy/unoq_setup.sh bench on` points it at a port that
   does not exist (persistent drop-in), `bench off` removes it. The page names a disabled fish
   and the bench.

## Alternatives

- **Keep 78 for certificates.** A restart does not fix them, but no fish is worse than no phone microphone.
- **`os._exit` from the signal handler.** It runs only when Python gets control back, so the same hang.

## Consequences

The grace and the 1 s check apply on the laptop too. The stuck-thread path is covered by unit
tests only so far. Evidence: [results](../results/2026-10-26-phase1-on-the-board.md).
