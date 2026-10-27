"""The bring-up checks, for the `/debug` page: what `tools/unoq_bringup.sh` and
`tools/unoq_checks.sh` look at, read by the running fish itself.

`run(st, hub)` returns rows `{group, name, status, detail, fix}` with status `pass`, `fail`,
`warn` or `skip` (not applicable on this machine). Everything is read from the state the
debug view already built, from plain files under /proc and /sys, and from a cache of what
the sound server says. That cache is filled by a one-shot thread started when a debug page
asks and the cache is older than `SOUND_TTL_S`: no request ever waits on `wpctl` or `pactl`.
"""
from __future__ import annotations

import grp
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

SOUND_TTL_S = 10.0
SOUND_TIMEOUT_S = 2.0
LOW_VOLUME = 0.6          # below this the microphone could not hear the speaker (40 % measured)
_sound: dict = {"t": 0.0, "data": None, "busy": False}
_sound_lock = threading.Lock()


# ---- the sound server (never on a request's thread) -----------------------------------------

def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=SOUND_TIMEOUT_S).stdout


def parse_wpctl_volume(text: str) -> dict:
    """`Volume: 0.40 [MUTED]` -> {"volume": 0.4, "muted": True}"""
    m = re.search(r"Volume:\s*([0-9.]+)", text)
    return {"volume": float(m.group(1)) if m else None, "muted": "MUTED" in text}


def parse_wpctl_inspect(text: str) -> dict:
    out = {}
    for key in ("node.name", "node.description"):
        m = re.search(rf'{re.escape(key)}\s*=\s*"([^"]*)"', text)
        out[key.split(".")[1]] = m.group(1) if m else ""
    return out


def parse_pactl_volume(text: str) -> float | None:
    m = re.search(r"(\d+)%", text)
    return int(m.group(1)) / 100.0 if m else None


def probe_sound(run=_run, which=shutil.which) -> dict:
    """What the sound server says about its default sink and source. Raises nothing."""
    out: dict = {"tool": "", "answered": False, "sink": {}, "source": {}, "sources": []}
    try:
        if which("wpctl"):
            out["tool"] = "wpctl"
            for what, handle in (("sink", "@DEFAULT_AUDIO_SINK@"), ("source", "@DEFAULT_AUDIO_SOURCE@")):
                info = parse_wpctl_inspect(run(["wpctl", "inspect", handle]))
                info.update(parse_wpctl_volume(run(["wpctl", "get-volume", handle])))
                out[what] = info
            out["answered"] = bool(out["sink"].get("name") or out["source"].get("name"))
        elif which("pactl"):
            out["tool"] = "pactl"
            for what, handle in (("sink", "@DEFAULT_SINK@"), ("source", "@DEFAULT_SOURCE@")):
                name = run(["pactl", f"get-default-{what}"]).strip()
                out[what] = {"name": name, "description": name,
                             "volume": parse_pactl_volume(run(["pactl", f"get-{what}-volume", handle])),
                             "muted": "yes" in run(["pactl", f"get-{what}-mute", handle])}
            out["answered"] = bool(out["sink"].get("name"))
        else:
            out["error"] = "no wpctl and no pactl"
            return out
        # The source names, for "FISH_MIC_SOURCE exists" (the page server's own listing).
        from . import viz
        for lister in (viz._pulse_sources, viz._pipewire_sources):
            found = lister()
            if found:
                out["sources"] = [s["id"] for s in found]
                break
    except Exception as e:                       # a hung or missing sound server
        out["error"] = type(e).__name__
    return out


def sound(now: float | None = None, probe=probe_sound) -> dict | None:
    """The cached answer (None until the first one arrived); starts a refresh when stale."""
    now = time.monotonic() if now is None else now
    with _sound_lock:
        stale = now - _sound["t"] > SOUND_TTL_S
        if stale and not _sound["busy"]:
            _sound["busy"] = True

            def work():
                try:
                    data = probe()
                except Exception as e:
                    data = {"answered": False, "error": type(e).__name__}
                with _sound_lock:
                    _sound.update(data=data, t=time.monotonic(), busy=False)
            threading.Thread(target=work, name="debug-sound", daemon=True).start()
        data = _sound["data"]
        age = now - _sound["t"] if _sound["t"] else None
    if data is None:
        return None
    return {**data, "age_s": round(age, 1) if age is not None else None}


# ---- files ------------------------------------------------------------------------------------

def _read(p: Path) -> str:
    try:
        return p.read_text(errors="replace").strip()
    except OSError:
        return ""


