"""One device table (ADR 0021): whether each part of the fish is there, failed or in use.

Pure functions over a `Facts` record. `debug_state._facts(hub)` reads the machine once per
`/debug/state` build and fills it; nothing here opens a file, runs a program or touches
another thread's objects, so every rule is a unit test. The defaults of `Facts` are a laptop
with nothing set: no type-C port, no remote, no speaker routes, the board's microphone.

The record, one per part in this fixed order (`IDS`):

    {id, label, present, marked, dead, in_use, level, state, reason, fix, tab}

    present   True / False, or None when it cannot be known here
    marked    the operator marked it failed (hw.py)
    dead      it is there but does not work (zeros from the microphone, a silent MCU, ...)
    in_use    a phone page is the thing playing or recording now (the phone rows, and the
              speaker or microphone whose work a phone took over)
    level     ok | warn | bad | off (off = not applicable here: the page hides the row)
    state     a few words: what it is now ("host", "USB", "this phone", "marked failed")
    reason    why the level is not ok ("" when it is)
    fix       what to do about it ("" when nothing)
    tab       the debug view's panel where it is looked at (the hints' `panel`)

`mic` also carries `capture` (as configured), `recorder` (`host` | `browser`, who records the
next hold), `out` (the board cannot hear: marked, its source gone or zeros) and `last_rec`; the
phone rows carry `pages`.

Precedence, the same for every part:

1. marked beats present: a part he marked failed is out even when it is detected;
2. dead beats present: a part that is there but sends nothing is out;
3. `in_use` only while a phone page is the thing playing or recording;
4. the level follows the fallback in use: a fault with a working fallback is `warn`, a fault
   with none is `bad`.

Derivation:

| id | from | ok | warn | bad | off |
|---|---|---|---|---|---|
| usb_port | the type-C data role | host | | device | no type-C port (laptop) |
| usb_devices | /sys/bus/usb products, root hubs left out | some | none seen | | no type-C port |
| speaker | mark, the next route, the sinks, the playback cards, --no-audio, the last playback | USB (or the default sink without routes) | marked, Bluetooth or a phone took over, the last playback failed, --no-audio | no route left, no player | |
| mic | mark, the configured source, two zero takes, the last recording, phone pages | the board records, or the phone by configuration | out or marked with a phone recording, a near-silent last take, browser capture with no phone | out or marked with no phone | |
| remote | the configured device, its devices, its thread, the mark | devices read | marked, none found, its thread stopped (the page's hold remains) | | none configured |
| motors | the link (attached, health, muted, mock), bench mode, the mark | attached, or the mock | bench, marked (muted), muted by the switch, not opened yet | off or a silent MCU | |
| internet | the mark, the probe, fish-net's state, whether the script covers an outage | online | marked or offline with the script covering it | marked or offline with a cloud stage in the turn path | |
| phone_speaker | the routes, the pages that armed it, the next route | armed, or not needed | needed (no other route) and not armed | | `phone` not among the routes |
| phone_mic | capture, the mark, the board microphone, the pages | a page ready, or not needed | needed and no page ready | | capture `host`, nothing marked or out, no page |
| printer | FISH_PRINTER, the fortune's ticket switch, the worker's snapshot (printer.py) | not checked yet, ready, printing #n, mock | misconfigured, did not start, its worker stopped, not reachable, the last ticket stalled or dropped | never: the reading is spoken and Reprint prints it later | none configured, tickets off |

`printer` is not a hardware mark (hw.PARTS): a ticket is an extra, never the act.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field

IDS = ("usb_port", "usb_devices", "speaker", "mic", "remote", "motors", "internet",
       "phone_speaker", "phone_mic", "printer")
LABELS = {"usb_port": "USB port", "usb_devices": "USB devices", "speaker": "Speaker",
          "mic": "Microphone", "remote": "Remote", "motors": "Motors", "internet": "Internet",
          "phone_speaker": "Phone speaker", "phone_mic": "Phone microphone",
          "printer": "Ticket printer"}
TABS = {"usb_port": "board", "usb_devices": "board", "speaker": "voice", "mic": "inputs",
        "remote": "inputs", "motors": "motors", "internet": "cloud", "phone_speaker": "voice",
        "phone_mic": "inputs", "printer": "visit"}
LEVELS = ("ok", "warn", "bad", "off")
ZERO_FRAC = 0.95            # a recording this much exact zeros: the microphone sent nothing


@dataclass
class Facts:
    """What the table is derived from. The defaults: a laptop with no environment set."""
    usb_role: str = ""                       # /sys/class/typec/port0/data_role; "" = no port
    usb_products: list = field(default_factory=list)
    marks: frozenset = frozenset()           # parts marked failed (hw.PARTS)
    bench: bool = False                      # the unit's bench drop-in
    no_audio: bool = False                   # --no-audio
    player: str = ""                         # the player's class name ("" = not built yet)
    audio_routes: list = field(default_factory=list)   # FISH_AUDIO_ROUTES
    audio_route: str = "default"             # the route of the last phrase played
    audio_next: str = "default"              # the route the next phrase takes
    sinks: list = field(default_factory=list)          # PipeWire sink names
    cooling: list = field(default_factory=list)        # routes resting after a failure
    playback_cards: int | None = None        # ALSA cards that play (None = not read)
    capture_cards: int | None = None
    last_play: str = ""                      # the last turn's playback result ("" / ok / error)
    capture: str = "host"                    # FISH_MIC_CAPTURE
    mic_source: str = ""                     # FISH_MIC_SOURCE
    mic_source_present: bool | None = None   # None: no source named, or not listable
    mic_zeroed: bool = False                 # two takes of exact zeros in a row
    last_rec: dict = field(default_factory=dict)       # rms, zero_frac, samples, origin
    silence_rms: float = 0.005
    mic_pages: int = 0                       # pages with their microphone ready
    speaker_pages: int = 0                   # pages armed as the hat's speaker
    remote_device: str = ""                  # FISH_PTT_DEVICE
    remote_devices: int | None = None        # devices read (None: no button built)
    remote_alive: bool | None = None         # its reader thread
    remote_keys: str = ""
    link: dict = field(default_factory=dict) # debug_state._link
    online: bool = True                      # cloud.is_online()
    net_state: str = ""                      # fish-net: "client", "ap", ...
    net_connection: str = ""
    offline_ok: bool = False                 # the script and local stages cover an outage
    printer: dict = field(default_factory=dict)        # debug_state._printer ({} = none set)


def _rec(id_, *, present=None, marked=False, dead=False, in_use=False, level="ok",
         state="", reason="", fix="", **extra) -> dict:
    out = {"id": id_, "label": LABELS[id_], "present": present, "marked": bool(marked),
           "dead": bool(dead), "in_use": bool(in_use), "level": level, "state": state,
           "reason": reason if level != "ok" else "", "fix": fix if level not in ("ok", "off") else "",
           "tab": TABS[id_]}
    out.update(extra)
    return out


# ---- decisions the acts call ----------------------------------------------------------------

def usb_host(role: str) -> bool | None:
    """The board's USB-C port is the host (True), a device (False); None: no type-C port."""
    if not role:
        return None
    return "[host]" in role


