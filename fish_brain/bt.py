"""Bluetooth speakers from the operator's page (ADR 0031): find one, tap it, the hat speaks there.

One worker thread owns every call that can take long, so a page's request never waits on the
radio and `snapshot()` is only a locked copy. `use(mac)` stops the search, pairs, trusts, connects
and waits for a PipeWire sink; only a sink makes a speaker Ready, because `Connect` succeeds when
any one profile connects. The chosen speaker's route goes ahead of FISH_AUDIO_ROUTES through
`with_chosen`, and devices.speaker_routes skips it while its sink is missing, so a lost speaker
falls back to USB by itself. The MP210 is never listed and cannot be forgotten from here.

A search is refused during a turn or a ticket and stops if one starts. A speaker that dropped is
retried with a backoff, never during a turn, an act, a ticket or a search. The board stays hidden:
only pairings started from the page have an agent to answer them.

`Bus` is the seam: `bt_bluez.DbusBus` talks to BlueZ (imported only with FISH_BLUETOOTH=on),
`FakeBus` here is the stand-in for FISH_BLUETOOTH=mock and the tests. Timers are estimates until
docs/results says otherwise; so is the map from BlueZ's errors to the sentences.
"""
from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
from pathlib import Path

from . import debug

ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
BATTERY = "org.bluez.Battery1"
A2DP_SINK = "0000110b-0000-1000-8000-00805f9b34fb"

SCAN_S = 20.0            # one search (estimate)
PAIR_S = 60.0            # longer than ASK_S, so the limit never ends a PIN being typed
ASK_S = 45.0             # his answer to a PIN or a number
CONNECT_S = 30.0
RECONNECT_CALL_S = 12.0  # a reconnect holds the worker; a failed page takes about 5 s (estimate)
SINK_S = 10.0            # from connected to a sink (estimate)
RETRY_FAST_S = 20.0      # after a drop: this often for RETRY_FAST tries, then RETRY_SLOW_S (estimates)
RETRY_FAST = 5
RETRY_SLOW_S = 60.0
TICK_BUSY_S = 1.0
TICK_IDLE_S = 3.0
DELAY_MS = 200           # the mouth's delay until he steps it (estimate, shown as one)
DELAY_MAX_MS = 800
NEAR_RSSI = -60          # "next to the fish" at first sight, for the order only (estimate)
NEARBY_CAP = 30

# Major device classes that are not speakers: computer, phone, LAN, peripheral, imaging, wearable,
# toy, health. Anything else, and a device with no class, may be one (some show audio only after
# pairing), so a named unknown stays in the list.
NON_AUDIO = {1, 2, 3, 5, 6, 7, 8, 9}
MAJOR_AV, MAJOR_IMAGING = 4, 6

SENTENCES = {
    "refused": "It refused. Is it in pairing mode?",
    "no_answer": "It didn't answer.",
    "off_or_far": "Off, or too far.",
    "held": "Busy. Is a phone connected to it?",
    "key_lost": "It forgot the hat. Forget it and pair again.",
    "no_sink": "Connected, but no sound path.",
    "gone": "Can't see it any more. Is it in pairing mode?",
    "internal": "Bluetooth failed. See the log.",
}


class BusError(RuntimeError):
    """A failed call: `name` is the D-Bus error (org.bluez.Error.Failed …), `text` its message."""

    def __init__(self, name: str, text: str = ""):
        super().__init__(f"{name}: {text}" if text else name)
        self.name, self.text = name, text


class BusTimeout(BusError):
    def __init__(self, what: str = ""):
        super().__init__("timeout", what)


def error_code(e: BusError) -> str:
    """The sentence for a failed call. My reading of BlueZ's error.h: results correct it."""
    if isinstance(e, BusTimeout):
        return "no_answer"
    both = f"{e.name} {e.text}"
    for needle, code in (("key-missing", "key_lost"),
                         ("AuthenticationFailed", "refused"), ("AuthenticationRejected", "refused"),
                         ("AuthenticationTimeout", "no_answer"), ("AuthenticationCanceled", "no_answer"),
                         ("connection-refused", "held"), ("connection-busy", "held"),
                         ("profile-unavailable", "held"), ("page-timeout", "off_or_far"),
                         ("ConnectionAttemptFailed", "off_or_far"), ("UnknownObject", "gone"),
                         ("DoesNotExist", "gone")):
        if needle in both:
            return code
    return "off_or_far"


def sink_pattern(mac: str) -> str:
    """The route of one speaker. Not `bluez_output_internal`, and not any other speaker."""
    return f"bluez_output.{mac.upper().replace(':', '_')}.*"


