# The Sorting Hat on the board, without motors — 2026-10-16

Host: the board `segunda` on the home Wi-Fi; core `arduino:zephyr` 0.55.2. fish_brain
`sorting-hat` `f06c87c` on the board (synced from the laptop; `.git/refs/heads/sorting-hat`
read there); Big_mouth `braintip` `6a7b2d5`. **Nothing wired to the header (owner's word):
level 3 for the firmware, level 5 without motors for the turns. Nothing here shows motion.**
Speaker (Jieli UACDemoV1.0) at 0.10 throughout, set by the owner's request.

Pass lines set before measuring: firmware check PASS and 122 of 122; every phrase renders;
each WAV-fed turn prints `[utt]`, `you>`, `fish>` and a `[turn]` line with `link=ok`; the page
answers 200 with the hat's title.

## Firmware with `DRIVER_STBY` on D9

| Step | Command | Result |
|---|---|---|
| Build | `deploy/unoq_fw.sh push && deploy/unoq_fw.sh compile` (laptop) | pushed `6a7b2d5` clean; built in 22 s; 27,372 bytes, sha256 `02dc699e…` |
| R4 build unchanged | `~/.platformio/penv/bin/pio run -e uno_r4_wifi`, then `sha256sum`, before and after the edit | `953f9f39…`, 50,292 bytes both times |
| Upload | `systemctl --user stop fish-brain`; `deploy/unoq_fw.sh upload --by assistant --note "tb6612 stby on d9; hat night"` | upload 6, 11 s; log row `6 2026-10-16T10:26:48+00:00 … assistant BigMouthQ normal 6a7b2d5 0` |
| Link | `tools/fw_check.py check --count 300 --release-router` (board) | PASS: 300 sent, 300 echoed, 300 answered, 0 lost; round trip 5.70 ms average, 47.99 ms maximum |
| Protocol | `tools/fw_check.py replay --drive --held --release-router` (board) | PASS: 122 of 122 lines answered as expected |

D9's voltage was not measured (no meter): it is the owner's step.

## The hat's set-up

| Step | Command | Result |
|---|---|---|
| Persona and mouth mode | drop-in `~/.config/systemd/user/fish-brain.service.d/50-hat.conf`: `Environment=FISH_PERSONA=hat FISH_MOUTH_MODE=gate`; `systemctl --user show -p Environment fish-brain` | both present; the owner's `echo.conf` untouched |
| Phrases | `FISH_PERSONA=hat FISH_MOUTH_MODE=gate .venv/bin/python -m fish_brain.app --prerender-canned`, service stopped | 22 of 22 `ok` in 6.9 s; new WAVs for `welcome`, `goodbye`, `timeout_stt_2` |
| Questions | `loq -o /tmp/hat_q{1,2,3}.wav -r 16000 -- "…"` (board) | mono, 16-bit, 16 kHz: 1.73, 1.49, 1.27 s |
| Bring-up | `tools/unoq_bringup.sh usb voice loop`, no `--volume` | PASS usb (port host, speaker, RedOctane), PASS voice 0.77 s; **FAIL loop: 0.000 during speech, 0.0000 before**. The loop records the default source, the XING WEI remote (id 67), not the RedOctane |
| Start | `systemctl --user start fish-brain` (welcome marker removed first) | `[fish] link=serial /dev/ttyHS1 stt=canary>groq llm=echo tts=loq …`; `/status` ready, listening, online, tls |

## Turns fed as WAV files (`POST /utterance` on the board's loopback)

| Mode | Input | Journal |
|---|---|---|
| echo | `hat_q1.wav` | `[utt] 16000 Hz 1.7 s`; `you> ¿Qué casa me toca a mí?`; `[turn] rec=2.0s stt=3.3s tts=0.5s play_start=0.5s burble=0.3s fill=1.1s link=ok`; `~/.cache/fish_brain/sounds` then held `hum_1..4-v1.wav` |
| luna (`/debug/set mode=llm`) | `hat_q2.wav` | `you> ¿cómo te llamas tú?`; `[llm] luna gpt-6-luna 6.04s`; `fish> Me llamo el Sombrero Seleccionador.`; `[turn] rec=2.0s stt=2.2s llm=6.0s tts=0.6s play_start=1.5s burble=0.1s fill=3.0s link=ok` |
| luna, reading | `POST /reading {"name":"Alejandra"}` | `[llm] luna gpt-6-luna 1.98s`; `[turn] read=tell llm=2.0s tts=2.3s play_start=2.4s link=ok` |
| echo | `hat_q3.wav` | `you> ¿Qué hora es?`; `[turn] rec=2.0s stt=2.8s tts=0.4s play_start=0.5s burble=0.2s fill=1.1s link=ok` |

The service was put back in echo mode after the reading.

## The page

| Check | Result |
|---|---|
| `curl -sk https://segunda.local:8724/`, `http://segunda.local:8723/` | 200 and 200; title `El Sombrero Adivino`; one `id="hat"` |
| `/img/neckRest_mouth0_tailRest.png` | 404 (the fish's sprites parked under `img/fish/`) |
| Headless Chromium on the board's page | the hat on its stool, flame green |

Not shown: the hat's mouth moving on the live page during a turn. Headless Chromium kept the
frame of the page load; the mouth path was seen moving only in `?pose=` stills on the laptop.

## End state

`fish-brain` enabled and active, echo mode (his drop-in), persona hat and gate mouth (the new
drop-in), sink at 0.10, `/status` listening and online.
