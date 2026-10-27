#!/usr/bin/env bash
# Set up and run fish_brain on the Arduino UNO Q. See deploy/README.md for the full sequence.
#
#   deploy/unoq_setup.sh sync [user@host]     laptop: copy this repo to the board
#   deploy/unoq_setup.sh install              board: venv, .env, canned phrases, link check
#   deploy/unoq_setup.sh service              board: install and (re)start the user service
#   deploy/unoq_setup.sh router release|restore   board: router lets go of / takes back the UART
#   deploy/unoq_setup.sh router off|on        board: PRINTS the root commands, runs nothing
#   deploy/unoq_setup.sh hotspot "<SSID>" "<password>" [connect]   board: save the phone hotspot
#   deploy/unoq_setup.sh kiosk on|off|pause|resume|status   board: the fish page on its own display
#   deploy/unoq_setup.sh tls [--force] [--local] [ip ...]   self-signed certificate for the phone page
#   deploy/unoq_setup.sh stt                  board: fetch the Canary speech-to-text model
#   deploy/unoq_setup.sh bench on|off|status  board: the fish keeps running with motors off
#   deploy/unoq_setup.sh ap "<SSID>" "<password>" [test <s>]   board: the board's own Wi-Fi profile
#   deploy/unoq_setup.sh net ap|auto|status   board: pin the board's own Wi-Fi, or let fish-net decide
#   deploy/unoq_setup.sh status               board: what is running, who has the port
#
# This script never calls sudo. Steps that need root are printed for the owner to run.
# Every subcommand can be run again safely.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY="$REPO/deploy"
PY="$REPO/.venv/bin/python"
BOARD="${FISH_BOARD:-arduino@segunda.local}"
BOARD_DIR="${FISH_BOARD_DIR:-fish_brain}"
ME="$(id -un)"
UNIT=fish-brain.service
POWERLOG_UNIT=fish-powerlog.service
NET_UNIT=fish-net.service
AP_PROFILE=fish-ap
STAMP="$REPO/.venv/.fish_install_ok"

APT_REQUIRED=(python3-venv python3-pip python3-dev gcc linux-libc-dev libportaudio2)
APT_OPTIONAL=(pulseaudio-utils pipewire-alsa stress-ng rsync)
ROUTER_UNITS=(arduino-router.service arduino-router-serial.service arduino-router-serial.path)

