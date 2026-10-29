"""printer.py: the worker against a socketpair that plays the printer, the mock, the setting,
the one-shot. No hardware, no network, no Bluetooth."""
import argparse
import io
import socket
import threading
import time

import pytest

from fish_brain import app, printer, ticket
from fish_brain.config import Config, FortuneConfig, PrinterConfig

FAST = printer.Timing(connect_s=0.5, retry_s=0.05, late_s=1.0, write_s=0.5, chunk=64,
                      gap_s=0.0, tail_s=0.0, reopen_s=0.0, probe_s=60.0)


def wait_for(cond, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def mock_cfg() -> PrinterConfig:
    return PrinterConfig(device="mock", channel=1)


class PairPort:
    """Each open() hands out the printer's end of a fresh socketpair; the test reads the
    other end. `fail` opens raise first, `block` makes open wait until abort()."""

    def __init__(self, fail: int = 0, block: bool = False, small: bool = False):
        self.fail, self.block, self.small = fail, block, small
        self.opened = 0
        self.peers: list[socket.socket] = []
        self.ends: list[socket.socket] = []
        self.released = threading.Event()

    def describe(self) -> str:
        return "pair"

    def open(self, timeout: float):
        self.opened += 1
        if self.block:
            self.released.wait(10)
            raise ConnectionAbortedError(103, "aborted")
        if self.opened <= self.fail:
            raise ConnectionRefusedError(111, "Connection refused")
        a, b = socket.socketpair()
        if self.small:
            a.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)
            b.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
        a.settimeout(timeout)
        self.ends.append(a)
        self.peers.append(b)
        return a

    def abort(self) -> None:
        self.released.set()

    def show(self, text: str, n: int) -> None:
        pass

    def close(self) -> None:
        for s in self.peers + self.ends:
            s.close()


def read_all(sock: socket.socket, timeout: float = 3.0) -> bytes:
    sock.settimeout(timeout)
    out = bytearray()
    while True:
        got = sock.recv(65536)
        if not got:
            return bytes(out)
        out.extend(got)


def make(port, **kw) -> printer.Printer:
    return printer.Printer(mock_cfg(), port, timing=kw.pop("timing", FAST), **kw).start()


@pytest.fixture
def rig():
    made = []

    def build(port, **kw):
        p = make(port, **kw)
        made.append((p, port))
        return p
    yield build
    for p, port in made:
        p.close()
        if isinstance(port, PairPort):
            port.close()


def big_plate(tmp_path):
    """A 384 x 800 plate for card 13: 38 KB, more than a small socket buffer holds."""
    (tmp_path / "tarot").mkdir()
    (tmp_path / "tarot" / "13.pbm").write_bytes(b"P4\n384 800\n" + b"\xaa" * (48 * 800))
    return tmp_path


# ---- bytes ---------------------------------------------------------------------------------------
def test_the_tickets_bytes_arrive_whole_and_in_order(rig):
    port = PairPort()
    p = rig(port)
    assert p.submit(ticket.SAMPLE)
    assert wait_for(lambda: port.peers)
    got = read_all(port.peers[0])
    want = b"".join(ticket.encode(ticket.layout(ticket.SAMPLE)))
    assert got == want
    assert got.startswith(b"\x1b@\x1c.\x1bR\x00\x1bt")
    assert p.wait(3)
    snap = p.snapshot()
    assert snap["state"] == "printed" and snap["bytes"] == len(want) and snap["printed"] == 1


def test_a_plate_goes_out_in_paced_pieces(rig, tmp_path):
    port = PairPort()
    p = rig(port, art_root=big_plate(tmp_path))
    sent = []

    class Spy:
        def __init__(self, s):
            self.s = s

        def settimeout(self, t):
            self.s.settimeout(t)

        def sendall(self, b):
            sent.append(len(b))
            self.s.sendall(b)

        def shutdown(self, how):
            self.s.shutdown(how)

        def close(self):
            self.s.close()
    real = port.open
    port.open = lambda timeout: Spy(real(timeout))
    assert p.submit(ticket.SAMPLE)
    assert wait_for(lambda: port.peers)
    got = read_all(port.peers[0])
    assert p.wait(3)
    assert max(sent) <= FAST.chunk and sum(sent) == len(got) > 48 * 800
    assert b"\x1dv0\x00\x30\x00" in got                      # a band of the 48-byte plate


