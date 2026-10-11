"""tools/fw_check.py against a pty that models the firmware, and a fake router.

Level 0: this shows the checker's logic (echo matching, the fault it reports for each
knob of the model, the router hand-back, the link lock). It says nothing about the real
link. The firmware's reply texts are pinned against the Big_mouth sources when that repo
is next to this one.
"""
from __future__ import annotations

import glob
import os
import signal
import sys
import threading
import time

import pytest

pytest.importorskip("serial")

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)

import fw_check  # noqa: E402
import uart_check  # noqa: E402
from fw_check import (R_DURATION, R_PAIRS, R_PARSE, R_SPECIFY, R_STOPPED,  # noqa: E402
                      R_UNKNOWN, FakeFirmware, Matcher)

BIG_MOUTH = os.path.join(os.path.dirname(TOOLS), "..", "Big_mouth")
FAST = ["--count", "300", "--hz", "300"]
# Short runs; the clock pass line is loosened where the clock is not the subject (a busy
# test machine moves a 2 s fit by more than 0.1 %).
TIMING = ["timing", "--drive", "--lengths", "2,10,30", "--repeat", "2",
          "--clock-seconds", "2"]
LOOSE_CLOCK = ["--clock-pct", "1"]


@pytest.fixture
def firmware():
    made = []

    def make(**knobs) -> FakeFirmware:
        made.append(FakeFirmware(**knobs))
        return made[-1]

    yield make
    for fw in made:
        fw.close()


def run(fw: FakeFirmware, cmd: str, *argv: str):
    code = fw_check.main([cmd, "--port", fw.path, *argv])
    return code, fw_check.main.last_report


def verdicts(rep) -> dict:
    return {name: verdict for name, verdict, _ in rep.rows}


# --- the matcher, on bytes ----------------------------------------------------------------

def test_matcher_pairs_by_echo_and_names_the_lost_line():
    m = Matcher()
    m.feed(0.0, b"\x00boot text\r\nReady for commands!\r\n\n> ")
    a, b, c = m.sent("PING 1", 1.0), m.sent("PING 2", 1.1), m.sent("STOP", 1.2)
    m.feed(1.3, b"PING 1\r\nUnknown command. Type HELP\r\n> ")
    m.feed(1.4, b"STOP\r\nAll motors stopped\r\n> ")      # PING 2 never reached the MCU
    assert m.junk == ["boot text", "Ready for commands!"]
    assert (a.replies, a.complete) == ([R_UNKNOWN], True)
    assert not b.echoed and b.done.is_set()
    assert (c.replies, c.complete) == ([R_STOPPED], True)


def test_matcher_trace_records_are_never_replies():
    m = Matcher()
    s = m.sent("MOUTH 238 14", 1.0)
    m.feed(1.0, b"MOUTH 238 14\r\nMOUTH -> 1 step\r\n> ")
    m.feed(1.1, b"\r#T 1200 1200345 M 238 10 238\r\n> \r#T 1214 1214350 M 0 00 0\r\n> ")
    m.feed(1.2, b"\r#L 2000 51234 180\r\n> \r#X 2\r\n> \r#B fw=abc trace=1\r\n> ")
    assert s.replies == ["MOUTH -> 1 step"] and m.stray == []
    kinds = [t.kind for t in m.traces]
    assert kinds == ["T", "T", "L", "X", "B"]
    first = m.traces[0]
    assert (first.ms, first.us, first.ch, first.pwm, first.pins, first.ena) == (
        1200, 1200345, "M", 238, "10", 238)
    assert (m.traces[2].loops, m.traces[2].gap_us, m.traces[3].dropped) == (51234, 180, 2)