say()  { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
ok()   { printf '  ok    %s\n' "$*"; }
warn() { printf '  WARN  %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

usage() {
    # The header comment of this file is the help text.
    sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

# The board subcommands change the machine they run on, and `install` renders speech with
# whatever TTS the local .env selects. Refuse on anything that is not the UNO Q.
require_board() {
    [[ -e /dev/ttyHS1 || "$(uname -m)" == aarch64 ]] && return 0
    if [[ "${FISH_FORCE:-}" == 1 ]]; then
        # Forced on another machine: still never start the Loquendo/Wine voice there.
        local tts
        tts="$(env_get FISH_TTS_BACKEND)"
        if [[ ( "$1" == install || "$1" == service ) && "${tts:-loq}" != openai ]]; then
            die "'$1' was forced on a machine that is not the UNO Q, and the TTS backend is
       '${tts:-loq}' (Wine). Set FISH_TTS_BACKEND=openai in $REPO/.env first."
        fi
        return 0
    fi
    die "'$1' runs on the UNO Q, and this machine ($(hostname), $(uname -m)) is not one.
       From the laptop use:  deploy/unoq_setup.sh sync
       then:                 ssh $BOARD 'cd $BOARD_DIR && deploy/unoq_setup.sh $1'"
}

# Value of KEY the way the app sees it: the environment wins, then the last KEY= line of .env.
env_get() {
    local key="$1" line val=""
    if [[ -n "${!key-}" ]]; then
        printf '%s' "${!key}"
        return 0
    fi
    [[ -f "$REPO/.env" ]] || return 0
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line#export }"
        [[ "$line" == "$key="* ]] || continue
        val="${line#*=}"
        val="${val%$'\r'}"
        val="${val%"${val##*[![:space:]]}"}"
        val="${val#[\"\']}"
        val="${val%[\"\']}"
    done < "$REPO/.env"
    printf '%s' "$val"
}

in_group() {  # in_group <group>: is $ME a member (as recorded, not only in this login)?
    local g
    for g in $(id -nG "$ME"); do
        [[ "$g" == "$1" ]] && return 0
    done
    return 1
}

pkg_installed() {
    local st
    st="$(dpkg-query -W -f='${db:Status-Status}' "$1" 2>/dev/null)" || return 1
    [[ "$st" == installed ]]
}

user_systemd() {
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    systemctl --user "$@"
}

# --- sync (laptop) ----------------------------------------------------------------------
cmd_sync() {
    local target="${1:-$BOARD}" dest
    dest="$target:$BOARD_DIR/"
    have ssh || die "ssh not found"
    step "Copy $REPO/ -> $dest"
    ssh -o ConnectTimeout=8 "$target" true \
        || die "cannot reach $target over ssh (board on? same network? FISH_BOARD=user@host)"
    # .env stays out: the board has its own keys. rsync leaves excluded files on the board alone.
    local excludes=(--exclude .venv --exclude .env --exclude __pycache__ --exclude '*.wav'
                    --exclude '*.egg-info' --exclude .pytest_cache)
    if have rsync && ssh -o ConnectTimeout=8 "$target" 'command -v rsync' >/dev/null 2>&1; then
        rsync -a --delete "${excludes[@]}" "$REPO/" "$dest"
        ok "rsync done (files deleted here were deleted there too)"
    else
        warn "no rsync on one side: using tar over ssh. Files deleted here stay on the board."
        warn "(rsync is in the apt line that 'install' prints.)"
        tar -C "$REPO" "${excludes[@]}" -cf - . |
            ssh -o ConnectTimeout=8 "$target" "mkdir -p '$BOARD_DIR' && tar -C '$BOARD_DIR' -xf -"
        ok "tar copy done"
    fi
    say
    say "Next, on the board:"
    say "  ssh $target"
    say "  cd $BOARD_DIR && deploy/unoq_setup.sh install"
}

# --- install (board) --------------------------------------------------------------------
print_owner_steps() {
    # Prints the root steps that are still pending. Returns 1 if a blocking one is missing.
    local p missing=() optional=() blocked=0 g groups_missing=()
    for p in "${APT_REQUIRED[@]}"; do pkg_installed "$p" || missing+=("$p"); done
    for p in "${APT_OPTIONAL[@]}"; do pkg_installed "$p" || optional+=("$p"); done
    if (( ${#missing[@]} )); then
        blocked=1
        say "  Missing system packages. Run this yourself (needs your password):"
        say
        say "    sudo apt update && sudo apt install -y ${missing[*]} ${optional[*]}"
        say
    elif (( ${#optional[@]} )); then
        say "  Optional packages not installed (tools only, nothing blocks on them):"
        say "    sudo apt update && sudo apt install -y ${optional[*]}"
    else
        ok "system packages present"
    fi

    for g in dialout audio input; do in_group "$g" || groups_missing+=("$g"); done
    # arduino-router >= 0.11 makes its socket 0660 root:arduino-router.
    if getent group arduino-router >/dev/null 2>&1; then
        in_group arduino-router || groups_missing+=(arduino-router)
    fi
    if (( ${#groups_missing[@]} )); then
        local joined
        joined="$(IFS=,; printf '%s' "${groups_missing[*]}")"
        say "  User $ME is not in: ${groups_missing[*]}. Run this yourself:"
        say
        say "    sudo usermod -aG $joined $ME"
        say
        say "  It takes effect after a reboot (or: sudo systemctl restart user@$(id -u))."
    else
        ok "groups: dialout audio input$(getent group arduino-router >/dev/null 2>&1 \
            && printf ' arduino-router')"
    fi
    return "$blocked"
}

# Which API keys the selected backends need and do not have. One name per line.
missing_keys() {
    local stt tts llm need_openai=0 need_groq=0 need_anthropic=0
    stt="$(env_get FISH_STT_BACKEND)"; stt="${stt:-local}"
    tts="$(env_get FISH_TTS_BACKEND)"; tts="${tts:-loq}"
    llm="$(env_get FISH_LLM_PROFILE)"; llm="${llm:-groq}"
    [[ "$stt" == openai || "$tts" == openai || "$llm" == luna ]] && need_openai=1
    [[ "$stt" == groq || "$llm" == groq ]] && need_groq=1
    # Only the chat profile makes it required: the reading uses Claude when the key is there.
    [[ "$llm" == claude || "$llm" == claude-sonnet ]] && need_anthropic=1
    if (( need_openai )) && [[ -z "$(env_get OPENAI_API_KEY)" ]]; then say OPENAI_API_KEY; fi
    if (( need_groq )) && [[ -z "$(env_get GROQ_API_KEY)" ]]; then say GROQ_API_KEY; fi
    if (( need_anthropic )) && [[ -z "$(env_get ANTHROPIC_API_KEY)" ]]; then say ANTHROPIC_API_KEY; fi
    return 0
}

check_reachable() {
    local hostport host port
    hostport="$(env_get FISH_CLOUD_CHECK_HOST)"; hostport="${hostport:-api.openai.com:443}"
    host="${hostport%%:*}"
    port="${hostport##*:}"
    [[ "$port" == "$host" ]] && port=443
    # shellcheck disable=SC2016  # $1/$2 are for the inner shell
    if timeout 6 bash -c 'exec 3<>"/dev/tcp/$1/$2"' _ "$host" "$port" 2>/dev/null; then
        ok "$host:$port reachable"
    else
        die "$host:$port is not reachable. Connect the board to the internet and re-run:
       deploy/unoq_setup.sh install"
    fi
}

verify_canned() {
    local cache names name line bad=0 f found
    cache="${XDG_CACHE_HOME:-$HOME/.cache}/fish_brain/canned"
    names="$("$PY" -m fish_brain.app --list-canned)" \
        || die "'python -m fish_brain.app --list-canned' failed"
    [[ -n "$names" ]] || die "--list-canned printed no phrase names"
    while IFS= read -r line; do
        name="${line//[[:space:]]/}"
        [[ "$name" =~ ^[A-Za-z0-9_-]+$ ]] || continue
        found=""
        for f in "$cache/$name"-*.wav; do
            [[ -s "$f" && "$f" != *.new.wav ]] || continue
            found="$f"
            break
        done
        if [[ -n "$found" ]]; then
            ok "canned '$name': ${found##*/}"
        else
            warn "canned '$name': no WAV in $cache"
            bad=1
        fi
    done <<< "$names"
    return "$bad"
}

cmd_install() {
    require_board install
    cd "$REPO"
    rm -f "$STAMP"

    step "1/7 Root steps (yours)"
    if ! print_owner_steps; then
        die "install the packages above, then re-run: deploy/unoq_setup.sh install"
    fi

    step "2/7 Python environment"
    if [[ ! -x "$PY" ]]; then
        python3 -m venv "$REPO/.venv"
        ok "created .venv"
    else
        ok ".venv exists"
    fi
    "$PY" -m pip install --quiet --upgrade pip
    "$PY" -m pip install --quiet -e ".[unoq]"
    ok "pip install -e .[unoq]"
    "$PY" -c 'import fish_brain, numpy, sounddevice, serial, openai' \
        || die "the installed packages do not import (see the error above)"
    "$PY" -c 'import evdev, msgpack' 2>/dev/null \
        || warn "evdev/msgpack not importable: the remote button and the bridge transport are off"

    step "3/7 Settings (.env)"
    if [[ ! -f "$REPO/.env" ]]; then
        install -m 600 "$DEPLOY/env.unoq.example" "$REPO/.env"
        ok "created .env from deploy/env.unoq.example"
    else
        ok ".env exists (left as it is)"
    fi
    if [[ "$(env_get FISH_VIZ_HOST)" == 0.0.0.0 && -z "$(env_get FISH_VIZ_TOKEN)" ]]; then
        warn "FISH_VIZ_TOKEN is empty and the page is open to the network (FISH_VIZ_HOST=0.0.0.0)."
        warn "Anyone on the hotspot could make the fish speak. Put this in .env:"
        warn "  FISH_VIZ_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(16))')"
    fi

    step "4/7 API keys"
    local missing
    missing="$(missing_keys)"
    if [[ -n "$missing" ]]; then
        say "  The selected backends need a key that is not set: ${missing//$'\n'/, }"
        say
        say "  Edit $REPO/.env, set ${missing//$'\n'/ and }, then re-run:"
        say "    deploy/unoq_setup.sh install"
        say
        say "  Done so far: packages checked, .venv, .env. Nothing was rendered or sent."
        exit 2
    fi
    ok "keys present for stt=$(env_get FISH_STT_BACKEND) tts=$(env_get FISH_TTS_BACKEND)" \
       "llm=$(env_get FISH_LLM_PROFILE)"

    step "5/7 Internet"
    check_reachable

    step "6/7 Canned phrases"
    "$PY" -m fish_brain.app --prerender-canned \
        || die "'python -m fish_brain.app --prerender-canned' failed"
    # The app can exit 0 with nothing rendered, so the files are the proof.
    verify_canned || die "some canned phrases were not rendered (see above); fix and re-run install"

    step "7/7 Motor link"
    if user_systemd is-active --quiet "$UNIT" 2>/dev/null; then
        warn "the service is running and owns the port: link check skipped"
    elif FISH_SERIAL_REQUIRED=true timeout 90 "$PY" -m fish_brain.app --check-link; then
        # FISH_SERIAL_REQUIRED=true for this one run: with false the app reports a link
        # that could not open as "degraded" and still exits 0.
        ok "link check passed"
    else
        warn "link check failed. With FISH_SERIAL_REQUIRED=false the fish still talks (voice only)."
        warn "See 'deploy/unoq_setup.sh status' and deploy/README.md (router release vs off)."
    fi

    date -Is > "$STAMP"
    step "Install finished"
    say "  Next: deploy/unoq_setup.sh service"
}

# --- service (board) --------------------------------------------------------------------
cmd_service() {
    require_board service
    [[ -f "$STAMP" ]] || die "install has not passed yet. Run: deploy/unoq_setup.sh install"
    [[ -z "$(missing_keys)" ]] || die "a required API key is missing in .env. Re-run install."
    # These would break the unit file or the path rewrite below.
    local bad="[[:space:]%|&\\\\\"\$']"
    [[ "$REPO" =~ $bad ]] \
        && die "the repo path '$REPO' has a space, quote or one of % | & \\ \$: move it"

    step "Linger (start at boot without a login)"
    local linger
    linger="$(loginctl show-user "$ME" -p Linger --value 2>/dev/null)" || linger=""
    if [[ "$linger" == yes ]]; then
        ok "linger is on for $ME"
    else
        say "  Linger is off: the fish would start only while $ME is logged in."
        say "  Run this yourself (once):"
        say
        say "    sudo loginctl enable-linger $ME"
        say
    fi

    step "Install the user unit"
    local dir="$HOME/.config/systemd/user" tmp
    mkdir -p "$dir"
    tmp="$(mktemp)"
    if [[ "$REPO" == "$HOME/fish_brain" ]]; then
        cp "$DEPLOY/$UNIT" "$tmp"
    else
        sed "s|%h/fish_brain|$REPO|g" "$DEPLOY/$UNIT" > "$tmp"
        say "  repo is at $REPO: paths in the unit rewritten"
    fi
    install -m 644 "$tmp" "$dir/$UNIT"
    rm -f "$tmp"
    ok "$dir/$UNIT"

    step "Enable and (re)start"
    user_systemd daemon-reload
    user_systemd enable "$UNIT"
    if user_systemd is-active --quiet "$UNIT"; then
        user_systemd restart "$UNIT"
        ok "restarted"
    else
        user_systemd start "$UNIT"
        ok "started"
    fi
    local u
    for u in "$POWERLOG_UNIT" "$NET_UNIT"; do
        if [[ "$REPO" == "$HOME/fish_brain" ]]; then
            cp "$DEPLOY/$u" "$tmp"
        else
            sed "s|%h/fish_brain|$REPO|g" "$DEPLOY/$u" > "$tmp"
        fi
        install -m 644 "$tmp" "$dir/$u"
        rm -f "$tmp"
    done
    user_systemd daemon-reload
    step "WirePlumber: the onboard codec (no jack) is never a speaker or a microphone"
    local wp="$HOME/.config/wireplumber/wireplumber.conf.d"
    mkdir -p "$wp"
    if ! cmp -s "$DEPLOY/wireplumber/51-fish.conf" "$wp/51-fish.conf"; then
        install -m 644 "$DEPLOY/wireplumber/51-fish.conf" "$wp/51-fish.conf"
        user_systemd restart wireplumber            # sound drops for about a second
        ok "installed; WirePlumber restarted"
    else
        ok "already installed"
    fi
    step "Power logger (his logger, from every boot)"
    user_systemd enable --now "$POWERLOG_UNIT"
    ok "$POWERLOG_UNIT: ~/power_soak.csv"
    step "fish-net (the board's own Wi-Fi when no known network is there)"
    user_systemd enable "$NET_UNIT"
    user_systemd restart "$NET_UNIT"
    if [[ -n "$(env_get FISH_NET_AP_PROFILE)" ]]; then
        ok "$NET_UNIT: watching for '$(env_get FISH_NET_AP_PROFILE)'"
    else
        say "  $NET_UNIT idle: no access point yet (deploy/unoq_setup.sh ap \"<SSID>\" \"<password>\")"
    fi

    sleep 3
    user_systemd --no-pager --lines=15 status "$UNIT" || true
    say
    say "Logs:  journalctl --user -u fish-brain -f"
}

# --- bench (board) ----------------------------------------------------------------------
# At the 2026-10-17 fair the fish had been stopped and disabled for a motor test and was still
# off hours later. The bench mode never stops it: a drop-in points it at a port that does not
# exist, so it talks without motors and /dev/ttyHS1 stays free for tools/fw_check.py.
BENCH_DROPIN="$HOME/.config/systemd/user/$UNIT.d/80-bench.conf"

cmd_bench() {
    require_board bench
    case "${1:-status}" in
        on)
            mkdir -p "$(dirname "$BENCH_DROPIN")"
            printf '%s\n' "# deploy/unoq_setup.sh bench on: motors off; remove with 'bench off'" \
                "[Service]" "Environment=FISH_SERIAL_PORT=/dev/null-no-motors" \
                "Environment=FISH_SERIAL_REQUIRED=false" > "$BENCH_DROPIN"
            user_systemd daemon-reload
            user_systemd restart "$UNIT"
            ok "bench ON: fish-brain runs with no motors; /dev/ttyHS1 is free for the tools"
            say "  It stays on across reboots until: deploy/unoq_setup.sh bench off"
            ;;
        off)
            rm -f "$BENCH_DROPIN"
            user_systemd daemon-reload
            user_systemd restart "$UNIT"
            ok "bench OFF: fish-brain drives the motors again"
            ;;
        status)
            if [[ -f "$BENCH_DROPIN" ]]; then say "bench: ON (no motors)"; else say "bench: off"; fi
            say "fish-brain: $(user_systemd is-enabled "$UNIT" 2>/dev/null || echo not-installed)," \
                "$(user_systemd is-active "$UNIT" 2>/dev/null)"
            ;;
        *) die "usage: deploy/unoq_setup.sh bench on|off|status" ;;
    esac
}

# --- the board's own Wi-Fi (board) ------------------------------------------------------
# Profile fields measured in docs/results/2026-10-26-board-wifi-modes.md: 2.4 GHz channel 6,
# because without a known network the regulatory domain falls back to WORLD, where 5 GHz may
# not start an access point ("Failed to start AP functionality", 2026-10-26); the adapter keeps
# its own MAC (Loquendo's licence); 10.42.0.1 shared (NetworkManager's dnsmasq hands out
# addresses); autoconnect off, fish-net raises it.
cmd_ap() {
    require_board ap
    local ssid="${1:-}" pass="${2:-}" mode="${3:-}" secs="${4:-300}"
    [[ -n "$ssid" && ${#pass} -ge 8 ]] \
        || die "usage: deploy/unoq_setup.sh ap \"<SSID>\" \"<password, 8+ chars>\" [test <seconds>]"
    command -v nmcli >/dev/null || die "nmcli not found"
    nmcli connection delete "$AP_PROFILE" >/dev/null 2>&1 || true
    nmcli connection add type wifi ifname wlan0 con-name "$AP_PROFILE" ssid "$ssid" \
        802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel 6 \
        802-11-wireless.cloned-mac-address permanent \
        wifi-sec.key-mgmt wpa-psk wifi-sec.proto rsn wifi-sec.pairwise ccmp wifi-sec.group ccmp \
        wifi-sec.psk "$pass" wifi-sec.psk-flags 0 \
        ipv4.method shared ipv4.addresses 10.42.0.1/24 ipv6.method disabled \
        connection.autoconnect no connection.permissions '' >/dev/null \
        || die "nmcli could not create the profile"
    ok "profile $AP_PROFILE saved (SSID $ssid, 10.42.0.1, inactive)"
    if [[ -z "$(env_get FISH_NET_AP_PROFILE)" ]]; then
        printf '%s\n' "FISH_NET_AP_PROFILE=$AP_PROFILE" >> "$REPO/.env"
        ok "FISH_NET_AP_PROFILE=$AP_PROFILE added to .env"
    fi
    if [[ "$mode" == test ]]; then
        # The way back is armed before the Wi-Fi drops: ssh over the home network ends here.
        user_systemd stop "$NET_UNIT" 2>/dev/null || true
        user_systemd stop fish-ap-test-end.timer fish-ap-test-end.service 2>/dev/null || true
        user_systemd reset-failed fish-ap-test-end.service 2>/dev/null || true
        systemd-run --user --on-active="$secs" --unit=fish-ap-test-end \
            sh -c "nmcli connection down $AP_PROFILE; systemctl --user start $NET_UNIT" >/dev/null
        say "  Switching to $ssid now for $secs s; then back to the known networks."
        setsid -f nmcli connection up "$AP_PROFILE" >/dev/null 2>&1
    fi
}

cmd_net() {
    require_board net
    local pin="${XDG_STATE_HOME:-$HOME/.local/state}/fish_brain/net-pin"
    case "${1:-status}" in
        ap)   mkdir -p "$(dirname "$pin")"; echo ap > "$pin"; ok "pinned: the board's own Wi-Fi stays up" ;;
        auto) rm -f "$pin"; ok "auto: fish-net raises the board's Wi-Fi only without a known network" ;;
        status)
            say "pin: $(cat "$pin" 2>/dev/null || echo auto)"
            cat "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/fish_brain/net.json" 2>/dev/null && echo
            ;;
        *) die "usage: deploy/unoq_setup.sh net ap|auto|status" ;;
    esac
}

# --- router (board) ---------------------------------------------------------------------
serial_port() {
    local p
    p="$(env_get FISH_SERIAL_PORT)"
    printf '%s' "${p:-/dev/ttyHS1}"
}

router_socket_args() {
    # The app accepts a path, unix:<path> or tcp://host:port; the cli wants a path or host:port.
    local s
    s="$(env_get FISH_ROUTER_SOCKET)"
    s="${s#unix:}"
    s="${s#tcp://}"
    [[ -n "$s" ]] && printf '%s\n%s\n' -s "$s"
    return 0
}

print_router_off() {
    local u d=/etc/systemd/system
    cat <<EOF
Router OFF: optional. The default setup ('router release', done by fish_brain itself)
needs none of this. Run these as root, in this order:

  # 1. The flag every drop-in below looks at.
  sudo install -d /etc/fish_brain
  sudo touch /etc/fish_brain/router-off

  # 2. A drop-in on all three router units (the .path unit too, or it keeps restarting
  #    the others). 'systemctl mask' does not work on arduino-router 0.10.0.
EOF
    for u in "${ROUTER_UNITS[@]}"; do
        say "  sudo install -d $d/$u.d"
        say "  printf '[Unit]\\nConditionPathExists=!/etc/fish_brain/router-off\\n' |" \
            "sudo tee $d/$u.d/90-fish-off.conf >/dev/null"
    done
    cat <<EOF
  sudo systemctl daemon-reload

  # 3. Stop the router. This resets the MCU: it shows the boot animation until step 4.
  sudo systemctl stop arduino-router-serial.path arduino-router-serial.service \\
      arduino-router.service

  # 4. Raise the "Linux is ready" line ourselves, now and at every boot.
  sudo install -m 644 $DEPLOY/fish-mcu-ready.service $d/fish-mcu-ready.service
  sudo systemctl daemon-reload
  sudo systemctl enable --now fish-mcu-ready.service

Then, as $ME: set FISH_ROUTER_RELEASE=false in $REPO/.env and run
  systemctl --user restart fish-brain
While the router is off, App Lab, Bridge sketches and FISH_SERIAL_TRANSPORT=bridge do not work.
Undo with: deploy/unoq_setup.sh router on
EOF
}

print_router_on() {
    local u d=/etc/systemd/system
    cat <<EOF
Router ON: undoes 'router off'. Run these as root, in this order:

  sudo systemctl disable --now fish-mcu-ready.service
  sudo rm -f $d/fish-mcu-ready.service
  sudo rm -f /etc/fish_brain/router-off
EOF
    for u in "${ROUTER_UNITS[@]}"; do
        say "  sudo rm -f $d/$u.d/90-fish-off.conf"
        say "  sudo rmdir --ignore-fail-on-non-empty $d/$u.d"
    done
    cat <<EOF
  sudo systemctl daemon-reload
  sudo systemctl start arduino-router.service arduino-router-serial.path

Starting the router resets the MCU. Then, as $ME: set FISH_ROUTER_RELEASE=true in
$REPO/.env and run
  systemctl --user restart fish-brain
EOF
}

cmd_router() {
    local action="${1:-}" port sockargs=()
    case "$action" in
        off) print_router_off; return 0 ;;
        on)  print_router_on;  return 0 ;;
        release|restore) ;;
        *) die "usage: deploy/unoq_setup.sh router release|restore|off|on" ;;
    esac
    require_board "router $action"
    have arduino-router-cli || die "arduino-router-cli not found (is this the UNO Q?)"
    port="$(serial_port)"
    mapfile -t sockargs < <(router_socket_args)
    # The port argument is mandatory: without it the router rejects the call.
    if [[ "$action" == release ]]; then
        arduino-router-cli "${sockargs[@]}" '$/serial/close' "$port" \
            || die "the router did not release $port (is arduino-router running? see 'status')"
        ok "router released $port"
        say "  Until 'router restore': Bridge sketches and App Lab cannot reach the MCU."
        say "  A router restart takes the port back by itself."
    else
        # Handing the port back under a running fish leaves it talking with dead motors
        # and nothing in its log.
        if [[ "${FISH_FORCE:-0}" != 1 ]]; then
            if user_systemd is-active --quiet "$UNIT" 2>/dev/null; then
                die "fish-brain is running and owns $port. Stop it first: systemctl --user stop fish-brain"
            fi
            local lock; lock="/run/lock/fish_brain-$(basename "$port").lock"
            if [[ -e "$lock" ]] && ! flock -n "$lock" true 2>/dev/null; then
                die "$port is held by another fish process ($(cat "$lock" 2>/dev/null)). Stop it first."
            fi
        fi
        arduino-router-cli "${sockargs[@]}" '$/serial/open' "$port" \
            || die "the router did not re-open $port (is something else holding it? see 'status')"
        ok "router owns $port again"
        say "  A Bridge sketch must boot after this: reset or reflash the MCU."
    fi
}

# --- hotspot (board) --------------------------------------------------------------------
cmd_hotspot() {
    require_board hotspot
    local ssid="${1:-}" pw="${2:-}" connect="${3:-}" con=fish-hotspot ifname line
    [[ -n "$ssid" && -n "$pw" ]] \
        || die "usage: deploy/unoq_setup.sh hotspot \"<SSID>\" \"<password>\" [connect]"
    (( ${#pw} >= 8 )) || die "a WPA password has at least 8 characters"
    have nmcli || die "nmcli not found"

    ifname=wlan0
    while IFS= read -r line; do
        if [[ "$line" == *:wifi ]]; then ifname="${line%%:*}"; break; fi
    done < <(nmcli -t -f DEVICE,TYPE device)

    step "Save the hotspot as '$con' on $ifname"
    # The profile is saved without connecting, so this works with the phone off and does
    # not drop the ssh session you are typing in.
    if nmcli -g connection.id connection show "$con" >/dev/null 2>&1; then
        nmcli connection modify "$con" 802-11-wireless.ssid "$ssid"
        ok "profile existed: updated"
    else
        nmcli connection add type wifi ifname "$ifname" con-name "$con" ssid "$ssid" >/dev/null
        ok "profile created"
    fi
    # priority 10 = after the home networks (IZZI 30, the parents' 20, his word 2026-10-24); retries 0 = keep trying forever;
    # psk-flags 0 + empty permissions = stored system-wide, usable at boot with nobody logged in.
    nmcli connection modify "$con" \
        802-11-wireless-security.key-mgmt wpa-psk \
        802-11-wireless-security.psk "$pw" \
        802-11-wireless-security.psk-flags 0 \
        connection.autoconnect yes \
        connection.autoconnect-priority 10 \
        connection.autoconnect-retries 0 \
        connection.permissions ''
    ok "autoconnect on, priority 10, retries forever"

    if [[ "$connect" == connect ]]; then
        say "  Switching to '$ssid' now (an ssh session over the old Wi-Fi will drop)..."
        nmcli connection up "$con" || die "could not join '$ssid' (hotspot on? password right?)"
        ok "connected"
    else
        say "  Not connected now. The board joins '$ssid' by itself at boot or when the"
        say "  current Wi-Fi goes away. To switch right away:"
        say "    nmcli connection up $con"
    fi
}

# --- status (board) ---------------------------------------------------------------------
unit_state() {  # unit_state [--user] <unit> -> "active/enabled"
    local a e
    if [[ "$1" == --user ]]; then
        a="$(user_systemd is-active "$2" 2>/dev/null)" || true
        e="$(user_systemd is-enabled "$2" 2>/dev/null)" || true
    else
        a="$(systemctl is-active "$1" 2>/dev/null)" || true
        e="$(systemctl is-enabled "$1" 2>/dev/null)" || true
    fi
    printf '%s/%s' "${a:-unknown}" "${e:-not-installed}"
}

cmd_status() {
    local u port g holders linger ver sock

    step "fish_brain"
    say "  repo            $REPO"
    say "  $UNIT   $(unit_state --user "$UNIT")   (user unit)"
    say "  install passed  $([[ -f "$STAMP" ]] && cat "$STAMP" || printf 'no')"
    say "  .env            $([[ -f "$REPO/.env" ]] && printf 'present' || printf 'MISSING')"
    say "  backends        stt=$(env_get FISH_STT_BACKEND) tts=$(env_get FISH_TTS_BACKEND)" \
        "llm=$(env_get FISH_LLM_PROFILE) transport=$(env_get FISH_SERIAL_TRANSPORT)"
    local tls_cert
    tls_cert="$(env_get FISH_VIZ_TLS_CERT)"
    if [[ -n "$tls_cert" ]]; then
        say "  https page      $([[ -r "$tls_cert" ]] && printf 'cert %s' "$tls_cert" \
            || printf 'cert MISSING: %s (the service exits 78)' "$tls_cert")"
    elif [[ -e "$(tls_cert_path)" ]]; then
        say "  https page      off (cert exists at $(tls_cert_path): add the .env lines from deploy/unoq_setup.sh tls)"
    else
        say "  https page      off (no cert yet: deploy/unoq_setup.sh tls)"
    fi

    step "Router"
    ver="$(dpkg-query -W -f='${Version}' arduino-router 2>/dev/null)" || ver="not installed"
    say "  arduino-router package   $ver"
    for u in "${ROUTER_UNITS[@]}" fish-mcu-ready.service; do
        say "  $(printf '%-30s' "$u") $(unit_state "$u")"
    done
    say "  router-off flag          $([[ -e /etc/fish_brain/router-off ]] && printf 'SET' \
        || printf 'not set')"
    sock="$(env_get FISH_ROUTER_SOCKET)"; sock="${sock:-/var/run/arduino-router.sock}"
    sock="${sock#unix:}"
    if [[ -S "$sock" ]]; then
        say "  socket                   $(stat -c '%A %U:%G' "$sock") $sock"
    else
        say "  socket                   missing ($sock)"
    fi

    port="$(serial_port)"
    step "Who holds $port"
    if [[ ! -e "$port" ]]; then
        say "  $port does not exist on this machine"
    else
        say "  $(stat -c '%A %U:%G' "$port") $port"
        holders=""
        if have fuser; then
            holders="$(fuser -v "$port" 2>&1)" || true
        elif have lsof; then
            holders="$(lsof "$port" 2>/dev/null)" || true
        fi
        if [[ -n "$holders" ]]; then
            say "$holders"
        else
            say "  no holder visible to $ME"
        fi
        say "  (only your own processes show here; the router runs as root. Full answer:"
        say "   sudo fuser -v $port)"
    fi

    step "User $ME"
    for g in dialout audio input; do
        say "  group $(printf '%-15s' "$g") $(in_group "$g" && printf 'yes' || printf 'NO')"
    done
    if getent group arduino-router >/dev/null 2>&1; then
        say "  group arduino-router  $(in_group arduino-router && printf 'yes' \
            || printf 'NO  (sudo usermod -aG arduino-router %s)' "$ME")"
    else
        say "  group arduino-router  does not exist (router < 0.11: socket is open to all)"
    fi
    linger="$(loginctl show-user "$ME" -p Linger --value 2>/dev/null)" || linger="unknown"
    say "  linger                $linger$([[ "$linger" == yes ]] \
        || printf '  (sudo loginctl enable-linger %s)' "$ME")"
    return 0
}

# The fish page on the board's own display. Everything here is the user's own files; the
# one root file is printed for the owner.
KIOSK_MARK="# fish-kiosk"
cmd_kiosk() {
    local action="${1:-status}" xs="$HOME/.xsession" conf=/etc/lightdm/lightdm.conf.d/50-fish-kiosk.conf
    local pause="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/fish-kiosk.pause"
    require_board "kiosk $action"
    case "$action" in
        on)
            local t
            for t in chromium xrandr xset xsetroot; do
                have "$t" || die "$t not found (the kiosk needs chromium and x11-xserver-utils)"
            done
            if [[ -e "$xs" ]] && ! grep -q "^$KIOSK_MARK" "$xs"; then
                mv "$xs" "$xs.fish-bak"
                warn "your own ~/.xsession was moved to ~/.xsession.fish-bak"
            fi
            printf '#!/bin/sh\n%s (deploy/unoq_setup.sh kiosk on; remove with: kiosk off)\nexec "%s/deploy/kiosk/session.sh"\n' \
                "$KIOSK_MARK" "$REPO" > "$xs"
            chmod 755 "$xs"
            ok "~/.xsession starts the fish page"
            [[ "$(env_get FISH_VIZ_TOKEN)" && "$(env_get FISH_VIZ_TRUST_LOCAL)" != true ]] &&
                warn "FISH_VIZ_TOKEN is set: add FISH_VIZ_TRUST_LOCAL=true to .env, or the display's button does nothing"
            if [[ -e "$conf" ]]; then
                ok "$conf is installed"
            else
                say ""
                say "Yours, once (the board then logs in by itself into the kiosk):"
                say "  sudo install -D -m 644 $REPO/deploy/kiosk/50-fish-kiosk.conf $conf"
                say "  sudo systemctl restart lightdm"
                say "Undo: sudo rm $conf && sudo systemctl restart lightdm"
            fi
            ;;
        off)
            if [[ -e "$xs" ]] && grep -q "^$KIOSK_MARK" "$xs"; then
                rm -f "$xs"; ok "~/.xsession removed"
                [[ -e "$xs.fish-bak" ]] && mv "$xs.fish-bak" "$xs" && ok "your own ~/.xsession is back"
            else
                say "  ~/.xsession is not the kiosk's; left alone"
            fi
            say "Root part, yours: sudo rm $conf && sudo systemctl restart lightdm"
            ;;
        pause)  : > "$pause"; ok "kiosk paused (the browser closes within a few seconds)" ;;
        resume) rm -f "$pause"; ok "kiosk resumed" ;;
        status)
            step "Kiosk"
            local c
            for c in /sys/class/drm/card*-*; do
                [[ -e "$c/status" ]] || continue
                say "  $(basename "$c")  $(cat "$c/status")  $(head -1 "$c/modes" 2>/dev/null)"
            done
            say "  root file    $([[ -e "$conf" ]] && printf 'installed' || printf 'NOT installed (kiosk on prints the command)')"
            say "  ~/.xsession  $([[ -e "$xs" ]] && grep -q "^$KIOSK_MARK" "$xs" && printf 'kiosk' || printf 'not the kiosk')"
            say "  session      $(pgrep -u "$ME" -f '[k]iosk/session.sh' >/dev/null && printf 'running' || printf 'not running')$(pgrep -x lightdm-gtk-gre >/dev/null && printf '   LOGIN SCREEN IS SHOWING')"
            say "  supervisor   $(pgrep -u "$ME" -f '[p]ython3 -m fish_brain.kiosk' >/dev/null && printf 'running' || printf 'not running')$([[ -e "$pause" ]] && printf '   PAUSED')"
            say "  browser      $(pgrep -u "$ME" -fc '[u]ser-data-dir=/tmp/fish-kiosk' 2>/dev/null || true) processes"
            journalctl -t fish-kiosk -n 3 --no-pager -o cat 2>/dev/null | sed 's/^/  /' || true
            ;;
        *) die "kiosk: on | off | pause | resume | status" ;;
    esac
}

# --- tls (board, or the laptop with --local) ---------------------------------------------
# A self-signed certificate for the HTTPS page: a phone's microphone needs a secure context.
# Files live outside the synced tree ('sync' runs rsync --delete) and never in the repo.
TLS_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/fish_brain/tls"
TLS_NAME=segunda
VIZ_TLS_PORT_DEFAULT=8724
VIZ_PORT_DEFAULT=8723

tls_cert_path() { printf '%s' "$TLS_DIR/$TLS_NAME.crt"; }
tls_key_path()  { printf '%s' "$TLS_DIR/$TLS_NAME.key"; }

tls_print_cert() {  # the lines an operator checks: subject, SAN, dates
    local crt="$1"
    openssl x509 -noout -subject -dates -in "$crt" 2>/dev/null | sed 's/^/  /'
    openssl x509 -noout -ext subjectAltName -in "$crt" 2>/dev/null | sed -n '2p' | sed 's/^ */  SAN: /'
}

# The Canary speech-to-text model (FISH_STT_BACKEND=canary), as packaged by sherpa-onnx.
STT_MODEL_NAME=sherpa-onnx-nemo-canary-180m-flash-en-es-de-fr-int8
STT_MODEL_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$STT_MODEL_NAME.tar.bz2"
STT_DIR="${FISH_STT_DIR:-$HOME/.cache/fish_brain/stt}"

cmd_stt() {
    local dir="$STT_DIR/$STT_MODEL_NAME" f
    require_board stt
    step "Canary model in $dir"
    if [[ -s "$dir/encoder.int8.onnx" && -s "$dir/decoder.int8.onnx" && -s "$dir/tokens.txt" ]]; then
        ok "already there"
    else
        have curl || die "curl not found (apt update && apt install curl)"
        mkdir -p "$STT_DIR"
        say "  downloading about 200 MB..."
        curl -fsSL -o "$STT_DIR/$STT_MODEL_NAME.tar.bz2" "$STT_MODEL_URL" \
            || die "download failed: $STT_MODEL_URL"
        tar -xjf "$STT_DIR/$STT_MODEL_NAME.tar.bz2" -C "$STT_DIR"
        rm -f "$STT_DIR/$STT_MODEL_NAME.tar.bz2"
        for f in encoder.int8.onnx decoder.int8.onnx tokens.txt; do
            [[ -s "$dir/$f" ]] || die "the archive has no $f"
        done
        ok "unpacked"
    fi
    if "$PY" -c 'import sherpa_onnx' 2>/dev/null; then
        ok "sherpa-onnx is installed"
    else
        warn "sherpa-onnx is not in the venv: run 'deploy/unoq_setup.sh install' (it is in the unoq extra)"
    fi

    step "Your .env lines (this script never edits .env)"
    say "  FISH_STT_BACKEND=canary"
    say "  FISH_STT_MODEL_DIR=$dir"
    say "  then: systemctl --user restart fish-brain"
    say "  FISH_STT_LONG=groq          (optional: recordings over 6 s go online first)"
    say "  A recording over 6 s goes to faster-whisper (FISH_STT_MODEL) when nothing online"
    say "  answers, so keep that model fetched: $PY -m fish_brain.app --stt local --prefetch-stt"
}

cmd_tls() {
    local force=0 local_mode=0 arg ip ips=() san crt key tls_port viz_port
    for arg in "$@"; do
        case "$arg" in
            --force) force=1 ;;
            --local) local_mode=1 ;;
            -h|--help) say "usage: deploy/unoq_setup.sh tls [--force] [--local] [ip ...]"; return 0 ;;
            -*) die "tls: unknown option $arg" ;;
            *) [[ "$arg" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "tls: '$arg' is not an IPv4 address"
               ips+=("$arg") ;;
        esac
    done
    (( local_mode )) || require_board tls
    have openssl || die "openssl not found (the board has OpenSSL 3.5.7; apt update && apt install openssl)"
    crt="$(tls_cert_path)"; key="$(tls_key_path)"
    tls_port="$(env_get FISH_VIZ_TLS_PORT)"; tls_port="${tls_port:-$VIZ_TLS_PORT_DEFAULT}"
    viz_port="$(env_get FISH_VIZ_PORT)"; viz_port="${viz_port:-$VIZ_PORT_DEFAULT}"

    step "Certificate in $TLS_DIR"
    if [[ -e "$crt" || -e "$key" ]] && (( ! force )); then
        ok "already there (--force to replace it; the phone then asks again)"
        tls_print_cert "$crt"
    else
        mkdir -p "$TLS_DIR"
        chmod 700 "$TLS_DIR"
        san="DNS:$TLS_NAME.local,DNS:localhost,IP:127.0.0.1"
        for ip in "${ips[@]}"; do san="$san,IP:$ip"; done
        # CA:TRUE so the same file can be installed as a trusted authority on the laptop.
        openssl req -x509 -newkey rsa:2048 -sha256 -days 820 -noenc \
            -keyout "$key" -out "$crt" -subj "/CN=$TLS_NAME.local" \
            -addext "subjectAltName=$san" \
            -addext "basicConstraints=critical,CA:TRUE" \
            -addext "extendedKeyUsage=serverAuth" 2>/dev/null \
            || die "openssl could not write the certificate"
        chmod 600 "$crt" "$key"
        ok "written: $crt, $key (mode 600; 820 days)"
        tls_print_cert "$crt"
        if (( ${#ips[@]} == 0 )); then
            say "  (no IP given: Chrome shows the warning for an IP address anyway; pass the"
            say "   hotspot IP as an argument to list it in the certificate)"
        fi
    fi

    step "Your .env lines (this script never edits .env)"
    say "  FISH_VIZ_TLS_CERT=$crt"
    say "  FISH_VIZ_TLS_KEY=$key"
    say "  FISH_VIZ_TLS_PORT=$tls_port"
    if (( local_mode )); then
        say "  Made on this machine. Copy to the board (then the lines above with /home/arduino):"
        say "    ssh $BOARD 'mkdir -p -m 700 .config/fish_brain/tls'"
        say "    scp $crt $key $BOARD:.config/fish_brain/tls/"
    else
        say "  then: systemctl --user restart fish-brain"
    fi

    step "On the phone (Chrome), once per device, again after 7 days"
    local ip_hint="${ips[0]:-<board ip>}"
    say "  1. Open  https://$ip_hint:$tls_port/   (add ?token=<FISH_VIZ_TOKEN> only if one is set)"
    say "  2. 'Your connection is not private' -> Advanced -> Proceed to $ip_hint (unsafe)."
    say "     Chrome remembers it for 7 days: accept it again on fair morning."
    say "  3. 'Activar micrófono' -> Allow."
    say "  Plan B (no certificate): chrome://flags/#unsafely-treat-insecure-origin-as-secure"
    say "     with  http://$ip_hint:$viz_port  then Relaunch."
    say "  The http page at http://$ip_hint:$viz_port keeps working with the board microphone."
    say "  The laptop resolves segunda.local: it can install $TLS_NAME.crt as a trusted authority."
}

main() {
    local cmd="${1:-}"
    [[ $# -gt 0 ]] && shift
    case "$cmd" in
        sync)    cmd_sync "$@" ;;
        install) cmd_install "$@" ;;
        service) cmd_service "$@" ;;
        router)  cmd_router "$@" ;;
        hotspot) cmd_hotspot "$@" ;;
        kiosk)   cmd_kiosk "$@" ;;
        tls)     cmd_tls "$@" ;;
        stt)     cmd_stt "$@" ;;
        bench)   cmd_bench "$@" ;;
        ap)      cmd_ap "$@" ;;
        net)     cmd_net "$@" ;;
        status)  cmd_status "$@"; cmd_bench status; cmd_kiosk status ;;
        ""|-h|--help|help) usage ;;
        *) usage >&2; die "unknown subcommand: $cmd" ;;
    esac
}

main "$@"
