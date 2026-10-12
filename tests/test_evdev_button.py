"""Push-to-talk button logic: hold, toggle, reset and arm, plus the device thread on fakes.

No real input device is opened: the state tests need nothing, and the thread tests replace
the two device-access methods with fakes built on a pipe.
"""
from __future__ import annotations

import errno
import os
import time
from collections import namedtuple

import pytest

from fish_brain.config import PTTConfig
from fish_brain.evdev_button import EV_KEY, ButtonState

# ---- pure state ---------------------------------------------------------------------------


def armed(mode: str = "hold") -> ButtonState:
    s = ButtonState(mode)
    s.arm(True)
    return s


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        ButtonState("latch")


def test_hold_follows_the_key_and_ignores_autorepeat():
    s = armed()
    assert not s.held
    s.on_event(1, 0.0)
    assert s.held
    s.on_event(2, 0.1)
    s.on_event(2, 0.2)
    assert s.held
    s.on_event(0, 0.3)
    assert not s.held
    s.on_event(2, 0.4)            # a stray repeat after the release starts nothing
    assert not s.held


def test_hold_cross_check_recovers_lost_events():
    s = armed()
    s.on_event(1, 0.0)
    s.on_active(False, 0.5)       # the key-up never arrived
    assert not s.held
    s.on_active(True, 1.0)        # the key-down never arrived
    assert s.held


def test_toggle_flips_on_presses_only():
    s = armed("toggle")
    s.on_event(1, 0.0)
    assert s.held
    s.on_event(0, 0.05)           # release keeps recording
    s.on_event(2, 0.06)
    assert s.held
    s.on_event(1, 1.0)
    assert not s.held
    s.on_event(0, 1.05)
    assert not s.held


def test_toggle_debounce():
    s = armed("toggle")
    s.on_event(1, 10.0)
    s.on_event(0, 10.02)
    s.on_event(1, 10.10)          # bounce, 100 ms after the press
    assert s.held
    s.on_event(0, 10.12)
    s.on_event(1, 10.249)         # still inside 250 ms
    assert s.held
    s.on_event(1, 10.25)          # the window is over
    assert not s.held


def test_toggle_has_no_cross_check():
    s = armed("toggle")
    s.on_event(1, 0.0)
    s.on_event(0, 0.1)
    s.on_active(False, 0.5)       # key is up, the toggle stays on
    assert s.held
    s.on_event(1, 1.0)
    assert not s.held
    s.on_active(True, 1.1)        # key is down, the toggle stays off
    assert not s.held


@pytest.mark.parametrize("mode", ["hold", "toggle"])
def test_reset_needs_a_release_event(mode):
    s = armed(mode)
    s.on_event(1, 0.0)
    assert s.held
    s.reset()
    assert not s.held and s.need_release
    s.on_event(1, 1.0)            # still the old press (or a press with no release seen)
    s.on_event(2, 1.1)
    assert not s.held
    s.on_event(0, 2.0)
    assert not s.held and not s.need_release
    s.on_event(1, 3.0)
    assert s.held


@pytest.mark.parametrize("mode", ["hold", "toggle"])
def test_reset_is_cleared_by_the_kernel_saying_released(mode):
    s = armed(mode)
    s.on_event(1, 0.0)
    s.reset()
    s.on_active(True, 0.5)        # still down: stays blocked
    assert not s.held and s.need_release
    s.on_active(False, 1.0)
    assert not s.need_release
    s.on_event(1, 2.0)
    assert s.held


@pytest.mark.parametrize("mode", ["hold", "toggle"])
def test_presses_do_not_count_while_unarmed(mode):
    s = ButtonState(mode)
    assert not s.armed
    s.on_event(1, 0.0)
    assert not s.held
    s.on_event(0, 0.1)
    s.on_event(1, 1.0)
    s.on_event(0, 1.1)
    s.arm(True)
    assert not s.held             # taps while the fish was speaking did not pre-arm
    s.on_event(1, 2.0)
    assert s.held


def test_key_held_across_arming_does_not_start_a_recording():
    s = ButtonState("hold")
    s.on_event(1, 0.0)            # pressed while unarmed and kept down
    s.arm(True)
    s.on_event(2, 0.1)
    s.on_active(True, 0.5)
    assert not s.held
    s.on_event(0, 1.0)
    s.on_event(1, 1.5)
    assert s.held


