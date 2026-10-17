# 2026-10-17: Loquendo's speed tag on the board

Commit `b44a540` (`sorting-hat`). Board `segunda`, `/home/arduino/.local/bin/loq` (Hangover
Wine, Jorge). Why: on the bench the hat's cam flapped "a bit slow" for the voice at PWM 238
(his words); a slower voice gives each phrase more flaps.

Command (one render per value, the same sentence):

```bash
~/.local/bin/loq -o /tmp/sp_$s.wav -- "\language=SpanishMx \speed=$s Hola. Dime tu nombre, por favor, y te diré tu casa."
```

| `\speed=` | WAV length | Against the default |
|---|---|---|
| none | 3.96 s | — |
| 50 | 3.96 s | same: 50 is the default |
| 40 | 4.04 s | +2 % |
| 30 | 4.49 s | +13 % |
| 20 | 5.08 s | +28 % |

Speed 30 and speed 20 were played to him on the USB speaker. He has not chosen one yet.

## How to apply it (not applied)

- The tag goes in the persona's Loquendo prefix: `FISH_LOQ_PREFIX="\language=SpanishMx \speed=30 "`.
  On the board that is a line in `~/.config/systemd/user/fish-brain.service.d/50-hat.conf`.
- The trailing space ends the tag.
- The canned phrases are cached by a hash that includes the prefix, so they are re-rendered at
  the new speed on the next start.
- Not measured:
  - whether `\speed` also changes the recorded hums (`\item=Hmh`);
  - how the hat's flap looks with the slower voice.

Also on the bench (2026-10-17): the same sentence at `FISH_MOUTH_OPEN_PWM=255` was run; his
verdict on the speed difference is not recorded.
