# UNO Q: the reading act and an uploaded recording under the service — 2026-10-11

Host: the board `segunda` on the home Wi-Fi, `fish-brain.service` restarted on commit `c9d8b95`
(synced), the board's `.env` as before (`stt=openai llm=luna tts=loq`, no `FISH_VIZ_TLS_*`,
`FISH_MIC_CAPTURE` unset = host). MCU link live, no drivers attached. Level 5 without motors; the
requests were sent from the board itself over loopback (`FISH_VIZ_TRUST_LOCAL`), not from a phone.
Pass line, set before: "a typed name produces a spoken prophecy with a `[turn] read=` line; an
uploaded speech WAV produces a transcript, a reply and a `[turn] rec=` line; no `fish_in_*` file left".

| Step | Command (on the board) | Result |
|---|---|---|
| Restart | `systemctl --user restart fish-brain` | `active`; `ptt=web+evdev(…)`; the two new canned phrases and the tamer welcome and goodbye rendered with Loquendo (cache: `reading_wait`, `reading_fail`, a second `welcome` and `goodbye`) |
| Certificate | `deploy/unoq_setup.sh tls 192.168.1.114` | `~/.config/fish_brain/tls/segunda.{crt,key}`, SAN `segunda.local, localhost, 127.0.0.1, 192.168.1.114`, 820 days; the `.env` lines printed, not applied |
| Reading, typed name | `curl -X POST -d '{"name":"María José García"}' http://127.0.0.1:8723/reading` | `{"ok": true, "name": "María José García"}`; `[llm] luna 7.24s`; `fish> (lectura)`; the prophecy spoken; `[turn] read=tell llm=7.2s tts=2.7s play_start=2.8s link=ok` |
| Upload while speaking | the WAV below during the prophecy | `409 {"ok": false, "busy": true}` (the guard) |
| Upload while listening | `curl -X POST -H 'Content-Type: audio/wav' -H 'X-Fish-Hold-Ms: 3000' --data-binary @welcome-….wav http://127.0.0.1:8723/utterance` (the cached welcome, 7.1 s of Loquendo speech) | `{"ok": true}`; `[utt] 16000 Hz 7.1 s 226408 B`; `you> Hola, soy el pez que todo lo sabe…`; `fish> ¡Hola, pez sabelotodo! ¿Qué predices para mí hoy?`; `[turn] rec=3.0s stt=1.9s llm=1.5s tts=0.8s play_start=0.9s link=ok`; `/tmp/fish_in_*`: none left |

Reading: the reading turn and the upload turn run through the normal speak path (mouth track,
gestures, close pulse) and the `[turn]` line; the inbox refuses an upload while the fish speaks.
`llm=7.2s` for the four-sentence prophecy against 1.5 s for a one-line reply: the prophecy is the
slow part, Loquendo takes 2.7 s to render it. Pass.

Not measured: anything from the phone (the https page, the microphone gate, a badge photo through
the camera), the hotspot, `FISH_SAY_ADDRESS`, the question path ("¿Tú eres X?" then the spoken
"sí"), a real badge.