def _major(props: dict) -> int | None:
    cls = props.get("Class")
    return (int(cls) >> 8) & 0x1f if cls is not None else None


def is_printer(props: dict, printer_mac: str = "") -> bool:
    return (bool(printer_mac) and props.get("Address", "").upper() == printer_mac.upper()
            or _major(props) == MAJOR_IMAGING or props.get("Icon") == "printer")


def _is_audio(props: dict) -> bool:
    return (A2DP_SINK in (props.get("UUIDs") or ()) or _major(props) == MAJOR_AV
            or str(props.get("Icon") or "").startswith("audio-"))


def kind_of(props: dict) -> str:
    icon = str(props.get("Icon") or "")
    if icon in ("audio-headphones", "audio-headset"):
        return "headphones"
    return "speaker" if _is_audio(props) else "unknown"


def devices_in(objects: dict) -> dict[str, tuple[str, dict]]:
    """GetManagedObjects -> {MAC: (path, the Device1 properties plus `Battery`)}."""
    out = {}
    for path, ifaces in (objects or {}).items():
        props = ifaces.get(DEVICE)
        if props and props.get("Address"):
            props = dict(props)
            battery = ifaces.get(BATTERY) or {}
            if "Percentage" in battery:
                props["Battery"] = battery["Percentage"]
            out[props["Address"].upper()] = (path, props)
    return out


def adapter_in(objects: dict) -> tuple[str, dict] | None:
    for path in sorted(objects or {}):
        if ADAPTER in objects[path]:
            return path, objects[path][ADAPTER]
    return None


def name_of(props: dict) -> str:
    """BlueZ's Alias falls back to the address: an unnamed device has no `Name`."""
    if props.get("Name"):
        return str(props.get("Alias") or props["Name"])
    return "Unnamed " + props.get("Address", "")[-5:]


def sort_lists(devs: dict, printer_mac: str = "") -> tuple[list, list, list]:
    """The MACs of (my speakers, nearby, the rest). The printer is in none of them."""
    mine, nearby, others = [], [], []
    for mac, (_, p) in devs.items():
        if is_printer(p, printer_mac):
            continue
        if p.get("Paired"):
            (mine if _is_audio(p) else others).append(mac)
        elif p.get("Name") and (_major(p) is None or _major(p) not in NON_AUDIO):
            nearby.append(mac)
        else:
            others.append(mac)
    return mine, nearby, others


def _default_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    return Path(base) / "fish_brain" / "bt.json"


