# 2026-10-27 — `gpt-transcribe` first on the board: the remote's takes and the route

ADR 0020 on the board `segunda`, commit `b541547`, home Wi-Fi (held on the main router), the
board on wall power with the hub. Two runs, both while `fish-brain` was running (they only
call the cloud or load a second Canary; nothing played and no turn ran).

## The bench on the remote's microphone

The 63 takes he recorded through the XING WEI remote on 2026-10-13
(`~/stt_bench/clips/sesion/remoto`), one run each, no `--gap`:

```bash
cd ~/fish_brain && .venv/bin/python tools/stt_bench.py run --clips ~/stt_bench/clips/sesion/remoto \
    --runs 1 --md --cand cloud:profile=openai > ~/stt_bench/out8/rem-openai.md
```

| Route, remote's takes | Median s | Worst s | Word errors | Source |
|---|---|---|---|---|
| `gpt-transcribe` (`openai`) | 0.72 | 1.74 | 6.0 % | this file |
| Groq turbo | 0.41 | 1.81 | 14.0 % | `~/stt_bench/out6/rem-groq-turbo.md`, 2026-10-13 |

By take length, `gpt-transcribe`:

| 0-3 s | 3-6 s | 6-10 s | 10-20 s | 20+ s |
|---|---|---|---|---|
| 0.72 s, 9 % (n=46) | 0.80 s, 0 % (n=8) | 0.82 s, 9 % (n=3) | 1.13 s, 5 % (n=3) | 1.51 s, 5 % (n=3) |

The bench's first call (a fresh process, no warm-up) took 7.39 s; it is not in the table.
The 25 s takes came back in 1.5 to 2.0 s. The worst misses were names: "Lexi tú" for "Alex,
¿y tú?", "Alexito", "Nevarte" for "Narvarte".

## The fish's own route

`stt.CanaryTranscriber` built from the board's environment with `online_first=("openai",)`,
`ensure_loaded()` first (19.1 s: Canary's model and the client), then four clips of the same
folder, then the list emptied:

| Clip | Length | Seconds | `last` |
|---|---|---|---|
| `voz10_1` | 2.3 s | 3.39 (the first call) | `openai`, `online first` |
| `voz12_1` | 3.1 s | 0.82 | `openai`, `online first` |
| `voz20_2` | 11.4 s | 1.12 | `openai`, `online first` (over 6 s: not sent to Groq or the local model) |
| `voz10_1` | 2.3 s | 0.81 | `openai`, `online first` |
| `voz10_1`, online first off | 2.3 s | 3.48 | `canary`, `canary` |

The first call after the warm-up took 3.39 s, under the 4 s limit but close to it; the
cold call without a warm-up (7.39 s above) would fall to Canary.

## The running fish

The service was restarted on `b541547` at 17:52:30 UTC; the board's `.env` has no
`FISH_STT_ONLINE` yet, so the start-up line read `stt=canary>groq`. Switches →
`stt_online=openai` and `silence_end_s=10` through `POST /debug/set` turned both on
(`[debug] speech-to-text online first: off -> openai`); they last until the next restart.

## Not measured

- A real turn on the online route (no one spoke to the fish).
- The fall-back with the data cut mid-hold.
- The silence end from the remote and from the phone, and a 30 s hold online and offline.
- The phone's level after Chrome's gain control.
