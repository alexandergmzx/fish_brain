"""Router RPC client and the links built on it, tested against a fake arduino-router.

The fake is a thread listening on an AF_UNIX socket that speaks the same MessagePack-RPC
framing as the real daemon, so none of this needs the board, a serial port or msgpack on
the wire being anything but what we send.
"""
from __future__ import annotations

import io
import os
import pty
import select
import socket
import threading
import time

import pytest

msgpack = pytest.importorskip("msgpack")

from fish_brain import router_rpc, serial_link  # noqa: E402
from fish_brain.config import SerialConfig  # noqa: E402
from fish_brain.router_rpc import RouterClient, RouterError, RouterWatchdog  # noqa: E402

KNOWN = {"fish_cmd", "fish_ping", "$/serial/open", "$/serial/close", "$/version"}


class FakeRouter:
    """Answers `True` to known methods, error code 2 to unknown ones, records everything."""

    def __init__(self, path: str, known=KNOWN, read: bool = True):
        self.path = path
        self.known = set(known)
        self.read = read                 # False = accept connections but never read (stall)
        self.frames: list = []           # every decoded message, in arrival order
        self._conns: list[socket.socket] = []
        self._stop = threading.Event()
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(path)
        self._srv.listen(8)
        threading.Thread(target=self._accept, daemon=True).start()

    @property
    def requests(self) -> list:
        return [(f[2], f[3]) for f in self.frames if f[0] == 0]

    @property
    def notifications(self) -> list:
        return [f for f in self.frames if f[0] == 2]

    def _accept(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return
            self._conns.append(conn)
            if self.read:
                threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        unpacker = msgpack.Unpacker(raw=False)
        while True:
            try:
                chunk = conn.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            unpacker.feed(chunk)
            for msg in unpacker:
                self.frames.append(msg)
                if msg[0] != 0:
                    continue
                _, msgid, method, _params = msg
                if method in self.known:
                    reply = [1, msgid, None, True]
                else:
                    reply = [1, msgid, [2, f"method {method} not available"], None]
                try:
                    conn.sendall(msgpack.packb(reply))
                except OSError:
                    return

    def stop(self) -> None:
        self._stop.set()
        for s in [self._srv, *self._conns]:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()
        try:
            os.unlink(self.path)
        except OSError:
            pass


def wait_for(cond, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return bool(cond())


@pytest.fixture
def sock_path(tmp_path):
    path = str(tmp_path / "r.sock")
    assert len(path) < 100, "AF_UNIX paths are limited to ~108 bytes"
    return path


@pytest.fixture
def router(sock_path):
    r = FakeRouter(sock_path)
    yield r
    r.stop()


def cfg_for(sock_path: str, **kw) -> SerialConfig:
    base = dict(port="/dev/ttyHS1", transport="bridge", router_socket=sock_path,
                max_cmd_hz=0, required=True, release_router=True,
                bridge_method="fish_cmd", bridge_ping_method="fish_ping")
    base.update(kw)
    return SerialConfig(**base)


# --- RouterClient ---------------------------------------------------------------------
def test_parse_address():
    assert router_rpc.parse_address("/run/x.sock") == ("unix", "/run/x.sock")
    assert router_rpc.parse_address("unix:/run/x.sock") == ("unix", "/run/x.sock")
    assert router_rpc.parse_address("tcp://127.0.0.1:7600") == ("tcp", ("127.0.0.1", 7600))
    with pytest.raises(ValueError):
        router_rpc.parse_address("tcp://nohost")


def test_notify_framing(router, sock_path):
    client = RouterClient(sock_path)
    assert client.notify("fish_cmd", "MOUTH 238 14") is True
    assert wait_for(lambda: router.frames)
    assert router.frames == [[2, "fish_cmd", ["MOUTH 238 14"]]]
    client.close()


def test_notify_bytes_on_the_wire(sock_path):
    """The exact bytes: a bare msgpack array, no length prefix, no delimiter."""
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    srv.listen(1)
    client = RouterClient(sock_path)
    client.notify("fish_cmd", "MOUTH 238 14")
    conn, _ = srv.accept()
    conn.settimeout(2)
    want = msgpack.packb([2, "fish_cmd", ["MOUTH 238 14"]])
    assert conn.recv(100) == want
    assert want[0] == 0x93 and want[1] == 0x02      # fixarray(3), then the type 2
    client.close(), conn.close(), srv.close()


def test_call_result_and_helpers(router, sock_path):
    client = RouterClient(sock_path)
    assert client.call("fish_ping") is True
    assert client.version() is True
    assert client.serial_close("/dev/ttyHS1") is True
    assert client.serial_open("/dev/ttyHS1") is True
    assert router.requests == [
        ("fish_ping", []), ("$/version", []),
        ("$/serial/close", ["/dev/ttyHS1"]), ("$/serial/open", ["/dev/ttyHS1"])]
    assert [f[1] for f in router.frames] == [1, 2, 3, 4]     # msgids count up
    client.close()


def test_call_unknown_method_is_router_error_2(router, sock_path):
    client = RouterClient(sock_path)
    with pytest.raises(RouterError) as info:
        client.call("nope")
    assert info.value.code == 2
    assert "not available" in info.value.msg
    assert client.call("fish_ping") is True         # the connection survives an error reply
    client.close()


def test_call_times_out_then_recovers(sock_path):
    stalled = FakeRouter(sock_path, read=False)
    client = RouterClient(sock_path)
    t0 = time.monotonic()
    with pytest.raises(TimeoutError):
        client.call("fish_ping", timeout=0.2)
    assert 0.15 < time.monotonic() - t0 < 1.0
    stalled.stop()
    good = FakeRouter(sock_path)
    try:
        assert client.call("fish_ping") is True
    finally:
        good.stop()
        client.close()


def test_call_without_router_raises_oserror(sock_path):
    with pytest.raises(OSError):
        RouterClient(sock_path).call("fish_ping")


def test_notify_never_raises_on_dead_socket(sock_path):
    client = RouterClient(sock_path, reconnect_s=0.05)
    assert client.notify("fish_cmd", "MOUTH 238 14") is False     # no router at all

    router = FakeRouter(sock_path)
    time.sleep(0.06)
    assert client.notify("fish_cmd", "A") is True
    assert wait_for(lambda: len(router.frames) == 1)

    router.stop()                                    # the router dies under us
    time.sleep(0.05)
    results = [client.notify("fish_cmd", f"B{i}") for i in range(20)]
    assert False in results                          # dropped, never raised

    router = FakeRouter(sock_path)                   # and comes back
    try:
        assert wait_for(lambda: client.notify("fish_cmd", "C"))
        assert wait_for(lambda: [2, "fish_cmd", ["C"]] in router.frames)
    finally:
        router.stop()
        client.close()


def test_notify_drops_when_router_stalls(sock_path):
    """A router stuck on a blocked UART write stops reading: sends must give up fast."""
    stalled = FakeRouter(sock_path, read=False)
    client = RouterClient(sock_path, reconnect_s=0.05)
    blob = "X" * 65536
    slowest, dropped = 0.0, 0
    try:
        for _ in range(40):
            t0 = time.monotonic()
            ok = client.notify("fish_cmd", blob)
            slowest = max(slowest, time.monotonic() - t0)
            dropped += not ok
    finally:
        stalled.stop()
        client.close()
    assert dropped > 0
    assert slowest < 0.5                             # 0.1 s send timeout, with slack


def test_tcp_address():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    client = RouterClient(f"tcp://127.0.0.1:{srv.getsockname()[1]}")
    assert client.notify("fish_cmd", "STOP") is True
    conn, _ = srv.accept()
    conn.settimeout(2)
    assert msgpack.unpackb(conn.recv(100)) == [2, "fish_cmd", ["STOP"]]
    client.close(), conn.close(), srv.close()


# --- RouterWatchdog -------------------------------------------------------------------
def test_watchdog_fires_after_router_restart(sock_path):
    calls = []
    router = FakeRouter(sock_path)
    dog = RouterWatchdog(sock_path, lambda: calls.append(1),
                         poll_s=0.05, backoff_min_s=0.02, backoff_max_s=0.1).start()
    try:
        time.sleep(0.2)
        assert calls == []                           # a healthy router is left alone
        router.stop()
        time.sleep(0.2)
        assert calls == []                           # nothing to talk to yet
        router = FakeRouter(sock_path)
        assert wait_for(lambda: calls == [1])
        time.sleep(0.2)
        assert calls == [1]                          # once per restart
        assert dog.restarts == 1
    finally:
        dog.stop()
        router.stop()


def test_watchdog_retries_a_failing_handler(router, sock_path):
    attempts = []

    def handler():
        attempts.append(1)
        if len(attempts) < 3:
            raise OSError("router not ready")

    dog = RouterWatchdog(sock_path, handler, poll_s=0.05, backoff_min_s=0.02,
                         backoff_max_s=0.1).start()
    try:
        time.sleep(0.1)
        for conn in list(router._conns):             # drop the connection, keep the router
            conn.shutdown(socket.SHUT_RDWR)
        assert wait_for(lambda: dog.restarts == 1)
        assert len(attempts) == 3
    finally:
        dog.stop()


def test_watchdog_sees_replaced_socket_file(sock_path):
    """Same connection still open, but the socket file is a new one: treat as a restart."""
    calls = []
    old = FakeRouter(sock_path)
    dog = RouterWatchdog(sock_path, lambda: calls.append(1),
                         poll_s=0.05, backoff_min_s=0.02, backoff_max_s=0.1).start()
    try:
        assert wait_for(lambda: old._conns)
        os.rename(sock_path, sock_path + ".old")     # old router keeps its connections
        new = FakeRouter(sock_path)
        assert wait_for(lambda: calls == [1])
        new.stop()
    finally:
        dog.stop()
        old.path = sock_path + ".old"
        old.stop()


# --- BridgeLink -----------------------------------------------------------------------
def test_bridge_link_framing(router, sock_path):
    link = serial_link.BridgeLink(cfg_for(sock_path))
    assert router.requests == [("$/serial/open", ["/dev/ttyHS1"]), ("fish_ping", [])]
    assert link.describe() == "bridge fish_cmd" and link.attached

    link.mouth_pulse(238, 14)
    link.gesture("neck", "180 450 -180 350")
    assert wait_for(lambda: len(router.notifications) == 2)
    assert router.notifications == [[2, "fish_cmd", ["MOUTH 238 14"]],
                                    [2, "fish_cmd", ["NECK 180 450 -180 350"]]]

    link.all_stop()                                  # a call first, then a notification
    assert wait_for(lambda: len(router.frames) == 6)
    assert router.frames[-2][0] == 0 and router.frames[-2][2:] == ["fish_cmd", ["STOP"]]
    assert router.frames[-1] == [2, "fish_cmd", ["STOP"]]
    link.close()


def test_bridge_link_stop_on_exit(router, sock_path):
    with serial_link.open_link(cfg_for(sock_path)) as link:
        assert isinstance(link, serial_link.BridgeLink)
    assert wait_for(lambda: [2, "fish_cmd", ["STOP"]] in router.frames)


def test_bridge_link_ping_not_registered(sock_path):
    router = FakeRouter(sock_path, known=KNOWN - {"fish_ping"})
    try:
        with pytest.raises(RuntimeError, match="fish_ping not registered.*router restore"):
            serial_link.BridgeLink(cfg_for(sock_path))
    finally:
        router.stop()


def test_bridge_link_skips_serial_open_for_a_laptop_port(router, sock_path):
    serial_link.BridgeLink(cfg_for(sock_path, port="/dev/ttyACM0")).close()
    assert router.requests == [("fish_ping", [])]


def test_bridge_all_stop_survives_a_dead_router(router, sock_path):
    link = serial_link.BridgeLink(cfg_for(sock_path))
    router.stop()
    link.all_stop()                                  # must not raise
    link.mouth_pulse(238, 14)
    link.close()


# --- ResilientLink --------------------------------------------------------------------
def test_resilient_link_drops_then_attaches(sock_path):
    cfg = cfg_for(sock_path, required=False)
    link = serial_link.open_link(cfg)                # no router yet
    assert isinstance(link, serial_link.ResilientLink)
    assert not link.attached
    assert link.describe() == "bridge fish_cmd (degraded)"
    link._retry_s = 0.05
    link.mouth_pulse(238, 14)                        # dropped, no error
    link.all_stop()

    router = FakeRouter(sock_path)
    try:
        time.sleep(0.06)
        assert wait_for(lambda: (link.mouth_pulse(238, 20), link.attached)[1])
        assert link.describe() == "bridge fish_cmd"
        link.mouth_pulse(-200, 30)
        assert wait_for(lambda: [2, "fish_cmd", ["MOUTH -200 30"]] in router.frames)
        assert [2, "fish_cmd", ["MOUTH 238 14"]] not in router.frames
        with link:
            pass
        assert wait_for(lambda: [2, "fish_cmd", ["STOP"]] in router.frames)
        assert not link.attached
    finally:
        router.stop()


def test_resilient_link_turns_errors_into_unattached(capsys):
    class Flaky(serial_link.MockSerialLink):
        fail = False
        closed = False

        def _write_raw(self, data):
            if self.fail:
                raise OSError("write failed")
            super()._write_raw(data)

        def close(self):
            self.closed = True

    cfg = SerialConfig(port="/dev/ttyHS1", max_cmd_hz=0, required=False)
    out = io.StringIO()
    made = []

    def factory():
        made.append(Flaky(cfg, stream=out))
        return made[-1]

    link = serial_link.ResilientLink(cfg, factory, retry_s=60)
    assert link.attached and link.describe() == "mock"
    link.mouth_pulse(238, 14)
    assert out.getvalue() == "  TX  MOUTH 238 14\n"

    made[0].fail = True
    link.mouth_pulse(238, 14)                        # the error is swallowed
    assert not link.attached and made[0].closed
    assert link.describe() == "serial /dev/ttyHS1 (degraded)"
    link.mouth_pulse(238, 14)                        # too early to retry: dropped
    link.all_stop()
    assert len(made) == 1
    assert link.try_attach() and len(made) == 2      # an explicit retry ignores the wait

    err = capsys.readouterr().err
    assert err.count("[link] attached") == 2
    assert err.count("voice-only mode") == 1         # state changes are logged once


def test_resilient_link_reports_ebusy_once(capsys):
    cfg = SerialConfig(port="/dev/ttyHS1", max_cmd_hz=0, required=False)

    def factory():
        raise OSError(16, "could not open port /dev/ttyHS1")

    link = serial_link.ResilientLink(cfg, factory, retry_s=60)
    link.try_attach(), link.try_attach()
    link.close()
    err = capsys.readouterr().err
    assert err.count("EBUSY: router still holds it") == 1
    assert "serial /dev/ttyHS1 unavailable" in err


# --- open_link ------------------------------------------------------------------------
def test_open_link_choices(sock_path):
    assert serial_link.open_link(cfg_for(sock_path), dry_run=True).describe() == "mock"
    with pytest.raises(ValueError):
        serial_link.open_link(cfg_for(sock_path, transport="carrier-pigeon"))
    with pytest.raises(OSError):                     # required: the failure propagates
        serial_link.open_link(cfg_for(sock_path, transport="bridge"))


def test_mock_link_output_unchanged():
    out = io.StringIO()
    with serial_link.MockSerialLink(SerialConfig(max_cmd_hz=0), stream=out) as link:
        link.mouth(120), link.mouth(120), link.mouth_pulse(238, 14)
        link.gesture("tail", "200 300 -200 300")
    assert out.getvalue() == ("  TX  MOUTH 120\n  TX  MOUTH 238 14\n"
                              "  TX  TAIL 200 300 -200 300\n  TX  STOP\n")


# --- SerialLink on a pty --------------------------------------------------------------
def read_pty(fd: int, want: bytes, timeout: float = 3.0) -> bytes:
    buf = b""
    deadline = time.monotonic() + timeout
    while want not in buf and time.monotonic() < deadline:
        if select.select([fd], [], [], 0.05)[0]:
            buf += os.read(fd, 4096)
    return buf


@pytest.fixture
def pty_port():
    pytest.importorskip("serial")
    master, slave = pty.openpty()
    yield master, os.ttyname(slave)
    os.close(master), os.close(slave)


def test_serial_link_laptop_port_never_touches_the_router(router, sock_path, pty_port):
    master, port = pty_port
    cfg = cfg_for(sock_path, port=port, transport="serial")
    with serial_link.open_link(cfg) as link:
        assert type(link) is serial_link.SerialLink
        assert link.describe() == f"serial {port}"
        link.mouth_pulse(238, 14)
    # One STOP when the link attaches, the command, and the STOP of the context exit.
    assert read_pty(master, b"14\nSTOP\n") == b"\nSTOP\nMOUTH 238 14\nSTOP\n"
    assert router.frames == []


def test_serial_link_releases_watches_and_restores(sock_path, pty_port, monkeypatch):
    master, port = pty_port
    monkeypatch.setattr(serial_link, "_is_unoq_port", lambda p: True)
    router = FakeRouter(sock_path)
    cfg = cfg_for(sock_path, port=port, transport="serial")
    link = serial_link.SerialLink(cfg)
    link._watchdog.stop()                            # swap in a fast one for the test
    link._watchdog = RouterWatchdog(sock_path, link._on_router_restart, poll_s=0.05,
                                    backoff_min_s=0.02, backoff_max_s=0.1).start()
    try:
        assert router.requests == [("$/serial/close", [port])]
        link.mouth_pulse(238, 14)
        assert read_pty(master, b"14\n") == b"\nSTOP\nMOUTH 238 14\n"

        router.stop()                                # the router restarts...
        router = FakeRouter(sock_path)
        assert wait_for(lambda: router.requests == [("$/serial/close", [port])])
        assert wait_for(link._stop_first.is_set)
        link.mouth_pulse(238, 20)                    # ...so the next command leads with STOP
        assert read_pty(master, b"20\n") == b"\nSTOP\nMOUTH 238 20\n"
        link.mouth_pulse(238, 21)                    # only once
        assert read_pty(master, b"21\n") == b"MOUTH 238 21\n"

        link.close()
        assert wait_for(lambda: ("$/serial/open", [port]) in router.requests)
    finally:
        link.close()
        router.stop()


def test_serial_link_without_router_just_opens(sock_path, pty_port, monkeypatch):
    """A /dev/ttyHS* port on a machine with no router (router-off setup): no waiting."""
    master, port = pty_port
    monkeypatch.setattr(serial_link, "_is_unoq_port", lambda p: True)
    monkeypatch.setattr(serial_link, "_ROUTER_UNIT_HINTS", ())
    t0 = time.monotonic()
    link = serial_link.SerialLink(cfg_for(sock_path, port=port, transport="serial"))
    assert time.monotonic() - t0 < 2.0
    assert link._watchdog is None and not link._released
    link.close()


def test_serial_link_restores_router_when_port_fails(router, sock_path, monkeypatch):
    pytest.importorskip("serial")
    cfg = cfg_for(sock_path, port="/dev/ttyHS_does_not_exist", transport="serial")
    with pytest.raises(OSError):
        serial_link.SerialLink(cfg)
    assert router.requests == [("$/serial/close", [cfg.port]), ("$/serial/open", [cfg.port])]


def test_serial_link_releases_late_when_router_starts_after_us(sock_path, pty_port,
                                                               monkeypatch):
    """Socket file present but nobody listening yet (boot race): the port opens, and the
    release is sent as soon as the router answers, then undone on close."""
    master, port = pty_port
    monkeypatch.setattr(serial_link, "_is_unoq_port", lambda p: True)
    dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    dead.bind(sock_path)                             # bound, never listening: ECONNREFUSED
    link = serial_link.SerialLink(cfg_for(sock_path, port=port, transport="serial"))
    router = None
    try:
        assert not link._released and link._watchdog is not None
        dead.close()
        os.unlink(sock_path)
        router = FakeRouter(sock_path)
        assert wait_for(lambda: router.requests == [("$/serial/close", [port])], timeout=8)
        assert wait_for(lambda: link._released)
        link.close()
        assert wait_for(lambda: ("$/serial/open", [port]) in router.requests)
    finally:
        link.close()
        if router is not None:
            router.stop()


def test_watchdog_assume_lost_fires_on_first_connection(router, sock_path):
    calls = []
    dog = RouterWatchdog(sock_path, lambda: calls.append(1), poll_s=0.05,
                         backoff_min_s=0.02, backoff_max_s=0.1, assume_lost=True).start()
    try:
        assert wait_for(lambda: calls == [1])
        time.sleep(0.2)
        assert calls == [1]
    finally:
        dog.stop()


def test_resilient_link_late_error_does_not_drop_the_new_link():
    cfg = SerialConfig(port="/dev/ttyHS1", max_cmd_hz=0, required=False)
    made = []

    def factory():
        made.append(serial_link.MockSerialLink(cfg, stream=io.StringIO()))
        return made[-1]

    link = serial_link.ResilientLink(cfg, factory, retry_s=60)
    old = made[0]
    link._detach(old, OSError("gone"))
    assert link.try_attach() and link._link is made[1]
    link._detach(old, OSError("a second thread reports the same dead link"))
    assert link.attached and link._link is made[1]
    link.close()
    assert not link.try_attach() and len(made) == 2  # closed: no further opens


def test_open_link_accepts_transport_in_any_case(router, sock_path):
    link = serial_link.open_link(cfg_for(sock_path, transport=" Bridge "))
    assert isinstance(link, serial_link.BridgeLink)
    link.close()


# --- one holder per port, and whether the MCU answers ----------------------------------
def test_second_link_is_refused_before_the_router_hears_of_it(sock_path, pty_port, monkeypatch):
    """The trap this guards: a second opener ends with `$/serial/open` and the router takes
    the UART back under the fish that is still talking."""
    master, port = pty_port
    monkeypatch.setattr(serial_link, "_is_unoq_port", lambda p: True)
    router = FakeRouter(sock_path)
    cfg = cfg_for(sock_path, port=port, transport="serial")
    first = serial_link.SerialLink(cfg)
    try:
        assert router.requests == [("$/serial/close", [port])]
        with pytest.raises(serial_link.LinkBusy) as err:
            serial_link.SerialLink(cfg)
        assert f"pid {os.getpid()}" in str(err.value)
        assert router.requests == [("$/serial/close", [port])]      # no second word to it
    finally:
        first.close()
    assert wait_for(lambda: ("$/serial/open", [port]) in router.requests)
    again = serial_link.SerialLink(cfg)                             # free again after close
    again.close()
    router.stop()


def test_laptop_port_takes_no_lock(pty_port, sock_path):
    master, port = pty_port
    cfg = cfg_for(sock_path, port=port, transport="serial")
    a = serial_link.SerialLink(cfg)
    b = serial_link.SerialLink(cfg)
    a.close(), b.close()


def test_link_tells_a_silent_mcu_from_an_answering_one(pty_port, sock_path, monkeypatch, capsys):
    master, port = pty_port
    cfg = cfg_for(sock_path, port=port, transport="serial")
    cfg.max_cmd_hz = 0
    clock = [100.0]
    link = serial_link.SerialLink(cfg)
    try:
        assert link.health() == "ok"                     # nothing known yet
        monkeypatch.setattr(serial_link.time, "monotonic", lambda: clock[0])
        for n in range(25):                              # 25 lines over 2.5 s, nothing back
            clock[0] += 0.1
            link.mouth_pulse(238, 10)
        assert link.health() == "silent"
        assert "(MCU silent)" in link.describe()
        assert capsys.readouterr().err.count("MCU silent") == 1     # said once
        os.write(master, b"MOUTH 238 10\r\nMOUTH -> 1 step\r\n> ")
        monkeypatch.undo()
        time.sleep(0.1)
        link.mouth_pulse(238, 10)
        assert link.health() == "ok"
        assert "answering again" in capsys.readouterr().err
    finally:
        link.close()


def test_wait_reply(pty_port, sock_path):
    master, port = pty_port
    link = serial_link.SerialLink(cfg_for(sock_path, port=port, transport="serial"))
    try:
        assert link.wait_reply(0.2) is False
        os.write(master, b"> ")
        assert link.wait_reply(1.0) is True
    finally:
        link.close()
    out = io.StringIO()
    assert serial_link.MockSerialLink(SerialConfig(), stream=out).wait_reply(0.1) is None


def test_link_log_records_both_directions(pty_port, sock_path, tmp_path):
    master, port = pty_port
    cfg = cfg_for(sock_path, port=port, transport="serial")
    cfg.max_cmd_hz = 0
    cfg.log_path = str(tmp_path / "link.log")
    link = serial_link.SerialLink(cfg)
    try:
        link.mouth_pulse(238, 14)
        os.write(master, b"MOUTH 238 14\r\n")
        time.sleep(0.1)
        link.mouth_pulse(-200, 20)
    finally:
        link.close()
    lines = (tmp_path / "link.log").read_text().splitlines()
    kinds = [ln.split(" ", 2)[1:] for ln in lines]
    assert ["T", "MOUTH 238 14"] in kinds and ["T", "MOUTH -200 20"] in kinds
    assert any(k == "R" and "MOUTH 238 14" in text for k, text in kinds)


def test_link_log_that_cannot_open_is_only_a_note(pty_port, sock_path):
    master, port = pty_port
    cfg = cfg_for(sock_path, port=port, transport="serial")
    cfg.log_path = "/nonexistent-dir/link.log"
    link = serial_link.SerialLink(cfg)
    link.mouth_pulse(238, 14)
    link.close()
