#!/usr/bin/env bash
# unoq_bringup.sh - run the board tests that were first done by hand on 2026-10-10 and
# print one PASS/FAIL line each. Run it on the UNO Q, from the repo (~/fish_brain).
#
#   tools/unoq_bringup.sh                 usb, voice, loop and link tests
#   tools/unoq_bringup.sh usb loop        only the named tests
#   tools/unoq_bringup.sh --stt tiny      also time local speech-to-text (slow; tiny|base|small)
#   tools/unoq_bringup.sh --volume 0.8    speaker volume for the loop test (default: leave it)
#
# Tests:
#   usb    the USB-C port is the host; a USB speaker and a USB microphone are present
#   voice  Loquendo: start its daemon, time one warm sentence          (pass: 2 s or less)
#   loop   play that sentence on the speaker, record it with the microphone
#                                                 (pass: level 0.02 or more, 10x the silence)
#   link   MCU link, 300 lines at the fish's rate: the fish firmware's motor-safe check
#          (fw_check.py), or uart_check.py when the uart_echo sketch is flashed
#                                                 (pass: none lost)
#   stt    local speech-to-text on the loop recording, time per turn   (reported, no pass line)
#
# Needs no root. `loop` makes sound. `link` asks the router to release /dev/ttyHS1 for the
# test and hands it back; it is skipped while fish-brain runs or something else holds the
# link lock. Nothing else is changed; files go under /tmp.
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
PORT="${FISH_SERIAL_PORT:-/dev/ttyHS1}"
PHRASE="Hola, soy un pez parlante y estoy probando la bocina."
WAV=/tmp/fish_bringup_say.wav
REC=/tmp/fish_bringup_rec.wav
STT_MODEL=""
VOLUME=""
TESTS=()
FAILED=0

usage() { sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --stt) [ $# -gt 1 ] || { echo "--stt needs a model: tiny, base or small" >&2; exit 2; }
           STT_MODEL="$2"; shift ;;
    --volume) [ $# -gt 1 ] || { echo "--volume needs a value such as 0.8" >&2; exit 2; }
              VOLUME="$2"; shift ;;
    -h | --help) usage; exit 0 ;;
    usb | voice | loop | link | stt) TESTS+=("$1") ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
[ ${#TESTS[@]} -gt 0 ] || TESTS=(usb voice loop link)
if [ -n "$STT_MODEL" ]; then
  case " ${TESTS[*]} " in *" stt "*) ;; *) TESTS+=(stt) ;; esac
fi

export PATH="$HOME/.local/bin:$PATH"
LOQ="${FISH_LOQ_BIN:-$(command -v loq || true)}"

result() {   # result PASS|FAIL|INFO name detail
  printf '%-5s %-6s %s\n' "$1" "$2" "$3"
  [ "$1" = FAIL ] && FAILED=$((FAILED + 1))
  return 0
}

now() { date +%s.%N; }
since() { awk -v a="$1" -v b="$(now)" 'BEGIN { printf "%.2f", b - a }'; }

have_say_wav() {
  [ -s "$WAV" ] && return 0
  [ -n "$LOQ" ] || return 1
  WINEDEBUG=-all timeout 120 "$LOQ" -o "$WAV" -- "$PHRASE" >/dev/null 2>&1
}

test_usb() {
  local role speaker mic
  role="$(cat /sys/class/typec/port0/data_role 2>/dev/null || echo unknown)"
  case "$role" in
    *"[host]"*) result PASS usb "port is the USB host" ;;
    *) result FAIL usb "port role is '$role' (want [host]): check the cable and that the hub is powered" ;;
  esac
  speaker="$(grep -l 'Playback:' /proc/asound/card*/stream0 2>/dev/null | head -1)"
  mic="$(grep -l 'Capture:' /proc/asound/card*/stream0 2>/dev/null | head -1)"
  if [ -n "$speaker" ]; then result PASS usb "speaker: $(head -1 "$speaker" | cut -d: -f1)"
  else result FAIL usb "no USB speaker (aplay -l)"; fi
  if [ -n "$mic" ]; then result PASS usb "microphone: $(head -1 "$mic" | cut -d: -f1)"
  else result FAIL usb "no USB microphone (arecord -l)"; fi
}

test_voice() {
  local t secs
  [ -n "$LOQ" ] || { result FAIL voice "loq not found (set FISH_LOQ_BIN)"; return; }
  t="$(now)"
  if ! WINEDEBUG=-all timeout 150 "$LOQ" --start >/dev/null 2>&1; then
    result FAIL voice "the loq daemon did not start"; return
  fi
  result INFO voice "daemon ready after $(since "$t") s"
  rm -f "$WAV"
  WINEDEBUG=-all timeout 60 "$LOQ" -o "$WAV" -- "$PHRASE" >/dev/null 2>&1   # first one warms up
  t="$(now)"
  if WINEDEBUG=-all timeout 60 "$LOQ" -o "$WAV" -- "$PHRASE" >/dev/null 2>&1 && [ -s "$WAV" ]; then
    secs="$(since "$t")"
    if awk -v s="$secs" 'BEGIN { exit !(s <= 2.0) }'; then result PASS voice "warm sentence in $secs s"
    else result FAIL voice "warm sentence took $secs s (want 2 s or less)"; fi
  else
    result FAIL voice "loq could not render the sentence"
  fi
}

