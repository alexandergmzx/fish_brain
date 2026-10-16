"""The burbles: the short sound the body answers a released button with. The fish's are
bubbles; the Sorting Hat's is a hum, "mmm?" (`hum`, chosen by the persona).

The sounds are synthesized here, so nothing is taken from anywhere: each burble is two to
four bubbles, a bubble being a sine whose pitch rises quickly under a short decaying
envelope, with a little noise where it pops. The seeds are fixed, so the same sounds come
out every time. 22050 Hz, mono, 16-bit, 0.3 to 0.6 s, peak about -3 dBFS.

They are written once into the cache (`ensure`), next to the canned phrases: WAV files are
neither tracked nor copied to the board, so the board makes its own at the first start.

    python -m fish_brain.burble --out DIR [--sound hum]   # write the four WAVs, to listen
    python -m fish_brain.burble --self-test   # no file written
"""
from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

import numpy as np

RATE = 22050
PEAK = 0.7                      # about -3 dBFS
VERSION = 1                     # in the file names: a changed recipe makes new files
# (seed, bubbles): four burbles that do not sound alike.
RECIPES = ((11, 3), (23, 2), (37, 4), (53, 3))


def bubble(rng: np.random.Generator, seconds: float, f0: float, rise: float) -> np.ndarray:
    """One bubble: the pitch goes from `f0` up by `rise` octaves, fast at first."""
    n = int(RATE * seconds)
    t = np.arange(n) / RATE
    x = t / seconds
    freq = f0 * 2.0 ** (rise * x ** 0.6)
    phase = 2 * np.pi * np.cumsum(freq) / RATE
    env = np.sin(np.pi * np.minimum(1.0, x * 6.0) / 2) * np.exp(-3.5 * x)   # quick in, slow out
    pop = rng.standard_normal(n) * np.exp(-60.0 * x) * 0.15                  # the pop at the start
    return (np.sin(phase) + 0.25 * np.sin(2 * phase)) * env + pop * env


