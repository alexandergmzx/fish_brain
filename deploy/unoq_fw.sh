#!/usr/bin/env bash
# Push, compile and upload MCU sketches for the Arduino UNO Q, with a numbered upload log.
#
#   deploy/unoq_fw.sh push [SKETCH_DIR]       laptop: copy a sketch folder to the board
#   deploy/unoq_fw.sh compile [NAME] [--trace]
#   deploy/unoq_fw.sh upload [NAME] --by WHO [--trace] [--note TEXT] [--force]
#   deploy/unoq_fw.sh status
#   deploy/unoq_fw.sh log [N]
#
# SKETCH_DIR defaults to $FISH_FW_REPO/unoq/BigMouthQ (FISH_FW_REPO: ../Big_mouth beside this
# repo); NAME defaults to BigMouthQ. The board is FISH_BOARD (arduino@segunda.local).
#
# Run it on the laptop. compile, upload, status and log run on the board: this file is sent
# to a shell there over ssh, so the laptop's copy is the only one. On the board itself they
# run directly. On the board everything lives under ~/fish_fw, and the log is
# ~/.local/state/fish_fw/uploads.tsv (append-only, one row per upload attempt).
#
# upload flashes the MCU: it resets it and replaces what runs there. It refuses while
# fish-brain is running or holds the link (--force overrides only this), when the core is
# not the tested one, when --by assistant already has ten rows, and when the build is
# missing or older than the last push. It never compiles and never stops a service.
#
# This script never calls sudo.
set -euo pipefail

BOARD="${FISH_BOARD:-arduino@segunda.local}"
FQBN=arduino:zephyr:unoq
CORE=arduino:zephyr
CORE_WANT=0.55.2
DEFAULT_NAME=BigMouthQ
ASSISTANT_LIMIT=10
UNIT=fish-brain.service
LINK_LOCK="${FISH_LINK_LOCK:-/run/lock/fish_brain-ttyHS1.lock}"

# Board side. $HOME is the board's when these are used there.
FW="$HOME/fish_fw"
STATE="$HOME/.local/state/fish_fw"
LOG="$STATE/uploads.tsv"
LOG_HEADER=$'n\ttime\tntp\tby\tsketch\tvariant\tgit\tdirty\tsha256\tcore\trc\tseconds\tnote'