class BtManager:
    def __init__(self, bus, *, printer_mac: str = "", busy=None, sinks=None, poke=None,
                 path=None, clock=time.monotonic, setting: str = "on"):
        self.bus, self.printer_mac, self.setting = bus, printer_mac.upper(), setting
        self.busy = busy or (lambda: "")     # a reason ("printing", "busy") or ""; set by app.py
        self._sinks = sinks or (lambda: [])
        self._poke = poke or (lambda: None)
        self.path = Path(path) if path else _default_path()
        self._clock = clock
        self.sink_s, self.scan_s, self.ask_s = SINK_S, SCAN_S, ASK_S
        self._lock = threading.RLock()
        self._jobs: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._objects: dict = {}
        self.alive, self.problem = False, ""
        self.phase, self.step = "idle", ""
        self.target = ""
        self._scan_until = 0.0
        self._scanning = False               # BlueZ was told to search
        self._order: dict[str, tuple] = {}   # the rows' frozen order: fixed at first sight
        self._ask: dict | None = None
        self._ask_reply: queue.Queue = queue.Queue(1)
        self._pin_tried = False
        self._cancel = False
        self.result: dict | None = None
        self.chosen, self.chosen_name = "", ""
        self.delays: dict[str, int] = {}
        self._was_ready = False
        self._tries, self._retry_at = 0, 0.0
        self.trying = False
        self._load()

    # ---- what survives a restart --------------------------------------------------------------
    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text())
            self.chosen = str(data.get("chosen") or "").upper()
            self.chosen_name = str(data.get("name") or "")
            self.delays = {str(k).upper(): int(v) for k, v in (data.get("delays") or {}).items()}
        except (OSError, ValueError, AttributeError, TypeError):
            pass

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"chosen": self.chosen, "name": self.chosen_name,
                                       "delays": self.delays}))
            os.replace(tmp, self.path)
        except OSError as e:
            print(f"[bt] not saved: {e}", flush=True)

    # ---- the worker ---------------------------------------------------------------------------
    def start(self) -> "BtManager":
        self._thread = threading.Thread(target=self._run, name="bt", daemon=True)
        self._thread.start()
        return self

    def close(self) -> None:
        self._stop.set()
        self._answer(None)
        self._jobs.put(None)
        if self._thread is not None:
            self._thread.join(1.0)
        close = getattr(self.bus, "close", None)
        if close is not None:
            close()

    def _run(self) -> None:
        self.run_once()                      # at once: the page has its lists, a chosen speaker its try
        while not self._stop.is_set():
            self.run_once(TICK_BUSY_S if self.phase != "idle" else TICK_IDLE_S)

    def run_once(self, wait_s: float = 0.0) -> None:
        """One job if any, then one tick. The tests call this instead of starting the thread."""
        try:
            job = self._jobs.get(timeout=wait_s) if wait_s else self._jobs.get_nowait()
        except queue.Empty:
            job = None
        try:
            if job is not None:
                job()
            if not self._stop.is_set():
                self._tick()
        except BusError as e:
            print(f"[bt] {e}", flush=True)
        except Exception as e:               # one bad answer never ends the worker
            print(f"[bt] {type(e).__name__}: {e}", flush=True)

    def _refresh(self) -> bool:
        try:
            objects = self.bus.objects()
        except BusError as e:
            with self._lock:
                if self.alive or not self.problem:
                    print(f"[bt] no BlueZ: {e}", flush=True)
                self.alive, self.problem = False, getattr(self.bus, "down_text", "Bluetooth service not answering")
                self._objects, self._scanning = {}, False
                if self.phase == "scanning":
                    self.phase = "idle"
            return False
        with self._lock:
            self._objects = objects
            self.alive = True
            self.problem = "" if adapter_in(objects) else "No Bluetooth adapter"
            self._remember_order()
        return True

    def _remember_order(self) -> None:
        for mac, (_, p) in devices_in(self._objects).items():
            if mac not in self._order:
                near = int(p.get("RSSI", -127)) >= NEAR_RSSI
                self._order[mac] = (0 if _is_audio(p) else 1, 0 if near else 1, len(self._order))

    def _tick(self) -> None:
        if not self._refresh():
            return
        now = self._clock()
        if self.phase == "scanning":
            why = self.busy()
            if why:
                self._scan_end(f"Search stopped: {_REASON.get(why, 'the hat is busy')}.")
            elif now >= self._scan_until:
                self._scan_end()
        self._watch_chosen(now)

    def _call(self, path, iface, method, *args, timeout=10.0):
        return self.bus.call(path, iface, method, *args, timeout=timeout)

    # ---- the search -----------------------------------------------------------------------------
    def _scan_start(self) -> None:
        ad = adapter_in(self.bus.objects())
        if ad is None:
            raise BusError("no adapter")
        try:
            self._call(ad[0], ADAPTER, "SetDiscoveryFilter", {"Transport": "bredr"})
            self._call(ad[0], ADAPTER, "StartDiscovery")
        except BusError as e:
            if "InProgress" not in e.name:
                with self._lock:
                    self.phase = "idle"
                    self.result = self._result(False, "internal")
                print(f"[bt] search: {e}", flush=True)
                return
        with self._lock:
            self._scanning = True

    def _scan_end(self, why: str = "") -> None:
        with self._lock:
            was, self._scanning = self._scanning, False
            if self.phase == "scanning":
                self.phase = "idle"
            if why:
                self.result = {"ok": False, "code": "busy", "text": why, "name": ""}
        if not was:
            return
        ad = adapter_in(self._objects)
        if ad is not None:
            try:
                self._call(ad[0], ADAPTER, "StopDiscovery")
            except BusError as e:
                print(f"[bt] stop search: {e}", flush=True)

    # ---- one tap --------------------------------------------------------------------------------
    def _result(self, ok: bool, code: str = "", name: str = "") -> dict:
        return {"ok": ok, "code": code, "text": SENTENCES.get(code, ""), "name": name}

    def _step(self, step: str) -> None:
        with self._lock:
            self.step = step
        debug.emit("bluetooth", event=step, name=self._name(self.target))

    def _name(self, mac: str) -> str:
        entry = devices_in(self._objects).get(mac)
        return name_of(entry[1]) if entry else (self.chosen_name if mac == self.chosen else "")

    def _use(self, mac: str) -> None:
        name = ""
        try:
            self._scan_end()
            self._refresh()
            entry = devices_in(self._objects).get(mac)
            if entry is None:
                raise BusError("DoesNotExist")
            path, props = entry
            name = name_of(props)
            if not props.get("Paired"):
                self._pair(path)
                # At once, never before Pair: a speaker that connects back first would be
                # rejected, and a failed device that was trusted stays stored.
                self.bus.set_prop(path, DEVICE, "Trusted", True)
            elif not props.get("Trusted"):
                self.bus.set_prop(path, DEVICE, "Trusted", True)
            self._check_cancel()
            self._step("connecting")
            self._connect(path, CONNECT_S)
            self._step("sound")
            if not self._wait_sink(mac):
                self._call(path, DEVICE, "ConnectProfile", A2DP_SINK, timeout=CONNECT_S)
                if not self._wait_sink(mac):
                    self._call(path, DEVICE, "Disconnect", timeout=CONNECT_S)
                    raise _NoSink()
            old = self.chosen
            with self._lock:
                self.chosen, self.chosen_name = mac, name
                self.delays.setdefault(mac, DELAY_MS)
                self._save()
                self._tries, self._retry_at, self._was_ready = 0, 0.0, True
                self.result = self._result(True, name=name)
            _ready(sink_pattern(mac))
            print(f"[bt] ready: {name}", flush=True)
            debug.emit("bluetooth", event="ready", name=name)
            if old and old != mac:           # last: a failed switch never loses the working one
                gone = devices_in(self._objects).get(old)
                if gone is not None:
                    self._call(gone[0], DEVICE, "Disconnect", timeout=CONNECT_S)
        except _Cancelled:
            with self._lock:
                self.result = None
        except _NoSink:
            with self._lock:
                self.result = self._result(False, "no_sink", name)
        except BusError as e:
            print(f"[bt] {name or mac}: {e}", flush=True)
            debug.emit("bluetooth", event="failed", name=name, error=str(e)[:200])
            with self._lock:
                self.result = self._result(False, error_code(e), name)
        finally:
            with self._lock:
                self.phase, self.step, self.target = "idle", "", ""
                self._ask = None
                self._cancel = False

    def _check_cancel(self) -> None:
        if self._cancel:
            raise _Cancelled()

    def _pair(self, path: str) -> None:
        self._step("pairing")
        self._pin_tried = False
        for attempt in (1, 2):
            self.bus.register_agent(self._agent_ask)   # a restarted bluetoothd lost the last one
            try:
                self._call(path, DEVICE, "Pair", timeout=PAIR_S)
                return
            except BusTimeout:
                try:
                    self._call(path, DEVICE, "CancelPairing")
                except BusError:
                    pass
                raise
            except BusError as e:
                if "AlreadyExists" in e.name:
                    return
                self._check_cancel()
                if attempt == 1 and self._pin_tried and "AuthenticationFailed" in e.name:
                    continue                   # 0000 was wrong: now the PIN box
                raise

    def _connect(self, path: str, limit: float) -> None:
        try:
            self._call(path, DEVICE, "Connect", timeout=limit)
        except BusError as e:
            if "AlreadyConnected" not in e.name and "InProgress" not in e.name:
                raise

    def _sink_of(self, mac: str) -> dict | None:
        import fnmatch
        pat = sink_pattern(mac)
        for s in self._sinks():
            if fnmatch.fnmatch(s.get("name", "") if isinstance(s, dict) else str(s), pat):
                return s
        return None

    def _wait_sink(self, mac: str) -> bool:
        end = self._clock() + self.sink_s
        while True:
            self._poke()
            if self._sink_of(mac) is not None:
                return True
            self._check_cancel()
            if self._clock() >= end or self._stop.wait(0.25):
                return False

    # ---- the agent: called from the bus's side, may block its caller ------------------------------
    def _agent_ask(self, kind: str, mac: str, number: str = ""):
        """What to answer BlueZ. Only for the device being paired: None rejects everything else.
        pin -> str, passkey -> int, confirm -> True, show -> True."""
        if mac.upper() != self.target or self.phase != "working":
            return None
        if kind == "pin" and not self._pin_tried:
            self._pin_tried = True
            return "0000"
        if kind == "authorize":
            return True
        with self._lock:
            self._ask = {"kind": kind, "number": str(number)}
            while not self._ask_reply.empty():
                self._ask_reply.get_nowait()
        if kind == "show":
            return True
        try:
            return self._ask_reply.get(timeout=self.ask_s)
        except queue.Empty:
            return None
        finally:
            with self._lock:
                self._ask = None

    def agent_cancelled(self) -> None:
        self._answer(None)

    def _answer(self, value) -> None:
        try:
            self._ask_reply.put_nowait(value)
        except queue.Full:
            pass

    # ---- a chosen speaker that dropped ------------------------------------------------------------
    def _watch_chosen(self, now: float) -> None:
        mac = self.chosen
        if not mac or self.phase != "idle":
            return
        entry = devices_in(self._objects).get(mac)
        ready = bool(entry and entry[1].get("Connected")) and self._sink_of(mac) is not None
        if ready:
            if not self._was_ready:
                print(f"[bt] back: {self.chosen_name}", flush=True)
                debug.emit("bluetooth", event="back", name=self.chosen_name)
                _ready(sink_pattern(mac))
            self._was_ready, self._tries, self._retry_at = True, 0, 0.0
            return
        if self._was_ready:
            self._was_ready = False
            self._poke()
            print(f"[bt] lost: {self.chosen_name}", flush=True)
            debug.emit("bluetooth", event="lost", name=self.chosen_name)
            self._retry_at = now + RETRY_FAST_S
            return
        if entry is None or entry[1].get("Connected") or now < self._retry_at or self.busy():
            return                               # connected and no sink yet: PipeWire is coming
        self._tries += 1
        self._retry_at = now + (RETRY_FAST_S if self._tries < RETRY_FAST else RETRY_SLOW_S)
        with self._lock:
            self.trying = True
        try:
            self._connect(entry[0], RECONNECT_CALL_S)
        except BusError as e:
            print(f"[bt] reconnect {self.chosen_name}: {e}", flush=True)
        finally:
            with self._lock:
                self.trying = False

    # ---- what the page asks ----------------------------------------------------------------------
    def do(self, body: dict) -> tuple[int, dict]:
        action = str(body.get("do") or "")
        fn = {"view": self._do_view, "find": self._do_find, "stop": self._do_stop,
              "use": self._do_use, "answer": self._do_answer, "cancel": self._do_cancel,
              "stop_using": self._do_stop_using, "forget": self._do_forget,
              "delay": self._do_delay}.get(action)
        if fn is None:
            return 400, {"ok": False, "error": "unknown action"}
        return fn(body)

    def _reply(self) -> tuple[int, dict]:
        return 200, {"ok": True, "bt": self.snapshot()}

    def _do_view(self, body) -> tuple[int, dict]:
        return self._reply()

    def _do_find(self, body) -> tuple[int, dict]:
        with self._lock:
            if self.phase == "working":
                return 409, {"ok": False, "error": "working"}
            why = self.busy()
            if why:
                return 409, {"ok": False, "error": why}
            self.result = None
            self._scan_until = self._clock() + self.scan_s
            if self.phase == "scanning":     # searching already: only longer
                return self._reply()
            self.phase = "scanning"
        self._jobs.put(self._scan_start)
        return self._reply()

    def _do_stop(self, body) -> tuple[int, dict]:
        self._jobs.put(self._scan_end)
        with self._lock:
            if self.phase == "scanning":
                self.phase = "idle"
        return self._reply()

    def _mac(self, body, *, listed: bool = True) -> str | None:
        mac = str(body.get("mac") or "").upper()
        if not _MAC.match(mac):
            return None
        if listed:
            entry = devices_in(self._objects).get(mac)
            if entry is None or is_printer(entry[1], self.printer_mac):
                return None
        return mac if mac != self.printer_mac else None

    def _do_use(self, body) -> tuple[int, dict]:
        mac = self._mac(body)
        if mac is None:
            return 400, {"ok": False, "error": "not a speaker"}
        with self._lock:
            if self.phase == "working":
                return 409, {"ok": False, "error": "working"}
            why = self.busy()
            if why == "printing":
                return 409, {"ok": False, "error": why}
            self.phase, self.target, self.step = "working", mac, "starting"
            self.result, self._cancel = None, False
        self._jobs.put(lambda: self._use(mac))
        return self._reply()

    def _do_answer(self, body) -> tuple[int, dict]:
        with self._lock:
            ask = self._ask
        if ask is None:
            return 409, {"ok": False, "error": "nothing asked"}
        if ask["kind"] == "pin":
            pin = str(body.get("pin") or "")
            if not _PIN.match(pin):
                return 400, {"ok": False, "error": "bad pin"}
            self._answer(pin)
        elif ask["kind"] == "passkey":
            pin = str(body.get("pin") or "")
            if not (pin.isdigit() and len(pin) <= 6):
                return 400, {"ok": False, "error": "bad pin"}
            self._answer(int(pin))
        else:
            self._answer(True if body.get("yes") else None)
        with self._lock:
            self._ask = None
        return self._reply()

    def _do_cancel(self, body) -> tuple[int, dict]:
        with self._lock:
            mac = self.target if self.phase == "working" else ""
            self._cancel = bool(mac)
        if mac:
            self._answer(None)
            entry = devices_in(self._objects).get(mac)
            if entry is not None and self.step == "pairing":
                try:
                    self._call(entry[0], DEVICE, "CancelPairing")
                except BusError:
                    pass
        return self._reply()

    def _forget_choice(self, mac: str) -> None:
        if self.chosen == mac:
            self.chosen, self.chosen_name, self._was_ready = "", "", False
        self._save()

    def _do_stop_using(self, body) -> tuple[int, dict]:
        mac = self._mac(body, listed=False)
        if mac is None:
            return 400, {"ok": False, "error": "not a speaker"}
        with self._lock:
            self._forget_choice(mac)

        def job():
            entry = devices_in(self._objects).get(mac)
            if entry is not None:
                self._call(entry[0], DEVICE, "Disconnect", timeout=CONNECT_S)
        self._jobs.put(job)
        return self._reply()

    def _do_forget(self, body) -> tuple[int, dict]:
        mac = self._mac(body, listed=False)
        if mac is None:
            return 400, {"ok": False, "error": "not a speaker"}
        entry = devices_in(self._objects).get(mac)
        if entry is not None and is_printer(entry[1], self.printer_mac):
            return 400, {"ok": False, "error": "not a speaker"}
        if body.get("confirm") is not True:
            return 400, {"ok": False, "error": "confirm expected"}
        with self._lock:
            self.delays.pop(mac, None)
            self._forget_choice(mac)

        def job():
            now = devices_in(self.bus.objects()).get(mac)
            ad = adapter_in(self._objects)
            if now is not None and ad is not None:
                self._call(ad[0], ADAPTER, "RemoveDevice", ("o", now[0]))
        self._jobs.put(job)
        return self._reply()

    def _do_delay(self, body) -> tuple[int, dict]:
        mac = self._mac(body, listed=False)
        if mac is None:
            return 400, {"ok": False, "error": "not a speaker"}
        try:
            ms = int(body.get("ms"))
        except (TypeError, ValueError):
            return 400, {"ok": False, "error": "ms expected"}
        if not 0 <= ms <= DELAY_MAX_MS:
            return 400, {"ok": False, "error": "ms 0 to 800"}
        with self._lock:
            self.delays[mac] = ms
            self._save()
        return self._reply()

    # ---- what the page and the route read -----------------------------------------------------------
    def chosen_route(self) -> str:
        return sink_pattern(self.chosen) if self.chosen else ""

    def delay_for(self, route: str) -> int | None:
        with self._lock:
            if not self.chosen or route != sink_pattern(self.chosen):
                return None
            return self.delays.get(self.chosen, DELAY_MS)

    def _row(self, mac: str, props: dict, names: dict) -> dict:
        row = {"mac": mac, "name": names[mac], "kind": kind_of(props),
               "connected": bool(props.get("Connected")),
               "ready": bool(props.get("Connected")) and self._sink_of(mac) is not None,
               "chosen": mac == self.chosen, "delay_ms": self.delays.get(mac, DELAY_MS),
               "delay_measured": False}
        if "Battery" in props:
            row["battery"] = int(props["Battery"])
        return row

    def snapshot(self) -> dict:
        with self._lock:
            devs = devices_in(self._objects)
            mine, nearby, others = sort_lists(devs, self.printer_mac)
            names = {m: name_of(devs[m][1]) for m in mine + nearby + others}
            counts: dict[str, int] = {}
            for n in names.values():
                counts[n] = counts.get(n, 0) + 1
            for m, n in list(names.items()):
                if counts[n] > 1:            # two of one model: the address's end tells them apart
                    names[m] = f"{n} ({m[-5:]})"
            key = lambda m: self._order.get(m, (9, 9, 0))
            nearby = sorted(nearby, key=key)
            others = sorted(others, key=key)
            ad = adapter_in(self._objects)
            ready = False
            chosen_row = None
            if self.chosen:
                entry = devs.get(self.chosen)
                ready = bool(entry and entry[1].get("Connected")) and self._sink_of(self.chosen) is not None
                chosen_row = {"mac": self.chosen, "name": names.get(self.chosen) or self.chosen_name,
                              "route": sink_pattern(self.chosen), "ready": ready, "lost": not ready,
                              "trying": self.trying}
            ask = dict(self._ask) if self._ask else None
            return {
                "setting": self.setting, "present": True, "alive": self.alive,
                "problem": self.problem, "powered": bool(ad and ad[1].get("Powered")),
                "phase": self.phase, "step": self.step,
                "scan_left_s": max(0, round(self._scan_until - self._clock())) if self.phase == "scanning" else 0,
                "target": {"mac": self.target, "name": names.get(self.target) or self._name(self.target)} if self.target else None,
                "ask": ask, "result": dict(self.result) if self.result else None,
                "busy": self.busy(), "chosen": chosen_row,
                "mine": [self._row(m, devs[m][1], names) for m in sorted(mine, key=key)],
                "nearby": [self._row(m, devs[m][1], names) for m in nearby[:NEARBY_CAP]],
                "others": [self._row(m, devs[m][1], names) for m in others[:NEARBY_CAP]],
            }


