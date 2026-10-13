#!/usr/bin/env python3
"""Local speech-to-text candidates, timed and scored on the same clips.

Each candidate transcribes every clip of a folder; the tool reports the load time, the
seconds per clip (median of the runs), the word error rate against the clip's reference
text, the peak memory and the CPU temperature, so a model or an engine is chosen with
numbers from the machine it will run on:

    tools/stt_bench.py run --clips DIR --cand fw:model=small --cand fw-window:model=small,window=10
    tools/stt_bench.py split --clips DIR --model small       # mel, encoder, decoder apart
    tools/stt_bench.py record --out DIR --mic a=SOURCE --mic b=SOURCE   # read phrases into microphones
    tools/stt_bench.py record --out DIR --mic a=SOURCE --remote "name:XING WEI"   # from a remote:
        # hold OK to record a take (three per line), left arrow drops the last take, right
        # arrow goes to the next line, mute ends; the line numbers are spoken
    tools/stt_bench.py --self-test                           # no model, no microphone

A clip is `name.wav` (mono, 16-bit, 16 kHz) with its reference text in `name.txt`.

Candidates, written `kind:key=value,key=value`:

    fw          faster-whisper as the fish calls it (Spanish, VAD on).
                model=small  compute=int8  beam=5  light=0 (1: no timestamps, temperature 0,
                no previous-text conditioning)
    fw-window   the same model through `fish_brain.stt.transcribe_window`: the encoder
                window follows the clip.  model=  compute=  beam=1  window=10  tail=3
                tokens=0 (limit of new tokens, 0 = the model's)
    canary      NVIDIA Canary through sherpa-onnx.     dir=MODEL_DIR  threads=4
    parakeet    NVIDIA Parakeet TDT through sherpa-onnx.  dir=MODEL_DIR  threads=4
    moonshine   Moonshine Voice, Spanish.              arch=  (empty = the package's default)
    fish        the fish's own transcriber from its `.env` (padding, long-recording rule).
                backend=  (empty = FISH_STT_BACKEND)
    cloud       the recording uploaded, as the fish's cloud backends do it
                (`fish_brain.stt.CloudTranscriber`; the key comes from `.env`).
                profile=openai (or groq)  model=  (empty = the profile's)

Every candidate runs in its own process, so its peak memory is its own and the next one
starts clean. The engines' libraries are imported only by their candidate: `fw*` needs the
fish's environment, `canary`, `parakeet` and `moonshine` the one they were installed in.

Word error rate: lowercase, punctuation removed, accents kept; (substitutions + deletions
+ insertions) over the reference words, summed over the clips.

Exit code: 0 = ran, 1 = a candidate failed, 2 = could not start.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import resource
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import unicodedata
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RATE = 16000

# What a visitor says to the fish: short answers, a name, a question, one long turn.
PHRASES = (
    "Sí.",
    "No, gracias.",
    "Me llamo Alejandra Martínez.",
    "Hola pez, ¿cómo estás?",
    "¿Qué me depara el futuro este año?",
    "Estudio ingeniería en sistemas y quiero saber si voy a terminar la carrera.",
    "Vengo de Guadalajara con mis amigos a ver los proyectos de la feria.",
    "Quiero preguntarte si me va a ir bien en el trabajo nuevo, porque empiezo el lunes "
    "y la verdad estoy un poco nervioso.",
)


class SetupError(Exception):
    """The benchmark could not start (no clips, bad candidate, missing program)."""


# --- clips and scoring ---------------------------------------------------------------------

def load_clips(folder: str) -> list[dict]:
    clips = []
    for path in sorted(glob.glob(os.path.join(folder, "*.wav"))):
        with wave.open(path, "rb") as w:
            if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, RATE):
                raise SetupError(f"{path}: need mono 16-bit {RATE} Hz")
            seconds = w.getnframes() / RATE
        ref = Path(path).with_suffix(".txt")
        clips.append({"name": Path(path).stem, "path": path, "seconds": seconds,
                      "ref": ref.read_text(encoding="utf-8").strip() if ref.exists() else ""})
    if not clips:
        raise SetupError(f"no .wav clips in {folder}")
    return clips


def read_audio(path: str):
    import numpy as np
    with wave.open(path, "rb") as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def words(text: str) -> list[str]:
    return re.sub(r"[^\w]+|_", " ", unicodedata.normalize("NFC", text).lower()).split()


def word_errors(ref: str, hyp: str) -> tuple[int, int]:
    """(errors, reference words): the edit distance between the two word lists."""
    r, h = words(ref), words(hyp)
    row = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, row[0] = row[0], i
        for j, hw in enumerate(h, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (rw != hw))
    return row[len(h)], len(r)


def cpu_temp_c() -> float | None:
    """The hottest CPU zone, or the hottest zone when none is named after the CPU."""
    cpu, other = [], []
    for zone in glob.glob("/sys/class/thermal/thermal_zone*"):
        try:
            kind = Path(zone, "type").read_text().strip().lower()
            temp = int(Path(zone, "temp").read_text()) / 1000.0
        except (OSError, ValueError):
            continue
        (cpu if "cpu" in kind else other).append(temp)
    return max(cpu or other, default=None)


# --- candidates ----------------------------------------------------------------------------

def parse_spec(spec: str) -> tuple[str, dict]:
    kind, _, rest = spec.partition(":")
    opts = {}
    for part in filter(None, rest.split(",")):
        key, eq, value = part.partition("=")
        if not eq:
            raise SetupError(f"{spec!r}: write options as key=value")
        opts[key.strip()] = value.strip()
    if kind not in ADAPTERS:
        raise SetupError(f"{spec!r}: unknown candidate (choices: {', '.join(sorted(ADAPTERS))})")
    return kind, opts


def _take(opts: dict, **defaults):
    """The options with their defaults, typed like the defaults; an unknown key is an error."""
    unknown = set(opts) - set(defaults)
    if unknown:
        raise SetupError(f"unknown option {sorted(unknown)[0]!r} (known: {', '.join(defaults)})")
    return {k: type(d)(opts.get(k, d)) for k, d in defaults.items()}


def _fw_model(model: str, compute: str):
    from faster_whisper import WhisperModel
    return WhisperModel(model, device="cpu", compute_type=compute)


def make_fw(opts: dict):
    o = _take(opts, model="small", compute="int8", beam=5, light=0)
    model = _fw_model(o["model"], o["compute"])
    extra = dict(without_timestamps=True, temperature=0.0,
                 condition_on_previous_text=False) if o["light"] else {}

    def run(clip: dict) -> str:
        segments, _info = model.transcribe(clip["path"], language="es", vad_filter=True,
                                           beam_size=o["beam"], **extra)
        return " ".join(seg.text.strip() for seg in segments).strip()
    return run


def make_fw_window(opts: dict):
    o = _take(opts, model="small", compute="int8", beam=1, window=10.0, tail=3.0, tokens=0)
    sys.path.insert(0, str(REPO))
    from fish_brain.stt import transcribe_window
    model = _fw_model(o["model"], o["compute"])

    def run(clip: dict) -> str:
        return transcribe_window(model, read_audio(clip["path"]), language="es",
                                 window_s=o["window"], tail_s=o["tail"], beam_size=o["beam"],
                                 max_new_tokens=o["tokens"] or None)
    return run


def _model_file(folder: str, stem: str) -> str:
    """`stem.int8.onnx` when the folder has it, else `stem.onnx`."""
    for name in (f"{stem}.int8.onnx", f"{stem}.onnx"):
        if os.path.exists(os.path.join(folder, name)):
            return os.path.join(folder, name)
    raise SetupError(f"no {stem}.int8.onnx or {stem}.onnx in {folder}")


def _sherpa_run(recognizer):
    def run(clip: dict) -> str:
        stream = recognizer.create_stream()
        stream.accept_waveform(RATE, read_audio(clip["path"]))
        recognizer.decode_stream(stream)
        return stream.result.text.strip()
    return run


def make_canary(opts: dict):
    o = _take(opts, dir="", threads=4)
    import sherpa_onnx
    return _sherpa_run(sherpa_onnx.OfflineRecognizer.from_nemo_canary(
        encoder=_model_file(o["dir"], "encoder"), decoder=_model_file(o["dir"], "decoder"),
        tokens=os.path.join(o["dir"], "tokens.txt"),
        src_lang="es", tgt_lang="es", num_threads=o["threads"]))


def make_parakeet(opts: dict):
    o = _take(opts, dir="", threads=4)
    import sherpa_onnx
    return _sherpa_run(sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=_model_file(o["dir"], "encoder"), decoder=_model_file(o["dir"], "decoder"),
        joiner=_model_file(o["dir"], "joiner"), tokens=os.path.join(o["dir"], "tokens.txt"),
        num_threads=o["threads"], model_type="nemo_transducer"))


def make_moonshine(opts: dict):
    o = _take(opts, arch="")
    import moonshine_voice as mv
    arch = mv.string_to_model_arch(o["arch"]) if o["arch"] else None
    path, arch = mv.get_model_for_language("es", arch)      # downloads on first use
    transcriber = mv.Transcriber(model_path=path, model_arch=arch)

    def run(clip: dict) -> str:
        transcript = transcriber.transcribe_without_streaming(
            read_audio(clip["path"]).tolist(), RATE)
        return " ".join(line.text.strip() for line in transcript.lines).strip()
    return run


def make_cloud(opts: dict):
    o = _take(opts, profile="openai", model="")
    sys.path.insert(0, str(REPO))
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO / ".env")               # the keys, as the app reads them
    except ImportError:
        pass
    from fish_brain.config import STTConfig
    from fish_brain.stt import CloudTranscriber
    cfg = STTConfig()
    cfg.backend, cfg.cloud_model = o["profile"], o["model"]
    transcriber = CloudTranscriber(cfg)
    return lambda clip: transcriber.transcribe(clip["path"])


def make_fish(opts: dict):
    """The fish's own transcriber, built from its environment (`.env`) like the service
    does, so a route with its padding and its long-recording rule is measured as deployed."""
    o = _take(opts, backend="")
    sys.path.insert(0, str(REPO))
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO / ".env")
    except ImportError:
        pass
    from fish_brain.config import STTConfig
    from fish_brain.stt import make_transcriber
    cfg = STTConfig()
    if o["backend"]:
        cfg.backend = o["backend"]
    transcriber = make_transcriber(cfg)
    transcriber.ensure_loaded()
    return lambda clip: transcriber.transcribe(clip["path"])


def make_fake(opts: dict):
    """For the self-test: answers the reference, with one word wrong when `wrong=1`."""
    o = _take(opts, wrong=0, fail=0)
    if o["fail"]:
        raise RuntimeError("fake candidate told to fail")

    def run(clip: dict) -> str:
        said = clip["ref"].split()
        if o["wrong"] and said:
            said[-1] = "equivocado"
        return " ".join(said)
    return run


ADAPTERS = {"fw": make_fw, "fw-window": make_fw_window, "canary": make_canary,
            "parakeet": make_parakeet, "moonshine": make_moonshine, "cloud": make_cloud,
            "fish": make_fish, "fake": make_fake}


# --- one candidate, in its own process -----------------------------------------------------

def run_one(spec: str, clips: list[dict], runs: int, gap: float = 0.0) -> dict:
    kind, opts = parse_spec(spec)
    out: dict = {"spec": spec, "temp_before": cpu_temp_c()}
    t0 = time.monotonic()
    transcribe = ADAPTERS[kind](opts)
    out["load_s"] = time.monotonic() - t0
    out["failed"] = []

    def attempt(clip: dict) -> str:
        try:
            return transcribe(clip)
        except Exception as e:                   # a lost network call is a result, not a crash
            out["failed"].append(f"{clip['name']}: {type(e).__name__}: {e}"[:900])
            return ""

    t0 = time.monotonic()
    attempt(clips[0])                            # the first call warms up; timed apart
    out["first_s"] = time.monotonic() - t0
    out["clips"] = []
    for clip in clips:
        times, text = [], ""
        for _ in range(runs):
            if gap:
                time.sleep(gap)                  # stay under a service's calls-per-minute limit
            t0 = time.monotonic()
            text = attempt(clip)
            times.append(time.monotonic() - t0)
        errors, ref_words = word_errors(clip["ref"], text)
        out["clips"].append({"name": clip["name"], "seconds": clip["seconds"], "times": times,
                             "text": text, "errors": errors, "ref_words": ref_words})
    out["temp_after"] = cpu_temp_c()
    out["peak_rss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    return out


def spawn_one(spec: str, folder: str, runs: int, gap: float = 0.0) -> dict:
    proc = subprocess.run([sys.executable, __file__, "_one", "--clips", folder,
                           "--cand", spec, "--runs", str(runs), "--gap", str(gap)],
                          stdout=subprocess.PIPE, text=True)
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    return {"spec": spec, "error": f"exit {proc.returncode}, no result"}


# --- report --------------------------------------------------------------------------------

def summary_row(res: dict) -> list[str]:
    if "error" in res:
        return [res["spec"], "FAILED: " + res["error"], "", "", "", "", ""]
    medians = [statistics.median(c["times"]) for c in res["clips"]]
    scored = [c for c in res["clips"] if c["ref_words"]]     # a clip without its .txt
    errors = sum(c["errors"] for c in scored)
    ref_words = sum(c["ref_words"] for c in scored)
    temps = (f"{res['temp_before']:.0f} to {res['temp_after']:.0f}"
             if res.get("temp_before") is not None and res.get("temp_after") is not None else "-")
    return [res["spec"], f"{res['load_s']:.1f}", f"{statistics.median(medians):.2f}",
            f"{max(medians):.2f}", f"{100.0 * errors / ref_words:.1f}" if ref_words else "-",
            f"{res['peak_rss_mb']:.0f}", temps]


def table(header: list[str], rows: list[list[str]], md: bool) -> str:
    if md:
        lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        return "\n".join(lines + ["| " + " | ".join(r) + " |" for r in rows])
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip()
                     for r in [header, *rows])


BUCKETS = ((0, 3), (3, 6), (6, 10), (10, 20), (20, 1e9))


def length_rows(results: list[dict]) -> tuple[list[str], list[list[str]]]:
    """Median seconds and WER by clip length, one row per candidate; empty buckets left out."""
    good = [r for r in results if "error" not in r]
    used = [b for b in BUCKETS
            if any(b[0] <= c["seconds"] < b[1] for r in good for c in r["clips"])]
    header = ["candidate"] + [f"{lo}-{hi} s" if hi < 1e9 else f"{lo}+ s" for lo, hi in used]
    rows = []
    for res in good:
        row = [res["spec"]]
        for lo, hi in used:
            clips = [c for c in res["clips"] if lo <= c["seconds"] < hi]
            if not clips:
                row.append("-")
                continue
            cell = f"{statistics.median(statistics.median(c['times']) for c in clips):.2f} s"
            ref_words = sum(c["ref_words"] for c in clips)
            if ref_words:
                errors = sum(c["errors"] for c in clips if c["ref_words"])
                cell += f", {100.0 * errors / ref_words:.0f} %"
            row.append(f"{cell} (n={len(clips)})")
        rows.append(row)
    return header, rows


def report(results: list[dict], md: bool) -> str:
    parts = [table(["candidate", "load s", "median s", "worst s", "WER %", "peak MB", "CPU C"],
                   [summary_row(r) for r in results], md)]
    header, rows = length_rows(results)
    if rows:
        parts.append("\nby clip length: median seconds, WER\n" + table(header, rows, md))
    for res in results:
        if "error" in res:
            continue
        if res.get("failed"):
            parts.append(f"\n{res['spec']}: {len(res['failed'])} failed calls, the first: "
                         f"{res['failed'][0]}")
        rows = [[c["name"], f"{c['seconds']:.1f}", f"{statistics.median(c['times']):.2f}",
                 f"{c['errors']}/{c['ref_words']}" if c["ref_words"] else "-", c["text"]]
                for c in res["clips"]]
        parts.append(f"\n{res['spec']} (first call {res['first_s']:.2f} s)\n"
                     + table(["clip", "clip s", "median s", "errors", "text"], rows, md))
    return "\n".join(parts)


# --- commands ------------------------------------------------------------------------------

def cmd_run(args) -> int:
    load_clips(args.clips)
    for spec in args.cand:
        parse_spec(spec)
    results = []
    for i, spec in enumerate(args.cand):
        if i and args.rest:
            time.sleep(args.rest)
        print(f"[bench] {spec}", file=sys.stderr)
        results.append(spawn_one(spec, args.clips, args.runs, args.gap))
    print(report(results, args.md))
    return 1 if any("error" in r for r in results) else 0


def cmd_one(args) -> int:
    try:
        res = run_one(args.cand[0], load_clips(args.clips), args.runs, args.gap)
    except Exception as e:                       # the parent prints it as the candidate's row
        res = {"spec": args.cand[0], "error": f"{type(e).__name__}: {e}"}
    print(json.dumps(res))
    return 0


def cmd_split(args) -> int:
    """Where one faster-whisper turn goes: features, the encoder at several windows, the
    decoder. The first clip of the folder, median of the runs."""
    sys.path.insert(0, str(REPO))
    from faster_whisper.audio import pad_or_trim
    from fish_brain.stt import _whisper_tokenizer
    clip = load_clips(args.clips)[0]
    audio = read_audio(clip["path"])
    model = _fw_model(args.model, args.compute)
    tokenizer = _whisper_tokenizer(model, "es")
    prompt = model.get_prompt(tokenizer, [], without_timestamps=True)

    def timed(fn):
        fn()
        times = []
        for _ in range(args.runs):
            t0 = time.monotonic()
            value = fn()
            times.append(time.monotonic() - t0)
        return statistics.median(times), value

    mel_s, features = timed(lambda: model.feature_extractor(audio)[:, :-1])
    rows = [["features", "-", f"{mel_s:.3f}", ""]]
    for frames in args.frames:
        if frames < features.shape[-1]:
            continue
        enc_s, enc = timed(lambda: model.encode(pad_or_trim(features, frames)))
        dec_s, result = timed(lambda: model.model.generate(enc, [prompt], beam_size=1)[0])
        text = tokenizer.decode(result.sequences_ids[0]).strip()
        rows.append(["encoder", str(frames), f"{enc_s:.2f}", ""])
        rows.append(["decoder, beam 1", str(frames), f"{dec_s:.2f}", text])
    print(f"{args.model} {args.compute}, clip {clip['name']} ({clip['seconds']:.1f} s)")
    print(table(["stage", "frames", "median s", "text"], rows, args.md))
    return 0


def cmd_record(args) -> int:
    phrases = PHRASES
    if args.phrases:
        phrases = [ln.strip() for ln in Path(args.phrases).read_text(encoding="utf-8").splitlines()
                   if ln.strip()]
    out = Path(args.out)
    base = ["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16"]
    # One folder per microphone, so each is a set of clips for `run`.
    mics = {}
    for item in args.mic:
        name, eq, source = item.partition("=")
        if not eq:
            raise SetupError(f"--mic {item!r}: write NAME=SOURCE")
        mics[out / name] = source
    if not mics:
        mics[out] = args.source
    for folder in mics:
        folder.mkdir(parents=True, exist_ok=True)
    if args.remote:
        sys.path.insert(0, str(REPO))
        from fish_brain.evdev_button import resolve_key, resolve_keys
        keys = {resolve_key(args.key_discard): "discard", resolve_key(args.key_next): "skip",
                resolve_key(args.key_end): "end"}
        keys.update({code: "talk" for code in resolve_keys(args.key_talk)})
        io = RemoteIO(mics, list(phrases), args.loq)
        print(f"[rec] ready: {len(phrases)} lines, {args.takes} takes each", flush=True)
        session = TakeSession(list(phrases), io, prefix=args.prefix, takes=args.takes)
        remote_loop(session, args.remote, keys)
        print(f"\nclips in {out}")
        return 0
    for i, phrase in enumerate(phrases, 1):
        name = f"{args.prefix}{i:02d}"
        if not args.redo and all((folder / f"{name}{ext}").exists()
                                 for folder in mics for ext in (".wav", ".txt")):
            print(f"{name}: already recorded")
            continue
        print(f"\n{i}/{len(phrases)}  {phrase}")
        input("  Enter, say it, Enter again ")
        try:
            recs = [subprocess.Popen([*base, *(["--target", source] if source else []),
                                      str(folder / f"{name}.wav")])
                    for folder, source in mics.items()]
        except FileNotFoundError:
            raise SetupError("pw-record is not installed") from None
        input("  recording... Enter to stop ")
        for rec in recs:
            rec.send_signal(signal.SIGINT)
        for rec in recs:
            rec.wait(timeout=5)
        for folder in mics:
            (folder / f"{name}.txt").write_text(phrase + "\n", encoding="utf-8")
    print(f"\nclips in {out}")
    return 0


# --- recording from a remote: hold to record, keys to discard, skip and end -----------------

class TakeSession:
    """Which line is being recorded and which takes it has. The keys call `press`,
    `release`, `discard`, `skip` and `end`; everything heard or written goes through `io`."""

    def __init__(self, phrases: list[str], io, prefix: str = "voz", takes: int = 3,
                 min_s: float = 0.3, min_rms: float = 0.005):
        self.phrases, self.io, self.prefix, self.want = phrases, io, prefix, takes
        self.min_s, self.min_rms = min_s, min_rms
        self.line, self.takes, self.count, self.recording, self.done = 0, [], 0, None, False
        self.io.announce(0, phrases[0])

    def press(self) -> None:
        if self.done or self.recording:
            return
        self.count += 1
        self.recording = f"{self.prefix}{self.line + 1:02d}_{self.count}"
        self.io.start(self.recording)

    def release(self) -> None:
        if not self.recording:
            return
        name, self.recording = self.recording, None
        seconds, rms = self.io.stop(name, self.phrases[self.line])
        if seconds < self.min_s or rms < self.min_rms:
            self.io.remove(name)
            self.io.beep("bad")                  # a tap, or a microphone that hears nothing
            return
        self.takes.append(name)
        self.io.beep("ok")
        if len(self.takes) >= self.want:
            self._next()

    def discard(self) -> None:
        if self.done or self.recording:
            return
        if self.takes:
            self.io.remove(self.takes.pop())
        self.io.beep("bad")

    def skip(self) -> None:
        if not (self.done or self.recording):
            self._next()

    def end(self) -> None:
        if self.recording:
            self.io.stop(self.recording, "")
            self.io.remove(self.recording)
            self.recording = None
        self.done = True

    def _next(self) -> None:
        self.line, self.takes, self.count = self.line + 1, [], 0
        if self.line >= len(self.phrases):
            self.done = True
            self.io.announce(-1, "")
        else:
            self.io.announce(self.line, self.phrases[self.line])


def _tone(path: Path, hz: float, seconds: float = 0.15) -> None:
    n = int(RATE * seconds)
    data = b"".join(int(9000 * math.sin(2 * math.pi * hz * i / RATE)).to_bytes(2, "little", signed=True)
                    for i in range(n))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data)


class RemoteIO:
    """The real side of a `TakeSession`: pw-record per microphone, the line numbers spoken
    by `loq` when it is there (rendered before the session), tones for the rest."""

    def __init__(self, mics: dict, phrases: list[str], loq: str):
        self.mics, self.recs = mics, []
        self.tmp = Path(tempfile.mkdtemp(prefix="stt_bench_"))
        _tone(self.tmp / "ok.wav", 1320.0)
        _tone(self.tmp / "bad.wav", 330.0, 0.3)
        self.spoken = {}
        if loq and os.path.exists(loq):
            for i in [*range(len(phrases)), -1]:
                wav = self.tmp / f"say{i}.wav"
                text = f"Frase {i + 1}." if i >= 0 else "Terminamos. Gracias."
                done = subprocess.run([loq, "-o", str(wav), "--", text],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if done.returncode == 0 and wav.exists():
                    self.spoken[i] = wav

    def _play(self, wav: Path) -> None:
        subprocess.run(["pw-play", str(wav)], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)

    def announce(self, line: int, phrase: str) -> None:
        print(f"[rec] line {line + 1}: {phrase}" if line >= 0 else "[rec] end of the lines",
              flush=True)
        if line in self.spoken:
            self._play(self.spoken[line])
        else:
            for _ in range(2):
                self._play(self.tmp / "ok.wav")

    def beep(self, kind: str) -> None:
        self._play(self.tmp / f"{kind}.wav")

    def start(self, name: str) -> None:
        base = ["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16"]
        self.recs = [subprocess.Popen([*base, *(["--target", source] if source else []),
                                       str(folder / f"{name}.wav")])
                     for folder, source in self.mics.items()]

    def stop(self, name: str, phrase: str) -> tuple[float, float]:
        """Seconds and level of the first microphone's take; the levels of all are printed."""
        for rec in self.recs:
            rec.send_signal(signal.SIGINT)
        for rec in self.recs:
            rec.wait(timeout=5)
        self.recs, levels = [], []
        for folder in self.mics:
            wav = folder / f"{name}.wav"
            try:
                audio = read_audio(str(wav))
            except (OSError, wave.Error, EOFError):
                audio = []
            seconds = len(audio) / RATE
            rms = float((audio * audio).mean() ** 0.5) if len(audio) else 0.0
            levels.append((seconds, rms))
            (folder / f"{name}.txt").write_text(phrase + "\n", encoding="utf-8")
        print(f"[rec] {name}: " + ", ".join(
            f"{folder.name} {sec:.1f} s rms {rms:.3f}"
            for folder, (sec, rms) in zip(self.mics, levels)), flush=True)
        return levels[0]

    def remove(self, name: str) -> None:
        print(f"[rec] {name}: discarded", flush=True)
        for folder in self.mics:
            for ext in (".wav", ".txt"):
                (folder / f"{name}{ext}").unlink(missing_ok=True)


