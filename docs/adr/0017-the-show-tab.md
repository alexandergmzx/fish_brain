# 0017 — The Show tab: the phone is the console (amends 0011)

**Status:** proposed · **Date:** 2026-10-26

## Context

At the fair the laptop was the only way to see what was wrong, and it was not ready. He wants
only the board and the phone at a show.

## Decision

The operator page opens on a **Show** tab (the default on a phone) with the visit's panel below:
go / no-go rows in plain Spanish (voice, speaker route, microphone, remote, motor link, network,
the visit's mode, lines ready, start at boot, records), each with what to do; a volume slider
for the live speaker; the scripted visit's mode (auto / siempre / apagado); the network pin
(automático / Wi-Fi propio); the phone speaker switch. The separate Visit tab is folded into it.
The actions are not motors and need no arm; motor tests, the speaker test and the restart stay
as in ADR 0009.

## Consequences

The switches still reset at a restart (only the network pin is a file).

## Amendment, 2026-10-26: English, his scene, hardware he marks

- The page is in English (he holds the phone). The summary never says "ready" before the
  board's state has arrived, and says when that state is older than 15 s.
- The hat sits in the study from `/face` (his sprites, window, candle, stool, sign); `/face`
  itself is unchanged.
- **Hardware marks**: USB speaker, USB microphone, remote button, motors, internet. A mark
  forces the fallback at once (speaker: Bluetooth, then the phone; microphone: the phone's;
  motors: muted; internet: the scripted visit) and stays across reboots until he clears it.
  Automatic detection still runs. `POST /debug/hw {part, failed}`.
- **Mode** is one control: Auto, Model, Script, Echo. When the model fails outside a scripted
  visit, the hat repeats the visitor (echo) instead of an error line.
- Measured on the board, 2026-10-26: with the USB speaker marked failed, one scripted visit
  played all 18 phrases on a stand-in phone page.