def sound_cards(root: str = "/") -> list[dict]:
    """ALSA cards from /proc/asound: id, description, usb or built-in, playback, capture."""
    base = Path(root) / "proc/asound"
    desc = {}
    for line in _read(base / "cards").splitlines():
        m = re.match(r"\s*(\d+)\s+\[(\S+)\s*\]:\s*(.*)", line)
        if m:
            desc[m.group(1)] = m.group(3).split(" - ")[-1].strip()
    cards = []
    for c in sorted(base.glob("card[0-9]*")):
        n = c.name[4:]
        stream = _read(c / "stream0")
        cards.append({"n": n, "id": _read(c / "id"), "name": desc.get(n, ""),
                      "usb": (c / "usbid").exists(),
                      "playback": "Playback:" in stream or any(c.glob("pcm*p")),
                      "capture": "Capture:" in stream or any(c.glob("pcm*c"))})
    return cards


def input_nodes(root: str = "/") -> list[dict]:
    out = []
    for d in sorted((Path(root) / "sys/class/input").glob("event*"),
                    key=lambda p: int(re.sub(r"\D", "", p.name) or 0)):
        node = Path(root) / "dev/input" / d.name
        out.append({"node": d.name, "name": _read(d / "device/name"),
                    "readable": os.access(node, os.R_OK)})
    return out


def user_groups() -> set[str]:
    names = set()
    for gid in os.getgroups():
        try:
            names.add(grp.getgrgid(gid).gr_name)
        except KeyError:
            pass
    return names


# ---- the rows -----------------------------------------------------------------------------------

