"""Push-to-talk from a button on a Linux input device (python-evdev).

For headless use (the fish on a board, no keyboard focus, no display): a USB voice remote,
a foot pedal or any keyboard key becomes the talk button. `EvdevButton` watches the device in
a background thread and answers one question for the recorder: `is_held()`.

- The device (`PTTConfig.evdev_device`) is a `/dev/input/...` path, `name:<substring>` or
  `auto` (every readable node that advertises the key). It may be absent at startup or
  unplugged later; the thread keeps looking for it once a second.
- The key (`PTTConfig.evdev_key`) is a `KEY_*`/`BTN_*` name or a number.
- `hold` mode: held while the key is down. `toggle` mode: one press starts, the next stops
  (for remotes that only send a short tap).

Bring-up without root (the user must be in the `input` group):

    python -m fish_brain.evdev_button --list            # nodes and the keys they have
    python -m fish_brain.evdev_button --watch           # press the button, read its name
    python -m fish_brain.evdev_button --watch name:remote --seconds 10

`evdev` is imported lazily, so the rest of the program runs without it.
"""
from __future__ import annotations

import argparse
import getpass
import glob
import os
import re
import select
import sys
import textwrap
import threading
import time

from .config import PTTConfig

EV_KEY = 1                # linux/input-event-codes.h; fixed kernel ABI
_SELECT_S = 0.2           # wait for events this long, then look at the stop flag
_RETRY_S = 1.0            # how often to look for the device while none is open
_RESCAN_S = 3.0           # auto/name: how often to look for extra nodes while one is open
_CROSS_CHECK_S = 0.5      # how often to compare our state with the kernel's key state
_DEBOUNCE_S = 0.25        # toggle mode: presses closer than this count as one
_FIRST_SCAN_S = 1.0       # the constructor waits at most this long for the first look
_INPUT_HINT = "add the user to the `input` group (`sudo usermod -aG input $USER`, re-login)"


class ButtonState:
    """What the button means right now. No devices here: feed it events and read `held`.

    `on_event(value, now)` takes a key event (1 press, 0 release, 2 autorepeat) and
    `on_active(active, now)` takes the kernel's own answer to "is the key down?".
    Presses only count while armed, and after `reset()` only once the key was seen released.
    """

    def __init__(self, mode: str = "hold", debounce_s: float = _DEBOUNCE_S):
        if mode not in ("hold", "toggle"):
            raise ValueError(f"unknown push-to-talk mode {mode!r} (use 'hold' or 'toggle')")
        self.mode = mode
        self.debounce_s = debounce_s
        self._lock = threading.Lock()
        self._held = False
        self._armed = False
        self._need_release = False
        self._down = False                    # last known physical state of the key
        self._last_edge = float("-inf")       # time of the last press that flipped the toggle

    @property
    def held(self) -> bool:
        with self._lock:
            return self._held

    @property
    def armed(self) -> bool:
        with self._lock:
            return self._armed

    @property
    def need_release(self) -> bool:
        with self._lock:
            return self._need_release

    def arm(self, on: bool) -> None:
        with self._lock:
            on = bool(on)
            if on == self._armed:
                return
            self._armed = on
            if not on:
                self._held = False
                # A key still down when we stop listening must not start the next recording.
                if self._down:
                    self._need_release = True

    def reset(self) -> None:
        with self._lock:
            self._held = False
            self._need_release = True

    def release(self) -> None:
        """The device is gone: nothing is held, in either mode, and nothing is pending."""
        with self._lock:
            self._held = False
            self._down = False
            self._need_release = False

    def on_event(self, value: int, now: float) -> None:
        with self._lock:
            if value == 0:
                self._down = False
                self._need_release = False
                if self.mode == "hold":
                    self._held = False
                return
            if value != 1:                    # 2 = autorepeat, says nothing new
                return
            self._down = True
            if not self._armed:
                # Pressed while nobody listens (the fish is speaking): this press never counts,
                # even if the key is still down when listening starts.
                self._need_release = True
                return
            if self._need_release:
                return
            if self.mode == "hold":
                self._held = True
            elif now - self._last_edge >= self.debounce_s:
                self._last_edge = now
                self._held = not self._held

    def on_active(self, active: bool, now: float) -> None:
        """Cross-check against the kernel's key state (recovers a lost press or release)."""
        with self._lock:
            self._down = bool(active)
            if not active:
                self._need_release = False
                if self.mode == "hold":
                    self._held = False
            elif self.mode == "hold":
                if not self._armed:
                    self._need_release = True
                elif not self._need_release:
                    self._held = True
            # toggle + key down: nothing to learn, only presses flip the toggle