def remote_loop(session: TakeSession, device: str, keys: dict) -> None:
    """Feed the remote's keys to the session until it is done. `device` is `name:<part>` or
    a /dev/input path; `keys` maps key codes to the session's method names."""
    import select

    import evdev
    from fish_brain.evdev_button import key_name, list_nodes
    part = device[5:].strip().lower() if device.lower().startswith("name:") else None
    devices = []
    for path in ([device] if part is None else list_nodes()):
        try:
            dev = evdev.InputDevice(path)
        except OSError:
            continue
        have = dev.capabilities().get(evdev.ecodes.EV_KEY, [])
        if (part is None or part in dev.name.lower()) and any(k in have for k in keys):
            devices.append(dev)
        else:
            dev.close()
    if not devices:
        raise SetupError(f"no input device {device!r} with those keys")
    print("[rec] listening on " + ", ".join(d.path for d in devices), flush=True)
    while not session.done:
        ready, _, _ = select.select(devices, [], [], 1.0)
        for dev in ready:
            for event in dev.read():
                if event.type != evdev.ecodes.EV_KEY:
                    continue
                if event.value != 2:             # every key, so a wrong button shows in the log
                    print(f"[key] {key_name(event.code)} {'down' if event.value else 'up'}"
                          f" ({dev.path})", flush=True)
                if event.code not in keys:
                    continue
                action = keys[event.code]
                if action == "talk":
                    if event.value == 1:
                        session.press()
                    elif event.value == 0:
                        session.release()
                elif event.value == 1:
                    getattr(session, action)()