def run(st: dict, hub, root: str = "/", snd="ask") -> list[dict]:
    cfg = hub.cfg
    rows: list[dict] = []

    def row(group, name, status, detail="", fix=""):
        rows.append({"group": group, "name": name, "status": status, "detail": str(detail),
                     "fix": fix if status in ("fail", "warn") else ""})

    def ok(cond):
        return "pass" if cond else "fail"

    sysinfo = st.get("system") or {}
    be = st.get("backends") or {}
    flags = st.get("flags") or {}
    svc = st.get("service") or {}
    board = bool(sysinfo.get("usb_role"))            # a type-C role exists: the UNO Q

    # -- power and USB
    role = sysinfo.get("usb_role", "")
    if role:
        row("Power and USB", "The port is the USB host", ok("[host]" in role), role,
            "change the USB-C cable: with some the board stays a USB device")
    else:
        row("Power and USB", "The port is the USB host", "skip", "no type-C port here")
    usb = sysinfo.get("usb") or []
    row("Power and USB", "Devices on USB", "pass" if usb else "warn",
        ", ".join(u["product"] for u in usb) or "none seen", "check the hub and its power")

    # -- speaker
    if snd == "ask":
        snd = sound()
    cards = sound_cards(root)
    play = [c for c in cards if c["playback"]]
    usb_play = [c for c in play if c["usb"]]
    row("Speaker", "A playback sound card is present", ok(play) if not board else ok(usb_play),
        ", ".join(f"{c['name'] or c['id']}{' (USB)' if c['usb'] else ''}" for c in play) or "none",
        "plug the USB speaker into the hub; it must show in /proc/asound/cards")
    if snd is None:
        row("Speaker", "The sound server answers", "warn", "asking… (reload in a moment)")
    else:
        row("Speaker", "The sound server answers", ok(snd.get("answered")),
            f"{snd.get('tool') or '?'}" + (f": {snd['error']}" if snd.get("error") else "")
            + (f", {snd['age_s']} s ago" if snd.get("age_s") is not None else ""),
            "PipeWire is a user service: is linger on? `systemctl --user status pipewire wireplumber`")
        sink = snd.get("sink") or {}
        if snd.get("answered"):
            usb_sink = any((c["id"] or "x") in sink.get("name", "") or
                           (c["name"] and c["name"].split()[0] in sink.get("description", ""))
                           for c in usb_play)
            row("Speaker", "Default sink", "pass" if (usb_sink or not board) else "warn",
                sink.get("description") or sink.get("name") or "none",
                "the USB speaker is not the default output: `wpctl status`, `wpctl set-default <id>`")
            vol = sink.get("volume")
            row("Speaker", "Sink volume", "fail" if sink.get("muted") else
                "warn" if vol is not None and vol < LOW_VOLUME else "pass",
                ("MUTED, " if sink.get("muted") else "") + (f"{vol:.2f}" if vol is not None else "?"),
                "`wpctl set-mute @DEFAULT_AUDIO_SINK@ 0` and `wpctl set-volume @DEFAULT_AUDIO_SINK@ 1.0`")
    want = cfg.ptt.speaker
    if want not in (None, ""):
        text = str(want)
        hit = text.isdigit() or any(text.lower() in (c["name"] + " " + c["id"]).lower() for c in play) \
            or text.lower() in ("pulse", "default", "pipewire")
        row("Speaker", "FISH_SPEAKER_DEVICE matches a card", "warn" if text.isdigit() else ok(hit),
            text + (" (an index: it can change between boots)" if text.isdigit() else ""),
            "use a name from /proc/asound/cards, or leave it empty for the default sink")
    player = be.get("player", "")
    row("Speaker", "The fish plays sound", "skip" if flags.get("no_audio") else ok(player != "SilentPlayer"),
        player or "?", "no player could be made: is sounddevice or pw-play installed?")

    # -- microphone
    cap = [c for c in cards if c["capture"]]
    phone = be.get("capture") == "browser"
    row("Microphone", "A capture sound card is present", ok(cap) if not phone else ("pass" if cap else "warn"),
        ", ".join(f"{c['name'] or c['id']}{' (USB)' if c['usb'] else ''}" for c in cap) or "none",
        "plug the microphone (the remote's dongle) into the hub")
    if snd and snd.get("answered"):
        src = snd.get("source") or {}
        row("Microphone", "Default source", ok(src.get("name")),
            src.get("description") or src.get("name") or "none", "`wpctl status`: no source at all")
        vol = src.get("volume")
        row("Microphone", "Source volume", "fail" if src.get("muted") else "pass",
            ("MUTED, " if src.get("muted") else "") + (f"{vol:.2f}" if vol is not None else "?"),
            "`wpctl set-mute @DEFAULT_AUDIO_SOURCE@ 0`")
        if cfg.ptt.source:
            names = snd.get("sources") or []
            row("Microphone", "FISH_MIC_SOURCE exists", ok(cfg.ptt.source in names) if names else "warn",
                cfg.ptt.source if names else cfg.ptt.source + " (the sources could not be listed)",
                "the name in .env is not among the sources: `wpctl status`, `pw-dump`")
    rec = st.get("rec") or {}
    if rec.get("samples"):
        zeros, quiet = rec.get("zero_frac", 0) > 0.95, rec.get("rms", 1) < cfg.ptt.silence_rms
        row("Microphone", "The last recording has signal", "fail" if zeros else "warn" if quiet else "pass",
            f"rms {rec.get('rms')}, zeros {round(rec.get('zero_frac', 0) * 100)} % ({rec.get('origin')})",
            "digital zeros: the microphone sent nothing; press again or replug it" if zeros
            else "near silence: wrong source or too far away")
    else:
        row("Microphone", "The last recording has signal", "skip", "no recording yet")
    if phone:
        tls = bool(cfg.viz.tls_cert and cfg.viz.tls_key)
        row("Microphone", "Phones can record (HTTPS)", ok(tls), "on" if tls else "off",
            "FISH_MIC_CAPTURE=browser needs FISH_VIZ_TLS_CERT and FISH_VIZ_TLS_KEY")

    # -- remote
    remote = st.get("remote") or {}
    if cfg.ptt.evdev_device:
        devs = remote.get("devices") or []
        row("Remote", "Devices read", ok(devs), f"{len(devs)}: " + ", ".join(
            d["path"].rsplit("/", 1)[-1] for d in devs) if devs else "none",
            "dongle unplugged, asleep or unreadable: press a key on it, check the hub")
        nodes = input_nodes(root)
        blind = [n["node"] for n in nodes if not n["readable"]]
        row("Remote", "Input nodes readable", ok(not blind), f"{len(nodes) - len(blind)} of {len(nodes)}",
            "the user must be in the `input` group (then log in again)")
        other = remote.get("other_keys") or {}
        row("Remote", "Only configured keys arrive", "warn" if other else "pass",
            ", ".join(f"{k} ×{n}" for k, n in other.items()) or f"listening for {remote.get('keys', '?')}",
            "a key outside FISH_PTT_KEY arrived: see the hint and the Inputs tab")
    else:
        row("Remote", "A remote is configured", "skip", "FISH_PTT_DEVICE is empty: the page or the keyboard triggers")

    # -- link
    link = st.get("link") or {}
    port = cfg.serial.port
    if link.get("mock"):
        row("Link", "Motor link", "skip", "mock link (--dry-run): nothing moves")
    else:
        p = Path(root) / str(port).lstrip("/")
        exists = p.exists()
        row("Link", "The port exists", ok(exists),
            f"{port}" + (f" mode {oct(p.stat().st_mode)[-3:]}" if exists else " missing"),
            "the MCU's serial node is gone: cable, or the board did not boot its MCU side")
        row("Link", "Attached", ok(link.get("attached")), link.get("desc", ""),
            "the fish talks without motors and retries; see the [link] lines in the log")
        seen = link.get("mcu_alive") is True or link.get("rx_bytes", 0) > 0
        row("Link", "The MCU answers", "fail" if link.get("health") != "ok" else
            "pass" if seen else "warn",
            f"health {link.get('health')}, {link.get('rx_bytes', 0)} bytes back"
            + ("" if seen else " (nothing sent yet: press Ping in the Motors tab)"),
            "LED4 must blink green; try Ping in the Motors tab")
    if board:
        sock = Path(root) / str(cfg.serial.router_socket).lstrip("/")
        row("Link", "The router's socket", ok(sock.exists()), str(cfg.serial.router_socket),
            "`systemctl status arduino-router` (yours: it needs sudo to change)")
        off = (Path(root) / "etc/fish_brain/router-off").exists()
        row("Link", "Router not switched off", "warn" if off else "pass",
            "/etc/fish_brain/router-off is present" if off else "no router-off flag",
            "the flag keeps the router down on purpose; remove it to get the router back")

    # -- voice and cloud
    if cfg.tts.backend == "loq":
        found = shutil.which(cfg.tts.loq_bin)        # looked up, never run
        row("Voice and cloud", "loq is installed", ok(found), found or f"{cfg.tts.loq_bin}: not on PATH",
            "install the Loquendo wrapper, or set FISH_LOQ_BIN / FISH_TTS_BACKEND")
    canned = st.get("canned") or []
    if isinstance(canned, list) and canned:
        done = sum(1 for c in canned if c.get("rendered"))
        row("Voice and cloud", "Canned phrases rendered", "pass" if done == len(canned) else "warn",
            f"{done} of {len(canned)}", "they render at start; with a cloud voice that needs the key and the internet")
    for name, present in (be.get("keys") or {}).items():
        needed = (name == "OPENAI_API_KEY" and cfg.tts.backend == "openai") \
            or name in (be.get("stt_keys") or ()) \
            or (name == cfg.llm.api_key_env and not be.get("echo"))
        if needed:
            row("Voice and cloud", f"{name} is set", ok(present), "present" if present else "MISSING",
                "put it in .env, then restart")
    row("Voice and cloud", "Internet", ok(be.get("online") is not False),
        "online" if be.get("online") is not False else "OFFLINE", "the hotspot's mobile data")

    # -- service
    row("Service", "Runs as a systemd service", "pass" if svc.get("supervised") else "skip",
        svc.get("unit") or "started by hand")
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    if svc.get("supervised") and user:
        linger = (Path(root) / "var/lib/systemd/linger" / user).exists()
        row("Service", "Linger is on", ok(linger), "yes" if linger else "no",
            f"`sudo loginctl enable-linger {user}` (yours): without it sound and fish stop after ssh logout")
    have = user_groups()
    for g, why in (("audio", "sound cards"), ("input", "the remote"), ("dialout", "the MCU's port")):
        need = (g != "input" or bool(cfg.ptt.evdev_device)) and (board or g == "input")
        row("Service", f"In group {g}", ok(g in have) if need else ("pass" if g in have else "skip"),
            "yes" if g in have else f"no ({why})", f"`sudo usermod -aG {g} {user}` (yours), then log in again")
    env = Path.cwd() / ".env"
    row("Service", ".env present", "pass" if env.exists() else "warn", str(env),
        "keys and the board's switches live there")

    # -- tests: what the buttons last said, and what cannot run under a live fish
    last = getattr(hub.actions, "last", {}) if hub.actions is not None else {}
    for key, label in (("loop", "Speaker → microphone loop"), ("voice", "Voice render"),
                       ("cloud", "Cloud round trip"), ("ping", "Link ping")):
        r = last.get(key)
        if not r:
            row("Tests", label, "skip", "not run yet: press its button")
        else:
            row("Tests", label, r.get("status", "warn"), r.get("detail", ""), r.get("fix", ""))
    for label, cmd in (("Link soak, 300 lines", "tools/unoq_bringup.sh link"),
                       ("Load and USB stability", "tools/unoq_checks.sh --stress"),
                       ("Which key the remote sends", "see the Inputs tab (live), or tools/unoq_checks.sh --keys")):
        row("Tests", label, "skip", f"not run here: needs the fish stopped or a person · {cmd}")
    return rows


def summary(rows: list[dict]) -> dict:
    counted = [r for r in rows if r["status"] != "skip"]
    return {"passed": sum(1 for r in counted if r["status"] == "pass"), "of": len(counted),
            "failed": sum(1 for r in counted if r["status"] == "fail"),
            "warned": sum(1 for r in counted if r["status"] == "warn")}