def _evdev():
    try:
        import evdev
    except ImportError as e:
        raise RuntimeError(
            "push-to-talk from an input device needs python-evdev: "
            "pip install evdev (or apt install python3-evdev)"
        ) from e
    return evdev


def resolve_key(spec: str | int) -> int:
    """Key code for a `KEY_*`/`BTN_*` name ('KEY_VOICECOMMAND', 'f9') or a number ('582')."""
    if isinstance(spec, int):
        return spec
    s = str(spec).strip()
    try:
        return int(s, 0)
    except ValueError:
        pass
    codes = _evdev().ecodes.ecodes
    for name in (s.upper(), "KEY_" + s.upper()):
        if name in codes:
            return int(codes[name])
    raise ValueError(f"unknown key {spec!r}: use a KEY_* name or a number (see --watch)")


def key_name(code: int) -> str:
    """'KEY_VOICECOMMAND' for 582; the number as text if the kernel table has no name."""
    ecodes = _evdev().ecodes
    name = ecodes.KEY.get(code) or ecodes.BTN.get(code)
    if isinstance(name, (list, tuple)):
        name = name[0]
    return name or str(code)


def _node_number(path: str) -> int:
    m = re.search(r"(\d+)$", path)
    return int(m.group(1)) if m else -1


def list_nodes() -> list[str]:
    """Every /dev/input/event* node, readable or not, in numeric order."""
    return sorted(glob.glob("/dev/input/event*"), key=_node_number)


def _has_key(dev, code: int) -> bool:
    return code in dev.capabilities().get(EV_KEY, [])


def _user() -> str:
    try:
        return getpass.getuser()
    except Exception:                         # a service uid with no passwd entry
        return f"uid {os.getuid()}"


def _close_quietly(dev) -> None:
    try:
        dev.close()
    except Exception:
        pass


