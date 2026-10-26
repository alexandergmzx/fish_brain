#!/usr/bin/env bash
# The power logger from "UNO Q power experiments never lose the hubs again.md" (his plan, the
# E4/E5/E9 commands), unchanged: one line every 10 s to ~/power_soak.csv. A drop in uptime
# means a reboot; a drop in the USB count means a lost device. Run at boot by
# deploy/fish-powerlog.service so a show always leaves this record.
while true; do
  printf '%s,%s,%s,%s\n' "$(date -Is)" "$(cut -d' ' -f1 /proc/uptime)" \
    "$(lsusb | wc -l)" "$(aplay -l 2>/dev/null | grep -c '^card')"
  sleep 10
done | tee -a ~/power_soak.csv