def test_matcher_split_reads_and_a_line_with_no_echo():
    m = Matcher()
    s = m.sent("STATUS", 1.0)
    for chunk in (b"STA", b"TUS\r", b"\n\n===== STATUS =====\r\n  MOUTH: stopped  [open=238",
                  b" close=-200 pulse=104ms]\r\n==================\n\r\n>", b" "):
        m.feed(1.1, chunk)
    assert s.complete and s.replies[1] == "MOUTH: stopped  [open=238 close=-200 pulse=104ms]"
    m.feed(6.0, b"[MOUTH] watchdog stop (MAX_RUN_TIME)\r\n")
    assert m.stray == [(6.0, "[MOUTH] watchdog stop (MAX_RUN_TIME)")]


# --- the contract table ---------------------------------------------------------------------

@pytest.mark.parametrize("line, want", [
    ("PING 7", [R_UNKNOWN]),
    ("stop", [R_STOPPED]),
    ("MOUTH 238 14", ["MOUTH -> 1 step"]),
    ("M -200 14", ["MOUTH -> 1 step"]),
    ("NECK 230 650", ["NECK -> 1 step"]),
    ("TAIL 210 230 -210 210", ["TAIL -> 2 step chain"]),
    ("MOUTH 120", ["MOUTH -> pwm 120"]),
    ("MOUTH", [R_SPECIFY]),
    ("MOUTH X", [R_PARSE]),
    ("MOUTH 1 2 3", [R_PAIRS]),
    ("MOUTH 238 0", [R_DURATION]),
    ("NECK 230 5001", [R_DURATION]),
    ("NECK STOP", ["NECK stopped"]),
    ("MOUTH OPEN", []),
    ("MOUTH -", ["MOUTH -> pwm 0"]),
    ("TAIL 100 50-100 50", ["TAIL -> 2 step chain"]),
    ("NECK 1.5 20", [R_PARSE]),
    ("MOUTH " + "1 1 " * 20, ["MOUTH -> 20 step chain"]),
    ("MOUTH " + "1 1 " * 20 + "1", [R_PARSE]),
    ("STATUS", None),
])
def test_expected_reply(line, want):
    assert fw_check.expected_reply(line) == want


def test_model_and_table_agree(firmware):
    """The model is written from the firmware source on its own; the table must match it."""
    fw = firmware()
    lines = ["PING 7", "MOUTH", "MOUTH X", "MOUTH 1 2 3", "MOUTH 238 0", "NECK 230 5001",
             "NECK STOP", "MOUTH 238 14", "TAIL 210 230 -210 210", "STOP"]
    assert [fw._process(line) for line in lines] == [fw_check.expected_reply(x) for x in lines]


def test_firmware_repo_protocol_files_agree_with_the_table_and_the_model(firmware):
    """Big_mouth/protocol was written from the same source by other hands: replay it here."""
    folder = os.path.join(BIG_MOUTH, "protocol")
    if not os.path.isfile(os.path.join(folder, "v1.script")):
        pytest.skip("no protocol files in the Big_mouth repo")
    with open(os.path.join(folder, "v1.script")) as f:
        script = fw_check.parse_script(f.read())
    with open(os.path.join(folder, "v1.expect")) as f:
        expect = fw_check.parse_expect(f.read())
    for line, _ in script:
        want = fw_check.expected_reply(line)
        if want is not None and len(expect.get(line, ())) == 1:
            assert expect[line][0] == want, line
    code, rep = run(firmware(), "replay", "--script", os.path.join(folder, "v1.script"),
                    "--expect", os.path.join(folder, "v1.expect"))
    assert code == 0, rep.data["mismatches"]


def test_fw_contract_literals_are_in_the_firmware_source():
    headers = glob.glob(os.path.join(BIG_MOUTH, "include", "*.h"))
    if not headers:
        pytest.skip("the Big_mouth repo is not next to this one")
    source = "".join(open(h, encoding="utf-8", errors="replace").read() for h in headers)
    missing = [lit for lit in fw_check.FW_LITERALS if lit not in source]
    assert missing == [], f"reply text changed in the firmware: {missing}"


# --- check ----------------------------------------------------------------------------------

