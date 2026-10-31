# 0031 — Bluetooth speakers from the page

**Status:** proposed · **Date:** 2026-10-31 · Amends [0016](0016-speaker-and-microphone-routes.md),
[0017](0017-the-show-tab.md), [0024](0024-the-fortunes-ticket.md)

## Context

His word, 2026-10-31: at a party the music may be too loud for the USB speaker, so any Bluetooth
speaker or headphones must connect from a user interface. The route `bluez_output.*` existed since
ADR 0016, but pairing was a shell step, and a connected speaker changed nothing because USB comes
first in `FISH_AUDIO_ROUTES`. The board's facts and how other interfaces do this:
[results](../results/2026-10-31-bluetooth-board-facts.md).

## Decision

1. **A block in Settings**, hidden unless `FISH_BLUETOOTH` is set (empty = off, `mock`, `on`): My
   speakers, Find speakers, Nearby while searching. One tap on a row pairs, trusts, connects, waits
   for a sink and chooses it. Forget sits behind More and a second tap. Test is a separate press.
2. **Ready means a sink exists**, because `Connect` succeeds when any one profile connects.
3. **The chosen speaker's route goes ahead of `FISH_AUDIO_ROUTES`** while its sink exists; a lost
   one falls back to the next route, says so on every tab and is retried. The choice and a mouth
   delay per address live in `~/.local/state/fish_brain/bt.json` and survive a reboot.
4. **`dbus-fast`** (the `unoq` extra) on one thread with its own loop. The agent and the search die
   with their connection, so `bluetoothctl` as a subprocess is the wrong shape; it stays for
   diagnostics. A worker thread owns the slow calls, so a request never waits on the radio.
5. **The board stays hidden.** Agent `DisplayYesNo`, never the default agent, answering only for
   the device being paired from the page. `Trusted` is set straight after `Pair`.
6. **The printer is never listed** (its address, class 0x06, icon) and Forget refuses it on the
   server. A search is refused during a turn or a ticket and stops if one starts.
7. **`51-fish.conf`:** seat monitoring off, so Bluetooth audio stops depending on LightDM's session;
   headset autoswitch off, roles left at their default.
8. **A late non-zero exit from `pw-play` is a phrase not heard**, on every route, and the speaker
   test reports it. The phrase is not replayed.

## Rejected

| Option | Why not |
|---|---|
| The USB mark as "use Bluetooth" | It means "failed", arms the phone and survives reboots |
| A codec or profile picker | The board has no aac or aptx: a cheap speaker gets SBC |
| Making the board discoverable, as GNOME and Android do | With an empty token, only pairings from the page should exist |
| `session.suspend-timeout-seconds = 0` now | Only with evidence: it may keep silent A2DP on the air during uploads and tickets |

## Consequences

- The laptop is unchanged: no thread, no import, no block.
- With an empty token anyone on the hotspot can pair, the same exposure as the rest of `/debug`.
- The 200 ms mouth delay and every timer are estimates until
  `docs/results/` says otherwise, and so is the map from BlueZ's errors to the sentences.
- A speaker held by a phone, one that powers off on silence, and a dead sink that still looks
  connected are named or fallen back from, not solved. Coexistence with a 2.4 GHz hotspot is not
  measured.
- Amends 0016 (pairing is his press on the page), 0017 (`bt.json` is a saved file), 0024 (the MP210
  is paired on the board; its own pairing stays in the shell).
