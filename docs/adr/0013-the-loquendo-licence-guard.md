# 0013 — The Loquendo licence guard

**Status:** proposed · **Date:** 2026-10-26

## Context

Loquendo binds its licence to a network adapter's MAC, and the Wine prefix's wineserver fixes
the adapter list when it starts. NetworkManager scanned with a random MAC on `wlan0`, and the
fish started Loquendo inside that window, so every render was "la licencia que posee no es
válida para este ordenador" instead of the phrase, and nothing noticed
([results](../results/2026-10-25-loquendo-licence.md)).

## Decision

1. `wlan0` scans with its own MAC (`deploy/nm/90-fish-wlan0-own-mac.conf`, his step).
2. At start-up the fish renders a probe phrase and compares its length with the clean length
   measured on the board (`FISH_LOQ_PROBE_S`). Off: stop the daemon, kill the prefix's
   wineserver, wait for the adapter's own MAC (`FISH_LOQ_MAC_IFACE`), start again, probe again.
   Still off: tainted. No live render, cached clips only, re-checked every minute.
3. A render as long as the warning (`FISH_LOQ_WARNING_S`) is probed again and deleted if the
   probe fails, so the warning is never cached.
4. No new licence codes, no copied or spoofed MAC addresses.

## Alternatives

- **Transcribe every render to look for the warning.** Too slow on the board for live replies.
- **Restart only the Loquendo daemon.** It does not clear the wineserver's adapter list.

## Consequences

Start-up takes one more render (about 1 s warm). The laptop is unchanged (`FISH_LOQ_PROBE_S=0`).