def recorder(capture: str, mic_marked: bool, mic_out: bool, mic_pages: int) -> str:
    """Who records the next hold: `browser` (a phone page with its microphone ready) or
    `host` (the board's microphone). A phone is wanted when the capture is `browser`, the
    microphone is marked failed, or the capture is `auto` and the board's microphone is out;
    with no phone ready the board records anyway."""
    want_phone = capture == "browser" or mic_marked or (capture == "auto" and mic_out)
    return "browser" if want_phone and mic_pages > 0 else "host"


def _name(sink) -> str:
    return sink.get("name", "") if isinstance(sink, dict) else str(sink)


def speaker_routes(routes, speaker_marked: bool, sinks, speaker_pages: int,
                   cooling, now: float = 0.0) -> list[tuple[str, str]]:
    """The routes a phrase can take now, in order, as (route, sink node name). A route that
    cools is skipped (`cooling`: a {route: until} map, or a list of routes cooling now); a
    marked speaker removes the USB routes; `phone` needs an armed page."""
    if isinstance(cooling, dict):
        resting = {r for r, until in cooling.items() if until > now}
    else:
        resting = set(cooling or ())
    names = [_name(s) for s in sinks or ()]
    out = []
    for route in routes or ():
        if route in resting:
            continue
        if route.startswith("alsa_output.usb") and speaker_marked:
            continue
        if route == "phone":
            if speaker_pages > 0:
                out.append((route, ""))
            continue
        node = next((n for n in names if fnmatch.fnmatch(n, route)), None)
        if node is not None:
            out.append((route, node))
    return out


def internet(marked: bool, online: bool) -> tuple[bool, str]:
    """Whether the model can be reached, and why not (the acts' why strings)."""
    if marked:
        return False, "internet marked failed"
    if not online:
        return False, "offline"
    return True, "online"


