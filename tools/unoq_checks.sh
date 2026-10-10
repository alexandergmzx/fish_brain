#!/usr/bin/env bash
# unoq_checks.sh - bring-up checks for fish_brain on the Arduino UNO Q (Braintip Phase 1).
#
# Default run: read-only. It prints what the board sees (USB, audio cards, input devices,
# sound server, thermal, the MCU link and the router) and ends with the "Results" table
# of docs/BRAINTIP.md in Markdown, ready to paste. Rows it cannot measure say "manual"
# or name the option that fills them.
#
#   tools/unoq_checks.sh                    read-only checks + table
#   tools/unoq_checks.sh --keys [SECONDS]   find the remote's button: press it while this
#                                           watches every input device (default 15 s)
#   tools/unoq_checks.sh --mic CARD         record 5 s twice (without / with the remote's
#                                           button held), print the levels, play both back
#   tools/unoq_checks.sh --stress [SECONDS] CPU + audio load test (default 600 s)
#   --speaker CARD                          playback card for --mic / --stress
#
# CARD is an ALSA card id from the "Audio cards" section (for example "Device").
# Nothing here needs root and nothing changes the system: no package installs, no
# service or GPIO changes. --mic and --stress make sound and write only under /tmp.
# Missing tools are reported as "n/a", so it also runs on the laptop.
set -u

MIC_CARD=""
SPK_CARD=""
DO_KEYS=0
KEYS_S=15
DO_MIC=0
DO_STRESS=0
STRESS_S=600
TAKE_S=5
TTY_PORT="${FISH_SERIAL_PORT:-/dev/ttyHS1}"
ROUTER_SOCK="${FISH_ROUTER_SOCKET:-/var/run/arduino-router.sock}"

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; }

is_number() { case "$1" in '' | *[!0-9]*) return 1 ;; *) return 0 ;; esac; }

