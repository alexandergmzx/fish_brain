# UNO Q: USB audio and Loquendo — 2026-10-10

Host: the board `segunda`, powered from a power bank through a USB-C hub with a newer cable
(with the first cable the port stayed in device mode and nothing on the hub was seen).
Commit `3f8bc0d`. Pass lines set beforehand: a warm render of a one-to-two sentence reply in
2 s or less; the microphone level during speech above the 0.005 silence threshold.

## Devices

| Device | Seen as |
|---|---|
| Speaker | Jieli "UACDemoV1.0" (`4c4a:4155`), playback only, stereo 48 kHz; also an input device with media keys |
| Microphone | RedOctane USB Microphone (`1430:474a`), mono 48 kHz; PipeWire source "RedOctane USB Microphone Mono" |

PipeWire made both the defaults without configuration.

## Loquendo under Hangover Wine 11.9

Phrase: "Hola, soy un pez parlante y estoy probando la bocina." (3.43 s of audio, 16 kHz mono).

| Run | Command | Time |
|---|---|---|
| One-shot | `loq --oneshot -o /tmp/loq_test.wav -- "<phrase>"` | 8.25 s |
| Daemon start | `loq --start` | 2.54 s |
| Warm 1 | `loq -o /tmp/loq_w1.wav -- "<phrase>"` | 0.96 s |
| Warm 2 | same | 0.75 s |
| Warm 3 | same | 0.75 s |

Pass (warm). Not done: many renders in a row, long phrases, behaviour after hours of uptime.

## Speaker to microphone

`pw-play` of the phrase while `pw-record --rate 16000 --channels 1` ran; level = RMS of the
recording, full scale 1.0.

| Speaker volume | Level during speech | Level before it |
|---|---|---|
| 40 % | about 0.002 | 0.001 |
| 100 % | mean 0.24, highest quarter-second 0.39 | 0.0007 |

Pass at 100 %. The positions of speaker and microphone were not controlled, so the gap
between the two rows is not only the volume setting. A person speaking was not measured.
The speaker was left at 100 %.
