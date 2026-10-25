# 2026-10-25: the clean canned clips, backed up

Board `segunda`, tree `b44a540` (`sorting-hat`). Why: these 80 WAVs are the only Loquendo renders
known to be free of the licence warning (see
[2026-10-25-loquendo-licence.md](2026-10-25-loquendo-licence.md)). Nothing in the fish checks a
render today, and any phrase rendered inside the random-MAC window is cached for good.

Commands (board, then desktop):

```bash
cp -a --no-clobber ~/.cache/fish_brain/canned ~/.local/share/fish_brain/canned-clean-2026-10-16
find ~/.cache/fish_brain/canned -newermt '2026-10-16 23:49' -name '*.wav' | wc -l   # 0
scp -r arduino@segunda.local:.local/share/fish_brain/canned-clean-2026-10-16 ~/fish_brain_backups/segunda/2026-10-25/
```

Result: 80 files on the board and on the desktop, sha256 identical. Pass line: 80 of 80 with
matching hashes. Passed. Clip times are the file mtimes in UTC.

| File | Seconds | Rate | sha256 (12) | Rendered (UTC) |
|---|---|---|---|---|
| `filler_first_1-0595722c.wav` | 2.99 | 16000 | `83db9bb396c4` | 2026-10-16 19:25 |
| `filler_first_1-1ef8a502.wav` | 1.56 | 16000 | `e474940ff3aa` | 2026-10-13 18:14 |
| `filler_first_1-4b868ee5.wav` | 2.92 | 16000 | `eed4d0255f0d` | 2026-10-13 15:59 |
| `filler_first_1-e941633c.wav` | 3.21 | 16000 | `230c569e85e8` | 2026-10-16 23:48 |
| `filler_first_2-14972b8a.wav` | 2.77 | 16000 | `40a6e3fc799f` | 2026-10-13 15:59 |
| `filler_first_2-358ebd64.wav` | 1.63 | 16000 | `4510bfbe923e` | 2026-10-16 23:48 |
| `filler_first_2-7d378dba.wav` | 1.63 | 16000 | `4510bfbe923e` | 2026-10-16 19:25 |
| `filler_first_2-82b4a1ab.wav` | 0.98 | 16000 | `12931f5b843e` | 2026-10-13 18:14 |
| `filler_first_3-0647d778.wav` | 1.69 | 16000 | `6e08de454606` | 2026-10-16 23:48 |
| `filler_first_3-13112f63.wav` | 1.58 | 16000 | `18a44b5b0084` | 2026-10-13 18:14 |
| `filler_first_3-1bac855e.wav` | 4.40 | 16000 | `9d0e77435edb` | 2026-10-13 15:59 |
| `filler_first_3-1e1f14b8.wav` | 1.69 | 16000 | `6e08de454606` | 2026-10-16 19:25 |
| `filler_first_4-532a9d53.wav` | 2.19 | 16000 | `f73abb22d92d` | 2026-10-16 19:25 |
| `filler_first_4-57b6deb3.wav` | 1.61 | 16000 | `d5acb21b4d47` | 2026-10-13 18:14 |
| `filler_first_4-8b09c086.wav` | 3.01 | 16000 | `0e038e415634` | 2026-10-13 15:59 |
| `filler_first_4-ef4c4e84.wav` | 2.19 | 16000 | `f73abb22d92d` | 2026-10-16 23:48 |
| `filler_first_5-382e9088.wav` | 2.62 | 16000 | `d2939de873af` | 2026-10-13 15:59 |
| `filler_first_5-3eb72955.wav` | 1.49 | 16000 | `4e2acfbbfe6a` | 2026-10-16 23:48 |
| `filler_first_5-a565a64e.wav` | 1.80 | 16000 | `da762b700c04` | 2026-10-13 18:14 |
| `filler_first_5-c4c678b6.wav` | 1.49 | 16000 | `4e2acfbbfe6a` | 2026-10-16 19:25 |
| `filler_first_6-44f91e13.wav` | 0.92 | 16000 | `54829e31e3f0` | 2026-10-13 18:14 |
| `filler_first_6-8507c988.wav` | 3.23 | 16000 | `6bd35d57de1b` | 2026-10-13 15:59 |
| `filler_first_6-b9269ad4.wav` | 0.79 | 16000 | `9236f1f3a037` | 2026-10-16 19:25 |
| `filler_first_6-f29ed9b4.wav` | 0.79 | 16000 | `9236f1f3a037` | 2026-10-16 23:48 |
| `filler_first_7-2ccc7d0a.wav` | 3.43 | 16000 | `16a646e188c4` | 2026-10-13 15:59 |
| `filler_first_7-52e9ca67.wav` | 0.96 | 16000 | `410e995a4242` | 2026-10-13 18:14 |
| `filler_first_7-7ba7f864.wav` | 1.83 | 16000 | `340491c7199e` | 2026-10-16 23:48 |
| `filler_first_7-9406a490.wav` | 1.83 | 16000 | `340491c7199e` | 2026-10-16 19:25 |
| `filler_first_8-4e4d4ae6.wav` | 2.08 | 16000 | `89fc92cfad44` | 2026-10-16 23:48 |
| `filler_first_8-6d79a576.wav` | 1.72 | 16000 | `01b82f8ee67a` | 2026-10-13 18:14 |
| `filler_first_8-7fa3280e.wav` | 2.08 | 16000 | `89fc92cfad44` | 2026-10-16 19:25 |
| `filler_first_8-b840353b.wav` | 3.81 | 16000 | `fb5ca8d906f9` | 2026-10-13 15:59 |
| `filler_more_1-0777a32b.wav` | 1.39 | 16000 | `5be659d7dcf0` | 2026-10-13 18:14 |
| `filler_more_1-4331edb6.wav` | 2.66 | 16000 | `2399328f30cc` | 2026-10-13 15:59 |
| `filler_more_1-d4196b01.wav` | 1.96 | 16000 | `885a45e5ff7d` | 2026-10-16 23:48 |
| `filler_more_1-e558977a.wav` | 1.96 | 16000 | `885a45e5ff7d` | 2026-10-16 19:25 |
| `filler_more_2-0504e965.wav` | 1.76 | 16000 | `84c2accd5fd7` | 2026-10-13 18:14 |
| `filler_more_2-8c34ad36.wav` | 2.86 | 16000 | `3f4d6d432c93` | 2026-10-13 15:59 |
| `filler_more_2-d3ba8deb.wav` | 2.32 | 16000 | `e95b00b571a1` | 2026-10-16 23:48 |
| `filler_more_2-f2462fa4.wav` | 2.32 | 16000 | `e95b00b571a1` | 2026-10-16 19:25 |
| `filler_more_3-0eeacb3f.wav` | 3.86 | 16000 | `6ab120cb9e53` | 2026-10-13 15:59 |
| `filler_more_3-12785dc4.wav` | 1.37 | 16000 | `1a1988007ce4` | 2026-10-13 18:14 |
| `filler_more_3-d1c506a9.wav` | 1.37 | 16000 | `f5b97f62ed82` | 2026-10-16 19:25 |
| `filler_more_3-e45af431.wav` | 1.37 | 16000 | `f5b97f62ed82` | 2026-10-16 23:48 |
| `filler_more_4-0504e965.wav` | 1.76 | 16000 | `f5510fd213bc` | 2026-10-16 19:25 |
| `filler_more_4-1661bd75.wav` | 1.76 | 16000 | `f5510fd213bc` | 2026-10-16 23:48 |
| `filler_more_4-3f88dcc1.wav` | 3.51 | 16000 | `2941ff0123bc` | 2026-10-13 15:59 |
| `filler_more_4-a0f659fd.wav` | 1.43 | 16000 | `654d5a14da86` | 2026-10-13 18:14 |
| `filler_more_5-033c5ed8.wav` | 1.95 | 16000 | `0efdef93db64` | 2026-10-13 18:14 |
| `filler_more_5-63f174ba.wav` | 2.66 | 16000 | `240d2bc949f1` | 2026-10-16 23:48 |
| `filler_more_5-7bf3eade.wav` | 2.66 | 16000 | `240d2bc949f1` | 2026-10-16 19:25 |
| `filler_more_5-9fbe1ad1.wav` | 3.36 | 16000 | `f589e43fb40d` | 2026-10-13 15:59 |
| `filler_more_6-5d1a6121.wav` | 1.36 | 16000 | `62c50c79399c` | 2026-10-16 19:25 |
| `filler_more_6-6274b65e.wav` | 1.09 | 16000 | `ac20243f111d` | 2026-10-13 18:14 |
| `filler_more_6-6fdf3678.wav` | 1.36 | 16000 | `62c50c79399c` | 2026-10-16 23:48 |
| `filler_more_6-a409c61f.wav` | 2.80 | 16000 | `af48d3ee7916` | 2026-10-13 15:59 |
| `goodbye-1e3192b8.wav` | 2.92 | 16000 | `09ef13f2a258` | 2026-10-16 10:43 |
| `goodbye-73e99138.wav` | 2.44 | 16000 | `e6167156bac1` | 2026-10-11 17:07 |
| `goodbye-dc7e1f99.wav` | 2.97 | 16000 | `1b03a7481372` | 2026-10-12 00:43 |
| `goodbye-e3529be7.wav` | 2.92 | 16000 | `09ef13f2a258` | 2026-10-16 23:48 |
| `no_mic-3c5de595.wav` | 2.59 | 16000 | `cf2730bb42bf` | 2026-10-11 17:07 |
| `no_mic-ba19963e.wav` | 2.59 | 16000 | `cf2730bb42bf` | 2026-10-16 23:48 |
| `no_signal-65e07b45.wav` | 3.98 | 16000 | `d8404960f5be` | 2026-10-16 23:48 |
| `no_signal-bb3b4486.wav` | 3.98 | 16000 | `d8404960f5be` | 2026-10-11 17:07 |
| `reading_fail-879e4d8e.wav` | 3.83 | 16000 | `3837183bc56e` | 2026-10-12 00:43 |
| `reading_fail-a173e1fa.wav` | 3.83 | 16000 | `3837183bc56e` | 2026-10-16 23:48 |
| `reading_wait-79af9f8b.wav` | 3.97 | 16000 | `a0f47ff999aa` | 2026-10-16 23:48 |
| `reading_wait-b3f30500.wav` | 3.97 | 16000 | `a0f47ff999aa` | 2026-10-12 00:43 |
| `timeout_stt_1-7c2e5adf.wav` | 4.02 | 16000 | `c077bd73eacc` | 2026-10-16 23:48 |
| `timeout_stt_1-a3173e31.wav` | 3.47 | 16000 | `36c5d9816e54` | 2026-10-13 15:59 |
| `timeout_stt_1-f0fa04f2.wav` | 4.02 | 16000 | `c077bd73eacc` | 2026-10-16 19:25 |
| `timeout_stt_2-1bb69bee.wav` | 3.60 | 16000 | `6b1742810623` | 2026-10-16 23:48 |
| `timeout_stt_2-c9485538.wav` | 4.23 | 16000 | `cc5656e39622` | 2026-10-13 15:59 |
| `timeout_stt_2-d8cc1327.wav` | 3.60 | 16000 | `6b1742810623` | 2026-10-16 10:43 |
| `visit_greeting-0ca917f9.wav` | 5.74 | 16000 | `07ca755aefa5` | 2026-10-16 19:25 |
| `visit_greeting-4f4f72a0.wav` | 5.74 | 16000 | `07ca755aefa5` | 2026-10-16 23:48 |
| `welcome-3a2c6e9e.wav` | 7.07 | 16000 | `970d52fb7f27` | 2026-10-12 00:43 |
| `welcome-9eb1060a.wav` | 7.11 | 16000 | `a6126779ef40` | 2026-10-16 23:48 |
| `welcome-aad56e9e.wav` | 4.69 | 16000 | `d1d731a710e0` | 2026-10-11 17:07 |
| `welcome-dc77df07.wav` | 7.11 | 16000 | `a6126779ef40` | 2026-10-16 10:43 |
