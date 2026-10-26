# 0014 — Evidence that survives a pulled plug

**Status:** proposed · **Date:** 2026-10-26

## Context

The board's power is always pulled, it has no RTC, and journald kept about 4 boots and synced
every 5 min. Nothing of the fair or the house tests survived.

## Decision

1. A journald drop-in (`deploy/journald/90-fish.conf`, his step): 400 MB, synced every 15 s.
2. The fish's own record (`FISH_RECORD_DIR`, `fish_brain/record.py`): one JSON line per turn,
   page action, button press, voice change, start and stop, plus a beat with the board's facts.
   A writer thread fsyncs outside the debug hub's lock. One file per process, named by boot id
   and pid; the monotonic time, the wall time and whether the clock was synced on every line.
   `tools/records.py` makes the table.
3. His power logger from his plan, unchanged, runs from every boot as `fish-powerlog.service`.

## Alternatives

**Journald alone.** It still loses up to 15 s, and grep-ing it for a drill is fragile.

## Consequences

The records keep visitors' transcripts, as the journal already does; capped at 30 files and
100 MB.
