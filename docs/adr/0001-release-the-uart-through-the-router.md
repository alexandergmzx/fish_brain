# 0001 — Release the UART through the router

**Status:** accepted · **Date:** 2026-10-10

## Context

On the UNO Q the motor MCU is reached over `/dev/ttyHS1`, which the `arduino-router` daemon
opens at boot. fish_brain streams plain text lines at up to 33 per second and wants the port
to itself. The notes in [`UNOQ_BRIDGE_RPC_EXPLAINED.md`](../UNOQ_BRIDGE_RPC_EXPLAINED.md)
proposed stopping and masking the router.

Found on the board (router 0.10.0): the units cannot be masked, because they are real files in
`/etc/systemd/system`; and stopping the router resets the MCU and takes away the signal its
loader waits for, so the sketch never starts.

## Decision

fish_brain asks the router to let go of the port (`$/serial/close`), opens it with pyserial,
watches the router socket and asks again after a router restart, and hands the port back
(`$/serial/open`) when it closes. The router stays installed and running.

`FISH_SERIAL_TRANSPORT=bridge` is kept as a second transport: the same text lines sent as
MessagePack-RPC notifications to a method a Bridge sketch provides.

## Alternatives

- Router switched off with a drop-in plus a unit that raises GPIO line 70: works, more moving
  parts, breaks App Lab. Printed by `deploy/unoq_setup.sh router off` for whoever wants it.
- An FTDI adapter on D0/D1: needs hardware and a USB port.

## Consequences

- While the port is released, App Lab and Bridge sketches do not work.
- A router restart is invisible to a serial writer; the socket watchdog is what notices it.
- From router 0.11 the socket needs membership of the `arduino-router` group.