class _Cancelled(Exception):
    pass


class _NoSink(Exception):
    pass


_MAC = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")
_PIN = re.compile(r"^[0-9A-Za-z]{1,16}$")
_REASON = {"printing": "a ticket is printing", "speaking": "the hat is speaking", "busy": "the hat is busy"}


# ---- the stand-in ---------------------------------------------------------------------------------

class FakeBus:
    """BlueZ with no radio, for FISH_BLUETOOTH=mock and the tests. `calls` holds what was asked,
    in order. Behaviours by device: good, pin, confirm, off, held, no_sink, refuses."""

    def __init__(self, *, latency: float = 0.0):
        self.latency = latency
        self.calls: list[tuple] = []
        self.sinks: list[dict] = []
        self.ask = None
        self.up = True
        self.adapter = "/org/bluez/hci0"
        self.known: dict[str, dict] = {}
        self.behaviour: dict[str, str] = {}
        self.hidden: dict[str, dict] = {}
        self.register_agent_calls = 0

    def add(self, mac: str, name: str | None, *, cls: int | None = None, icon: str = "",
            behaviour: str = "good", paired: bool = False, seen: bool = False, **extra) -> None:
        props = {"Address": mac, "Paired": paired, "Trusted": paired, "Connected": False,
                 "Alias": name or mac.replace(":", "-"), "RSSI": -50, **extra}
        if name:
            props["Name"] = name
        if cls is not None:
            props["Class"] = cls
        if icon:
            props["Icon"] = icon
        self.behaviour[mac] = behaviour
        (self.known if paired or seen else self.hidden)[mac] = props

    def _path(self, mac: str) -> str:
        return f"{self.adapter}/dev_{mac.replace(':', '_')}"

    def objects(self) -> dict:
        if not self.up:
            raise BusError("org.freedesktop.DBus.Error.ServiceUnknown")
        out = {self.adapter: {ADAPTER: {"Powered": True, "Discovering": False}}}
        for mac, p in self.known.items():
            out[self._path(mac)] = {DEVICE: dict(p)}
        return out

    def register_agent(self, ask) -> None:
        self.register_agent_calls += 1
        self.ask = ask
        self.calls.append(("RegisterAgent",))

    def set_prop(self, path, iface, name, value) -> None:
        self.calls.append(("set", name, value))
        self.known[self._mac(path)][name] = value

    def _mac(self, path: str) -> str:
        return path.rsplit("dev_", 1)[-1].replace("_", ":")

    def call(self, path, iface, method, *args, timeout=10.0):
        self.calls.append((method, *args))
        if self.latency:
            time.sleep(self.latency)
        if method == "StartDiscovery":
            self.known.update(self.hidden)
            self.hidden = {}
        elif method == "Pair":
            self._pair(self._mac(path))
        elif method == "Connect":
            self._link(self._mac(path))
        elif method == "ConnectProfile":
            pass
        elif method == "Disconnect":
            mac = self._mac(path)
            self.known[mac]["Connected"] = False
            self.sinks = [s for s in self.sinks if s["name"] != self._sink(mac)]
        elif method == "RemoveDevice":
            self.known.pop(self._mac(args[0][1]), None)

    def _sink(self, mac: str) -> str:
        return f"bluez_output.{mac.replace(':', '_')}.1"

    def _pair(self, mac: str) -> None:
        how = self.behaviour.get(mac, "good")
        if how == "refuses":
            raise BusError("org.bluez.Error.AuthenticationFailed")
        if how == "off":
            raise BusError("org.bluez.Error.ConnectionAttemptFailed", "Page Timeout")
        if how == "pin" and self.ask("pin", mac) != "4321":
            raise BusError("org.bluez.Error.AuthenticationFailed")
        if how == "confirm" and not self.ask("confirm", mac, "482913"):
            raise BusError("org.bluez.Error.AuthenticationRejected")
        self.known[mac]["Paired"] = True

    def _link(self, mac: str) -> None:
        how = self.behaviour.get(mac, "good")
        if how == "held":
            raise BusError("org.bluez.Error.Failed", "br-connection-busy")
        if how == "off":
            raise BusError("org.bluez.Error.Failed", "br-connection-page-timeout")
        self.known[mac]["Connected"] = True
        if how != "no_sink" and not any(s["name"] == self._sink(mac) for s in self.sinks):
            self.sinks.append({"id": 900 + len(self.sinks), "name": self._sink(mac), "desc": mac})

    def drop(self, mac: str) -> None:
        self.known[mac]["Connected"] = False
        self.sinks = [s for s in self.sinks if s["name"] != self._sink(mac)]


