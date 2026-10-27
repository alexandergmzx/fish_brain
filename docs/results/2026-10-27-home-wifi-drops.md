# 2026-10-27 — The home Wi-Fi: two access points, the beacon-mode drops, the phone's TDLS

Why the page on the phone said "no connection" and why the board vanished from the desktop
for four minutes at 07:50 CST while its service kept running. Board `segunda` on the home
network `IZZI_5053.5`, commit `0765b1f`, read from the journals of three boots (the 24-hour boot
of 2026-10-26 13:50 to 2026-10-27 13:57 UTC, and the two boots after his replugs). Times
below are UTC (CST + 6).

## Two access points on one channel

| What the board logged | Count in the 24-hour boot | Access point |
|---|---|---|
| `AP … appears to change mode (expected VHT, found HT) in beacon, disconnect` (the kernel, `wlan0`) | 14 | `90:5e:44:99:7f:90`, the main router, 5745 MHz, signal 100 at the board's spot |
| `CTRL-EVENT-BEACON-LOSS` then `DISCONNECTED … reason=4` | 10 | `b8:fb:b3:8c:3b:dd`, the extender, 5745 MHz, signal 45 at the board's spot |

Both serve the SSID on channel 149; after each drop the board joined whichever answered first,
and the last ten associations alternate between the two. The drop felt from the desktop: the
board unreachable (ping, ssh, mDNS) from about 13:50 to 13:55; the fish's `[cloud] offline` at
13:52:06, re-associated at 13:54:52, the service never stopped. A band lock would change
nothing (both are 5 GHz); the profile is now held on the main router's BSSID:

```bash
nmcli connection modify IZZI_5053.5 802-11-wireless.bssid 90:5E:44:99:7F:90   # no sudo: auth-polkit=false
nmcli connection up IZZI_5053.5
```

The reconnection took 10 s (`[cloud] offline` 14:41:22, `online` 14:41:32; `fish-net`:
`client -> wait -> client`). The main router's beacon-mode drops stay (about 14 a day,
estimate from one day); each is now a reconnection to the same router, a few seconds.
`fish-net` raises the board's own Wi-Fi after 45 s if the router is gone, so a locked profile
cannot strand the board.

## The phone's TDLS attempts

`wpa_supplicant` lines `TDLS: Creating peer entry for 66:f9:af:03:3f:5b` … `TDLS: Failed to set
TPK to the driver`: 15 in the 24-hour boot, and in the boot of 14:00 at 14:24:08, 14:24:34,
14:24:44 and 14:25:16, exactly while the phone drove the page (the marks at 14:24:05, a visit at
14:24:50, uploads at 14:25:15 and 14:25:19). That MAC is 192.168.1.136, the only client of the
page's event stream; the board's neighbour entry for it read `FAILED` at 14:28. The page said
"no connection", and the phone speaker route failed twice with "the phone did not start the
phrase" (the `play` event never arrived). The driver `ath10k_snoc` (kernel 7.0.0) refuses the
TDLS key, so the phone sets the link up, the board tears it down, and the phone tries again 10
to 30 s later.

`wpa_supplicant` 2.10 (`2:2.10-24`): `SET tdls_disabled 1` makes `wpa_supplicant_rx_tdls` discard
every TDLS frame, so no setup is ever answered. The control socket `/run/wpa_supplicant/wlan0`
is `0770 root:netdev` and `arduino` is in `netdev`: `/usr/sbin/wpa_cli -i wlan0 set tdls_disabled
1` answered `OK` without sudo, the association untouched. The board has no `nft`, `tc` or their
modules, so filtering the frames instead was not an option. `fish-net` sets the flag after every
client link from this commit on; the flag lives in the supplicant's interface object and
survives re-associations.

## Not measured

- The phone's page over a long session with the lock and the flag in place (he had left the
  page by then).
- How often the main router's beacons flip mode on other days.
- Whether the phone stops asking: with the frames discarded it gets no answer, which is harmless
  either way.