def test_check_clean_firmware_passes(firmware, capsys):
    fw = firmware()
    code, rep = run(fw, "check", *FAST, "--md")
    assert code == 0
    assert [(n, v) for n, v, _ in rep.rows[:3]] == [
        ("probe", "PASS"), ("status", "PASS"), ("soak", "PASS")]
    assert "| soak | PASS |" in capsys.readouterr().out
    # motor-safe: nothing but PING and STATUS reached the MCU
    assert {line.split()[0] for line in fw.received} == {"PING", "STATUS"}


def test_check_is_the_default_command(firmware):
    fw = firmware()
    assert fw_check.main(["--port", fw.path, "--count", "20", "--hz", "300"]) == 0


def test_check_counts_lost_lines(firmware):
    code, rep = run(firmware(drop_every=50), "check", *FAST)
    assert code == 1
    assert verdicts(rep)["soak"] == "FAIL" and rep.data["lost"] == 6


def test_check_reports_a_channel_that_is_not_stopped(firmware):
    code, rep = run(firmware(stuck_running="NECK"), "check", *FAST)
    assert code == 1
    assert verdicts(rep)["status"] == "FAIL" and verdicts(rep)["soak"] == "PASS"


def test_check_exit_3_when_the_echo_sketch_answers(firmware):
    code, _ = run(firmware(ack_mode=True), "check", *FAST)
    assert code == 3


def test_check_wrong_unknown_reply(firmware):
    code, rep = run(firmware(wrong_reply=("Type HELP", "Type H")), "check", *FAST)
    assert code == 1 and verdicts(rep)["probe"] == "FAIL"


# --- replay ---------------------------------------------------------------------------------

SCRIPT = """\
# fixture written from Big_mouth include/CommandProcessor.h
PING 1
MOUTH
MOUTH X
MOUTH 1 2 3
MOUTH 238 0
STATUS
NECK 230 650      #drive
STATUS            #drive
MOUTH 238 14      #drive
STOP
STATUS
"""
EXPECT = f"""\
>>> PING 1
{R_UNKNOWN}

>>> MOUTH
{R_SPECIFY}
>>> MOUTH X
{R_PARSE}
>>> MOUTH 1 2 3
{R_PAIRS}
>>> MOUTH 238 0
{R_DURATION}
>>> STATUS
===== STATUS =====
  MOUTH: stopped  [open=238 close=-200 pulse=104ms]
  NECK: stopped  [open=255 close=-100 pulse=500ms]
  TAIL: stopped  [open=240 close=-180 pulse=500ms]
==================
>>> NECK 230 650
NECK -> 1 step
>>> STATUS
===== STATUS =====
  MOUTH: stopped  [open=238 close=-200 pulse=104ms]
  NECK: RUNNING (pwm 230, step 1/1)  [open=255 close=-100 pulse=500ms]
  TAIL: stopped  [open=240 close=-180 pulse=500ms]
==================
>>> MOUTH 238 14
MOUTH -> 1 step
>>> STOP
{R_STOPPED}
>>> STATUS
===== STATUS =====
  MOUTH: stopped  [open=238 close=-200 pulse=104ms]
  NECK: stopped  [open=255 close=-100 pulse=500ms]
  TAIL: stopped  [open=240 close=-180 pulse=500ms]
==================
"""


@pytest.fixture
def protocol(tmp_path):
    script, expect = tmp_path / "v1.script", tmp_path / "v1.expect"
    script.write_text(SCRIPT)
    expect.write_text(EXPECT)
    return ["--script", str(script), "--expect", str(expect)]


def test_parse_script_and_expect():
    script = fw_check.parse_script(SCRIPT)
    assert script[0] == ("PING 1", False) and ("MOUTH 238 14", True) in script
    assert script[7] == ("STATUS", True)
    expect = fw_check.parse_expect(EXPECT)
    assert expect["MOUTH"][0] == [R_SPECIFY]
    assert len(expect["STATUS"]) == 3 and "RUNNING" in expect["STATUS"][1][2]