def mock_bus(printer_mac: str = "") -> FakeBus:
    """The room FISH_BLUETOOTH=mock shows: every state of the block is one tap away."""
    bus = FakeBus(latency=0.4)
    bus.add("DC:0D:51:92:74:DA", "MP210", cls=0x040680, icon="printer", paired=True)
    bus.add("A0:00:00:00:00:01", "JBL Flip 5", cls=0x240414, icon="audio-card")
    bus.add("A0:00:00:00:00:02", "Space Q45", cls=0x240404, icon="audio-headset")
    bus.add("A0:00:00:00:00:03", "Old Speaker (PIN 4321)", cls=0x240414, icon="audio-card", behaviour="pin")
    bus.add("A0:00:00:00:00:04", "Number Speaker", cls=0x240414, icon="audio-card", behaviour="confirm")
    bus.add("A0:00:00:00:00:05", "Off Speaker", cls=0x240414, icon="audio-card", behaviour="off")
    bus.add("A0:00:00:00:00:06", "Held by a phone", cls=0x240414, icon="audio-card", behaviour="held")
    bus.add("A0:00:00:00:00:07", "No Sound", cls=0x240414, icon="audio-card", behaviour="no_sink")
    bus.add("A0:00:00:00:00:08", "No Class Speaker")
    bus.add("B0:00:00:00:00:01", "Somebody's phone", cls=0x5a020c, icon="phone")
    bus.add("B0:00:00:00:00:02", None)
    return bus