def check_status(level: str) -> str:
    """A device level as a bring-up check's status."""
    return {"ok": "pass", "warn": "warn", "bad": "fail"}.get(level, "skip")


# ---- the rows ---------------------------------------------------------------------------------

def _where(route: str) -> str:
    if route == "none":
        return "none"
    if route == "phone":
        return "this phone"
    if route.startswith("bluez"):
        return "Bluetooth"
    if route.startswith("alsa_output.usb"):
        return "USB"
    if route.startswith("alsa"):
        return "built-in"
    return "default"


def _usb_port(f: Facts) -> dict:
    host = usb_host(f.usb_role)
    if host is None:
        return _rec("usb_port", level="off", state="no type-C port")
    if host:
        return _rec("usb_port", present=True, state="host")
    return _rec("usb_port", present=True, level="bad", state="device",
                reason="the board is a USB device: nothing on the hub is seen",
                fix="change the USB-C cable")


def _usb_devices(f: Facts) -> dict:
    if usb_host(f.usb_role) is None:
        return _rec("usb_devices", level="off", state="no type-C port")
    seen = [p for p in f.usb_products if p and "Host Controller" not in p]
    if seen:
        return _rec("usb_devices", present=True, state=", ".join(seen))
    return _rec("usb_devices", present=False, level="warn", state="none",
                reason="nothing seen on USB", fix="check the hub and its power")


def _speaker(f: Facts) -> dict:
    marked = "speaker" in f.marks
    dead = f.last_play not in ("", "ok")
    nxt = f.audio_next or "default"
    phone = nxt == "phone"
    if f.audio_routes:
        usb = [r for r in f.audio_routes if r.startswith("alsa_output.usb")]
        names = [_name(s) for s in f.sinks]
        present = any(fnmatch.fnmatch(n, r) for r in usb for n in names) if usb else None
    else:
        present = (f.playback_cards > 0) if f.playback_cards is not None else None
    where = _where(nxt)
    if f.no_audio:
        return _rec("speaker", present=present, marked=marked, level="warn",
                    state="silent (--no-audio)", reason="the fish plays no sound")
    if f.player == "SilentPlayer":
        return _rec("speaker", present=present, marked=marked, dead=True, level="bad",
                    state="no player", reason="no player could be made",
                    fix="is sounddevice or pw-play installed?")
    if nxt == "none":
        return _rec("speaker", present=present, marked=marked, dead=dead, level="bad",
                    state="none", reason="no speaker route left",
                    fix="plug in a speaker or tap 'Use this phone as a speaker'")
    fallback = bool(f.audio_routes) and nxt != f.audio_routes[0]
    if marked or fallback:
        why = ("USB marked failed" if marked else
               "the first route is cooling" if f.audio_routes[0] in f.cooling else
               "the first route is missing")
        return _rec("speaker", present=present, marked=marked, dead=dead, in_use=phone,
                    level="warn", state=where, reason=why,
                    fix="clear the mark once the USB speaker is back" if marked
                    else "plug the USB speaker into the hub")
    if dead:
        return _rec("speaker", present=present, dead=True, in_use=phone, level="warn",
                    state=where, reason="the last reply was not heard",
                    fix="check the speaker's cable and the sink")
    if present is False:
        return _rec("speaker", present=False, level="warn", state=where,
                    reason="no playback card", fix="plug in a speaker")
    return _rec("speaker", present=present, in_use=phone, state=where)


def _mic_out(f: Facts) -> bool:
    return f.mic_source_present is False or f.mic_zeroed


def _mic(f: Facts) -> dict:
    marked = "mic" in f.marks
    out = _mic_out(f)
    who = recorder(f.capture, marked, out, f.mic_pages)
    rec = f.last_rec or {}
    zeros = bool(rec.get("samples")) and rec.get("zero_frac", 0) > ZERO_FRAC
    quiet = bool(rec.get("samples")) and "rms" in rec and rec["rms"] < f.silence_rms
    if f.mic_source_present is not None:
        present = f.mic_source_present
    else:
        present = (f.capture_cards > 0) if f.capture_cards is not None else None
    extra = {"capture": f.capture, "recorder": who, "last_rec": dict(rec), "out": marked or out}
    common = dict(present=present, marked=marked, dead=f.mic_zeroed or zeros,
                  in_use=who == "browser", **extra)
    if marked or out:
        why = ("marked failed" if marked else "the remote sends silence" if f.mic_zeroed
               else "its source is gone")
        if who == "browser":
            return _rec("mic", level="warn", state="this phone", reason=why,
                        fix="clear the mark once the microphone is back" if marked
                        else "replug the remote's dongle", **common)
        return _rec("mic", level="bad", state="board", reason=why,
                    fix="turn on this phone's microphone", **common)
    if f.capture == "browser":
        if who == "browser":
            return _rec("mic", state="this phone", **common)
        return _rec("mic", level="warn", state="board",
                    reason="no phone has its microphone on",
                    fix="turn on this phone's microphone", **common)
    if zeros:
        return _rec("mic", level="warn", state="board",
                    reason="the last recording is digital zeros",
                    fix="press again; if it repeats, replug it", **common)
    if quiet:
        return _rec("mic", level="warn", state="board",
                    reason=f"the last recording is near silence (rms {rec.get('rms')})",
                    fix="check which source is selected", **common)
    if present is False:
        return _rec("mic", level="warn", state="board", reason="no capture card",
                    fix="plug the microphone into the hub", **common)
    return _rec("mic", state="this phone" if who == "browser" else "board", **common)


