#!/bin/sh
# The whole X session of the board's display: the fish page and nothing else. Started by
# ~/.xsession (installed by `deploy/unoq_setup.sh kiosk on`). No desktop, so no App Lab, no
# screen locker and nothing that takes focus away from the page.
#
# It must never exit: an exit puts the login screen on the visitors' display.
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
xset s off; xset s noblank; xset -dpms
xsetroot -solid '#1a365d'
command -v xfwm4 >/dev/null 2>&1 && xfwm4 --compositor=off >/dev/null 2>&1 &
cd "$REPO" || exec sleep infinity
while :; do
    /usr/bin/python3 -m fish_brain.kiosk 2>&1 | systemd-cat -t fish-kiosk
    sleep 2
done