# --- self-test -----------------------------------------------------------------------------

def self_test() -> int:
    failures = []

    def check(name: str, ok: bool) -> None:
        print(f"[self-test] {name}")
        if not ok:
            failures.append(name)

    check("word errors: equal, one wrong, one missing, one extra, case and punctuation",
          word_errors("Hola pez, ¿cómo estás?", "hola pez como estás") == (1, 4)
          and word_errors("sí", "Sí.") == (0, 1) and word_errors("uno dos", "uno") == (1, 2)
          and word_errors("uno", "uno dos") == (1, 1) and word_errors("", "algo") == (1, 0)
          and word_errors(unicodedata.normalize("NFD", "cómo estás"), "cómo estás") == (0, 2))
    check("candidate options", parse_spec("fw-window:model=base,window=15") ==
          ("fw-window", {"model": "base", "window": "15"})
          and _take({"window": "15"}, window=10.0, beam=1) == {"window": 15.0, "beam": 1})
    for bad in ("nada:x=1", "fw:model"):
        try:
            parse_spec(bad)
            check(f"bad candidate {bad!r} refused", False)
        except SetupError:
            check(f"bad candidate {bad!r} refused", True)
    with tempfile.TemporaryDirectory() as folder:
        for name, ref in (("a", "hola pez"), ("b", "me llamo Alejandra")):
            with wave.open(os.path.join(folder, name + ".wav"), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(RATE)
                w.writeframes(b"\0\0" * RATE)
            Path(folder, name + ".txt").write_text(ref, encoding="utf-8")
        clips = load_clips(folder)
        check("clips: two, one second each, with their references",
              [(c["name"], c["seconds"], c["ref"]) for c in clips]
              == [("a", 1.0, "hola pez"), ("b", 1.0, "me llamo Alejandra")])
        good = spawn_one("fake", folder, 2)
        bad = spawn_one("fake:wrong=1", folder, 2)
        dead = spawn_one("fake:fail=1", folder, 2)
        check("a candidate in its own process: times, texts, memory",
              "error" not in good and len(good["clips"]) == 2
              and len(good["clips"][0]["times"]) == 2 and good["peak_rss_mb"] > 1)
        check("report: 0 % for the right answers, 40 % for one wrong word per clip",
              summary_row(good)[4] == "0.0" and summary_row(bad)[4] == "40.0")
        header, rows = length_rows([good, bad])
        check("by clip length: one bucket, both candidates",
              header == ["candidate", "0-3 s"] and rows[0][1].endswith(", 0 % (n=2)")
              and rows[1][1].endswith(", 40 % (n=2)"))
        try:                                     # the cloud candidate, with no network
            sys.path.insert(0, str(REPO))
            from types import SimpleNamespace
            from fish_brain import cloud
            calls = []
            real = cloud.client, cloud.is_online
            cloud.is_online = lambda: True
            cloud.client = lambda *a, **k: SimpleNamespace(audio=SimpleNamespace(
                transcriptions=SimpleNamespace(
                    create=lambda **kw: calls.append(kw) or SimpleNamespace(text=" hola pez "))))
            try:
                said = make_cloud({"profile": "groq", "model": "whisper-large-v3"})(clips[0])
            finally:
                cloud.client, cloud.is_online = real
            check("cloud candidate: the fish's own request, the model overridden",
                  said == "hola pez" and calls[0]["model"] == "whisper-large-v3"
                  and calls[0]["language"] == "es" and str(calls[0]["file"]) == clips[0]["path"])
        except ImportError as e:
            print(f"[self-test] cloud candidate skipped: {e}")
        check("a failing candidate is a row, not a crash",
              "RuntimeError" in dead.get("error", "") and "FAILED" in report([dead, good], True))
    class FakeIO:
        def __init__(self, results):
            self.results, self.log = list(results), []

        def announce(self, line, phrase):
            self.log.append(("say", line))

        def beep(self, kind):
            self.log.append((kind,))

        def start(self, name):
            self.log.append(("start", name))

        def stop(self, name, phrase):
            return self.results.pop(0)

        def remove(self, name):
            self.log.append(("remove", name))

    good, tap, deaf = (2.0, 0.1), (0.1, 0.1), (2.0, 0.0)
    io = FakeIO([good, tap, deaf, good, good, good, good])
    ses = TakeSession(["uno", "dos", "tres"], io, takes=3)
    for _ in range(4):                           # a good take, a tap, a deaf one, a good one
        ses.press()
        ses.press()                              # a second press while recording: ignored
        ses.release()
    ses.discard()                                # the last good take was garbled
    for _ in range(2):
        ses.press()
        ses.release()
    check("remote session: bad takes refused, a discard, three good takes move to the next line",
          ses.line == 1 and ses.takes == [] and not ses.done
          and [e for e in io.log if e[0] == "remove"] ==
          [("remove", "voz01_2"), ("remove", "voz01_3"), ("remove", "voz01_4")]
          and [e[1] for e in io.log if e[0] == "start"][-1] == "voz01_6"
          and io.log[-1] == ("say", 1))
    ses.skip()
    ses.press()
    ses.release()
    ses.skip()
    check("remote session: skipping lines reaches the end", ses.done and io.log[-1] == ("say", -1)
          and ("start", "voz03_1") in io.log)
    io = FakeIO([good])
    ses = TakeSession(["uno"], io)
    ses.press()
    ses.end()
    ses.press()
    check("remote session: the end key drops a take in progress and stops",
          ses.done and ("remove", "voz01_1") in io.log
          and [e for e in io.log if e[0] == "start"] == [("start", "voz01_1")])
    print("[self-test] " + ("FAILED: " + ", ".join(failures) if failures else "all passed"))
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--self-test" in argv:
        return self_test()
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("run", "_one"):
        c = sub.add_parser(name, help="time and score candidates" if name == "run" else None)
        c.add_argument("--clips", required=True, help="folder of name.wav + name.txt")
        c.add_argument("--cand", action="append", required=True, help="kind:key=value,...")
        c.add_argument("--runs", type=int, default=3, help="timed runs per clip")
        c.add_argument("--rest", type=float, default=0.0, help="seconds between candidates")
        c.add_argument("--gap", type=float, default=0.0,
                       help="seconds before each call (a service's calls-per-minute limit)")
        c.add_argument("--md", action="store_true", help="tables as Markdown")
    c = sub.add_parser("split", help="features, encoder and decoder of faster-whisper apart")
    c.add_argument("--clips", required=True)
    c.add_argument("--model", default="small")
    c.add_argument("--compute", default="int8")
    c.add_argument("--frames", type=int, nargs="+", default=[3000, 1500, 1000],
                   help="encoder windows to time, 100 per second")
    c.add_argument("--runs", type=int, default=3)
    c.add_argument("--md", action="store_true")
    c = sub.add_parser("record", help="read phrases into a microphone, one clip each")
    c.add_argument("--out", required=True)
    c.add_argument("--source", default="", help="PipeWire source name (default: the default)")
    c.add_argument("--mic", action="append", default=[], metavar="NAME=SOURCE",
                   help="record several microphones at once, each into OUT/NAME (repeatable)")
    c.add_argument("--phrases", help="a text file, one phrase per line")
    c.add_argument("--prefix", default="voz", help="clip names start with this")
    c.add_argument("--redo", action="store_true", help="record again over existing clips")
    c.add_argument("--remote", metavar="DEVICE", default="",
                   help="record from a remote instead of the terminal: name:<part> or a "
                        "/dev/input path. Hold the talk key to record a take")
    c.add_argument("--takes", type=int, default=3, help="--remote: takes per line")
    c.add_argument("--key-talk", default="KEY_ENTER,BTN_LEFT",
                   help="hold to record; several codes for a remote that changes mode")
    c.add_argument("--key-discard", default="KEY_LEFT", help="drops the last take")
    c.add_argument("--key-next", default="KEY_RIGHT", help="next line with fewer takes")
    c.add_argument("--key-end", default="KEY_MUTE", help="ends the session")
    c.add_argument("--loq", default=os.path.expanduser("~/.local/bin/loq"),
                   help="--remote: the voice that says the line numbers (tones without it)")
    args = p.parse_args(argv)
    try:
        return {"run": cmd_run, "_one": cmd_one, "split": cmd_split,
                "record": cmd_record}[args.cmd](args)
    except SetupError as e:
        print(f"stt_bench: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