def burble(seed: int, bubbles: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    parts, total = [], 0.0
    for i in range(bubbles):
        seconds = float(rng.uniform(0.07, 0.13))
        gap = float(rng.uniform(0.015, 0.05))
        f0 = float(rng.uniform(260.0, 520.0)) * (1.0 + 0.12 * i)     # each a little higher
        parts.append(bubble(rng, seconds, f0, float(rng.uniform(0.7, 1.3))) * (0.75 + 0.25 * rng.random()))
        parts.append(np.zeros(int(RATE * gap)))
        total += seconds + gap
    parts.append(np.zeros(int(RATE * 0.06)))                         # room for the tail to end
    x = np.concatenate(parts)
    x = x / max(1e-9, float(np.abs(x).max())) * PEAK
    fade = int(RATE * 0.005)
    x[:fade] *= np.linspace(0.0, 1.0, fade)
    return x


# (seed, f0 Hz): four hums, a little different each, all low and closed-mouthed.
HUM_RECIPES = ((7, 196.0), (19, 220.0), (31, 175.0), (43, 208.0))


def hum(seed: int, f0: float) -> np.ndarray:
    """The hat's "mmm?": two hummed tones a fourth apart, the second rising at its end like a
    question; a slow vibrato, a dark closed-mouth timbre, soft in and out."""
    rng = np.random.default_rng(seed)
    a = float(rng.uniform(0.12, 0.15))                 # the first tone
    glide = 0.025
    b = float(rng.uniform(0.15, 0.19))                 # the second, the question
    room = 0.03
    n = int(RATE * (a + glide + b))
    t = np.arange(n) / RATE
    f1, f2 = f0, f0 * 2.0 ** (5 / 12)
    freq = np.where(t < a, f1, f2)
    g = (t >= a) & (t < a + glide)
    freq[g] = f1 * (f2 / f1) ** ((t[g] - a) / glide)
    tail = t > a + glide + b - 0.06
    freq[tail] *= 2.0 ** ((2 / 12) * (t[tail] - (a + glide + b - 0.06)) / 0.06)
    vib_hz = float(rng.uniform(5.2, 5.8))
    vib = 1.0 + 0.015 * np.minimum(1.0, t / 0.08) * np.sin(2 * np.pi * vib_hz * t)
    phase = 2 * np.pi * np.cumsum(freq * vib) / RATE
    x = (np.sin(phase) + 0.5 * np.sin(2 * phase) + 0.2 * np.sin(3 * phase)
         + 0.08 * np.sin(4 * phase))
    env = np.ones(n)
    att, rel = int(RATE * 0.03), int(RATE * 0.07)
    env[:att] = 0.5 - 0.5 * np.cos(np.pi * np.arange(att) / att)
    env[-rel:] = 0.5 + 0.5 * np.cos(np.pi * np.arange(rel) / rel)
    dip = (t >= a - 0.01) & (t < a + 0.01)
    env[dip] *= 0.75
    x = np.concatenate([x * env, np.zeros(int(RATE * room))])
    x = x / max(1e-9, float(np.abs(x).max())) * PEAK
    fade = int(RATE * 0.005)
    x[:fade] *= np.linspace(0.0, 1.0, fade)
    return x


# name -> (recipes, maker, file prefix)
SOUNDS = {"bubbles": (RECIPES, burble, "burble"), "hum": (HUM_RECIPES, hum, "hum")}


def write(path: Path, x: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((x * 32767.0).astype("<i2").tobytes())


def ensure(folder: Path, sound: str = "bubbles") -> list[Path]:
    """The WAV files of `sound` in `folder`, written now if they are not there."""
    if sound not in SOUNDS:
        raise ValueError(f"unknown burble sound {sound!r}; choose one of {list(SOUNDS)}")
    recipes, make, prefix = SOUNDS[sound]
    folder = Path(folder)
    paths = []
    for i, args in enumerate(recipes, 1):
        path = folder / f"{prefix}_{i}-v{VERSION}.wav"
        if not path.exists():
            folder.mkdir(parents=True, exist_ok=True)
            part = path.with_name(path.name + ".part")
            write(part, make(*args))
            part.replace(path)
        paths.append(path)
    return paths


def _rises(x: np.ndarray) -> bool:
    """The pitch of the last 40 % is above that of the first 40 % (the question)."""
    n = len(x)
    def peak_hz(seg: np.ndarray) -> float:
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
        return float(np.fft.rfftfreq(len(seg), 1 / RATE)[int(np.argmax(spec))])
    return peak_hz(x[int(0.6 * n):int(0.95 * n)]) > peak_hz(x[int(0.05 * n):int(0.4 * n)])


def self_test() -> int:
    failures = []
    for name, (recipes, make, prefix) in SOUNDS.items():
        sounds = [make(*args) for args in recipes]
        for i, x in enumerate(sounds, 1):
            seconds, peak = len(x) / RATE, float(np.abs(x).max())
            ok = 0.3 <= seconds <= 0.6 and 0.65 <= peak <= 0.75
            print(f"[self-test] {prefix}_{i}: {seconds:.2f} s, peak {peak:.2f}")
            if not ok:
                failures.append(f"{prefix}_{i}")
            if name == "hum" and not _rises(x):
                failures.append(f"{prefix}_{i} does not rise")
        if not np.array_equal(make(*recipes[0]), sounds[0]):
            failures.append(f"{name} not reproducible")
        if len({len(x) for x in sounds}) != len(sounds):
            failures.append(f"two {name} sounds of the same length")
    print("[self-test] " + ("FAILED: " + ", ".join(failures) if failures else "all passed"))
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path, help="write the WAVs here")
    p.add_argument("--sound", default="bubbles", choices=list(SOUNDS))
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.out is None:
        p.error("--out DIR or --self-test")
    for path in ensure(args.out, args.sound):
        with wave.open(str(path), "rb") as w:
            print(f"{path}: {w.getnframes() / w.getframerate():.2f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
