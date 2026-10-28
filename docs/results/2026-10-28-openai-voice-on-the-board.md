# The old hat's voice on the board: the canned phrases rendered — 2026-10-28

Host: the UNO Q `segunda` on the home Wi-Fi, fish_brain at `ce4cf24` plus the uncommitted
`FISH_TTS_RATE_FACTOR` change ([ADR 0023](../adr/0023-the-old-hat-voice.md)), `FISH_PERSONA=hat`
(unit drop-in), `.env`: `FISH_TTS_BACKEND=openai`, `FISH_TTS_VOICE=ash`, `FISH_TTS_RATE_FACTOR=0.88`.
Pass line, written first: every phrase of the hat's set renders once at start-up with no failure,
at 21120 Hz.

    systemctl --user restart fish-brain        # 06:59:51 UTC; start-up line: tts=openai
    # every 30 s: find ~/.cache/fish_brain/canned -name "*.wav" -newermt "06:59:50" ! -name "*.new.wav" | wc -l

| Measure | Result |
|---|---|
| Phrases rendered | 307 (the hat with the show on: show 143, fortune 141, fillers 14, the rest 9) |
| Time | 06:59:51 → 07:10:47, 10 min 56 s, about 2.1 s a phrase in the background thread |
| Failures | none in the journal |
| Header rate | 21120 Hz on the 300 newest files checked |
| Size | 133 MB on the board; a copy on the desktop in `~/fish_brain_canned/openai-ash-088/` (307 files, outside git) |

**PASS.** Not measured: a live turn's `tts=` time, how the four "Mmm" phrases sound
(`filler_first_1`, `show_greet_4`, `show_suspense_1`, `fortune_suspense_1`), the cost of the run.

## Second run: 2 semitones lower at 0.72 tempo through rubberband

Same host, the working tree on `f7b9c9f` plus the uncommitted `FISH_TTS_PITCH_ST` /
`FISH_TTS_TEMPO` change, `rubberband-cli` 3.3.0 from apt. `.env`: `FISH_TTS_RATE_FACTOR=0.88`
removed, `FISH_TTS_PITCH_ST=-2` and `FISH_TTS_TEMPO=0.72` added. Pass line, written first: every
phrase renders again under the new key with no failure, at 24000 Hz.

    rubberband -q -F -p-2 -T0.72 rb_in.wav rb_out.wav      # one line by hand first: 8.04 s in
    systemctl --user restart fish-brain                     # 22:06:15 UTC; start-up line: tts=openai
    # until stable: find ~/.cache/fish_brain/canned -name "*.wav" -newermt "2026-10-28 22:06" | wc -l

| Measure | Result |
|---|---|
| rubberband alone, one line | 0.84 s for an 8.04 s line (out 11.17 s, ratio 1.389) |
| Phrases rendered | 307 |
| Time | 22:06:15 → 22:23:53, 17 min 38 s, about 3.4 s a phrase (render and reshape; 1.3 s a phrase more than the first run, not split) |
| Failures | none in the journal |
| Header rate | 24000 Hz on all 307 |
| Audio | 66.9 min in all; longest `fortune_re_sueno_jugar`, 29.4 s |
| Size | 193 MB on the board; a copy on the desktop in `~/fish_brain_canned/openai-ash-p-2-t072/` (307 files, outside git) |

**PASS.** Not measured: the reshape's share of a live reply, how the set sounds on the speaker
(his ear).
