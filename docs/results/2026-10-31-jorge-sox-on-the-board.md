# Jorge through sox in the stone room: the canned phrases on the board — 2026-10-31

Host: the UNO Q `segunda` on the home Wi-Fi. fish_brain was at `46545f7` plus the uncommitted
`FISH_TTS_FORMANTS` / `FISH_TTS_ROOM` change ([ADR 0028](../adr/0028-jorge-in-a-stone-room.md)).
The tree synced with `deploy/unoq_setup.sh sync` also carried the uncommitted fortune changes of
ADR 0026 and 0027, so the fortune set is ADR 0027's. sox 14.4 came from apt.

`.env` was edited by key, never read. It was backed up first to `~/env.backup-2026-10-31-ash`
(0600):
- `FISH_TTS_BACKEND=loq`
- `FISH_TTS_PITCH_ST=-2`, kept
- `FISH_TTS_FORMANTS=shift` and `FISH_TTS_ROOM=stone`, added
- `FISH_TTS_TEMPO`, removed

The guard lines `FISH_LOQ_PROBE_S`, `FISH_LOQ_WARNING_S` and `FISH_LOQ_MAC_IFACE` were present.

Pass line, written first: every phrase renders under the new key with no failure, and none of
them is the licence warning.

    systemctl --user restart fish-brain                        # 06:42:52 UTC
    # every 60 s: find ~/.cache/fish_brain/canned -name "*.wav" -newermt "2026-10-31 06:42:50" | wc -l

| Measure | Result |
|---|---|
| Licence probe | `[voice] CLEAN (3.01 s, clean 3.01 s)` at 06:42:54 |
| Phrases rendered | 349: show 143, fortune 183, fillers 14, the rest 9 |
| Time | First file 06:42:55, last 06:50:01: 7 min 6 s, about 1.2 s a phrase in the background thread |
| Count by minute | 27, 80, 142, 188, 222, 272, 314, 349, 349 |
| Failures | No line with fail, error or traceback in the journal since the restart |
| Rate | 16000 Hz on all 349 |
| Audio | 32.0 min in all. The ash set at 0.72 was 66.9 min |
| Near the warning's 4.52 s | 6 files within 0.06 s: `show_future_G_1`, `show_re_A2_volcan`, `show_nose_4`, `show_pref_S_1`, `show_re_A3_libro`, `show_re_C3_linterna`. Transcribed with faster-whisper `small`: all six are their own phrases |
| Size | 60 MB. A copy on the desktop is in `~/fish_brain_canned/jorge-p-2-stone/` (349 files, outside git) |

**PASS.**

His ear (2026-10-31, `welcome` and `fortune_vision_1` from the new cache as MP3): "they are good".

Not measured:
- a live turn's `tts=`;
- the set on the board's speaker;
- the mouth on the reverb tail (level 4).