def test_replay_without_drive_skips_the_marked_lines(firmware, protocol):
    fw = firmware()
    code, rep = run(fw, "replay", *protocol)
    assert code == 0 and "3 '#drive' lines skipped" in rep.rows[0][2]
    assert not any(line.startswith(("MOUTH 238 14", "NECK")) for line in fw.received)


def test_replay_with_drive_compares_every_line(firmware, protocol):
    fw = firmware()
    code, rep = run(fw, "replay", *protocol, "--drive")
    assert code == 0 and rep.rows[0][2].startswith("11 of 11")
    assert fw.received[-1] == "STOP"        # a driving run ends with STOP


def test_replay_names_the_line_with_the_wrong_reply(firmware, protocol):
    code, rep = run(firmware(wrong_reply=("1 step", "1 steps")), "replay", *protocol,
                    "--drive")
    assert code == 1
    assert len(rep.data["mismatches"]) == 2
    assert "'MOUTH 238 14': got ['MOUTH -> 1 steps']" in rep.data["mismatches"][1]


def test_replay_without_protocol_files_cannot_run(firmware, tmp_path):
    fw = firmware()
    code = fw_check.main(["replay", "--port", fw.path, "--script", str(tmp_path / "none"),
                          "--expect", str(tmp_path / "none")])
    assert code == 2 and fw.received == []


# --- timing ---------------------------------------------------------------------------------

def test_timing_needs_drive(firmware):
    with pytest.raises(SystemExit) as e:
        fw_check.main(["timing", "--port", firmware().path])
    assert e.value.code == 2


def test_timing_clean_trace_build_passes(firmware):
    code, rep = run(firmware(trace=True), *TIMING, *LOOSE_CLOCK)
    assert code == 0 and rep.failed == []
    v = verdicts(rep)
    assert v["truth table"] == v["pre-emption"] == v["stop latency"] == "PASS"
    assert v["pulse MOUTH 238 30"] == v["chain TAIL 210 230 -210 210"] == "PASS"
    assert v["held limit"] == "SKIP"
    assert max(abs(e) for e in rep.data["pulse_err_us"]) < 500


def test_timing_reports_stretched_pulses(firmware):
    code, rep = run(firmware(trace=True, stretch_ms=3), *TIMING, *LOOSE_CLOCK)
    assert code == 1
    errs = rep.data["pulse_err_us"]
    assert abs(sum(errs) / len(errs) - 3000) <= 500
    assert verdicts(rep)["pulse MOUTH 238 10"] == "FAIL"
    assert verdicts(rep)["chain NECK 230 650"] == "FAIL"


def test_timing_reports_a_fast_clock(firmware):
    code, rep = run(firmware(trace=True, clock_ppm=20000), *TIMING)
    assert code == 1 and verdicts(rep)["clock rate"] == "FAIL"
    assert abs(rep.data["clock_ppm"] - 20000) <= 2000


def test_timing_without_trace_records_is_skipped(firmware):
    fw = firmware()
    code, rep = run(fw, *TIMING)
    assert code == 0
    assert {v for _, v, _ in rep.rows} == {"SKIP", "INFO"}
    assert fw.received == []                # nothing was driven


def test_timing_held_limit(firmware):
    code, rep = run(firmware(trace=True), "timing", "--drive", "--held", "--lengths", "5",
                    "--repeat", "1", "--clock-seconds", "2", *LOOSE_CLOCK)
    assert code == 0, rep.rows
    assert verdicts(rep)["held limit"] == "PASS" and 4.99 <= rep.data["held_s"] <= 5.1


# --- soak -----------------------------------------------------------------------------------

def test_soak_without_drive_sends_only_ping(firmware):
    fw = firmware()
    code, rep = run(fw, "soak", "--seconds", "1", "--hz", "100")
    assert code == 0 and verdicts(rep)["status"] == "PASS"
    assert {line.split()[0] for line in fw.received} == {"PING", "STOP", "STATUS"}