say()  { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
ok()   { printf '  ok    %s\n' "$*"; }
warn() { printf '  WARN  %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
# refuse <exit code> <message>: an upload that was not attempted. No log row is written.
refuse() { local rc="$1"; shift; printf 'REFUSED: %s\n' "$*" >&2; exit "$rc"; }
have() { command -v "$1" >/dev/null 2>&1; }

usage() {
    cat <<EOF
Usage: deploy/unoq_fw.sh <command>

  push [SKETCH_DIR]                 laptop: copy a sketch folder to $BOARD:fish_fw/<name>/
  compile [NAME] [--trace]          board: build into fish_fw/build/<name>-<normal|trace>
  upload [NAME] --by WHO [--trace] [--note TEXT] [--force]
                                    board: flash that build and add a row to the log
  status                            board: last uploads, builds, services
  log [N]                           board: the last N rows of the upload log (default 20)

NAME defaults to $DEFAULT_NAME. FISH_BOARD=user@host picks another board,
FISH_FW_REPO another firmware checkout.
EOF
}

on_board() { [[ -e /dev/ttyHS1 || "$(uname -m)" == aarch64 ]]; }

user_systemd() {
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    systemctl --user "$@"
}

check_name() {  # the name becomes a path under ~/fish_fw and a field of the log
    [[ "$1" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]*$ ]] || die "not a sketch name: '$1'"
    [[ "$1" != build && "$1" != protocol ]] || die "'$1' is a folder of ~/fish_fw, not a sketch name"
}

# Send this file to a shell on the board and run one sub-command there.
on_the_board() {
    local self="${BASH_SOURCE[0]:-}" args
    [[ -n "$self" && -f "$self" ]] || die "cannot find this script to send it to the board"
    have ssh || die "ssh not found"
    args="$(printf '%q ' "$@")"
    # The whole file is read before main runs, so nothing on the board reads the rest of it.
    ssh -o ConnectTimeout=8 "$BOARD" "bash -s -- $args" < "$self"
}

# --- push (laptop) ----------------------------------------------------------------------
cmd_push() {
    local repo fw_repo src name parent top git_id dirty branch stage tree stale
    [[ $# -le 1 ]] || die "usage: deploy/unoq_fw.sh push [SKETCH_DIR]"
    on_board && die "'push' runs on the laptop"
    repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    fw_repo="${FISH_FW_REPO:-$repo/../Big_mouth}"
    src="${1:-$fw_repo/unoq/$DEFAULT_NAME}"
    [[ -d "$src" ]] || die "no such sketch folder: $src"
    src="$(cd "$src" && pwd)"
    name="$(basename "$src")"
    parent="$(dirname "$src")"
    check_name "$name"
    stale="'$name'"          # what is removed on the board before the copy
    [[ -f "$src/$name.ino" ]] || die "$src has no $name.ino (the folder and the .ino share a name)"
    have ssh || die "ssh not found"

    git_id=nogit; dirty=1; branch=-
    if top="$(git -C "$src" rev-parse --show-toplevel 2>/dev/null)"; then
        git_id="$(git -C "$top" rev-parse --short=7 HEAD)"
        branch="$(git -C "$top" rev-parse --abbrev-ref HEAD)"
        if [[ -z "$(git -C "$top" status --porcelain)" ]]; then dirty=0; fi
    else
        top=""
        warn "$src is not in a git checkout: the build id will say 'nogit'"
    fi
    (( dirty == 0 )) || warn "uncommitted changes in ${top:-$src}: this push is marked dirty"

    step "Stage $name ($git_id, dirty=$dirty, branch $branch)"
    stage="$(mktemp -d)"
    # shellcheck disable=SC2064
    trap "rm -rf '$stage'" EXIT
    # Links are followed: the board gets plain files, and a dangling link stops here.
    tar -C "$parent" --dereference --exclude .pushed --exclude BuildId.h -cf - "$name" \
        | tar -C "$stage" -xf - \
        || die "could not copy $src (a dangling link?)"
    cat > "$stage/$name/BuildId.h" <<EOF
// Written by fish_brain/deploy/unoq_fw.sh push. Not part of any repository.
#ifndef FISH_BUILD_ID_H
#define FISH_BUILD_ID_H
#define FISH_BUILD_GIT "$git_id"
#define FISH_BUILD_DIRTY $dirty
#endif
EOF
    # One hash over the staged sources: compile stores it, upload compares it.
    tree="$(cd "$stage/$name" && find . -type f ! -name .pushed -print0 | LC_ALL=C sort -z \
            | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)"
    cat > "$stage/$name/.pushed" <<EOF
git=$git_id
dirty=$dirty
branch=$branch
tree=$tree
time=$(date -Is)
EOF
    if [[ -n "$top" && -d "$top/protocol" ]]; then
        mkdir "$stage/protocol"
        tar -C "$top/protocol" -cf - . | tar -C "$stage/protocol" -xf -
        stale="'$name' protocol"
        ok "protocol/ goes along as fish_fw/protocol/ (where tools/fw_check.py looks)"
    fi

    step "Copy to $BOARD:fish_fw/$name/"
    ssh -o ConnectTimeout=8 "$BOARD" true \
        || die "cannot reach $BOARD over ssh (board on? same network? FISH_BOARD=user@host)"
    # A fresh folder each time: arduino-cli compiles every source it finds there.
    tar -C "$stage" -cf - . | ssh -o ConnectTimeout=8 "$BOARD" \
        "set -e; mkdir -p \"\$HOME/fish_fw\"; cd \"\$HOME/fish_fw\"; rm -rf -- $stale; tar -xf -"
    ok "pushed $name $git_id $( (( dirty )) && echo dirty || echo clean )"
    say
    say "Next:"
    say "  deploy/unoq_fw.sh compile $name"
}

# --- board side -------------------------------------------------------------------------
board_env() {
    on_board || die "this part runs on the UNO Q, and this machine ($(hostname), $(uname -m)) is not one"
    PATH="$HOME/.local/bin:$HOME/bin:/usr/local/bin:$PATH"
    have arduino-cli || die "arduino-cli not found on the board"
}

pushed_get() {  # pushed_get <file> <key>
    local line
    [[ -f "$1" ]] || return 0
    while IFS= read -r line; do
        if [[ "$line" == "$2="* ]]; then printf '%s' "${line#*=}"; return 0; fi
    done < "$1"
}

core_version() {  # installed version of the core, empty if it is not installed
    arduino-cli core list </dev/null 2>/dev/null | awk -v id="$CORE" '$1 == id { print $2; exit }'
}

# The file an upload sends: the first of these found in the build path.
artifact() {
    local dir="$1" pat f
    for pat in '*.ino.bin' '*.ino.elf-zsk' '*.bin' '*.elf-zsk' '*.ino.elf' '*.elf'; do
        for f in "$dir"/$pat; do
            if [[ -f "$f" ]]; then printf '%s' "$f"; return 0; fi
        done
    done
    return 1
}

sha_of() { sha256sum "$1" | cut -d' ' -f1; }

# Running unless systemd clearly says otherwise: a question that cannot be asked counts as yes.
fish_brain_active() {
    local a
    a="$(user_systemd is-active "$UNIT" 2>/dev/null)" || true
    [[ "$a" != inactive && "$a" != failed && "$a" != unknown ]]
}

link_locked() {  # is somebody holding fish_brain's lock on the MCU link?
    local f
    have flock || return 0
    for f in "$LINK_LOCK" "${TMPDIR:-/tmp}/$(basename "$LINK_LOCK")"; do
        [[ -e "$f" ]] || continue
        flock -n "$f" true 2>/dev/null || return 0
    done
    return 1
}

parse_build_args() {  # sets NAME VARIANT BY NOTE FORCE from the arguments
    NAME=""; VARIANT=normal; BY=""; NOTE=""; FORCE=0
    while (( $# )); do
        case "$1" in
            --trace) VARIANT=trace ;;
            --force) FORCE=1 ;;
            --by)    [[ $# -ge 2 ]] || die "--by needs a name"; BY="$2"; shift ;;
            --note)  [[ $# -ge 2 ]] || die "--note needs a text"; NOTE="$2"; shift ;;
            -*)      die "unknown option: $1" ;;
            *)       [[ -z "$NAME" ]] || die "one sketch name, got '$NAME' and '$1'"; NAME="$1" ;;
        esac
        shift
    done
    NAME="${NAME:-$DEFAULT_NAME}"
    check_name "$NAME"
}

cmd_compile() {
    local NAME VARIANT BY NOTE FORCE sketch build props=() t0 rc art
    parse_build_args "$@"
    board_env
    sketch="$FW/$NAME"
    build="$FW/build/$NAME-$VARIANT"
    [[ -f "$sketch/$NAME.ino" ]] || die "no sketch at $sketch: run 'deploy/unoq_fw.sh push' first"
    if [[ "$VARIANT" == trace ]]; then
        props=(--build-property "build.extra_flags=-DFISH_TRACE=1")
    fi
    if fish_brain_active; then
        warn "fish-brain is running: a compile keeps all cores busy for about a minute"
    fi

    step "Compile $NAME ($VARIANT, $(pushed_get "$sketch/.pushed" git))"
    mkdir -p "$build"
    rm -f "$build/.fish_built"
    t0=$SECONDS
    rc=0
    arduino-cli compile -b "$FQBN" --warnings default --build-path "$build" \
        "${props[@]}" "$sketch" </dev/null || rc=$?
    (( rc == 0 )) || die "compile failed (exit $rc) after $(( SECONDS - t0 )) s"
    art="$(artifact "$build")" || die "compile ended well but left no .bin or .elf-zsk in $build"
    [[ -f "$sketch/.pushed" ]] && cp "$sketch/.pushed" "$build/.fish_built"
    ok "built in $(( SECONDS - t0 )) s"
    ok "$(basename "$art")  $(stat -c %s "$art") bytes  sha256 $(sha_of "$art")"
}

cmd_upload() {
    local NAME VARIANT BY NOTE FORCE sketch build art sha ver n k git_id dirty ntp t0 rc secs now
    parse_build_args "$@"
    board_env
    [[ -n "$BY" ]] || die "upload needs --by WHO (who is flashing: owner, assistant, ...)"
    [[ "$BY" =~ ^[A-Za-z0-9_.-]+$ ]] || die "--by takes one plain word, got '$BY'"
    NOTE="${NOTE//[$'\t\r\n']/ }"
    sketch="$FW/$NAME"
    build="$FW/build/$NAME-$VARIANT"

    if (( ! FORCE )); then
        if fish_brain_active; then
            refuse 3 "fish-brain is running and talks to the MCU. Stop it first (the fish says goodbye):
         systemctl --user stop fish-brain
         then upload, then: systemctl --user start fish-brain"
        fi
        if link_locked; then
            refuse 3 "$LINK_LOCK is held: a fish_brain program has the MCU link open"
        fi
    fi
    ver="$(core_version)"
    [[ "$ver" == "$CORE_WANT" ]] \
        || refuse 4 "the installed $CORE core is '${ver:-none}', tested with $CORE_WANT only"
    [[ -f "$sketch/$NAME.ino" ]] || refuse 6 "no sketch at $sketch: push and compile first"
    art="$(artifact "$build")" \
        || refuse 6 "no $VARIANT build of $NAME: run 'deploy/unoq_fw.sh compile $NAME$([[ $VARIANT == trace ]] && echo ' --trace')'"
    if [[ ! -f "$build/.fish_built" ]] ||
       [[ "$(pushed_get "$build/.fish_built" tree)" != "$(pushed_get "$sketch/.pushed" tree)" ]]; then
        refuse 6 "the $VARIANT build of $NAME is not from the sources pushed last: compile again"
    fi
    sha="$(sha_of "$art")"
    git_id="$(pushed_get "$sketch/.pushed" git)"
    dirty="$(pushed_get "$sketch/.pushed" dirty)"

    mkdir -p "$STATE"
    exec 9>>"$LOG"
    flock -w 30 9 || die "another upload is writing the log"
    [[ -s "$LOG" ]] || printf '%s\n' "$LOG_HEADER" > "$LOG"
    n=$(( $(awk 'END { print NR }' "$LOG") ))          # header + rows, so this is the next number
    k="$(awk -F'\t' -v who="$BY" 'NR > 1 && $4 == who { c++ } END { print c + 0 }' "$LOG")"
    if [[ "$BY" == assistant ]]; then
        (( k < ASSISTANT_LIMIT )) \
            || refuse 5 "the log already has $k uploads by assistant (limit $ASSISTANT_LIMIT). The next ones are the owner's: --by owner"
        say "upload $n (assistant $(( k + 1 )) of $ASSISTANT_LIMIT)"
    else
        say "upload $n ($BY $(( k + 1 )))"
    fi
    say "  $NAME $VARIANT  git ${git_id:-?} dirty=${dirty:-?}  $(basename "$art") sha256 ${sha:0:16}..."

    ntp=no
    if [[ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" == yes ]]; then ntp=yes; fi
    now="$(date -Is)"
    t0=$SECONDS
    rc=0
    arduino-cli upload -b "$FQBN" --build-path "$build" "$sketch" </dev/null || rc=$?
    secs=$(( SECONDS - t0 ))
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$n" "$now" "$ntp" "$BY" "$NAME" "$VARIANT" "${git_id:--}" "${dirty:--}" "$sha" "$ver" \
        "$rc" "$secs" "${NOTE:--}" >> "$LOG"
    exec 9>&-
    if (( rc == 0 )); then
        ok "upload $n done in $secs s; the MCU was reset and now runs $NAME ($VARIANT)"
    else
        warn "upload $n failed (exit $rc) after $secs s; it is in the log as a failed row"
    fi
    return "$rc"
}

show_rows() {  # show_rows <n>: header plus the last n rows
    local n="$1"
    if [[ ! -s "$LOG" ]]; then
        say "  (no uploads logged yet: $LOG)"
        return 0
    fi
    { head -n 1 "$LOG"; tail -n +2 "$LOG" | tail -n "$n"; } | cut -f1-8,10-13 |
        if have column; then column -t -s $'\t'; else cat; fi | sed 's/^/  /'
}

cmd_log() {
    local n="${1:-20}"
    [[ "$n" =~ ^[0-9]+$ ]] || die "usage: deploy/unoq_fw.sh log [N]"
    board_env
    show_rows "$n"
    say
    say "  full rows with the sha256 column: $LOG"
}

cmd_status() {
    local last_sha="" last="" d name art sha same ver k a
    board_env

    step "Upload log"
    show_rows 5
    if [[ -s "$LOG" ]]; then
        last="$(awk -F'\t' 'NR > 1 && $11 == 0 { row = $0 } END { print row }' "$LOG")"
        k="$(awk -F'\t' 'NR > 1 && $4 == "assistant" { c++ } END { print c + 0 }' "$LOG")"
        say "  uploads by assistant: $k of $ASSISTANT_LIMIT"
        if [[ -n "$last" ]]; then
            last_sha="$(printf '%s' "$last" | cut -f9)"
            say "  last good upload: #$(printf '%s' "$last" | cut -f1,4-8 | tr '\t' ' ')"
        fi
        say "  (the log knows what this helper flashed, not what another tool flashed since)"
    fi

    step "Builds"
    if compgen -G "$FW/build/*" >/dev/null; then
        for d in "$FW"/build/*/; do
            name="$(basename "$d")"
            if art="$(artifact "$d")"; then
                sha="$(sha_of "$art")"
                same=no; [[ -n "$last_sha" && "$sha" == "$last_sha" ]] && same=yes
                say "  $name  git $(pushed_get "$d/.fish_built" git) dirty=$(pushed_get "$d/.fish_built" dirty)  ${sha:0:16}...  equals last upload: $same"
            else
                say "  $name  (no artifact)"
            fi
        done
    else
        say "  (none under $FW/build)"
    fi

    step "Board"
    ver="$(core_version)"
    if [[ "$ver" == "$CORE_WANT" ]]; then
        ok "$CORE $ver"
    else
        warn "$CORE is '${ver:-none}', uploads need $CORE_WANT"
    fi
    a="$(user_systemd is-active "$UNIT" 2>/dev/null)" || true
    say "  $UNIT   ${a:-unknown}$([[ "$a" == active ]] && echo '   (upload refuses while it runs)')"
    a="$(systemctl is-active arduino-router.service 2>/dev/null)" || true
    say "  arduino-router.service   ${a:-unknown}"
    if link_locked; then
        say "  $LINK_LOCK   held"
    else
        say "  $LINK_LOCK   free"
    fi
}

# --- main -------------------------------------------------------------------------------
main() {
    local cmd="${1:-}"
    [[ $# -gt 0 ]] && shift
    case "$cmd" in
        push) cmd_push "$@" ;;
        compile|upload|status|log)
            if on_board; then
                "cmd_$cmd" "$@"
            else
                on_the_board "$cmd" "$@"
            fi
            ;;
        ""|-h|--help|help) usage ;;
        *) usage >&2; die "unknown command: $cmd" ;;
    esac
}

main "$@"