test_loop() {
  local rec_pid out
  command -v pw-play >/dev/null && command -v pw-record >/dev/null ||
    { result FAIL loop "pw-play / pw-record not found"; return; }
  have_say_wav || { result FAIL loop "no sentence to play (run the voice test, or put a WAV at $WAV)"; return; }
  [ -n "$VOLUME" ] && wpctl set-volume @DEFAULT_AUDIO_SINK@ "$VOLUME"
  rm -f "$REC"
  pw-record --rate 16000 --channels 1 --format s16 "$REC" &
  rec_pid=$!
  sleep 1
  pw-play "$WAV"
  sleep 1
  kill -INT "$rec_pid" 2>/dev/null
  wait "$rec_pid" 2>/dev/null
  out="$(python3 - "$REC" <<'PYEOF'
import math, struct, sys, wave
w = wave.open(sys.argv[1]); r = w.getframerate()
d = w.readframes(w.getnframes()); s = struct.unpack("<%dh" % (len(d) // 2), d)
rms = lambda x: math.sqrt(sum(v * v for v in x) / max(1, len(x))) / 32768
quiet, speech = rms(s[: int(0.8 * r)]), rms(s[int(1.2 * r): len(s) - r])
ok = speech >= 0.02 and speech >= 10 * max(quiet, 1e-5)
print(("PASS" if ok else "FAIL"), f"level during speech {speech:.3f}, silence before {quiet:.4f}")
PYEOF
)"
  if [ -n "$out" ]; then result "${out%% *}" loop "${out#* }"
  else result FAIL loop "nothing was recorded"; fi
}

test_link() {
  local out rc
  [ -x "$PY" ] || { result FAIL link "no venv at $REPO/.venv (run deploy/unoq_setup.sh install)"; return; }
  if systemctl --user is-active --quiet fish-brain 2>/dev/null; then
    result INFO link "fish-brain is running and holds the port: link test skipped"; return
  fi
  out="$("$PY" "$REPO/tools/fw_check.py" check --port "$PORT" --count 300 --release-router 2>&1)"
  rc=$?
  case "$out" in
    *"is in use by"*)   # the link lock is held: the tool refused before touching the router
      result INFO link "$(printf '%s\n' "$out" | grep 'is in use by' | head -1 | sed 's/^\[fw_check\] //' | cut -c1-150): link test skipped"
      return ;;
  esac
  if [ $rc -eq 0 ]; then
    result PASS link "firmware: $(printf '%s\n' "$out" | grep -E '^PASS +soak' | tr -s ' ' | cut -d' ' -f3- | cut -c1-150)"
    return
  fi
  if [ $rc -ne 3 ]; then
    result FAIL link "fw_check exit $rc: $(printf '%s\n' "$out" | grep -E '^FAIL|^\[fw_check\]' | tail -2 | paste -sd' ' | cut -c1-200) (is the fish firmware or uart_echo flashed? run tools/fw_check.py --release-router for the full table)"
    return
  fi
  # Exit 3: the uart_echo sketch answered, so judge the wire alone.
  out="$("$PY" "$REPO/tools/uart_check.py" --port "$PORT" --count 300 --release-router 2>&1)"
  rc=$?
  if [ $rc -eq 0 ]; then
    result PASS link "uart_echo sketch: $(printf '%s\n' "$out" | grep -iE 'acked|lost|rtt' | grep -v 'sent [0-9]*/' | tr -s ' ' | paste -sd';' | cut -c1-150)"
  else
    result FAIL link "uart_check exit $rc: $(printf '%s\n' "$out" | tail -2 | paste -sd' ' | cut -c1-160) (the uart_echo sketch answered the probe, then lost lines)"
  fi
}

test_stt() {
  local clip="$REC"
  [ -x "$PY" ] || { result FAIL stt "no venv at $REPO/.venv"; return; }
  [ -s "$clip" ] || clip="$WAV"
  [ -s "$clip" ] || { result FAIL stt "no recording to transcribe (run the loop test first)"; return; }
  (cd "$REPO" && "$PY" - "$clip" "${STT_MODEL:-tiny}" <<'PYEOF' 2>/dev/null
import sys, time
from fish_brain.config import STTConfig
from fish_brain.stt import Transcriber
cfg = STTConfig(); cfg.model = sys.argv[2]
t = Transcriber(cfg); t0 = time.monotonic(); t.ensure_loaded(); load = time.monotonic() - t0
t.transcribe(sys.argv[1])                       # first run warms up
t0 = time.monotonic(); text = t.transcribe(sys.argv[1]); dt = time.monotonic() - t0
print(f"INFO  stt    {cfg.model}: {dt:.1f} s per turn (load {load:.1f} s) -> {text!r}")
PYEOF
  ) || result FAIL stt "transcription failed"
}

echo "fish_brain board bring-up, $(date '+%Y-%m-%d %H:%M'), $(hostname)"
for t in "${TESTS[@]}"; do "test_$t"; done
echo
if [ "$FAILED" -eq 0 ]; then echo "all tests passed"; else echo "$FAILED failed"; fi
exit $((FAILED > 0))