def test_cross_check_while_unarmed_blocks_the_held_key():
    s = ButtonState("hold")
    s.on_active(True, 0.0)        # down, and we never saw the press
    s.arm(True)
    s.on_active(True, 0.5)
    assert not s.held
    s.on_active(False, 1.0)
    s.on_active(True, 1.5)
    assert s.held


def test_disarm_clears_held_and_wants_a_release_if_still_down():
    s = armed()
    s.on_event(1, 0.0)
    s.arm(False)
    assert not s.held
    s.arm(True)
    s.on_active(True, 0.5)
    assert not s.held             # same press as before
    s.on_event(0, 1.0)
    s.on_event(1, 1.1)
    assert s.held


def test_disarm_clears_a_toggle_left_on():
    s = armed("toggle")
    s.on_event(1, 0.0)
    s.on_event(0, 0.1)
    s.arm(False)
    assert not s.held
    s.arm(True)
    assert not s.held
    s.on_event(1, 1.0)
    assert s.held


@pytest.mark.parametrize("mode", ["hold", "toggle"])
def test_release_clears_everything(mode):
    s = armed(mode)
    s.on_event(1, 0.0)
    assert s.held
    s.release()                   # the device went away
    assert not s.held and not s.need_release
    s.on_event(1, 1.0)
    assert s.held


# ---- the device thread, on fake devices -----------------------------------------------------

evdev = pytest.importorskip("evdev")
from fish_brain import evdev_button as eb  # noqa: E402

KEY_F9 = evdev.ecodes.KEY_F9
Ev = namedtuple("Ev", "type code value")


class FakeDev:
    """Looks enough like evdev.InputDevice: a pipe makes select() wake up."""

    def __init__(self, path: str, name: str = "Fake Remote", keys=(KEY_F9,)):
        self.path, self.name, self.keys = path, name, list(keys)
        self.fd, self._w = os.pipe()
        os.set_blocking(self.fd, False)
        self.pending: list[Ev] = []
        self.down: set[int] = set()
        self.dead = False
        self.grabbed = False
        self.closed = False

    def feed(self, value: int, code: int = KEY_F9) -> None:
        if value == 1:
            self.down.add(code)
        elif value == 0:
            self.down.discard(code)
        self.pending.append(Ev(EV_KEY, code, value))
        os.write(self._w, b"x")

    def unplug(self) -> None:
        self.dead = True
        os.write(self._w, b"x")

    def capabilities(self):
        return {EV_KEY: self.keys}

    def active_keys(self):
        if self.dead:
            raise OSError(errno.ENODEV, "No such device")
        return list(self.down)

    def read(self):
        if self.dead:
            raise OSError(errno.ENODEV, "No such device")
        try:
            os.read(self.fd, 4096)
        except BlockingIOError:
            pass
        if not self.pending:
            raise BlockingIOError
        evs, self.pending = self.pending, []
        return iter(evs)

    def grab(self):
        self.grabbed = True

    def close(self):
        if not self.closed:
            self.closed = True
            os.close(self.fd)
            os.close(self._w)


class FakeButton(eb.EvdevButton):
    nodes: dict = {}

    def _list_nodes(self):
        return list(self.nodes)

    def _open(self, path):
        dev = self.nodes.get(path)
        if dev is None:
            raise FileNotFoundError(path)
        if isinstance(dev, Exception):
            raise dev
        return dev


def make(nodes: dict, **cfg) -> FakeButton:
    cls = type("B", (FakeButton,), {"nodes": nodes})
    cfg.setdefault("evdev_device", "auto")
    cfg.setdefault("evdev_key", "KEY_F9")
    return cls(PTTConfig(**cfg))


