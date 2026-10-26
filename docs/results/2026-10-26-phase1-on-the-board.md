# 2026-10-26: the fish always comes up, stops, never speaks the licence warning, leaves a record

Board `segunda`, home IZZI, `sorting-hat` up to `8c0cee0`, synced with `deploy/unoq_setup.sh sync`.
The hat's 3xAA pack was disconnected by him for every run (no motion possible). Level 5.

| Check | Command | Pass line | Result |
|---|---|---|---|
| Voice guard at start-up | `systemctl --user restart fish-brain` | `[voice] CLEAN` | `[voice] CLEAN (3.01 s, clean 3.01 s)`; `/status` voice `clean` |
| Recovery and tainted state | temporary drop-in `FISH_LOQ_PROBE_S=6.0` | recovery runs, then tainted, nothing cached | recovery in 4 s, `[voice] TAINTED`, 0 clips cached; removed, `CLEAN` again |
| Certificate missing (T1) | temporary drop-in `FISH_VIZ_TLS_CERT=/nonexistent.crt` | the fish runs, page on http | active; `/status` `tls: false, tls_error: certificate`; the warning line; removed, https back |
| Page before the voice | restart, then poll `/status` | page answers before the voice is ready | page 6.4 s after the restart, `ready` 11.1 s |
| Bench mode | `deploy/unoq_setup.sh bench on`, then `off` | the fish keeps running, no motors | `link=serial /dev/null-no-motors (degraded)`, BENCH hint on the page, enabled and active; `off` back to `/dev/ttyHS1` |
| Power logger | `deploy/unoq_setup.sh service` | a line every 10 s | `~/power_soak.csv`: `2026-10-26T00:23:53+00:00,19149.97,10,5` ... |
| Record survives a hard kill | `kill -9` the fish's main pid | lines before the kill are on disk | start and voice lines present, "No end line"; systemd restarted it into a new file |
| Stop path (desktop, mock link) | SIGINT to a `--dry-run --text --tts openai --echo` fish | STOP at once and at exit | `TX  STOP` before the goodbye and after it, exit 0 in 2.5 s |

Not run yet:

- **S1:** STOP with the main thread really stuck on the board. Only the unit tests cover it.
- **R1:** a real pulled plug.
- **The licence pass line:** a cold boot with no known Wi-Fi.