class EvdevButton:
    """A push-to-talk source backed by one or more input devices.

    Starts a daemon thread and never raises because the device is missing or unreadable; it
    says why once and keeps trying. A wrong key name or mode, or python-evdev not being
    installed, does raise (ValueError / RuntimeError): retrying cannot fix those.
    """

    def __init__(self, cfg: PTTConfig):
        self._spec = (cfg.evdev_device or "auto").strip()
        self._grab = bool(cfg.grab)
        self._state = ButtonState(cfg.mode)
        self._code = resolve_key(cfg.evdev_key)
        self._key = key_name(self._code)
        low = self._spec.lower()
        self._name_sub = self._spec[5:].strip().lower() if low.startswith("name:") else None
        self._auto = low == "auto"
        self._devs: dict[int, object] = {}        # fd -> InputDevice; owned by the thread
        self._seen: set[str] = set()              # nodes already looked at (auto/name)
        self._said: set[str] = set()              # one-time messages already printed
        self._count = 0
        self._check_now = threading.Event()
        self._stop = threading.Event()
        self._scanned = threading.Event()
        self._thread = threading.Thread(target=self._run, name="evdev-ptt", daemon=True)
        self._thread.start()
        # So that device_count/describe() are true in the startup summary. Bounded: a slow
        # or missing device never holds up the program.
        self._scanned.wait(_FIRST_SCAN_S)

    # ---- what the recorder uses -------------------------------------------------------------

    def is_held(self) -> bool:
        return self._state.held

    def reset(self) -> None:
        """Forget held/toggle state; ignore presses until the key is seen released."""
        self._state.reset()
        self._check_now.set()     # the kernel can tell us right away that it is released

    def arm(self, on: bool) -> None:
        """Presses only count while armed (the recorder arms while it waits and records)."""
        self._state.arm(on)

    @property
    def device_count(self) -> int:
        return self._count

    def describe(self) -> str:
        n = self._count
        return f"evdev({n} device{'' if n == 1 else 's'}, {self._key}, {self._state.mode})"

    def close(self) -> None:
        self._stop.set()
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)

    # ---- device access (replaced by fakes in the tests) -------------------------------------

    def _list_nodes(self) -> list[str]:
        return list_nodes()

    def _open(self, path: str):
        return _evdev().InputDevice(path)

    # ---- the thread -------------------------------------------------------------------------

    def _log(self, msg: str) -> None:
        print(f"[ptt] evdev: {msg}", flush=True)

    def _say_once(self, kind: str, msg: str) -> None:
        if kind not in self._said:
            self._said.add(kind)
            self._log(msg)

    def _run(self) -> None:
        self._next_scan = 0.0
        self._next_check = 0.0
        try:
            while not self._stop.is_set():
                try:
                    self._step()
                except Exception as e:        # never let the talk button die silently
                    self._say_once(f"bug:{type(e).__name__}",
                                   f"unexpected {type(e).__name__}: {e}; reopening the device")
                    for dev in list(self._devs.values()):
                        self._forget(dev)
                    self._state.release()
                    self._stop.wait(_RETRY_S)
                finally:
                    self._scanned.set()
        finally:
            self._scanned.set()
            for dev in list(self._devs.values()):
                _close_quietly(dev)
            self._devs.clear()
            self._count = 0

    def _step(self) -> None:
        now = time.monotonic()
        explicit = not (self._auto or self._name_sub is not None)
        if now >= self._next_scan and not (explicit and self._devs):
            self._scan()
            self._next_scan = time.monotonic() + (_RESCAN_S if self._devs else _RETRY_S)
        self._scanned.set()
        if not self._devs:
            self._stop.wait(_SELECT_S)
            return
        try:
            ready, _, _ = select.select(list(self._devs), [], [], _SELECT_S)
        except (OSError, ValueError) as e:
            for dev in list(self._devs.values()):
                self._drop(dev, e)
            return
        for fd in ready:
            dev = self._devs.get(fd)
            if dev is not None:
                self._read(dev)
        now = time.monotonic()
        if self._devs and (now >= self._next_check or self._check_now.is_set()):
            self._check_now.clear()
            self._next_check = now + _CROSS_CHECK_S
            self._cross_check(now)

    def _read(self, dev) -> None:
        try:
            for ev in dev.read():
                if ev.type == EV_KEY and ev.code == self._code:
                    self._state.on_event(ev.value, time.monotonic())
        except BlockingIOError:
            pass
        except OSError as e:                  # unplugged (ENODEV) or the remote went to sleep
            self._drop(dev, e)

    def _cross_check(self, now: float) -> None:
        active = False
        for dev in list(self._devs.values()):
            try:
                if self._code in dev.active_keys():
                    active = True
            except OSError as e:
                self._drop(dev, e)
        self._state.on_active(active, now)

    def _forget(self, dev) -> None:
        for fd in [fd for fd, d in self._devs.items() if d is dev]:
            del self._devs[fd]
        self._seen.discard(getattr(dev, "path", ""))
        self._count = len(self._devs)
        _close_quietly(dev)

    def _drop(self, dev, err: Exception) -> None:
        self._forget(dev)
        self._said.clear()                    # a new situation: explain it again if needed
        self._log(f"lost {dev.path} ({err}); looking for it again")
        if not self._devs:
            # A gone device holds no key, and in toggle mode it could never send the press
            # that stops the recording.
            self._state.release()

    def _adopt(self, dev) -> bool:
        try:
            for _ in dev.read():              # events from before we started listening
                pass
        except BlockingIOError:
            pass
        except OSError as e:
            _close_quietly(dev)
            self._say_once(f"read:{dev.path}", f"cannot read {dev.path} ({e}); retrying")
            return False
        try:
            if self._code in dev.active_keys():
                self._state.reset()           # already down at open: wait for a fresh press
        except OSError:
            pass
        if self._grab:
            try:
                dev.grab()
            except OSError as e:
                self._log(f"could not grab {dev.path} ({e}); sharing it instead")
        self._devs[dev.fd] = dev
        self._count = len(self._devs)
        self._said.clear()
        self._log(f"listening on {dev.path} '{dev.name}' for {self._key}")
        return True

    def _scan(self) -> None:
        if self._auto or self._name_sub is not None:
            self._scan_nodes()
        else:
            self._scan_path()

    def _scan_path(self) -> None:
        path = self._spec
        try:
            dev = self._open(path)
        except PermissionError:
            self._say_once("perm", f"{path} is not readable by {_user()} — "
                                   f"{_INPUT_HINT}")
            return
        except FileNotFoundError:
            self._say_once("missing", f"{path} is not there yet; waiting for it")
            return
        except OSError as e:
            self._say_once("oserror", f"cannot open {path} ({e}); retrying")
            return
        try:
            if not _has_key(dev, self._code):
                self._say_once("nokey", f"{path} '{dev.name}' does not advertise {self._key}; "
                                        "check FISH_PTT_KEY with --watch")
        except OSError:
            pass
        self._adopt(dev)

    def _scan_nodes(self) -> None:
        nodes = self._list_nodes()
        self._seen &= set(nodes)
        open_paths = {d.path for d in self._devs.values()}
        unreadable = 0
        for path in nodes:
            if path in open_paths:
                continue
            if path in self._seen:
                continue
            if not os.access(path, os.R_OK):
                unreadable += 1
                continue
            try:
                dev = self._open(path)
            except PermissionError:
                unreadable += 1
                continue
            except OSError:
                continue                      # node vanished or is not ready; look again later
            try:
                if self._name_sub is not None:
                    wanted = self._name_sub in (dev.name or "").lower()
                else:
                    wanted = _has_key(dev, self._code)
            except OSError:
                _close_quietly(dev)
                continue
            if not wanted:
                self._seen.add(path)          # looked at, not ours: skip it from now on
                _close_quietly(dev)
            else:
                self._adopt(dev)              # on failure it stays unseen and is retried
        if self._devs:
            return
        user = _user()
        readable = len(nodes) - unreadable
        if not nodes:
            self._say_once("nonodes", "no /dev/input/event* nodes yet; waiting")
        elif readable == 0:
            self._say_once("perm", f"{len(nodes)} nodes, none readable by {user} — "
                                   f"{_INPUT_HINT}")
        elif self._name_sub is not None:
            extra = f" ({unreadable} more not readable by {user})" if unreadable else ""
            self._say_once("noname", f"no input device named like '{self._name_sub}' among "
                                     f"{readable} readable nodes{extra}; see --list")
        else:
            extra = f" ({unreadable} more not readable by {user})" if unreadable else ""
            self._say_once("nokey", f"none of the {readable} readable nodes has {self._key}"
                                    f"{extra}; see python -m fish_brain.evdev_button --list")


