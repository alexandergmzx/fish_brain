"""tools/printer_check.py against a socketpair that plays the printer.

Level 0: this shows the tool's byte builders, pacing and exit codes. It says nothing about
the MP210 itself. No hardware, no network.
"""
from __future__ import annotations

import os
import re
import sys

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)

import printer_check as pc  # noqa: E402


def test_self_test_passes(capsys):
    assert pc.self_test() == 0
    assert "[self-test] all passed" in capsys.readouterr().out


def test_standalone_no_package_import():
    with open(os.path.join(TOOLS, "printer_check.py"), encoding="utf-8") as f:
        src = f.read()
    assert not re.search(r"^\s*(import|from)\s+fish_brain", src, re.MULTILINE)


def test_raster_header_little_endian():
    assert pc.raster_header(48, 800) == bytes.fromhex("1d 76 30 00 30 00 20 03")


def test_mac_required(monkeypatch, capsys):
    monkeypatch.delenv("FISH_PRINTER", raising=False)
    try:
        pc.main(["connect"], check_service=False)
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError("no --mac accepted")
    assert "--mac" in capsys.readouterr().err


def test_default_mac_from_environment(monkeypatch):
    monkeypatch.setenv("FISH_PRINTER", "mock")
    assert pc._default_mac() is None
    monkeypatch.setenv("FISH_PRINTER", "DC:0D:51:92:74:DA")
    assert pc._default_mac() == "DC:0D:51:92:74:DA"
