#!/usr/bin/env python3
"""The Bluetooth speaker manager against the real BlueZ, with no pairing and no sound (ADR 0031):
reads the adapter, registers the agent, searches, prints what the page's lists would hold.

    .venv/bin/python tools/bt_check.py [--scan-s 12]
"""
import argparse
import tempfile
import time
from pathlib import Path

from fish_brain import bt, pw
from fish_brain.bt_bluez import DbusBus


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan-s", type=float, default=12.0)
    args = ap.parse_args()
    bus, cache = DbusBus(), pw.cache()
    with tempfile.TemporaryDirectory() as d:
        m = bt.BtManager(bus, sinks=cache.sinks, poke=cache.poke, path=Path(d) / "bt.json")
        m.scan_s = args.scan_s
        m.run_once()
        v = m.snapshot()
        print(f"alive={v['alive']} powered={v['powered']} problem={v['problem']!r}")
        t0 = time.monotonic()
        bus.register_agent(lambda *a: None)
        print(f"agent registered in {time.monotonic() - t0:.3f} s")
        print("find:", m.do({"do": "find"})[0])
        while m.phase == "scanning":
            m.run_once(1.0)
        v = m.snapshot()
        print(f"searched {args.scan_s:.0f} s; result={v['result']}")
        for key in ("mine", "nearby", "others"):
            print(f"{key}: {len(v[key])}")
            for r in v[key]:
                print(f"  {r['kind']:<11} {r['name']}")
        print("printer listed:", any("MP210" in r["name"] for k in ("mine", "nearby", "others") for r in v[k]))
        m.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
