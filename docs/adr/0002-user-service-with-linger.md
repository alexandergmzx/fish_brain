# 0002 — A systemd user service with linger

**Status:** accepted · **Date:** 2026-10-10

## Context

The board must start the fish at power-on with no login. Its image runs PipeWire and
WirePlumber as per-user services, and fish_brain prefers PipeWire sources and sinks because
their names survive reboots and replugging.

## Decision

`deploy/fish-brain.service` is a user unit for `arduino`, started at boot through
`loginctl enable-linger arduino`. It restarts always, stops with SIGINT so the goodbye line
and `STOP` are sent, and does not restart on exit status 78 (nothing to trigger a turn).

## Alternatives

- A system unit on raw ALSA devices: can order after the network, but competes with PipeWire
  for the USB sound devices and needs an `~/.asoundrc`.

## Consequences

- A user unit cannot wait for the network, so the program handles being offline itself.
- Group changes for `arduino` need a reboot (or a restart of `user@1000`) to reach the service.
