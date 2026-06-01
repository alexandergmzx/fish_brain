"""Serial link to the ESP32-S3 firmware.

The firmware is a thin executor: newline-terminated, upper-cased commands at 115200 baud,
PWM -255..255. It echoes every command back; we ignore inbound serial entirely.

Safety: the firmware has no current sensing (only a 5 s MAX_RUN_TIME watchdog), so this
link guarantees a STOP on close/exit/exception via the context-manager protocol.

Use `open_link(cfg, dry_run=...)` to get either a real `SerialLink` or a `MockSerialLink`
that prints commands instead of driving motors.
"""
from __future__ import annotations

import sys
import time
from typing import Optional

from .config import SerialConfig


class BaseLink:
    """Shared command helpers + rate limiting. Subclasses implement `_write_raw`."""

    def __init__(self, cfg: SerialConfig):
        self.cfg = cfg
        self._min_interval = 1.0 / cfg.max_cmd_hz if cfg.max_cmd_hz > 0 else 0.0
        self._last_send = 0.0
        self._last_mouth: Optional[int] = None

    # --- low level ---
    def _write_raw(self, data: bytes) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def send(self, command: str, *, throttle: bool = True) -> None:
        """Send one command line (newline appended). `throttle` paces high-rate streams."""
        if throttle and self._min_interval:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_send)
            if wait > 0:
                time.sleep(wait)
        line = command.strip().encode("ascii", "ignore") + self.cfg.newline
        self._write_raw(line)
        self._last_send = time.monotonic()

    # --- high level helpers ---
    def mouth(self, pwm: int) -> None:
        """Stream a mouth position. Skips redundant repeats of the same value."""
        pwm = max(-255, min(255, int(pwm)))
        if pwm == self._last_mouth:
            return
        self._last_mouth = pwm
        self.send(f"MOUTH {pwm}")

    def gesture(self, channel: str, chain_body: str) -> None:
        """Send a neck/tail timed-chain gesture, e.g. channel='NECK', body='180 450 -180 350'."""
        # Gestures are not throttled against the mouth stream cadence — they're rare.
        self.send(f"{channel.upper()} {chain_body}", throttle=False)

    def all_stop(self) -> None:
        self._last_mouth = None
        self.send("STOP", throttle=False)

    # --- context manager: guarantee a stop + clean close ---
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.all_stop()
        except Exception:
            pass
        self.close()
        return False

    def close(self) -> None:
        pass


class SerialLink(BaseLink):
    def __init__(self, cfg: SerialConfig):
        super().__init__(cfg)
        import serial  # pyserial; imported lazily so --dry-run needs no hardware libs

        self._ser = serial.Serial(cfg.port, cfg.baud, timeout=0, write_timeout=1)
        # Give the board a moment after the port opens (USB-CDC reset on some boards).
        time.sleep(0.3)
        self._ser.reset_input_buffer()

    def _write_raw(self, data: bytes) -> None:
        self._ser.write(data)
        # We never read replies back; drop whatever the firmware echoed so the OS
        # buffer doesn't grow without bound during long sessions.
        try:
            self._ser.reset_input_buffer()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass


class MockSerialLink(BaseLink):
    """Prints commands instead of driving motors. For --dry-run testing."""

    def __init__(self, cfg: SerialConfig, stream=sys.stdout):
        super().__init__(cfg)
        self._stream = stream

    def _write_raw(self, data: bytes) -> None:
        self._stream.write("  TX  " + data.decode("ascii", "ignore").rstrip() + "\n")
        self._stream.flush()


def open_link(cfg: SerialConfig, *, dry_run: bool = False) -> BaseLink:
    if dry_run:
        return MockSerialLink(cfg)
    return SerialLink(cfg)