while [ $# -gt 0 ]; do
  case "$1" in
    --keys)
      DO_KEYS=1
      if [ $# -gt 1 ] && is_number "$2"; then KEYS_S="$2"; shift; fi ;;
    --mic)
      [ $# -gt 1 ] || { echo "--mic needs a card id (see 'arecord -l')" >&2; exit 2; }
      DO_MIC=1; MIC_CARD="$2"; shift ;;
    --speaker)
      [ $# -gt 1 ] || { echo "--speaker needs a card id (see 'aplay -l')" >&2; exit 2; }
      SPK_CARD="$2"; shift ;;
    --stress)
      DO_STRESS=1
      if [ $# -gt 1 ] && is_number "$2"; then STRESS_S="$2"; shift; fi ;;
    -h | --help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/unoq_checks.XXXXXX")" || exit 2
STRESS_PIDS=""
cleanup() {
  # shellcheck disable=SC2086  # word splitting wanted: a list of pids
  [ -n "$STRESS_PIDS" ] && kill $STRESS_PIDS 2>/dev/null
  rm -rf "$WORK"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

have() { command -v "$1" >/dev/null 2>&1; }
section() { printf '\n== %s ==\n' "$1"; }

# show CMD ARGS...: print the command's output indented, or "n/a" when it is missing.
show() {
  if have "$1"; then
    "$@" 2>&1 | sed 's/^/  /'
  else
    echo "  n/a ($1 not installed)"
  fi
}

# Table cells, filled as the checks run.
R_SPK="n/a"; N_SPK=""
R_MIC="n/a"; N_MIC=""
R_NOHOLD="not tested"; N_NOHOLD="run: tools/unoq_checks.sh --mic CARD"
R_KEY="not tested"; N_KEY="run: tools/unoq_checks.sh --keys"
R_SND="n/a"; N_SND=""
R_LOAD="not tested"; N_LOAD="run: tools/unoq_checks.sh --stress"

# --- read-only checks ---------------------------------------------------------------------

basics() {
  section "Board basics"
  echo "  arch:      $(uname -m) (UNO Q: aarch64)"
  echo "  kernel:    $(uname -r)"
  if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091  # the file only exists on the target
    echo "  os:        $(. /etc/os-release && echo "${PRETTY_NAME:-unknown}")"
  fi
  echo "  python3:   $(have python3 && python3 --version 2>&1 || echo n/a)"
  echo "  page size: $(getconf PAGESIZE 2>/dev/null || echo n/a) (Wine/Hangover needs 4096)"
  echo "  user:      $(id -un), groups: $(id -Gn)"
  local g
  for g in audio input dialout; do
    id -Gn | tr ' ' '\n' | grep -qx "$g" ||
      echo "  WARNING: not in group '$g' (sudo usermod -aG $g $(id -un), then log in again)"
  done
  if have loginctl; then
    echo "  linger:    $(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null ||
      echo n/a) (the user service needs yes)"
  fi
  show free -h
  show df -h /
}

usb() {
  section "USB devices"
  show lsusb
  local role
  for role in /sys/class/typec/*/data_role; do
    [ -r "$role" ] && echo "  $role: $(cat "$role")  ([host] = hub and devices can work)"
  done
}

# One line per ALSA card: "<id> <usb|builtin> <play|-> <capture|-> <description>".
cards() {
  local d id kind play cap desc
  for d in /proc/asound/card[0-9]*; do
    [ -d "$d" ] || continue
    id="$(cat "$d/id" 2>/dev/null)" || continue
    kind=builtin; [ -e "$d/usbid" ] && kind=usb
    play=-; ls "$d"/pcm*p >/dev/null 2>&1 && play=play
    cap=-; ls "$d"/pcm*c >/dev/null 2>&1 && cap=capture
    desc="$(grep -A1 "\[$id *\]" /proc/asound/cards 2>/dev/null | tail -n 1 | sed 's/^ *//')"
    echo "$id $kind $play $cap $desc"
  done
}

audio() {
  section "Audio cards"
  if [ ! -d /proc/asound ]; then
    echo "  n/a (no ALSA on this machine)"
    return
  fi
  local list spk mic
  list="$(cards)"
  if [ -z "$list" ]; then
    echo "  no sound cards"
  else
    printf '%s\n' "$list" | sed 's/^/  /'
  fi
  echo "  -- aplay -l";   show aplay -l
  echo "  -- arecord -l"; show arecord -l
  spk="$(echo "$list" | awk '$2=="usb" && $3=="play" {print $1}' | paste -sd, -)"
  mic="$(echo "$list" | awk '$2=="usb" && $4=="capture" {print $1}' | paste -sd, -)"
  if [ -n "$spk" ]; then R_SPK="$spk"; N_SPK="plughw:CARD=${spk%%,*},DEV=0"
  else R_SPK="none found"; N_SPK="no USB playback card (is the hub powered through PD?)"; fi
  if [ -n "$mic" ]; then R_MIC="$mic"; N_MIC="plughw:CARD=${mic%%,*},DEV=0"
  else R_MIC="none found"; N_MIC="no USB capture card (the remote must show in arecord -l)"; fi
}

sound_server() {
  section "Sound server"
  local found=""
  # timeout: without a user session these can wait on a socket nobody answers.
  if have wpctl && timeout 5 wpctl status >"$WORK/wpctl" 2>&1; then
    found="PipeWire"
    awk '/^Video/ { exit } { print "  " $0 }' "$WORK/wpctl"
  elif have wpctl; then
    echo "  wpctl is installed but PipeWire does not answer (no user session?)"
  fi
  if have pactl && timeout 5 pactl info >"$WORK/pactl" 2>&1; then
    found="${found:+$found, }pactl works"
    grep -E '^(Server Name|Default Sink|Default Source)' "$WORK/pactl" | sed 's/^/  /'
  fi
  have pactl || echo "  pactl: not installed (fish_brain falls back to pw-dump)"
  have pw-dump || echo "  pw-dump: not installed"
  if [ -n "$found" ]; then R_SND="yes"; N_SND="$found"
  else R_SND="no"; N_SND="plain ALSA (default device)"; fi
}

input_devices() {
  section "Input devices"
  local ev name link any=0
  for ev in /dev/input/event*; do
    [ -e "$ev" ] || continue
    any=1
    name="$(cat "/sys/class/input/${ev##*/}/device/name" 2>/dev/null || echo '?')"
    if [ -r "$ev" ]; then echo "  $ev  $name"; else echo "  $ev  $name  (not readable)"; fi
  done
  [ "$any" = 1 ] || echo "  no /dev/input/event* nodes"
  if [ -d /dev/input/by-id ]; then
    echo "  -- /dev/input/by-id (stable names; use these for FISH_PTT_DEVICE)"
    for link in /dev/input/by-id/*; do
      [ -e "$link" ] && echo "  $link -> $(readlink -f "$link")"
    done
  else
    echo "  /dev/input/by-id: absent (no USB input device attached)"
  fi
}

thermal() {
  section "Thermal"
  local z t any=0
  for z in /sys/class/thermal/thermal_zone*; do
    [ -r "$z/temp" ] || continue
    t="$(cat "$z/temp" 2>/dev/null)" || continue
    is_number "$t" || continue
    any=1
    printf '  %-16s %-22s %d.%d C\n' "${z##*/}" "$(cat "$z/type" 2>/dev/null)" \
      "$((t / 1000))" "$((t % 1000 / 100))"
  done
  [ "$any" = 1 ] || echo "  n/a (no thermal zones)"
}

max_temp() {
  local z t max=0
  for z in /sys/class/thermal/thermal_zone*/temp; do
    t="$(cat "$z" 2>/dev/null)" || continue
    is_number "$t" && [ "$t" -gt "$max" ] && max="$t"
  done
  echo "$((max / 1000))"
}

mcu_link() {
  section "MCU link and router"
  if [ -e "$TTY_PORT" ]; then
    echo "  $(ls -l "$TTY_PORT")"
    [ -r "$TTY_PORT" ] && [ -w "$TTY_PORT" ] || echo "  WARNING: $(id -un) cannot open it"
  else
    echo "  $TTY_PORT: absent (not a UNO Q, or FISH_SERIAL_PORT points elsewhere)"
  fi
  if [ -S "$ROUTER_SOCK" ]; then
    echo "  $(ls -l "$ROUTER_SOCK")"
  else
    echo "  $ROUTER_SOCK: absent (router not running)"
  fi
  local u
  if have systemctl; then
    for u in arduino-router.service arduino-router-serial.service \
      arduino-router-serial.path arduino-app-cli.service; do
      printf '  %-32s %s / %s\n' "$u" "$(systemctl is-active "$u" 2>/dev/null)" \
        "$(systemctl is-enabled "$u" 2>/dev/null || true)"
    done
  else
    echo "  systemctl: n/a"
  fi
  if have dpkg-query; then
    echo "  arduino-router package: $(dpkg-query -W -f '${Version}' arduino-router 2>/dev/null ||
      echo 'not installed')"
  fi
  if getent group arduino-router >/dev/null 2>&1; then
    if id -Gn | tr ' ' '\n' | grep -qx arduino-router; then
      echo "  group arduino-router: $(id -un) is a member"
    else
      echo "  group arduino-router: exists, $(id -un) is NOT a member" \
        "(sudo usermod -aG arduino-router $(id -un))"
    fi
  else
    echo "  group arduino-router: absent (router <= 0.10: the socket is open to everyone)"
  fi
  if have arduino-router-cli && [ -S "$ROUTER_SOCK" ]; then
    echo "  router version: $(timeout 3 arduino-router-cli -s "$ROUTER_SOCK" '$/version' 2>&1 |
      tail -n 1)"
  fi
  if have gpioinfo && [ -e /dev/gpiochip1 ]; then
    echo "  -- gpiochip1 lines 37 / 38 (MCU reset) / 70 (Linux ready)"
    gpioinfo -c gpiochip1 37 38 70 2>&1 | sed 's/^/  /'
  fi
  echo "  -- arduino-cli core list"
  show arduino-cli core list
}