def _remote(f: Facts) -> dict:
    if not f.remote_device:
        return _rec("remote", level="off", state="none configured")
    marked = "remote" in f.marks
    n = f.remote_devices
    present = None if n is None else n > 0
    if marked:
        return _rec("remote", present=present, marked=True, level="warn", state="marked failed",
                    reason="its presses are not used", fix="use Hold to talk on this page")
    if f.remote_alive is False:
        return _rec("remote", present=present, dead=True, level="warn", state="not read",
                    reason="its reader stopped", fix="use Hold to talk on this page; restart")
    if not n:
        return _rec("remote", present=False if n == 0 else None, level="warn",
                    state="not found", reason="its dongle is unplugged, asleep or unreadable",
                    fix="press a key on it; check the hub; meanwhile Hold to talk on this page")
    return _rec("remote", present=True, state="connected" + (f" ({n})" if n > 1 else ""))


def _motors(f: Facts) -> dict:
    link = f.link or {}
    marked = "motors" in f.marks
    kind = link.get("kind", "none")
    health = link.get("health", "")
    attached = bool(link.get("attached"))
    present = attached if kind != "none" else None
    if marked:
        return _rec("motors", present=present, marked=True, level="warn",
                    state="marked failed (muted)", reason="nothing moves",
                    fix="clear the mark when the motors are back")
    if f.bench:
        return _rec("motors", present=present, level="warn", state="bench mode",
                    reason="the fish runs with no motors", fix="deploy/unoq_setup.sh bench off")
    if kind == "none":
        return _rec("motors", level="warn", state="not opened yet",
                    reason="the link is not open", fix="wait for the start-up")
    if link.get("mock"):
        return _rec("motors", present=True, state="mock: nothing moves")
    if health == "off" or not attached:
        return _rec("motors", present=False, level="bad", state="not connected",
                    reason="the hat talks without moving",
                    fix="check the port and the router; it retries by itself")
    if health == "silent":
        return _rec("motors", present=True, dead=True, level="bad", state="MCU silent",
                    reason=f"{link.get('unanswered', '?')} lines unanswered",
                    fix="LED4 must blink green; Ping in the Motors tab")
    if link.get("muted"):
        return _rec("motors", present=True, level="warn", state="muted",
                    reason="every motor line is dropped", fix="Switches: Motors → on (armed)")
    return _rec("motors", present=True, state="connected")


def _internet(f: Facts) -> dict:
    marked = "internet" in f.marks
    usable, why = internet(marked, f.online)
    conn = f.net_connection
    if f.net_state == "ap":
        conn = "own Wi-Fi (no internet)"
    if usable:
        return _rec("internet", present=True, state="online" + (f" · {conn}" if conn else ""))
    level = "warn" if f.offline_ok else "bad"
    state = "marked failed" if marked else "offline" + (f" · {conn}" if conn else "")
    fix = ("visits run on the script" if f.offline_ok else
           "check the hotspot's data" if not marked else "clear the mark when it is back")
    return _rec("internet", present=None if marked else False, marked=marked, level=level,
                state=state, reason=why if marked else "cloud stages fail" + (
                    "; the script covers it" if f.offline_ok else ""), fix=fix)


def _phone_speaker(f: Facts) -> dict:
    if "phone" not in (f.audio_routes or ()):
        return _rec("phone_speaker", level="off", state="not a route", pages=f.speaker_pages)
    n = f.speaker_pages
    in_use = f.audio_next == "phone"
    if n > 0:
        return _rec("phone_speaker", present=True, in_use=in_use,
                    state="playing" if in_use else "armed", pages=n)
    if f.audio_next == "none":
        return _rec("phone_speaker", present=False, level="warn", state="not armed",
                    reason="no other speaker is left",
                    fix="tap 'Use this phone as a speaker'", pages=0)
    return _rec("phone_speaker", present=False, state="not armed (not needed)", pages=0)