# ---- command line: find the device and the key without root ---------------------------------


def _open_readable(paths: list[str]) -> tuple[list, int]:
    """(open devices, number of nodes we could not read)."""
    evdev = _evdev()
    devs, unreadable = [], 0
    for path in paths:
        try:
            devs.append(evdev.InputDevice(path))
        except PermissionError:
            unreadable += 1
        except OSError:
            pass
    return devs, unreadable


def _key_names(dev) -> list[str]:
    return [key_name(c) for c in sorted(dev.capabilities().get(EV_KEY, []))]


def _cmd_list() -> int:
    nodes = list_nodes()
    devs, unreadable = _open_readable(nodes)
    for dev in devs:
        try:
            names = _key_names(dev)
        except OSError as e:
            print(f"{dev.path}  '{dev.name}'  (cannot read its keys: {e})")
            _close_quietly(dev)
            continue
        print(f"{dev.path}  '{dev.name}'  ({len(names)} keys)")
        if names:
            print(textwrap.fill(" ".join(names), width=98, initial_indent="    ",
                                subsequent_indent="    ", break_long_words=False))
        _close_quietly(dev)
    print(f"{len(devs)} readable, {unreadable} not readable by {_user()}"
          f" (of {len(nodes)} nodes)")
    if nodes and not devs:
        print(f"hint: {_INPUT_HINT}")
    return 0 if devs else 1


