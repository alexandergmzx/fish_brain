# 2026-10-31 — Bluetooth speakers on the board: the manager before any speaker

Board `segunda`, branch `bluetooth-speaker`, commit `8e8ae6a` plus `tools/bt_check.py`; no fish body
involved. The block is still off in the running fish (`FISH_BLUETOOTH` not set). **Nothing was
paired and no sound was played over Bluetooth.** Added as the windows run.

Pass lines decided before: the fish and WirePlumber come back with the fragment; the manager reads
BlueZ; a search ends by itself and leaves the adapter not discovering and not discoverable; the
MP210 is not listed.

## Installed

```
rsync -a --checksum (no --delete; excludes as deploy/unoq_setup.sh, and .git) from the worktree
.venv/bin/python -m pip install "dbus-fast>=2.44,<6"
deploy/unoq_setup.sh service
```

`deploy/unoq_setup.sh sync` was not used: a dry run from the worktree would have deleted the board's
`rehearsals/` and replaced its `.git` directory with the worktree's `.git` file.

| Check | Result | Command |
|---|---|---|
| Service and WirePlumber after the fragment | Both active; USB speaker and XING WEI microphone back as defaults | `systemctl --user is-active`, `wpctl status` |
| A2DP endpoints | 11 registered again in the last minute | `journalctl -u bluetooth --since "-1 min"` |
| Endpoint with the switch off | `503 bluetooth off` | `POST /debug/bluetooth {"do":"view"}` |

## The manager against the real BlueZ

`PYTHONPATH=. .venv/bin/python tools/bt_check.py`, 12 s search, with the fish running:

| Item | Result |
|---|---|
| Bus, adapter | alive, powered, no problem |
| `RegisterAgent` | 0.004 s |
| Search | Ended by itself; `Discovering: no`, `Discoverable: no` afterwards |
| Lists | mine 0, nearby 1 (a neighbour's "Billboard Soundbar", shown as headphones), others 0 |
| MP210 | Not listed |

Pass on all lines. The soundbar's "headphones" comes from BlueZ's icon, which follows the class the
device reports; only the label is wrong and the row still works the same.

## Not run

Pairing, connecting, a sink's real name, any sound, latency, idle clipping, a pulled sink, reconnect,
headphones, a speaker held by a phone, the seat with LightDM stopped, coexistence on the hotspot.