def test_soak_with_drive_and_bursts(firmware):
    fw = firmware(trace=True)
    code, rep = run(fw, "soak", "--seconds", "3", "--hz", "33", "--drive", "--bursts",
                    "--gesture-every", "0.5")
    assert code == 0, rep.rows
    got = fw.received
    for line in ("MOUTH 238 14", "MOUTH -200 14", "NECK 230 650", "NECK -200 560",
                 "TAIL 210 230 -210 210"):
        assert line in got
    i = got.index("NECK 230 650")
    assert got[i - 1].startswith("MOUTH")   # the gesture follows a mouth line in one write
    # head home and mouth closed, then STOP, the STATUS check, and the STOP of every exit
    assert got[-4:] == ["MOUTH -200 74", "STOP", "STATUS", "STOP"]
    assert rep.data["drops"] == 0


def test_soak_counts_lost_lines(firmware):
    code, rep = run(firmware(drop_every=40), "soak", "--seconds", "2", "--hz", "100")
    assert code == 1 and rep.data["lost"] == 5


# --- send, listen ---------------------------------------------------------------------------

def test_send_prints_the_reply(firmware, capsys):
    fw = firmware()
    assert fw_check.main(["send", "PING 9", "--port", fw.path, "--wait", "0.5"]) == 0
    out = capsys.readouterr().out
    assert "PING 9" in out and R_UNKNOWN in out


def test_send_refuses_a_held_pwm(firmware):
    fw = firmware()
    for line in ("MOUTH 120", "n -200"):
        with pytest.raises(SystemExit) as e:
            fw_check.main(["send", line, "--port", fw.path])
        assert e.value.code == 2
    time.sleep(0.1)
    assert fw.received == []
    assert fw_check.main(["send", "MOUTH 120", "--held", "--port", fw.path,
                          "--wait", "0.3"]) == 0
    assert fw.received == ["MOUTH 120"]


def test_listen_prints_what_arrives(firmware, capsys):
    fw = firmware()
    assert fw_check.main(["listen", "--port", fw.path, "--seconds", "0.5"]) == 0
    assert "Ready for commands!" in capsys.readouterr().out


# --- analyze --------------------------------------------------------------------------------

def write_log(path, lines, skip_echo=(), late=()):
    grid = fw_check.GRID_MS / 1000.0
    with open(path, "w") as f:
        f.write("99.000000 R b'\\x00junk\\r\\n> '\n")
        for i, line in enumerate(lines):
            t = 100.0 + i * grid + (0.004 if i in late else 0.0)
            f.write(f"{t:.6f} T {line}\n")
            if i not in skip_echo:
                reply = (fw_check.expected_reply(line) or [""])[0]
                f.write(f"{t + 0.002:.6f} R {(line + chr(13) + chr(10)).encode()!r}\n")
                f.write(f"{t + 0.003:.6f} R {(reply + chr(13) + chr(10) + '> ').encode()!r}\n")


def test_analyze_names_the_line_that_was_never_echoed(tmp_path, capsys):
    log = str(tmp_path / "link.log")
    lines = ["MOUTH 238 14", "MOUTH -200 14", "NECK 230 650", "MOUTH 238 30",
             "MOUTH -200 30", "STOP"]
    write_log(log, lines, skip_echo={2}, late={4})
    assert fw_check.main(["analyze", log]) == 1
    rep = fw_check.main.last_report
    assert rep.data["lost"] == ["NECK 230 650"] and rep.data["rejected"] == []
    assert "5 of 6 echoed" in capsys.readouterr().out
    late = sorted(rep.data["lateness_ms"])
    assert len(late) == 4 and late[0] == pytest.approx(0.0, abs=0.01)
    assert late[-1] == pytest.approx(4.0, abs=0.05)


def test_analyze_clean_log_and_rejected_lines(tmp_path):
    log = str(tmp_path / "link.log")
    write_log(log, ["MOUTH 238 14", "MOUTH -200 14", "STOP"])
    assert fw_check.main(["analyze", log, "--md"]) == 0
    write_log(log, ["MOUTH 238 14", "MOUTH 238 0", "BOGUS"])
    assert fw_check.main(["analyze", log]) == 1
    assert len(fw_check.main.last_report.data["rejected"]) == 2
    assert fw_check.main(["analyze", str(tmp_path / "missing.log")]) == 2


