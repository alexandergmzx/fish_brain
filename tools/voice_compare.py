#!/usr/bin/env python3
"""How close each voice sample is to a reference: length, median pitch, the pauses, the shape
and the tone colour. Numpy only (scipy only when a file is not 16 kHz).

    tools/voice_compare.py REF.wav CAND.wav [CAND.wav ...]

- length and F0: seconds and the median pitch by autocorrelation (rough on reverberant files).
- pauses: the inner silences of 0.15 s or more.
- shape: 13 MFCCs with mean removal, aligned to the reference by DTW, mean distance per step;
  lower is closer. Two processings of the same render scored about 10 (2026-10-31).
- colour: RMS difference of the mean log-mel spectra, the overall tone.
The rows are sorted by shape.
"""
import sys, wave, numpy as np
from math import gcd

def load(f):
    w = wave.open(f); sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(float) / 32768
    if w.getnchannels() > 1: x = x.reshape(-1, w.getnchannels()).mean(1)
    if sr != 16000:
        from scipy.signal import resample_poly
        g = gcd(16000, sr); x = resample_poly(x, 16000 // g, sr // g)
    return x

def frames(x, n=400, h=160):
    m = 1 + (len(x) - n) // h
    idx = np.arange(n)[None] + h * np.arange(m)[:, None]
    return x[idx] * np.hanning(n)

def mfcc(x):
    F = np.abs(np.fft.rfft(frames(x), 512)) ** 2
    mel = lambda f: 2595 * np.log10(1 + f / 700)
    pts = 700 * (10 ** (np.linspace(mel(60), mel(7600), 42) / 2595) - 1)
    bins = np.floor(512 * pts / 16000).astype(int)
    fb = np.zeros((40, 257))
    for i in range(40):
        a, b, c = bins[i], bins[i+1], bins[i+2]
        fb[i, a:b] = (np.arange(a, b) - a) / max(b - a, 1)
        fb[i, b:c] = (c - np.arange(b, c)) / max(c - b, 1)
    E = np.log(F @ fb.T + 1e-10)
    n = np.arange(40); k = np.arange(1, 14)[:, None]
    dct = np.cos(np.pi * k * (2 * n + 1) / 80)
    C = E @ dct.T
    return C - C.mean(0), E.mean(0)          # cepstra (CMN), mean log-mel = overall colour

def dtw(A, B):
    D = np.sqrt(((A[:, None] - B[None]) ** 2).sum(-1))
    n, m = D.shape; acc = np.full((n + 1, m + 1), np.inf); acc[0, 0] = 0
    for i in range(1, n + 1):
        row = acc[i]; prev = acc[i-1]
        for j in range(1, m + 1):
            row[j] = D[i-1, j-1] + min(prev[j], prev[j-1], row[j-1])
    return acc[n, m] / (n + m)

def pauses(x):
    e = np.sqrt((frames(x) ** 2).mean(1)); thr = 0.06 * np.percentile(e, 95)
    quiet = e < thr; out = []; i = 0
    while i < len(quiet):
        if quiet[i]:
            j = i
            while j < len(quiet) and quiet[j]: j += 1
            if j - i >= 15 and i > 0 and j < len(quiet): out.append(round((j - i) * 0.01, 2))
            i = j
        else: i += 1
    return out

def f0(x):
    fr = frames(x, 640, 160); vals = []
    for f in fr:
        if np.sqrt((f**2).mean()) < 0.02: continue
        r = np.correlate(f, f, 'full')[639:]; lo, hi = 16000 // 300, 16000 // 60
        k = lo + np.argmax(r[lo:hi])
        if r[k] > 0.4 * r[0]: vals.append(16000 / k)
    return np.median(vals)

ref = load(sys.argv[1]); rC, rE = mfcc(ref)
rC = rC[::2]
print(f"{'sample':34s} {'length':>6s} {'F0':>4s} {'pauses (s)':28s} {'shape':>6s} {'colour':>6s}")
print(f"{'reference':34s} {len(ref)/16000:6.2f} {f0(ref):4.0f} {str(pauses(ref)):28s}")
rows = []
for f in sys.argv[2:]:
    x = load(f); C, E = mfcc(x); C = C[::2]
    rows.append((f.split('/')[-1], len(x)/16000, f0(x), pauses(x), dtw(rC, C), np.sqrt(((E - rE) ** 2).mean())))
for r in sorted(rows, key=lambda r: r[4]):
    print(f"{r[0]:34s} {r[1]:6.2f} {r[2]:4.0f} {str(r[3]):28s} {r[4]:6.2f} {r[5]:6.2f}")
