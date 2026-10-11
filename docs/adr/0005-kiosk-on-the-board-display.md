# 0005 — The page on the board's own display, and the screen as the turn trigger

**Status:** accepted · **Date:** 2026-10-11

## Context

There is no remote, so nothing at the fair could start a turn except the page opened on a
phone. An HDMI touch display can hang off the hub. The board's image boots into LightDM with
XFCE, whose autostart launches App Lab and a screen locker, and X blanks the screen after ten
minutes. The page was a debug view: its talk button sat below the fold on a small screen and
its operator controls were public.

## Decision

- At the fair a turn starts with a hold on the touch display. The page on a phone stays as
  the spare.
- LightDM logs `arduino` in automatically into the default X session, where `~/.xsession`
  runs `deploy/kiosk/session.sh` and nothing else. One root file, installed by the owner.
- `fish_brain/kiosk.py` (standard library, system Python) keeps Chromium on the page while a
  display is connected and the fish answers `GET /status`, a local waiting page while it does
  not, and no browser at all with no display.
- The visitor view is the same page with `?kiosk=1`. Its states come from the events the
  page already receives. Operator controls sit behind a corner tap sequence.
- Requests from the board itself need no token (`FISH_VIZ_TRUST_LOCAL`), so the token is
  never in a URL or a command line.
- The fish unit unsets `DISPLAY`: it must run the same with and without a display.

## Alternatives

- Autologin into XFCE with an autostart entry: brings the desktop, App Lab and the locker.
- A dedicated session file under `/usr/share/xsessions`: a second root file, and no way to
  switch the kiosk off without `sudo`.
- A Wayland kiosk compositor: not installed and never run on this board.
- The token in the kiosk URL: it would show in `ps` and in the browser profile.

## Consequences

- The public screen runs a browser as `arduino`: keep the hub's free ports out of reach.
- If the kiosk session ends, the login screen shows; `sudo systemctl restart lightdm` brings
  the kiosk back without touching the fish.
- The display needs its own power and must be on before the board (measured 2026-10-11).
- The fish must stay identical with no display attached: both set-ups are rehearsed.