# --- the router and the link lock -----------------------------------------------------------

@pytest.fixture
def router(tmp_path):
    pytest.importorskip("msgpack")
    sock = str(tmp_path / "router.sock")
    fake = uart_check._FakeRouter(sock)
    yield fake, ["--release-router", "--router-socket", sock]
    fake.close()


def close_open(port):
    return [("$/serial/close", [port]), ("$/serial/open", [port])]


def test_release_router_close_before_open_after(firmware, router):
    fake, released = router
    fw = firmware()
    code, _ = run(fw, "check", *released, *FAST)
    assert code == 0 and fake.calls == close_open(fw.path)


def test_keep_released_does_not_hand_back(firmware, router):
    fake, released = router
    fw = firmware()
    code, _ = run(fw, "check", *released, "--keep-released", "--count", "20", "--hz", "300")
    assert code == 0 and fake.calls == [("$/serial/close", [fw.path])]


def test_sigterm_mid_soak_stops_and_hands_the_port_back(firmware, router):
    fake, released = router
    fw = firmware()
    timer = threading.Timer(1.5, os.kill, (os.getpid(), signal.SIGTERM))
    timer.start()
    try:
        code, _ = run(fw, "soak", *released, "--seconds", "30", "--drive")
    finally:
        timer.cancel()
    assert code == 130
    assert fake.calls == close_open(fw.path)
    time.sleep(0.1)
    assert fw.received[-1] == "STOP"


def test_lock_held_means_exit_2_and_no_router_call(firmware, router):
    fake, released = router
    fw = firmware()
    holder = uart_check.link_lock(fw.path)
    try:
        assert open(uart_check.lock_path(fw.path)).read().startswith(f"pid {os.getpid()} ")
        code, _ = run(fw, "check", *released, *FAST)
        assert code == 2 and fake.calls == [] and fw.received == []
        code, _ = run(fw, "check", *released, "--force", "--count", "20", "--hz", "300")
        assert code == 0 and fake.calls == close_open(fw.path)
    finally:
        holder.close()
    code, _ = run(fw, "check", "--count", "20", "--hz", "300")     # free again
    assert code == 0


def test_lock_path_matches_the_app():
    serial_link = pytest.importorskip("fish_brain.serial_link")
    if not hasattr(serial_link, "link_lock_path"):
        pytest.skip("the app has no link lock yet")
    assert serial_link.link_lock_path("/dev/ttyHS1") == uart_check.lock_path("/dev/ttyHS1")


# --- uart_check: the pieces changed with this tool ------------------------------------------

def test_uart_check_lock_held_refuses_before_the_router(router):
    fake, released = router
    path, close = uart_check._pty_peer("ack")
    holder = uart_check.link_lock(path)
    try:
        assert uart_check.main(["--port", path, *released, "--count", "5"]) == 2
        assert fake.calls == []
    finally:
        holder.close()
        close()


@pytest.mark.parametrize("mode, echoes", [("firmware", 60), ("ack", 0)])
def test_uart_check_expect_auto(mode, echoes):
    path, close = uart_check._pty_peer(mode)
    try:
        code = uart_check.main(["--port", path, "--count", "60", "--hz", "300",
                                "--expect", "auto", "--timeout", "1"])
    finally:
        close()
    res = uart_check.main.last_result
    assert code == 0 and res.lost == 0 and res.echoes == echoes


def test_uart_check_any_mode_skips_trace_records():
    m = uart_check.Matcher("any")
    m.running = True
    m.sent(1, "PING 1")
    for raw in (b"PING 1", b"#T 1 2 M 238 10 238", b"> #L 1000 5 9", b"Unknown command"):
        m.line(time.monotonic(), raw)
    assert (m.res.acked, m.res.echoes, m.res.garbage) == (1, 1, [])
