#!/usr/bin/env python3
"""Turn the fish's record (fish_brain/record.py) into a markdown table for docs/results.

    tools/records.py ~/.local/state/fish_brain/records/<file>.jsonl     # one file
    tools/records.py ~/.local/state/fish_brain/records                  # the newest file
    tools/records.py --self-test

Times are seconds since the first line (monotonic, so a clock jump at the NTP sync does not
move them). The last line says whether the record ended cleanly: no "end" line means the
power was pulled or the process was killed.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

SHOWN = ("start", "voice", "turn", "action", "ticket", "stop", "end")
TICKET_ENDS = ("printed", "failed")     # a ticket's other states are its way there


def _summary(line: dict) -> str:
    kind = line.get("kind")
    if kind == "turn":
        times = line.get("times") or {}
        t = " ".join(f"{k}={v}" for k, v in times.items() if isinstance(v, (int, float)))
        return f"{line.get('outcome', '')} {t}".strip()
    if kind == "voice":
        return f"{line.get('state')} (probe {line.get('probe_s')} s, clean {line.get('clean_s')} s)"
    if kind == "start":
        v = line.get("version") or {}
        return f"{v.get('commit', '')} stt={line.get('stt')} llm={line.get('llm')} tts={line.get('tts')}"
    if kind == "action":
        return f"{line.get('what', '')} {line.get('result', '')}".strip()
    if kind == "ticket":
        what = "reprint" if line.get("reprint") else "ticket"
        out = f"{what} #{line.get('n')} {line.get('state')}"
        if line.get("why"):
            out += f" ({line['why']})"
        if line.get("state") == "printed":
            out += f" {line.get('bytes')} B in {line.get('seconds')} s, connect {line.get('connect_s')} s"
        return out
    if kind == "stop":
        return " ".join(f"{k}={v}" for k, v in line.items()
                        if k not in ("kind", "mono", "wall", "synced"))
    return ""


def table(lines: list[dict]) -> str:
    if not lines:
        return "(empty record)\n"
    t0 = lines[0].get("mono", 0.0)
    rows = ["| t (s) | Kind | What |", "|---|---|---|"]
    for line in lines:
        if line.get("kind") == "ticket" and line.get("state") not in TICKET_ENDS:
            continue
        if line.get("kind") in SHOWN:
            rows.append(f"| {line.get('mono', 0.0) - t0:.1f} | {line['kind']} | "
                        f"{_summary(line).replace('|', '/')} |")
    ended = lines[-1].get("kind") == "end"
    rows.append("")
    rows.append("Ended cleanly." if ended else
                "No end line: the power was pulled or the process was killed.")
    return "\n".join(rows) + "\n"


def read(path: Path) -> list[dict]:
    out = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            pass                                    # a line cut by the pull
    return out


def _self_test() -> int:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "a.jsonl"
        p.write_text('{"kind":"start","mono":10}\n{"kind":"turn","mono":12.5,"outcome":"spoken",'
                     '"times":{"stt":0.6}}\n{"kind":"ticket","mono":13,"n":1,"state":"queued"}\n'
                     '{"kind":"ticket","mono":16,"n":1,"state":"printed","bytes":900,"seconds":3.1,'
                     '"connect_s":1.2}\n{"kind":"tu')
        out = table(read(p))
        assert "| 2.5 | turn | spoken stt=0.6 |" in out and "No end line" in out, out
        assert "| 6.0 | ticket | ticket #1 printed 900 B in 3.1 s, connect 1.2 s |" in out, out
        assert "queued" not in out, out
    print("self-test: all passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", nargs="?")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.path:
        ap.error("a record file or folder")
    p = Path(a.path).expanduser()
    if p.is_dir():
        files = sorted(p.glob("*.jsonl"), key=lambda f: f.stat().st_mtime)
        if not files:
            print(f"no records in {p}", file=sys.stderr)
            return 1
        p = files[-1]
    print(f"Record `{p.name}`\n")
    print(table(read(p)), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