def _phone_mic(f: Facts) -> dict:
    marked = "mic" in f.marks
    out = _mic_out(f)
    n = f.mic_pages
    wanted = f.capture == "browser" or marked or (f.capture == "auto" and out)
    if f.capture == "host" and not marked and not out and n == 0:
        return _rec("phone_mic", level="off", state="not used", pages=0)
    who = recorder(f.capture, marked, out, n)
    if n > 0:
        return _rec("phone_mic", present=True, in_use=who == "browser",
                    state="recording the holds" if who == "browser" else "ready", pages=n)
    if wanted:
        return _rec("phone_mic", present=False, level="warn", state="off",
                    reason="the board's microphone records instead",
                    fix="turn on this phone's microphone", pages=0)
    return _rec("phone_mic", present=False, state="off (not needed)", pages=0)


def _printer(f: Facts) -> dict:
    p = f.printer or {}
    setting = p.get("setting", "off")
    if setting == "off":
        return _rec("printer", level="off", state="none configured")
    if setting == "bad":
        return _rec("printer", level="warn", state="misconfigured",
                    reason=p.get("problem") or "FISH_PRINTER is not usable",
                    fix="set FISH_PRINTER to the printer's address (or mock) and restart")
    if not p.get("present"):
        return _rec("printer", level="warn", state="did not start",
                    reason="no tickets this run", fix="see the [printer] line in the log")
    if not p.get("tickets", True):
        return _rec("printer", present=p.get("reach"), level="off", state="tickets off")
    if p.get("alive") is False:
        return _rec("printer", dead=True, level="warn", state="stopped",
                    reason="its worker stopped: no ticket prints", fix="restart the hat")
    n, state, why = p.get("n"), p.get("state", "idle"), p.get("why", "")
    reach = p.get("reach")
    if state in ("queued", "connecting", "printing"):
        return _rec("printer", present=reach, state=f"printing #{n}" if n else "printing")
    if reach is False:
        return _rec("printer", present=False, level="warn", state="not reachable",
                    reason=why or "the last connect failed",
                    fix="is it on, charged, with paper? Reprint once it is")
    if state == "failed" and why.startswith(("stalled", "dropped")):
        return _rec("printer", present=True, level="warn", state=f"ticket #{n} failed",
                    reason=why, fix="check the paper and the battery; Reprint")
    mock = "mock: " if p.get("device") == "mock" else ""
    if reach is None:
        return _rec("printer", state=mock + "not checked yet")
    printed = p.get("printed") or 0
    return _rec("printer", present=True,
                state=mock + "ready" + (f" · {printed} printed" if printed else ""))


_ROWS = {"usb_port": _usb_port, "usb_devices": _usb_devices, "speaker": _speaker, "mic": _mic,
         "remote": _remote, "motors": _motors, "internet": _internet,
         "phone_speaker": _phone_speaker, "phone_mic": _phone_mic, "printer": _printer}


def build(f: Facts) -> list[dict]:
    """The table, one record per part in `IDS` order."""
    return [_ROWS[i](f) for i in IDS]


def by_id(table: list[dict]) -> dict:
    return {d["id"]: d for d in table}


def summary(table: list[dict]) -> dict:
    """The worst level among the rows that apply, the rows behind it, and one line."""
    bad = [d for d in table if d["level"] == "bad"]
    warn = [d for d in table if d["level"] == "warn"]

    def say(d):
        return d["label"] + " · " + (d["state"] or d["reason"])
    if bad:
        level, text = "bad", "Check: " + "; ".join(say(d) for d in bad)
    elif warn:
        level, text = "warn", "Ready, with a warning: " + "; ".join(say(d) for d in warn)
    else:
        level, text = "ok", "Ready for visitors"
    return {"level": level, "bad": [d["id"] for d in bad], "warn": [d["id"] for d in warn],
            "text": text}


def hints_for(table: list[dict]) -> list[dict]:
    """One hint per bad device, on its panel (the shape of debug_state.hints)."""
    out = []
    for d in table:
        if d["level"] == "bad":
            text = f"{d['label']}: {d['state']}" + (f" ({d['reason']})" if d["reason"] else "") + "."
            out.append({"level": "bad", "panel": d["tab"], "text": text, "fix": d["fix"]})
    return out