def test_the_mock_logs_the_ticket_as_text():
    out = io.StringIO()
    p = printer.make_printer(mock_cfg(), stream=out)
    try:
        assert p.describe() == "mock"
        assert p.submit(ticket.SAMPLE)
        assert p.wait(3)
    finally:
        p.close()
    text = out.getvalue()
    assert text.startswith("[printer] mock ticket #0 (")
    assert "  | " + ticket.preview(ticket.layout(ticket.SAMPLE)).split("\n")[0] in text
    assert "  |      p a r a   P r u e b a\n" in text
    assert "  | Palabra mágica ......... Zumbalí\n" in text
    assert p.port.data == b"".join(ticket.encode(ticket.layout(ticket.SAMPLE)))


# ---- connecting ----------------------------------------------------------------------------------
def test_retries_end_in_success(rig):
    port = PairPort(fail=2)
    p = rig(port)
    assert p.submit(ticket.SAMPLE)
    assert wait_for(lambda: port.peers)
    read_all(port.peers[0])
    assert p.wait(3)
    snap = p.snapshot()
    assert port.opened == 3
    assert snap["state"] == "printed" and snap["reach"] is True


def test_a_printer_that_never_answers_fails_after_late_s(rig, capsys):
    port = PairPort(fail=10_000)
    p = rig(port)
    t0 = time.monotonic()
    assert p.submit(ticket.SAMPLE)
    assert p.wait(3)
    took = time.monotonic() - t0
    snap = p.snapshot()
    assert snap["state"] == "failed" and snap["why"].startswith("not reachable")
    assert "ECONNREFUSED" in snap["why"] and snap["reach"] is False
    assert FAST.late_s - FAST.retry_s - 0.1 <= took < FAST.late_s + 0.5
    assert port.opened > 3
    err = capsys.readouterr().err
    assert err.count("[printer] not reachable (") == 1        # said once, not per retry
    assert "ticket #0 failed: not reachable" in err


def test_late_s_counts_from_the_hand_over_not_from_the_pick_up(rig):
    port = PairPort(fail=10_000)
    p = rig(port)
    t0 = time.monotonic()
    assert p.submit(ticket.sample(0))
    assert wait_for(lambda: port.opened == 1)
    assert p.submit(ticket.sample(1))                         # queued behind the first
    assert p.wait(3)
    took = time.monotonic() - t0
    assert took < FAST.late_s + 0.5                            # not two windows end to end
    assert p.snapshot()["failed"] == 2


def test_a_ticket_queued_past_late_s_fails_without_a_connect(rig):
    port = PairPort()
    held = threading.Event()
    real = port.open
    timeouts = []

    def slow(timeout):
        timeouts.append(timeout)
        if len(timeouts) == 1:
            held.wait(3)
            raise ConnectionRefusedError(111, "Connection refused")
        return real(timeout)
    port.open = slow
    p = rig(port, timing=printer.Timing(**{**FAST.__dict__, "connect_s": 5.0}))
    assert p.submit(ticket.sample(0))
    assert wait_for(lambda: timeouts)
    assert timeouts[0] <= FAST.late_s                          # capped by what is left
    assert p.submit(ticket.sample(1))
    time.sleep(FAST.late_s + 0.1)
    held.set()
    assert p.wait(3)
    snap = p.snapshot()
    assert len(timeouts) == 1                                  # the second never connected
    assert snap["failed"] == 2 and snap["why"] == "late"


def test_no_bluetooth_sockets_fail_at_once_with_the_hint(monkeypatch, rig):
    monkeypatch.delattr(socket, "AF_BLUETOOTH", raising=False)
    with pytest.raises(RuntimeError, match="FISH_PRINTER=mock"):
        printer._bt()
    p = rig(printer.RfcommPort("DC:0D:51:92:74:DA", 1))
    assert p.describe() == "DC:0D:51:92:74:DA ch1"
    t0 = time.monotonic()
    assert p.submit(ticket.SAMPLE)
    assert p.wait(3) and time.monotonic() - t0 < 0.5             # no retries
    assert "Bluetooth sockets" in p.snapshot()["why"]


def test_make_printer_without_bluetooth_sockets_is_off(monkeypatch, capsys):
    monkeypatch.delattr(socket, "AF_BLUETOOTH", raising=False)
    assert printer.make_printer(PrinterConfig(device="DC:0D:51:92:74:DA")) is None
    assert capsys.readouterr().err.startswith("[printer] off: the ticket printer needs")


# ---- failing mid-ticket --------------------------------------------------------------------------
def test_a_printer_that_never_reads_is_stalled(rig, tmp_path):
    port = PairPort(small=True)
    p = rig(port, art_root=big_plate(tmp_path),
            timing=printer.Timing(**{**FAST.__dict__, "write_s": 0.3}))
    assert p.submit(ticket.SAMPLE)
    assert p.wait(3)
    snap = p.snapshot()
    assert snap["state"] == "failed" and snap["why"] == "stalled"
    assert port.opened == 1                                     # no resend