tts_tools() {
  section "Local TTS tools (looked up only, never run)"
  local t p
  for t in loq wine; do
    p="$(command -v "$t" 2>/dev/null)"
    [ -z "$p" ] && [ -x "$HOME/.local/bin/$t" ] && p="$HOME/.local/bin/$t (not on PATH)"
    echo "  $t: ${p:-not found}"
  done
}

# --- opt-in modes ---------------------------------------------------------------------------

by_id_for() {
  local link
  for link in /dev/input/by-id/*; do
    [ -e "$link" ] && [ "$(readlink -f "$link")" = "$1" ] && { echo "$link"; return; }
  done
  echo "$1"
}

keys_mode() {
  section "Remote button (--keys, ${KEYS_S}s)"
  local ev readable="" pids="" first node key py
  for ev in /dev/input/event*; do
    [ -r "$ev" ] && readable="$readable $ev"
  done
  if [ -z "$readable" ]; then
    echo "  no readable /dev/input/event* node (is $(id -un) in group 'input'?)"
    R_KEY="n/a"; N_KEY="no readable input device"
    return
  fi
  if have evtest; then
    echo "  Press and release the remote's voice button a few times now..."
    for ev in $readable; do
      # stdbuf: keep evtest line-buffered into the pipe so timeout does not eat events.
      if have stdbuf; then
        timeout "$KEYS_S" stdbuf -oL evtest "$ev" 2>/dev/null
      else
        timeout "$KEYS_S" evtest "$ev" 2>/dev/null
      fi | sed -n "s|^Event: .*(EV_KEY), code \([0-9]*\) (\([A-Z0-9_?]*\)), value 1\$|$ev \2 \1|p" \
        >>"$WORK/keys" &
      pids="$pids $!"
    done
    # shellcheck disable=SC2086  # word splitting wanted: a list of pids
    wait $pids
    if [ ! -s "$WORK/keys" ]; then
      echo "  no key press seen"
      R_KEY="none seen"; N_KEY="no EV_KEY press in ${KEYS_S}s (Bluetooth-only remote?)"
      return
    fi
    echo "  presses seen (count, device, key, code):"
    sort "$WORK/keys" | uniq -c | sort -rn | sed 's/^/  /'
    first="$(sort "$WORK/keys" | uniq -c | sort -rn | head -n 1)"
    node="$(echo "$first" | awk '{print $2}')"
    key="$(echo "$first" | awk '{print $3}')"
    [ "$key" = "?" ] && key="$(echo "$first" | awk '{print $4}')"
    node="$(by_id_for "$node")"
    echo
    echo "  FISH_PTT_DEVICE=$node"
    echo "  FISH_PTT_KEY=$key"
    R_KEY="$node + $key"; N_KEY="most pressed key in ${KEYS_S}s"
    return
  fi
  # No evtest: the app's own watcher prints key names live (needs python-evdev).
  py="$(dirname "$0")/../.venv/bin/python"
  [ -x "$py" ] || py=python3
  if (cd "$(dirname "$0")/.." && "$py" -c 'import evdev, fish_brain.evdev_button') \
    2>/dev/null; then
    echo "  evtest is not installed; using fish_brain.evdev_button. Press the button now..."
    (cd "$(dirname "$0")/.." && timeout "$KEYS_S" "$py" -m fish_brain.evdev_button --watch) |
      sed 's/^/  /'
    R_KEY="see output"; N_KEY="read the device and KEY name from the lines above"
  else
    echo "  n/a: neither evtest nor python-evdev is available"
    R_KEY="n/a"; N_KEY="install evtest (sudo apt update && sudo apt install evtest)"
  fi
}

# level FILE -> "peak rms" of a 16-bit WAV, as fractions of full scale (stdlib only).
level() {
  python3 - "$1" <<'PY' 2>/dev/null || echo "n/a n/a"
import array, math, sys, wave
with wave.open(sys.argv[1], "rb") as w:
    data = array.array("h", w.readframes(w.getnframes()))
if not data:
    print("0.0000 0.0000")
else:
    peak = max(abs(x) for x in data) / 32768.0
    rms = math.sqrt(sum(x * x for x in data) / len(data)) / 32768.0
    print(f"{peak:.4f} {rms:.4f}")
PY
}

record() { # record CARD FILE SECONDS
  arecord -q -D "plughw:CARD=$1,DEV=0" -f S16_LE -r 16000 -c 1 -d "$3" "$2"
}

play() { # play FILE
  if [ -n "$SPK_CARD" ]; then aplay -q -D "plughw:CARD=$SPK_CARD,DEV=0" "$1"
  else aplay -q "$1"; fi
}

pause() { # wait for Enter on a terminal, else just give the user 3 s
  if [ -t 0 ]; then
    printf '  %s Press Enter to start. ' "$1"; read -r _
  else
    echo "  $1 Starting in 3 s."; sleep 3
  fi
}

mic_mode() {
  section "Mic (--mic $MIC_CARD)"
  if ! have arecord || ! have aplay; then
    echo "  n/a (alsa-utils not installed)"
    R_NOHOLD="n/a"; N_NOHOLD="arecord/aplay missing"
    return
  fi
  local rms1 rms2 peak1 peak2 quiet=0.005   # same floor as the app's silence gate
  pause "Take 1: do NOT touch the remote's button, speak for $TAKE_S s."
  if ! record "$MIC_CARD" "$WORK/free.wav" "$TAKE_S"; then
    echo "  arecord failed on card '$MIC_CARD' (check the id in 'Audio cards')"
    R_NOHOLD="n/a"; N_NOHOLD="arecord failed on card $MIC_CARD"
    return
  fi
  pause "Take 2: HOLD the remote's voice button and speak for $TAKE_S s."
  record "$MIC_CARD" "$WORK/held.wav" "$TAKE_S" || true
  read -r peak1 rms1 <<<"$(level "$WORK/free.wav")"
  read -r peak2 rms2 <<<"$(level "$WORK/held.wav")"
  echo "  take 1 (button free): peak $peak1  rms $rms1"
  echo "  take 2 (button held): peak $peak2  rms $rms2"
  echo "  playing both back..."
  play "$WORK/free.wav" || echo "  aplay failed (pass --speaker CARD)"
  [ -s "$WORK/held.wav" ] && play "$WORK/held.wav"
  N_NOHOLD="rms free $rms1 / held $rms2 (silence floor $quiet)"
  case "$(awk -v a="$rms1" -v b="$rms2" -v q="$quiet" 'BEGIN {
      if (a == "n/a") print "na"; else if (a + 0 >= q) print "yes";
      else if (b + 0 >= q) print "gated"; else print "silent" }')" in
    yes) R_NOHOLD="yes" ;;
    gated) R_NOHOLD="no (only while the button is held)" ;;
    silent) R_NOHOLD="no signal in either take" ;;
    *) R_NOHOLD="n/a"; N_NOHOLD="could not read the recordings" ;;
  esac
  cp "$WORK/free.wav" "${TMPDIR:-/tmp}/mic.wav" 2>/dev/null &&
    echo "  kept take 1 as ${TMPDIR:-/tmp}/mic.wav"
}

usb_errors() {
  dmesg 2>/dev/null | grep -ciE 'usb disconnect|reset|over-current|under-?voltage'
}

stress_mode() {
  section "Load test (--stress, ${STRESS_S}s)"
  local boot0 boot1 err0 err1 t0 t1 end clip loops=0 audio_fail=0 audio="yes" why="" port
  boot0="$(uptime -s 2>/dev/null || echo n/a)"
  err0="$(usb_errors)"
  t0="$(max_temp)"
  if ! dmesg >/dev/null 2>&1; then
    echo "  dmesg is not readable by $(id -un): USB errors cannot be counted"
    err0="n/a"
  fi

  if have stress-ng; then
    stress-ng --cpu 4 --timeout "${STRESS_S}s" >/dev/null 2>&1 &
    STRESS_PIDS="$!"
    echo "  CPU load: stress-ng --cpu 4"
  else
    for _ in 1 2 3 4; do
      timeout "$STRESS_S" sh -c 'while :; do :; done' &
      STRESS_PIDS="$STRESS_PIDS $!"
    done
    echo "  CPU load: 4 shell busy loops (stress-ng not installed)"
  fi

  # Audio out + in for the whole run, like the fair: play a clip, record 5 s, repeat.
  clip="$WORK/loop.wav"
  if ! have arecord || ! have aplay; then
    audio="no"; echo "  audio loop: n/a (alsa-utils not installed), CPU load only"
  elif [ -n "$MIC_CARD" ] && ! record "$MIC_CARD" "$clip" "$TAKE_S"; then
    audio="no"; audio_fail=1; echo "  audio loop: arecord failed on card '$MIC_CARD'"
  elif [ -z "$MIC_CARD" ] && ! arecord -q -f S16_LE -r 16000 -c 1 -d "$TAKE_S" "$clip" \
    2>/dev/null; then
    audio="no"; echo "  audio loop: no default capture device (pass --mic CARD), CPU load only"
  fi
  end=$(($(date +%s) + STRESS_S))
  while [ "$(date +%s)" -lt "$end" ]; do
    if [ "$audio" = "yes" ]; then
      loops=$((loops + 1))
      play "$clip" 2>/dev/null || audio_fail=$((audio_fail + 1))
      if [ -n "$MIC_CARD" ]; then
        record "$MIC_CARD" "$WORK/in.wav" "$TAKE_S" 2>/dev/null
      else
        arecord -q -f S16_LE -r 16000 -c 1 -d "$TAKE_S" "$WORK/in.wav" 2>/dev/null
      fi || { audio_fail=$((audio_fail + 1)); sleep 1; }  # a dead card fails at once
    else
      sleep 5
    fi
  done
  # shellcheck disable=SC2086  # word splitting wanted: a list of pids
  wait $STRESS_PIDS 2>/dev/null
  STRESS_PIDS=""

  boot1="$(uptime -s 2>/dev/null || echo n/a)"
  t1="$(max_temp)"
  echo "  boot time: $boot0 -> $boot1"
  echo "  hottest zone: ${t0} C -> ${t1} C"
  echo "  audio loops: $loops, failed plays/records: $audio_fail"
  [ "$boot0" = "$boot1" ] || why="${why}rebooted; "
  if [ "$err0" != "n/a" ]; then
    err1="$(usb_errors)"
    echo "  dmesg USB/power lines: $err0 -> $err1"
    if [ "$err1" -gt "$err0" ]; then
      why="${why}$((err1 - err0)) new USB/power lines in dmesg; "
      dmesg | grep -iE 'usb disconnect|reset|over-current|under-?voltage' | tail -n 5 |
        sed 's/^/    /'
    fi
  fi
  [ "$audio_fail" -eq 0 ] || why="${why}${audio_fail} audio failures; "
  for port in /sys/class/typec/*; do
    [ -e "$port" ] && echo "  typec: ${port##*/}"
  done
  N_LOAD="${STRESS_S}s, max ${t1} C"
  [ "$audio" = "yes" ] || N_LOAD="$N_LOAD, CPU only (no audio loop)"
  [ "$err0" != "n/a" ] || N_LOAD="$N_LOAD, dmesg not readable"
  if [ -z "$why" ]; then R_LOAD="PASS"; else R_LOAD="FAIL"; N_LOAD="${why}$N_LOAD"; fi
  echo "  $R_LOAD"
}

results() {
  section "Results (paste into docs/BRAINTIP.md)"
  echo
  echo "| Check | Result | Notes |"
  echo "|---|---|---|"
  echo "| Speaker card id | $R_SPK | $N_SPK |"
  echo "| Mic card id | $R_MIC | $N_MIC |"
  echo "| Mic works without holding the button? | $R_NOHOLD | $N_NOHOLD |"
  echo "| Remote input device + KEY code | $R_KEY | $N_KEY |"
  echo "| PipeWire/Pulse present? | $R_SND | $N_SND |"
  echo "| 10 min load test passed? | $R_LOAD | $N_LOAD |"
  echo "| Voltage at meter under load | manual | read the inline USB-C meter during --stress |"
  echo "| Battery runtime (power bank model) | manual | time a full run on the power bank |"
}

echo "unoq_checks on $(hostname) at $(date '+%Y-%m-%d %H:%M:%S')"
basics
usb
audio
sound_server
input_devices
thermal
mcu_link
tts_tools
[ "$DO_KEYS" = 1 ] && keys_mode
[ "$DO_MIC" = 1 ] && mic_mode
[ "$DO_STRESS" = 1 ] && stress_mode
results
