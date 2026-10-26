# 0016 — Speaker and microphone routes

**Status:** proposed · **Date:** 2026-10-26

## Context

At the fair the hub lost power and the USB speaker, the remote and its microphone with it. When
a speaker goes away PipeWire moves the stream to the board's onboard codec, which has no jack,
so the hat would play into silence; a stuck PortAudio call blocks every later sounddevice call;
on 2026-10-13 a microphone that never started froze the fish.

## Decision

1. `FISH_AUDIO_ROUTES` (board: `alsa_output.usb-*,bluez_output.*,phone`): each phrase goes to
   the first route that is there. Sinks are found by PipeWire node name and played with
   `pw-play --target <node>` with no fallback, a subprocess with a time limit. `phone` is the
   operator page (armed by a tap; it plays the phrase and says when it started). A failing route
   cools for 30 s and the same phrase goes to the next. No route: silence and a still hat.
2. The motors follow the route's real start plus its delay (`FISH_AUDIO_DELAY_MS`).
3. WirePlumber never offers the onboard codec's sink or source (`deploy/wireplumber/51-fish.conf`).
4. `FISH_MIC_BACKEND=pw-record`: the board records through a subprocess; no audio within 3 s is
   a microphone error, never a hang. `FISH_MIC_CAPTURE=auto`: after two takes of exact zeros
   (or the source gone) the remote's presses record on a phone that has its microphone on.

## Alternatives

**sounddevice with time limits:** a stuck PortAudio call cannot be cleared inside the process.

## Consequences

The laptop is unchanged (no routes, sounddevice). The phone route depends on the page staying
open with its sound unlocked. Bluetooth works once a speaker is paired (his step).