def test_a_printer_that_drops_the_link_fails_without_a_resend(rig):
    port = PairPort()
    real = port.open

    def open_then_drop(timeout):
        a = real(timeout)
        port.peers[-1].close()
        return a
    port.open = open_then_drop
    p = rig(port)
    assert p.submit(ticket.SAMPLE)
    assert p.wait(3)
    snap = p.snapshot()
    assert snap["state"] == "failed" and snap["why"].startswith("dropped (")
    assert port.opened == 1


# ---- the queue and Reprint -----------------------------------------------------------------------
def test_a_full_queue_says_no_at_once(rig):
    port = PairPort(block=True)
    p = rig(port)
    assert p.submit(ticket.sample(0))
    assert wait_for(lambda: port.opened == 1)                   # the worker holds the first
    assert p.submit(ticket.sample(1)) and p.submit(ticket.sample(2))
    t0 = time.monotonic()
    assert p.submit(ticket.sample(3)) is False
    assert time.monotonic() - t0 < 0.05
    assert p.snapshot()["last_n"] == 0 and p.reprint() == (False, "printing")


def test_reprint_is_refused_while_busy_and_prints_the_last_ticket_after(rig):
    port = PairPort()
    p = rig(port)
    assert p.reprint() == (False, "no ticket yet")
    held = threading.Event()
    real = port.open

    def slow(timeout):
        held.wait(3)
        return real(timeout)
    port.open = slow
    t = ticket.sample(7)
    assert p.submit(t)
    assert p.reprint() == (False, "printing")
    held.set()
    assert wait_for(lambda: port.peers)
    first = read_all(port.peers[0])
    assert p.wait(3)
    assert p.reprint() == (True, t.n)
    assert wait_for(lambda: len(port.peers) == 2)
    assert read_all(port.peers[1]) == first
    assert p.wait(3)
    snap = p.snapshot()
    assert snap["printed"] == 2 and snap["reprint"] is True


def test_a_kept_ticket_reprints_without_having_printed(rig):
    port = PairPort()
    p = rig(port)
    p.keep(ticket.SAMPLE)
    assert port.opened == 0
    assert p.reprint() == (True, 0)
    assert wait_for(lambda: port.peers)
    assert read_all(port.peers[0])


def test_a_printer_not_started_takes_nothing():
    p = printer.Printer(mock_cfg(), PairPort(), timing=FAST)
    assert p.submit(ticket.SAMPLE) is False
    assert p.reprint() == (False, "no printer")
    assert p.probe() is False


# ---- probe, snapshot, close ----------------------------------------------------------------------
def test_a_probe_connects_and_closes_and_is_skipped_when_recent(rig):
    port = PairPort()
    p = rig(port)
    assert p.snapshot()["reach"] is None
    assert p.probe()
    assert wait_for(lambda: p.snapshot()["reach"] is True)
    assert read_all(port.peers[0]) == b""                       # nothing reaches the paper
    assert wait_for(lambda: p.probe() is False)                  # contact is fresh
    assert port.opened == 1


def test_close_returns_within_a_second_with_a_job_stuck_sending(rig, tmp_path):
    port = PairPort(small=True)
    p = rig(port, art_root=big_plate(tmp_path),
            timing=printer.Timing(**{**FAST.__dict__, "write_s": 30.0}))
    assert p.submit(ticket.SAMPLE)
    assert wait_for(lambda: p.snapshot()["state"] == "printing")
    time.sleep(0.1)
    t0 = time.monotonic()
    p.close()
    assert time.monotonic() - t0 < 1.0
    assert not p._thread.is_alive()
    assert p.snapshot()["state"] == "failed" and p.snapshot()["why"] == "stopped"


def test_close_returns_within_a_second_with_a_connect_stuck(rig):
    port = PairPort(block=True)
    p = rig(port, timing=printer.Timing(**{**FAST.__dict__, "late_s": 60.0}))
    assert p.submit(ticket.SAMPLE)
    assert wait_for(lambda: port.opened == 1)
    t0 = time.monotonic()
    p.close()
    assert time.monotonic() - t0 < 1.0 and not p._thread.is_alive()
    assert p.submit(ticket.SAMPLE) is False


