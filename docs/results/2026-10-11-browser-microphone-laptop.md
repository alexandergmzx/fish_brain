# The browser's microphone from the laptop's Chrome, over https — 2026-10-11

Host: the board `segunda` on the home Wi-Fi, `fish-brain.service` on commit `28ca0f8`, the board's
`.env` with the three `FISH_VIZ_TLS_*` lines (the self-signed certificate made by
`deploy/unoq_setup.sh tls 192.168.1.114`), the token set. Client: Chrome on the Linux Mint laptop at
`https://192.168.1.114:8724/?console=1&mic=browser&token=…`, the certificate warning accepted
(Advanced → Proceed). Level 5 without motors, the owner at the laptop. Pass line: "the microphone
button appears, a held phrase is uploaded and answered, with `[utt]` and `[turn]` lines".

| Step | Result |
|---|---|
| Page over https from the laptop | `/status` 200, `tls: true`; the page opened after Proceed |
| Plain https URL without `mic=browser` | no microphone button (the board was on `host`); with `&mic=browser` the button appeared and Chrome granted the microphone |
| One held phrase | `[utt] 16000 Hz 5.9 s 189228 B upload=0.01s`; `[turn] rec=5.4s stt=1.8s llm=1.8s tts=1.2s play_start=1.3s link=ok`; the fish answered from its speaker |
| `FISH_MIC_CAPTURE=browser` in the board's `.env`, restart | `ptt=web+browser-mic`; `/status` `mic_capture: browser` |

Reading: the whole chain phone-side recording → WAV upload → cloud STT → Luna → Loquendo runs at the
same speed as a board-microphone turn (`stt` 1.8 s against 1.3 to 1.9 s measured before). Pass.

Not measured: the Android phone (its Chrome, the click-through, the worklet's sample rate), the
hotspot, the badge photo from a camera, the question path ("¿Tú eres X?" then "sí").