def wait_for(cond, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


@pytest.fixture(autouse=True)
def fast_and_readable(monkeypatch):
    monkeypatch.setattr(eb, "_RETRY_S", 0.05)
    monkeypatch.setattr(eb, "_RESCAN_S", 0.05)
    monkeypatch.setattr(eb, "_CROSS_CHECK_S", 0.05)
    monkeypatch.setattr(eb.os, "access", lambda *a, **k: True)


def test_key_names_and_numbers():
    assert eb.resolve_key("KEY_VOICECOMMAND") == 582
    assert eb.resolve_key("f9") == KEY_F9
    assert eb.resolve_key("582") == 582
    assert eb.resolve_key(582) == 582
    assert eb.key_name(582) == "KEY_VOICECOMMAND"
    assert eb.key_name(99999) == "99999"
    with pytest.raises(ValueError):
        eb.resolve_key("KEY_NOPE")


def test_auto_picks_the_node_with_the_key_and_follows_it():
    remote = FakeDev("/dev/input/event7")
    mouse = FakeDev("/dev/input/event3", "Mouse", keys=(272,))
    b = make({mouse.path: mouse, remote.path: remote})
    try:
        assert wait_for(lambda: b.device_count == 1)
        assert mouse.closed and not remote.closed
        assert b.describe() == "evdev(1 device, KEY_F9, hold)"
        remote.feed(1)
        time.sleep(0.2)
        assert not b.is_held()                  # not armed yet
        remote.feed(0)
        time.sleep(0.1)
        b.arm(True)
        remote.feed(1)
        assert wait_for(b.is_held)
        remote.feed(2)
        remote.feed(0)
        assert wait_for(lambda: not b.is_held())
    finally:
        b.close()
    assert remote.closed and b.device_count == 0


def test_lost_release_is_recovered_by_the_cross_check():
    remote = FakeDev("/dev/input/event7")
    b = make({remote.path: remote})
    try:
        assert wait_for(lambda: b.device_count == 1)
        b.arm(True)
        remote.feed(1)
        assert wait_for(b.is_held)
        remote.down.clear()                     # released, but no event arrives
        assert wait_for(lambda: not b.is_held())
    finally:
        b.close()


def test_reset_blocks_until_released():
    remote = FakeDev("/dev/input/event7")
    b = make({remote.path: remote})
    try:
        assert wait_for(lambda: b.device_count == 1)
        b.arm(True)
        remote.feed(1)
        assert wait_for(b.is_held)
        b.reset()
        assert not b.is_held()
        time.sleep(0.3)                         # still down: the cross-check must not re-hold
        assert not b.is_held()
        remote.feed(0)
        time.sleep(0.1)
        remote.feed(1)
        assert wait_for(b.is_held)
    finally:
        b.close()


def test_toggle_mode_through_the_thread():
    remote = FakeDev("/dev/input/event7")
    b = make({remote.path: remote}, mode="toggle")
    try:
        assert wait_for(lambda: b.device_count == 1)
        b.arm(True)
        remote.feed(1)
        remote.feed(0)
        assert wait_for(b.is_held)
        time.sleep(0.3)                         # key is up; the cross-check leaves it on
        assert b.is_held()
        remote.feed(1)
        remote.feed(0)
        assert wait_for(lambda: not b.is_held())
        assert b.describe() == "evdev(1 device, KEY_F9, toggle)"
    finally:
        b.close()


def test_key_down_at_open_waits_for_a_fresh_press():
    remote = FakeDev("/dev/input/event7")
    remote.feed(1)                              # stale: pressed before we opened it
    b = make({remote.path: remote})
    try:
        b.arm(True)
        assert wait_for(lambda: b.device_count == 1)
        time.sleep(0.3)
        assert not b.is_held()
        remote.feed(0)
        time.sleep(0.1)
        remote.feed(1)
        assert wait_for(b.is_held)
    finally:
        b.close()


def test_unplug_releases_and_replug_is_found_again(capsys):
    nodes = {"/dev/input/event7": FakeDev("/dev/input/event7")}
    b = make(nodes)
    try:
        assert wait_for(lambda: b.device_count == 1)
        b.arm(True)
        first = nodes["/dev/input/event7"]
        first.feed(1)
        assert wait_for(b.is_held)
        del nodes["/dev/input/event7"]
        first.unplug()
        assert wait_for(lambda: b.device_count == 0)
        assert not b.is_held() and first.closed
        nodes["/dev/input/event9"] = FakeDev("/dev/input/event9")
        assert wait_for(lambda: b.device_count == 1)
        nodes["/dev/input/event9"].feed(1)
        assert wait_for(b.is_held)
    finally:
        b.close()
    assert "lost /dev/input/event7" in capsys.readouterr().out


def test_name_match_and_grab():
    remote = FakeDev("/dev/input/event7", "ACME Voice Remote Consumer Control")
    other = FakeDev("/dev/input/event2", "AT Keyboard")
    b = make({other.path: other, remote.path: remote}, evdev_device="name:voice remote",
             grab=True)
    try:
        assert wait_for(lambda: b.device_count == 1)
        assert remote.grabbed and other.closed and not other.grabbed
    finally:
        b.close()


def test_explicit_path_absent_then_present(capsys):
    nodes: dict = {}
    b = make(nodes, evdev_device="/dev/input/by-id/usb-remote-event-if01")
    try:
        time.sleep(0.3)
        assert b.device_count == 0
        assert b.describe() == "evdev(0 devices, KEY_F9, hold)"
        nodes["/dev/input/by-id/usb-remote-event-if01"] = FakeDev(
            "/dev/input/by-id/usb-remote-event-if01")
        assert wait_for(lambda: b.device_count == 1)
    finally:
        b.close()
    assert capsys.readouterr().out.count("is not there yet") == 1


def test_permission_error_on_a_path_is_reported_once(capsys):
    b = make({"/dev/input/event5": PermissionError(13, "Permission denied")},
             evdev_device="/dev/input/event5")
    try:
        time.sleep(0.4)                         # several retries
        assert b.device_count == 0
    finally:
        b.close()
    out = capsys.readouterr().out
    assert out.count("input` group") == 1 and "/dev/input/event5" in out


def test_no_readable_nodes_gives_the_group_hint_once(capsys, monkeypatch):
    monkeypatch.setattr(eb.os, "access", lambda *a, **k: False)
    b = make({"/dev/input/event0": FakeDev("/dev/input/event0"),
              "/dev/input/event1": FakeDev("/dev/input/event1")})
    try:
        time.sleep(0.4)
        assert b.device_count == 0
    finally:
        b.close()
    out = capsys.readouterr().out
    assert out.count("2 nodes, none readable by") == 1 and "usermod -aG input" in out


def test_no_node_with_the_key_is_reported_once(capsys):
    mouse = FakeDev("/dev/input/event3", "Mouse", keys=(272,))
    b = make({mouse.path: mouse})
    try:
        time.sleep(0.4)
        assert b.device_count == 0
    finally:
        b.close()
    assert capsys.readouterr().out.count("none of the 1 readable nodes has KEY_F9") == 1


def test_the_first_look_is_done_when_the_constructor_returns():
    remote = FakeDev("/dev/input/event7")
    b = make({remote.path: remote})
    try:
        assert b.describe() == "evdev(1 device, KEY_F9, hold)"
    finally:
        b.close()


def test_losing_the_device_stops_a_toggle_recording():
    nodes = {"/dev/input/event7": FakeDev("/dev/input/event7")}
    b = make(nodes, mode="toggle")
    try:
        b.arm(True)
        first = nodes.pop("/dev/input/event7")
        first.feed(1)
        first.feed(0)
        assert wait_for(b.is_held)
        first.unplug()
        assert wait_for(lambda: not b.is_held())
    finally:
        b.close()


def test_the_thread_survives_an_unexpected_error(capsys):
    class Odd(FakeDev):
        broken = True

        def read(self):
            if self.broken:
                raise RuntimeError("boom")
            return super().read()

    remote = Odd("/dev/input/event7")
    b = make({remote.path: remote})
    try:
        b.arm(True)
        remote.feed(1)
        assert wait_for(lambda: "unexpected RuntimeError" in capsys.readouterr().out)
        remote.broken = False
        remote.closed = False                   # the same fake is handed out again
        remote.fd, remote._w = os.pipe()
        os.set_blocking(remote.fd, False)
        remote.down.clear()
        assert wait_for(lambda: b.device_count == 1)
        time.sleep(0.2)
        remote.feed(1)
        assert wait_for(b.is_held)
    finally:
        b.close()


def test_several_keys_are_one_button():
    """A remote in mouse mode sends BTN_LEFT for the button that was KEY_ENTER."""
    assert eb.resolve_keys("KEY_ENTER, BTN_LEFT,KEY_ENTER") == (28, 272)
    assert eb.resolve_keys(272) == (272,)
    with pytest.raises(ValueError):
        eb.resolve_keys(" , ")
    keys = FakeDev("/dev/input/event2", "ACME Remote", keys=(28,))
    mouse = FakeDev("/dev/input/event3", "ACME Remote Mouse", keys=(272,))
    b = make({keys.path: keys, mouse.path: mouse}, evdev_device="name:acme",
             evdev_key="KEY_ENTER,BTN_LEFT")
    try:
        assert wait_for(lambda: b.device_count == 2)
        assert b.describe() == "evdev(2 devices, KEY_ENTER+BTN_LEFT, hold)"
        b.arm(True)
        mouse.feed(1, 272)
        assert wait_for(b.is_held)
        mouse.feed(0, 272)
        assert wait_for(lambda: not b.is_held())
        keys.feed(1, 28)
        assert wait_for(b.is_held)
        keys.feed(0, 28)
        assert wait_for(lambda: not b.is_held())
    finally:
        b.close()