def test_snapshot_is_safe_from_another_thread(rig, tmp_path):
    port = PairPort()
    p = rig(port, art_root=big_plate(tmp_path))
    seen, errors, stop = set(), [], threading.Event()

    def watch():
        while True:                     # one more look after the stop: the ticket has ended
            last = stop.is_set()
            try:
                s = p.snapshot()
                seen.add(s["state"])
                assert {"alive", "why", "n", "busy", "reach", "bytes"} <= s.keys()
            except Exception as e:      # noqa: BLE001
                errors.append(e)
            if last:
                break
    w = threading.Thread(target=watch)
    w.start()
    reader = threading.Thread(target=lambda: wait_for(lambda: port.peers) and read_all(port.peers[0]))
    reader.start()
    assert p.submit(ticket.SAMPLE)
    assert p.wait(5)
    stop.set()
    w.join(2)
    reader.join(5)
    assert not errors
    assert "printed" in seen and p.snapshot()["alive"] is True


def test_a_record_follows_each_state(rig, monkeypatch):
    calls = []
    from fish_brain import debug
    monkeypatch.setattr(debug, "emit", lambda kind, **f: calls.append((kind, f)))
    port = PairPort()
    p = rig(port)
    assert p.submit(ticket.SAMPLE)
    assert wait_for(lambda: port.peers)
    read_all(port.peers[0])
    assert p.wait(3)
    states = [f["state"] for kind, f in calls if kind == "ticket"]
    assert states == ["queued", "connecting", "printing", "printed"]
    assert calls[-1][1]["bytes"] > 0 and calls[-1][1]["n"] == 0


# ---- the setting ---------------------------------------------------------------------------------
@pytest.mark.parametrize("device,channel,kind", [
    ("", 1, "off"), ("mock", 1, "mock"), ("MOCK", 1, "mock"),
    ("dc:0d:51:92:74:da", 1, "rfcomm"), ("DC:0D:51:92:74:DA", 30, "rfcomm"),
    ("DC:0D:51:92:74", 1, "bad"), ("printer", 1, "bad"), ("DC:0D:51:92:74:DA", 0, "bad"),
])
def test_the_setting(device, channel, kind):
    cfg = PrinterConfig(device=device, channel=channel)
    assert cfg.kind() == kind
    assert bool(cfg.problem()) == (kind == "bad")
    assert printer.summary(cfg) == {"off": "off", "bad": "off", "mock": "mock",
                                    "rfcomm": f"DC:0D:51:92:74:DA ch{channel}"}[kind]


def test_the_laptop_has_no_printer_and_tickets_on(capsys):
    cfg = Config()
    assert cfg.printer.kind() == "off" and cfg.printer.channel == 1
    assert cfg.fortune.ticket is True
    assert printer.make_printer(cfg.printer) is None
    assert capsys.readouterr().err == ""


def test_the_environment(monkeypatch):
    monkeypatch.setenv("FISH_PRINTER", " dc:0d:51:92:74:da ")
    monkeypatch.setenv("FISH_PRINTER_CHANNEL", "3")
    monkeypatch.setenv("FISH_FORTUNE_TICKET", "false")
    cfg = Config()
    assert printer.summary(cfg.printer) == "DC:0D:51:92:74:DA ch3"
    assert FortuneConfig().ticket is False


def test_a_malformed_printer_is_off_with_one_line_never_an_exit(capsys):
    assert printer.make_printer(PrinterConfig(device="DC-0D-51")) is None
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and err.startswith("[printer] off: FISH_PRINTER='DC-0D-51'")


# ---- the one-shot --------------------------------------------------------------------------------
def test_print_test_with_the_mock_prints_the_sample(capsys):
    cfg = Config()
    cfg.printer = mock_cfg()
    assert app._print_test(cfg, 13) == 0
    out = capsys.readouterr().out
    assert "[printer] mock ticket #0" in out and "XIII · LA MUERTE" in out
    assert out.splitlines()[-1].startswith("printer ok: mock, ")


@pytest.mark.parametrize("device", ["", "nonsense"])
def test_print_test_without_a_printer_is_a_configuration_problem(device, capsys):
    cfg = Config()
    cfg.printer = PrinterConfig(device=device)
    assert app._print_test(cfg, 13) == 78
    assert "Configuration problem" in capsys.readouterr().err


def test_print_test_fails_when_the_ticket_does_not_print(monkeypatch, capsys):
    cfg = Config()
    cfg.printer = mock_cfg()

    class Dead(printer.MockPort):
        def open(self, timeout):
            raise RuntimeError("the ticket printer needs Bluetooth sockets")
    monkeypatch.setattr(printer, "port_for", lambda c, s=None: Dead())
    assert app._print_test(cfg, 0) == 1
    assert "printer FAILED (mock): the ticket printer needs" in capsys.readouterr().err


@pytest.mark.parametrize("text,ok", [("0", True), ("21", True), ("22", False), ("-1", False),
                                     ("x", False)])
def test_the_card_argument(text, ok):
    if ok:
        assert app._card(text) == int(text)
    else:
        with pytest.raises(argparse.ArgumentTypeError):
            app._card(text)
