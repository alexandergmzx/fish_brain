"""The fish's own record: one JSON line per event, on disk before the plug is pulled.

The board's power is always pulled and it has no RTC, so the fair left no logs at all. With
FISH_RECORD_DIR set, every turn, page action and button press (the debug hub's records,
already scrubbed of keys and tokens), the voice's state, the start and the stop go to one file
per process start, `<boot id>-<pid>.jsonl`, plus a beat every FISH_RECORD_BEAT_S with the
board's facts. A writer thread writes and fsyncs, so nothing on the turn loop waits for the
disk. Each line carries the monotonic time, the wall time and whether the clock was synced.
It never raises: a write error turns the record off with one warning. Off when the folder is
empty (the laptop). `tools/records.py` turns a record into a table.
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

from .config import RecordConfig

_SYNCED = Path("/run/systemd/timesync/synchronized")


class Record:
    def __init__(self, cfg: RecordConfig):
        self.cfg = cfg
        folder = Path(cfg.dir).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / f"{_boot_id()[:8]}-{os.getpid()}.jsonl"
        self._rotate(folder)
        self._fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        self._q: queue.Queue = queue.Queue(maxsize=2000)
        self._on = True
        threading.Thread(target=self._writer, name="record", daemon=True).start()
        if cfg.beat_s > 0:
            threading.Thread(target=self._beats, name="record-beat", daemon=True).start()

    def _rotate(self, folder: Path) -> None:
        old = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        budget = self.cfg.max_mb * 1024 * 1024
        while old and (len(old) >= self.cfg.keep or sum(p.stat().st_size for p in old) > budget):
            old.pop(0).unlink(missing_ok=True)

    def write(self, kind: str, fields: dict | None = None) -> None:
        if not self._on:
            return
        line = {"kind": kind, "mono": round(time.monotonic(), 3), "wall": round(time.time(), 3),
                "synced": _SYNCED.exists()}
        line.update(fields or {})
        try:
            self._q.put_nowait(json.dumps(line, ensure_ascii=False, default=str) + "\n")
        except queue.Full:
            pass                                  # the disk is stuck: drop, never block

    def _writer(self) -> None:
        while True:
            lines = [self._q.get()]
            while True:                            # one fsync for whatever is queued
                try:
                    lines.append(self._q.get_nowait())
                except queue.Empty:
                    break
            try:
                os.write(self._fd, "".join(lines).encode("utf-8"))
                os.fsync(self._fd)
            except OSError as e:
                self._on = False
                print(f"[record] off: {e}", file=sys.stderr, flush=True)
                return

    def flush(self, timeout: float = 2.0) -> None:
        """Wait (bounded) until what was queued is on disk."""
        deadline = time.monotonic() + timeout
        while not self._q.empty() and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.02)

    def _beats(self) -> None:
        from . import debug_state
        while self._on:
            time.sleep(self.cfg.beat_s)
            try:
                facts = debug_state.system()
            except Exception as e:
                facts = {"error": type(e).__name__}
            self.write("beat", {"system": facts})


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip().replace("-", "")
    except OSError:
        return "noboot"


_record: Record | None = None


def open_record(cfg: RecordConfig) -> Record | None:
    global _record
    if _record is not None or not cfg.dir:
        return _record
    try:
        _record = Record(cfg)
    except OSError as e:
        print(f"[record] off: {e}", file=sys.stderr, flush=True)
        _record = None
    return _record


def write(kind: str, fields: dict | None = None) -> None:
    if _record is not None:
        _record.write(kind, fields)


def flush() -> None:
    if _record is not None:
        _record.flush()