def _watch_targets(spec: str) -> list[str]:
    low = spec.lower()
    if low in ("all", "auto") or low.startswith("name:"):
        return list_nodes()
    return [spec]


def _cmd_watch(spec: str, seconds: float) -> int:
    devs, unreadable = _open_readable(_watch_targets(spec))
    if spec.lower().startswith("name:"):
        sub = spec[5:].strip().lower()
        keep = [d for d in devs if sub in (d.name or "").lower()]
        for d in devs:
            if d not in keep:
                d.close()
        devs = keep
    if not devs:
        if unreadable:
            print(f"no readable device for '{spec}' ({unreadable} not readable by "
                  f"{_user()}) — {_INPUT_HINT}")
        else:
            print(f"no input device for '{spec}'; see --list")
        return 1
    for d in devs:
        print(f"watching {d.path} '{d.name}'")
    print("press the button (Ctrl-C to stop)", flush=True)
    by_fd = {d.fd: d for d in devs}
    labels = {0: "up", 1: "down", 2: "repeat"}
    deadline = time.monotonic() + seconds if seconds > 0 else None
    try:
        while by_fd and (deadline is None or time.monotonic() < deadline):
            try:
                ready, _, _ = select.select(list(by_fd), [], [], _SELECT_S)
            except (OSError, ValueError) as e:
                print(f"lost the devices ({e})", flush=True)
                break
            for fd in ready:
                dev = by_fd[fd]
                try:
                    for ev in dev.read():
                        if ev.type == EV_KEY:
                            print(f"{os.path.basename(dev.path)} '{dev.name}': "
                                  f"{key_name(ev.code)} ({ev.code}) "
                                  f"{labels.get(ev.value, ev.value)}", flush=True)
                except BlockingIOError:
                    pass
                except OSError as e:
                    print(f"lost {dev.path} ({e})", flush=True)
                    del by_fd[fd]
                    _close_quietly(dev)
    except KeyboardInterrupt:
        pass
    finally:
        for d in by_fd.values():
            _close_quietly(d)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m fish_brain.evdev_button",
        description="Find the input device and key for push-to-talk "
                    "(FISH_PTT_DEVICE / FISH_PTT_KEY).")
    what = ap.add_mutually_exclusive_group(required=True)
    what.add_argument("--list", action="store_true",
                      help="readable input nodes, their names and the keys they have")
    what.add_argument("--watch", nargs="?", const="all", metavar="DEVICE",
                      help="print key presses live; DEVICE is a path or name:<substring> "
                           "(default: every readable node)")
    ap.add_argument("--seconds", type=float, default=0.0, metavar="N",
                    help="with --watch: stop after N seconds (default: until Ctrl-C)")
    args = ap.parse_args(argv)
    try:
        if args.list:
            return _cmd_list()
        return _cmd_watch(args.watch, args.seconds)
    except RuntimeError as e:                 # python-evdev missing
        print(e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
