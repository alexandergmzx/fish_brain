# 2026-10-26: can the board's Wi-Fi run an access point? (N10)

Board `segunda`, `iw` 6.9 (installed by him), `wlan0` = wcn3990 (`ath10k_snoc`), on
`IZZI_5053.5`. Command: `/usr/sbin/iw list`, `iw reg get`, `iw dev` (`iw` is in `/usr/sbin`,
not on the ssh PATH).

| Fact | Value |
|---|---|
| Interface modes | IBSS, managed, AP, monitor, P2P-client, P2P-GO, P2P-device |
| Combinations | `#{managed} <= 2, #{AP, P2P-client, P2P-GO} <= 2, #{P2P-device} <= 1, total <= 4, #channels <= 1`; `#{managed} <= 2, #{P2P-client} <= 2, #{AP, P2P-GO} <= 1, #{P2P-device} <= 1, total <= 4, #channels <= 2`; `#{managed} <= 1, #{IBSS} <= 1, total <= 2, #channels <= 1` |
| Regulatory domain | MX (DFS-FCC): 5170–5250 MHz no DFS (channels 36–48), 5735–5835 MHz no DFS (149–165) |
| Now | managed on channel 149 (5745 MHz), 80 MHz |

What it means:

- **AP alone:** supported. It is the fallback when no known network appears (Phase 2).
- **AP and client at once:** a valid combination exists. It needs a second virtual interface
  for the AP, which would be one more adapter in Wine's list. Loquendo checks its licence
  against that list ([licence results](2026-10-25-loquendo-licence.md)), so it is not used
  until a licence render passes with that interface present.
- **Channel:** with `#channels <= 1` an AP beside a client must use the client's channel.
  Channel 36 and 149 need no DFS here.
