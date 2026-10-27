# 2026-10-27 — What `GET /debug/state` costs on the board, before and after the device table

ADR 0021, point 6. Board `segunda` on wall power with the hub (speaker, remote, Ethernet
adapter on USB), home Wi-Fi, no page open on a phone, the same four hardware marks (mic,
motors, remote, speaker) in both runs. Ten requests a second apart, on the board itself:

```bash
for i in $(seq 10); do curl -s -o /dev/null -w "%{time_total}\n" http://127.0.0.1:8723/debug/state; sleep 1; done
```

| Code | Started | Ten requests, s | Median s |
|---|---|---|---|
| `485f3d9` (before the table) | 17:37:46 UTC | 1.398, 0.957, 0.959, 0.973, 0.980, 1.005, 0.989, 1.015, 1.024, 1.014 | 0.99 |
| `b541547` (after C5) | 17:52:30 UTC | 0.133, 0.060, 0.063, 0.059, 0.060, 0.060, 0.083, 0.062, 0.059, 0.094 | 0.06 |

The state's own `timing` after the change, one build, in milliseconds:

| Section | ms |
|---|---|
| `system` | 23.2 |
| `checks` | 11.4 |
| `sound` | 5.1 |
| `version` | 4.1 |
| `config` | 2.7 |
| `show_tab` | 2.1 |
| `page` | 1.2 |
| `service` | 0.8 |
| `devices` | 0.6 |
| `canned` | 0.5 |
| the other twelve | 0.0 to 0.3 each |
| **total** | **53.2** |

The before run had no `timing` (it came with C1), so the split of the old second is not
measured; the plan's suspects were the volume read through `wpctl`, one glob per canned phrase
and `config.py` parsed again per build, all three cached since C1. The target in ADR 0021 was
the 0.5 s of 2026-10-26.
