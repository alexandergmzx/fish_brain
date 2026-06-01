"""Text-to-speech via the local `loq` engine (Loquendo "Jorge", MX Spanish).

We render to a WAV file *silently* (`loq -o`, no playback) because the conductor owns
playback so it can stay in sync with the streamed motor commands. The loq daemon stays
warm (~50 ms/phrase) once started.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .config import TTSConfig


def warm(cfg: TTSConfig) -> None:
    """Start/warm the loq daemon so the first phrase isn't slow. Best-effort."""
    try:
        subprocess.run([cfg.loq_bin, "--start"], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        pass


def synthesize(text: str, cfg: TTSConfig, out_path: str | Path | None = None) -> Path:
    """Render `text` to a WAV and return its path. Raises on loq failure."""
    text = text.strip()
    if not text:
        raise ValueError("synthesize(): empty text")
    if out_path is None:
        fd, name = tempfile.mkstemp(suffix=".wav", prefix="fish_")
        Path(name).unlink(missing_ok=True)  # loq writes it; we just want the name
        import os
        os.close(fd)
        out_path = name
    out_path = Path(out_path)
    cmd = [cfg.loq_bin, "-o", str(out_path), "-r", str(cfg.sample_rate), text]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out_path.exists():
        raise RuntimeError(
            f"loq failed (rc={proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return out_path