# ---- the one the route and the page read ---------------------------------------------------------

_manager: BtManager | None = None
_ready_hooks: list = []


def make_bt(cfg, printer_mac: str = "") -> BtManager | None:
    """None when off or the setting is bad (one [bt] line, never an exit). With `on` and no
    D-Bus library the block shows the problem instead of an exit."""
    global _manager
    kind = cfg.kind()
    if kind == "off":
        return None
    if kind == "bad":
        print(f"[bt] {cfg.problem()}: Bluetooth speakers are off", flush=True)
        return None
    from . import pw
    if kind == "mock":
        bus = mock_bus(printer_mac)
        _manager = BtManager(bus, printer_mac=printer_mac, sinks=lambda: bus.sinks,
                             path=cfg.state_path or None, setting="mock")
    else:
        try:
            from .bt_bluez import DbusBus
            bus = DbusBus()
        except ImportError as e:
            print(f"[bt] no D-Bus library ({e}): pip install -e .[unoq]", flush=True)
            bus = _NoLibrary()
        cache = pw.cache()
        _manager = BtManager(bus, printer_mac=printer_mac, sinks=cache.sinks, poke=cache.poke,
                             path=cfg.state_path or None)
    return _manager.start()


class _NoLibrary:
    down_text = "The D-Bus library is not installed: deploy/unoq_setup.sh install"

    def objects(self):
        raise BusError("dbus_fast is not installed")


