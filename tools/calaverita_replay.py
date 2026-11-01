"""One calaverita request through the act's compose, N times: how often it would give way to the clips,
and the pairs refused. Text only. .venv/bin/python tools/calaverita_replay.py "[CALAVERITA: ...]" [--takes 8]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--takes", type=int, default=8)
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    import os
    os.environ["FISH_PERSONA"] = "hat"
    from fish_brain import calaverita as cal
    from fish_brain.config import Config, LLMConfig
    from fish_brain.llm import make_conversation
    cfg = Config().fortune
    clients = [make_conversation(LLMConfig(profile="claude-sonnet", max_completion_tokens=2000)) for _ in range(3)]
    full = 0
    for t in range(args.takes):
        r = cal.compose(clients, cfg.calaverita_rules, args.tag, passes=cfg.calaverita_passes, budget_s=cfg.calaverita_compose_s)
        full += r["rhymed"] == cal.STANZAS
        print(f"--- take {t + 1}: {r['rhymed']}/3 rhymed, {r['passes']} passes, {r['versions']} versions")
        if r["stanzas"]:
            print("\n".join(" / ".join(s) for s in r["stanzas"]))
            for n, a, b in cal.bad_pairs(r["stanzas"]):
                print(f"  refused, stanza {n}: {a!r} | {b!r} ({cal.rhyme_key(a)} {cal.rhyme_key(b)})")
    print(f"fully rhymed {full}/{args.takes}; to the clips {args.takes - full}/{args.takes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
