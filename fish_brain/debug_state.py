"""The slow state of the fish for `GET /debug/state`, and the hints drawn from it.

Everything here is read-only and built on the HTTP thread that asked: no call that blocks,
loads a model, reads the motor port or touches another thread's objects. Each section is
built on its own; one that fails becomes `{"error": "<its type>"}` and the rest still come.

Secrets: the configuration is shown field by field, with `NOT_SHOWN` left out; a test fails
when a new field's name looks like a secret and nobody has classified it.
"""
from __future__ import annotations

import dataclasses
import os
import re
import sys
import time
from pathlib import Path

# (section, field): never sent to a page. The token and the paths of the certificate pair.
NOT_SHOWN = {("viz", "token"), ("viz", "tls_key"), ("viz", "tls_cert")}
# Field names that contain "key"/"token" and are not secrets: reviewed, safe to show.
REVIEWED = {("ptt", "hold_key"), ("ptt", "evdev_key"), ("llm", "api_key_env"),
            ("llm", "max_completion_tokens"), ("stt", "keywords")}
_SUSPECT = re.compile(r"key|token|secret|password", re.I)
_TEXT_MAX = 200


def unclassified_fields(cfg) -> list[tuple[str, str]]:
    """Config fields whose name looks like a secret and that nobody has classified."""
    out = []
    for sec in dataclasses.fields(cfg):
        for f in dataclasses.fields(getattr(cfg, sec.name)):
            pair = (sec.name, f.name)
            if _SUSPECT.search(f.name) and pair not in NOT_SHOWN and pair not in REVIEWED:
                out.append(pair)
    return out


def _env_names() -> dict[tuple[str, str], str]:
    """(section class, field) -> the FISH_* variable that sets it, read from config.py."""
    names: dict[tuple[str, str], str] = {}
    cls = ""
    src = (Path(__file__).parent / "config.py").read_text(encoding="utf-8")
    for line in src.splitlines():
        m = re.match(r"class (\w+)", line)
        if m:
            cls = m.group(1)
        m = re.match(r"\s+(\w+):.*?_env\w*\(\s*\"(\w+)\"", line)
        if m and cls:
            names[(cls, m.group(1))] = m.group(2)
    return names


def _plain(value):
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, bytes):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value][:40]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in list(value.items())[:40]}
    s = str(value)
    return s if len(s) <= _TEXT_MAX else s[:_TEXT_MAX] + f"… ({len(s)} chars)"


def config_view(cfg) -> list[dict]:
    """Every shown field with its value, its FISH_* name, and whether it differs from the
    default a fresh Config would have had without the environment's overrides applied."""
    env = _env_names()
    rows = []
    for sec in dataclasses.fields(cfg):
        section = getattr(cfg, sec.name)
        for f in dataclasses.fields(section):
            if (sec.name, f.name) in NOT_SHOWN:
                continue
            name = env.get((type(section).__name__, f.name), "")
            rows.append({"section": sec.name, "field": f.name, "env": name,
                         "value": _plain(getattr(section, f.name)),
                         "set": bool(name) and name in os.environ})
    rows.append({"section": "viz", "field": "token", "env": "FISH_VIZ_TOKEN",
                 "value": "set" if cfg.viz.token else "empty", "set": bool(cfg.viz.token)})
    rows.append({"section": "viz", "field": "tls", "env": "FISH_VIZ_TLS_CERT",
                 "value": "on" if (cfg.viz.tls_cert and cfg.viz.tls_key) else "off",
                 "set": bool(cfg.viz.tls_cert)})
    return rows


# ---- the machine: plain file reads, safe on any thread ---------------------------------------

def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace").strip()
    except OSError:
        return ""


