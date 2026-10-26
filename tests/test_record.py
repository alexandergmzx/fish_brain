"""record: the fish's own record, fsynced, never in the way."""
import json
import os
import time

import pytest

from fish_brain import debug, record
from fish_brain.config import Config, RecordConfig


def _cfg(tmp_path, **kw) -> RecordConfig:
    c = RecordConfig()
    c.dir, c.beat_s = str(tmp_path / "rec"), 0
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def _lines(rec: record.Record) -> list[dict]:
    rec.flush()
    return [json.loads(l) for l in rec.path.read_text().splitlines()]


def test_each_line_is_fsynced_and_carries_the_clocks(tmp_path, monkeypatch):
    synced = []
    real = os.fsync
    monkeypatch.setattr(record.os, "fsync", lambda fd: (synced.append(fd), real(fd)))
    rec = record.Record(_cfg(tmp_path))
    rec.write("turn", {"outcome": "spoken"})
    rec.write("voice", {"state": "clean"})
    lines = _lines(rec)
    assert [l["kind"] for l in lines] == ["turn", "voice"]
    assert {"mono", "wall", "synced"} <= set(lines[0]) and synced
    assert rec.path.name.endswith(f"-{os.getpid()}.jsonl")


def test_old_files_are_rotated_by_count(tmp_path):
    folder = tmp_path / "rec"
    folder.mkdir()
    for i in range(5):
        p = folder / f"old{i}.jsonl"
        p.write_text("{}\n")
        os.utime(p, (i, i))
    rec = record.Record(_cfg(tmp_path, keep=3))
    names = sorted(p.name for p in folder.iterdir())
    assert len(names) == 3 and "old4.jsonl" in names and rec.path.name in names


def test_a_write_error_turns_it_off_without_raising(tmp_path, monkeypatch, capsys):
    rec = record.Record(_cfg(tmp_path))

    def boom(*_):
        raise OSError("disk gone")
    monkeypatch.setattr(record.os, "write", boom)
    rec.write("turn", {})
    deadline = time.monotonic() + 2
    while rec._on and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not rec._on and "record] off" in capsys.readouterr().err
    rec.write("turn", {})                          # still no exception


def test_off_without_a_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(record, "_record", None)
    assert record.open_record(RecordConfig(dir="")) is None
    record.write("turn", {})                        # a no-op


def test_the_hub_sends_turns_to_the_record_scrubbed(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-0123456789abcdef")
    monkeypatch.setenv("FISH_DDNS_TOKEN", "tok-0123456789abcdef")
    monkeypatch.setattr(record, "_record", None)
    rec = record.open_record(_cfg(tmp_path))
    try:
        hub = debug.DebugHub(Config())
        hub.emit("turn", outcome="spoken", note="key sk-test-0123456789abcdef tok-0123456789abcdef")
        hub.emit("log", stream="out", text="not on disk")
        lines = _lines(rec)
        assert [l["kind"] for l in lines] == ["turn"]
        text = json.dumps(lines, ensure_ascii=False)
        assert "0123456789abcdef" not in text and "•••" in text
    finally:
        monkeypatch.setattr(record, "_record", None)
