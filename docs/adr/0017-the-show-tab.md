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