def system(root: str = "/") -> dict:
    r = Path(root)
    out: dict = {}
    zones = []
    for z in sorted((r / "sys/class/thermal").glob("thermal_zone*")):
        t = _read(z / "temp")
        if t.lstrip("-").isdigit():
            zones.append({"name": _read(z / "type") or z.name, "c": round(int(t) / 1000.0, 1)})
    out["thermal"] = zones
    load = _read(r / "proc/loadavg").split()
    out["load"] = [float(x) for x in load[:3]] if len(load) >= 3 else []
    out["cores"] = os.cpu_count() or 0
    mem = {}
    for line in _read(r / "proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        if k in ("MemTotal", "MemAvailable"):
            mem[k] = int(v.split()[0]) // 1024
    out["mem_mb"] = {"total": mem.get("MemTotal", 0), "available": mem.get("MemAvailable", 0)}
    up = _read(r / "proc/uptime").split()
    out["uptime_s"] = int(float(up[0])) if up else 0
    out["usb_role"] = _read(r / "sys/class/typec/port0/data_role")
    usb = []
    for d in sorted((r / "sys/bus/usb/devices").glob("*")):
        product = _read(d / "product")
        if product:
            usb.append({"id": f"{_read(d / 'idVendor')}:{_read(d / 'idProduct')}",
                        "product": product})
    out["usb"] = usb
    wifi = _read(r / "proc/net/wireless").splitlines()[2:]
    out["wifi"] = [{"dev": w.split()[0].rstrip(":"), "link": w.split()[2].rstrip(".")}
                   for w in wifi if len(w.split()) > 3]
    try:
        st = os.statvfs(root)
        out["disk_free_mb"] = st.f_bavail * st.f_frsize // (1024 * 1024)
    except OSError:
        pass
    return out


def service(root: str = "/") -> dict:
    """Whether this process is a systemd service (then a restart can be left to its unit)."""
    cgroup = _read(Path(root) / "proc/self/cgroup").splitlines()
    leaf = cgroup[-1].rsplit("/", 1)[-1] if cgroup else ""
    unit = leaf if leaf.endswith(".service") else ""
    out = {"supervised": bool(unit), "unit": unit,
           "pid": os.getpid(), "python": sys.version.split()[0]}
    if unit:
        # A user unit is enabled when its default.target link exists: a file check, no call
        # to systemctl. At the 2026-10-17 fair the fish had been left disabled for hours.
        home = Path(root) / os.path.expanduser("~").lstrip("/")
        user_units = home / ".config/systemd/user"
        out["enabled"] = (user_units / "default.target.wants" / unit).exists()
        out["bench"] = (user_units / f"{unit}.d" / "80-bench.conf").exists()
    return out


def version(repo: Path | None = None) -> dict:
    """The tree's commit, read from .git without running git."""
    repo = repo or Path(__file__).resolve().parent.parent
    head = _read(repo / ".git/HEAD")
    commit, branch = head, ""
    if head.startswith("ref: "):
        ref = head[5:]
        branch = ref.rsplit("/", 1)[-1]
        commit = _read(repo / ".git" / ref)
        if not commit:
            for line in _read(repo / ".git/packed-refs").splitlines():
                if line.endswith(" " + ref):
                    commit = line.split()[0]
    return {"commit": commit[:7], "branch": branch}


# ---- the sections --------------------------------------------------------------------------

def _section(fn):
    try:
        return fn()
    except Exception as e:
        return {"error": type(e).__name__}


def _link(hub) -> dict:
    link = hub.link
    if link is None:
        return {"kind": "none", "desc": "not opened yet", "health": "", "attached": False}
    inner = getattr(link, "_link", None) or link
    out = {"kind": type(inner).__name__, "desc": link.describe(), "health": link.health(),
           "attached": bool(link.attached), "tx_total": hub.counters["tx"],
           "tx_dropped": hub.counters["tx_dropped"], "rx_bytes": hub.counters["rx_bytes"],
           "rx_tail": hub.rx_tail[-600:], "mock": type(inner).__name__ == "MockSerialLink",
           "muted": bool(getattr(link, "muted", False))}
    for attr, name in (("_unanswered", "unanswered"), ("_mcu_alive", "mcu_alive")):
        if hasattr(inner, attr):
            out[name] = getattr(inner, attr)
    return out


def _remote(hub) -> dict:
    convo = hub.convo
    button = getattr(convo, "button", None) if convo is not None else None
    out = {"other_keys": dict(hub._key_other), "text_keys": hub._text_keys}
    if button is None:
        out.update({"present": False, "devices": []})
        return out
    out.update({"present": True, **button.snapshot()})
    return out


def _backends(hub) -> dict:
    cfg, convo = hub.cfg, hub.convo
    out = {"stt": cfg.stt.backend, "tts": cfg.tts.backend, "llm_profile": cfg.llm.profile,
           "llm_model": cfg.llm.model, "capture": cfg.ptt.capture,
           "mic_source": cfg.ptt.source, "mic_device": _plain(cfg.ptt.device),
           "speaker": _plain(cfg.ptt.speaker)}
    if convo is not None:
        out["ptt"] = convo.ptt_summary()
        out["echo"] = bool(convo.echo)
        llm = getattr(convo, "_llm", None)         # never the property: it builds a client
        if llm is not None:
            usage = getattr(llm, "last_usage", None)
            out["llm"] = {"last_s": getattr(llm, "last_latency_s", None),
                          "last_error": type(llm.last_error).__name__ if isinstance(
                              llm.last_error, BaseException) else (llm.last_error or ""),
                          "history": len(getattr(llm, "_history", ())),
                          "usage": _plain(getattr(usage, "__dict__", usage))}
        player = getattr(convo, "player", None)
        out["player"] = type(player).__name__ if player is not None else "none"
    from . import cloud
    out["online"] = cloud.is_online()
    keys = {"OPENAI_API_KEY", cfg.llm.api_key_env}
    # Speech-to-text's own services: a cloud backend, or where canary sends long recordings.
    from .config import STT_PROFILES
    names = (cfg.stt.backend,) if cfg.stt.backend in STT_PROFILES else (
        cfg.stt.long_online if cfg.stt.backend == "canary" else ())
    out["stt_keys"] = sorted({STT_PROFILES[n]["api_key_env"] for n in names if n in STT_PROFILES})
    keys.update(out["stt_keys"])
    out["keys"] = {k: bool(os.environ.get(k)) for k in sorted(k for k in keys if k)}
    return out


def _canned(hub) -> list[dict]:
    cfg = hub.cfg
    rows = []
    for name in cfg.canned.phrases:
        files = sorted(cfg.canned.cache_dir.glob(f"{name}-*.wav"))
        rows.append({"name": name, "rendered": bool(files)})
    return rows


def _clients(hub) -> dict:
    viz = hub.viz
    out = {"debug_pages": hub.viewers(), "dropped": hub.counters["page_dropped"],
           "evicted": hub.counters["page_evicted"]}
    if viz is not None:
        out.update({"pages": len(viz._subscribers), "max": viz.MAX_SUBSCRIBERS,
                    "mic_pages": viz.mic_pages()})
    return out


def _mode(hub) -> dict:
    viz, convo, actions = hub.viz, hub.convo, hub.actions
    speaker = getattr(convo, "speaker", None)
    from . import ptt
    return {"listening": bool(viz.listening) if viz is not None else False,
            "speaking": bool(speaker._lock.locked()) if speaker is not None else False,
            "recording": ptt.last_info().get("recording", False),
            "wait": bool(viz.wait_enabled()) if viz is not None else False,
            "armed_s": actions.armed_s() if actions is not None else 0,
            "restarting": bool(getattr(actions, "restarting", False))}


def _model(hub) -> dict:
    """What the models are given, as it stands now. The history is read from the client when
    one exists (never through the property that would build it): what visitors said."""
    cfg, convo = hub.cfg, hub.convo
    llm = getattr(convo, "_llm", None) if convo is not None else None
    return {"echo": bool(getattr(convo, "echo", False)),
            "profile": cfg.llm.profile, "model": cfg.llm.model,
            "prompt": cfg.llm.system_prompt, "reading_rules": cfg.reading.rules,
            "rules_active": bool(getattr(llm, "extra_rules", "")),
            "history": [dict(m) for m in list(getattr(llm, "_history", ()))],
            "history_max": cfg.llm.max_history_turns * 2,
            "stt_prompt": cfg.stt.prompt, "stt_keywords": list(cfg.stt.keywords or ()),
            "tts_instructions": cfg.tts.openai_instructions if cfg.tts.backend == "openai" else "",
            "badge_prompt": cfg.reading.badge_prompt}


def _checks(st: dict, hub) -> list:
    from . import debug_checks
    return debug_checks.run(st, hub)


def _flags(hub) -> dict:
    a = hub.args
    names = ("dry_run", "text", "echo", "no_audio", "viz")
    return {n: bool(getattr(a, n, False)) for n in names} if a is not None else {}


def _page(hub) -> dict:
    """What the operator's page needs to show its tools: the visit, the reader, the limits.
    (/status has the same facts for the old face; this page reads only the debug state.)"""
    viz, cfg = getattr(hub, "viz", None), hub.cfg
    visit = getattr(viz, "_visit", None) if viz is not None else None
    tls = getattr(viz, "_tls_httpd", None) if viz is not None else None
    show = getattr(getattr(hub, "convo", None), "show", None)
    view = visit.view() if visit is not None else None
    if view is not None and show is not None:
        view["show"] = show.view()             # the scripted visit's buttons after a reload
    return {"visit_enabled": visit is not None and bool(cfg.visit.enabled),
            "visit": view,
            "reading": getattr(viz, "_reader", None) is not None,
            "reading_look": bool(cfg.reading.look),
            "max_record_s": float(cfg.ptt.max_record_s),
            "capture": cfg.ptt.capture,
            "tls_port": cfg.viz.tls_port if tls is not None else None,
            "tls_error": getattr(viz, "tls_error", None) if viz is not None else None}


def _pron(cfg) -> list[str]:
    """The pronunciation candidates the Voice tab can play (loq only)."""
    from .say_as import CANDIDATES
    return [label for label, _ in CANDIDATES] if cfg.tts.backend == "loq" else []


def build(hub) -> dict:
    cfg = hub.cfg
    st = {"ok": True, "boot": hub.boot, "now": round(time.time(), 3),
          "started": round(hub.started, 3), "seq": hub.seq, "hub_errors": hub.errors,
          "host": os.uname().nodename}
    st["flags"] = _section(lambda: _flags(hub))
    st["version"] = _section(lambda: {**version(), "changed_since_start": hub.code_changed()})
    st["mode"] = _section(lambda: _mode(hub))
    st["page"] = _section(lambda: _page(hub))
    st["pron"] = _section(lambda: _pron(cfg))
    st["remote"] = _section(lambda: _remote(hub))
    st["link"] = _section(lambda: _link(hub))
    st["backends"] = _section(lambda: _backends(hub))
    st["canned"] = _section(lambda: _canned(hub))
    st["clients"] = _section(lambda: _clients(hub))
    st["system"] = _section(system)
    st["service"] = _section(service)
    st["rec"] = _section(hub.recording_stats)
    st["config"] = _section(lambda: config_view(cfg))
    st["token"] = bool(cfg.viz.token)
    if hub.actions is not None:
        st["motor_lines"] = _section(hub.actions.planned_lines)
        st["switches"] = _section(hub.actions.switches)
    st["model"] = _section(lambda: _model(hub))
    st["checks"] = _section(lambda: _checks(st, hub))
    if isinstance(st["checks"], list):
        from . import debug_checks
        st["checks_summary"] = debug_checks.summary(st["checks"])
    st["hints"] = _section(lambda: hints(st, hub))
    return st


# ---- hints: a signal, a plain sentence, the fix ----------------------------------------------

def hints(st: dict, hub) -> list[dict]:
    out: list[dict] = []

    def add(level, panel, text, fix=""):
        out.append({"level": level, "panel": panel, "text": text, "fix": fix})

    remote = st.get("remote") or {}
    other = remote.get("other_keys") or {}
    if other and remote.get("present"):
        presses = hub.recent("press", 20)
        last_ok = max((p["t"] for p in presses if p.get("configured")), default=0)
        last_bad = [p for p in presses if not p.get("configured") and p["t"] > last_ok]
        if last_bad:
            p = last_bad[-1]
            n = sum(1 for q in last_bad if q["key"] == p["key"])
            keys = remote.get("keys", "")
            add("bad", "inputs",
                f"{p['key']} arrived {n} time(s) from '{p['name']}' while the fish listens for "
                f"{keys}: the remote sends another key for that button.",
                f"FISH_PTT_KEY={keys.replace('+', ',')},{p['key']} in .env, then restart")
    if remote.get("present") and not remote.get("devices"):
        add("bad", "inputs", "No remote: its dongle is unplugged, asleep or unreadable.",
            "press a key on it; check the hub; the user must be in the input group")
    taps = [p for p in hub.recent("press", 6) if p.get("configured")][-3:]
    if len(taps) == 3 and all(p["held_s"] < 0.2 for p in taps):
        add("warn", "inputs", f"{taps[-1]['key']} only taps ({taps[-1]['held_s']} s each): "
            "it cannot be held to talk.", "use another key, or FISH_PTT_MODE=toggle")

    rec = st.get("rec") or {}
    if rec.get("zero_frac", 0) > 0.95 and rec.get("samples"):
        add("bad", "inputs", "The last recording is digital zeros: the microphone opened but "
            "sent nothing.", "press again; if it repeats, replug it or pick another source")
    elif "rms" in rec and rec["rms"] < getattr(hub.cfg.ptt, "silence_rms", 0.005):
        add("warn", "inputs", f"The last recording is near silence (rms {rec['rms']}).",
            "check which source is selected against the default one")

    svc = st.get("service") or {}
    if svc.get("supervised") and svc.get("enabled") is False:
        add("bad", "board", "fish-brain is not enabled: after the next reboot there is no fish.",
            "systemctl --user enable fish-brain (for motor tests: deploy/unoq_setup.sh bench on)")
    if svc.get("bench"):
        add("warn", "motors", "BENCH: the fish runs with no motors (deploy/unoq_setup.sh bench on).",
            "deploy/unoq_setup.sh bench off before a show")
    if (st.get("page") or {}).get("tls_error"):
        add("bad", "switches", "No https: the certificate could not be loaded, so the phone's "
            "microphone and screen lock are off. The page still works over http.",
            "deploy/unoq_setup.sh tls, then restart")
    flags, be, mode = st.get("flags") or {}, st.get("backends") or {}, st.get("mode") or {}
    if be.get("echo", flags.get("echo")):         # as it runs now, not as it was started
        add("warn", "switches", "ECHO mode: the fish only repeats what it hears.",
            "Switches tab: Mode → llm (a restart brings back what the unit says)")
    if flags.get("dry_run"):
        add("info", "motors", "DRY RUN: the mock link, nothing moves.")
    if mode.get("wait"):
        add("warn", "voice", "Wait-to-speak is on: replies wait in the text box.",
            "untick it in the Voice panel")
    if (st.get("version") or {}).get("changed_since_start"):
        add("warn", "board", "The code on disk changed after this process started: the "
            "running fish is the old code.", "restart fish-brain")

    link = st.get("link") or {}
    if link.get("muted"):
        add("warn", "switches", "The motors are muted: every motor line is dropped.",
            "Switches tab: Motors → on (armed)")
    if link.get("health") == "off":
        add("bad", "motors", f"Voice only: the motor link is not attached ({link.get('desc')}).",
            "check the port and the router; it retries by itself")
    elif link.get("health") == "silent":
        add("bad", "motors", f"The MCU is silent: {link.get('unanswered', '?')} lines "
            "unanswered.", "LED4 must blink green; look at the bytes back in Motors")
    if be.get("online") is False:
        add("bad", "cloud", "No internet: cloud stages will fail.", "check the hotspot's data")
    for name, present in (be.get("keys") or {}).items():
        if not present and not (name != "OPENAI_API_KEY" and be.get("echo")
                                and name not in (be.get("stt_keys") or ())):
            add("warn", "cloud", f"{name} is not set.", "add it to .env, then restart")

    turns = hub.recent("turn", 5)
    if turns:
        last = turns[-1]
        perf = last.get("perf") or {}
        if perf.get("result") not in (None, "ok"):
            add("bad", "voice", "The last reply was not heard: playback failed "
                f"({(perf.get('error') or {}).get('type', perf.get('result'))}). The phone page "
                "animated anyway.", "check the default sink and the speaker's cable")
        slow = [(k, v) for k, v in (last.get("times") or {}).items()
                if (k, v > 3.0) in (("stt", True), ("tts", True)) or (k == "llm" and v > 5.0)]
        for k, v in slow:
            add("warn", "cloud", f"{k} took {v:.1f} s in the last turn.",
                "first call after a start, or the network")
        if len(turns) >= 3 and all(t.get("outcome") == "not understood" for t in turns[-3:]):
            add("warn", "inputs", "Three turns in a row were not understood although the "
                "microphone had signal.", "listen to the last recording; check the language")
    for r in st.get("checks") if isinstance(st.get("checks"), list) else []:
        if r["status"] == "fail" and r["group"] in ("Speaker", "Microphone") \
                and r["name"] != "The last recording has signal":
            add("bad", "checks", f"{r['group']}: {r['name']} — {r['detail']}.", r["fix"])
    svc = st.get("system") or {}
    if svc.get("usb_role") and "[host]" not in svc["usb_role"]:
        add("bad", "board", "The board is a USB device, not a host: nothing on the hub is seen.",
            "change the USB-C cable")
    return out
