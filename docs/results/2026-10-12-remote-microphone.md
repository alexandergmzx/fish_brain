# The remote as trigger and microphone — 2026-10-12

Host: the board `segunda`, `fish-brain.service` on commit `0b319fe` (code of `8db48f7` plus the
relay merge), home Wi-Fi, `stt=openai llm=luna tts=loq`, no display. The owner at the remote.
Level 5 without motors. Pass line: "a phrase spoken into the remote while its voice key is held is
transcribed and answered".

Set-up: `FISH_PTT_DEVICE=name:Consumer Control` (the remote's voice key is on the "Consumer
Control" node of the XING WEI 2.4 GHz composite device, `/dev/input/event4`; the headset jack
carries the same key code and is left out), `FISH_MIC_SOURCE=alsa_input.usb-XING_WEI_2.4G_USB_USB_Composite_Device-00.mono-fallback`
(PipeWire source "USB Composite Device Mono", set as the default with `wpctl set-default`),
`FISH_MIC_CAPTURE=host`. The RedOctane USB microphone is retired: it draws more current than the
board gives (owner, 2026-10-12).

| Step | Result |
|---|---|
| Start-up line | `ptt=web+evdev(1 device, KEY_VOICECOMMAND, hold)`; `[ptt] evdev: listening on /dev/input/event4 'XING WEI 2.4G USB USB Composite Device Consumer Control'` |
| One phrase into the remote, key held | `you> Ok, se debería de haber escuchado en este micrófono, entonces quiero que guardes esta.`; the fish answered from its speaker |
| Timing | [turn] rec=78.0s stt=9.3s llm=2.9s tts=1.3s play_start=1.4s link=ok |

Reading: the remote records cleanly through PipeWire at 16 kHz with no gain trouble; the page's
hold target drives the same recording. Pass.

Not measured: the remote's range and battery, the hotspot, a reading end to end with the remote's
answer ("sí").