def manager() -> BtManager | None:
    return _manager


def close() -> None:
    global _manager
    m, _manager = _manager, None
    if m is not None:
        m.close()


def busy_reason(printer, convo, viz):
    """What stops a search and a reconnect: a ticket, a turn or an act."""
    def reason() -> str:
        try:
            if printer is not None and printer.snapshot().get("busy"):
                return "printing"
        except Exception:
            pass
        lock = getattr(getattr(convo, "speaker", None), "_lock", None)
        if lock is not None and lock.locked():
            return "speaking"
        if viz is not None and not viz.listening:
            return "busy"
        fortune = getattr(convo, "fortune", None)
        if fortune is not None and fortune.open:
            return "busy"
        return ""
    return reason


def with_chosen(routes) -> list:
    """The routes a phrase can take, with the chosen speaker first. Nothing chosen: unchanged."""
    route = _manager.chosen_route() if _manager is not None else ""
    routes = list(routes or ())
    if not route:
        return routes
    return [route] + [r for r in routes if r != route]


def delay_for(route: str) -> int | None:
    """The chosen speaker's own delay in ms, or None: then FISH_AUDIO_DELAY_MS decides."""
    return _manager.delay_for(route) if _manager is not None else None


def on_ready(fn) -> None:
    """Called with a route when its speaker is Ready, so a cooling from before it clears."""
    _ready_hooks.append(fn)


def _ready(route: str) -> None:
    for fn in list(_ready_hooks):
        try:
            fn(route)
        except Exception:
            pass
