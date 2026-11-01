"""One calaverita from a saved tag, composed and printed on FISH_PRINTER, no voice, no motors. Keeps the
best verse of up to --takes composes: paper is said to stay. Run with no act printing.
    .venv/bin/python tools/calaverita_print.py "[CALAVERITA: ...]" --first NAME --house HOUSE"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--first", default="")
    ap.add_argument("--house", default="")
    ap.add_argument("--place", default="")
    ap.add_argument("--takes", type=int, default=3)
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    import os
    os.environ["FISH_PERSONA"] = "hat"
    from fish_brain import calaverita as cal, printer, ticket
    from fish_brain.config import Config, LLMConfig
    from fish_brain.llm import make_conversation
    cfg = Config()
    clients = [make_conversation(LLMConfig(profile="claude-sonnet", max_completion_tokens=2000)) for _ in range(3)]
    best = None
    for _ in range(args.takes):
        r = cal.compose(clients, cfg.fortune.calaverita_rules, args.tag, passes=cfg.fortune.calaverita_passes,
                        budget_s=cfg.fortune.calaverita_compose_s)
        if r["stanzas"] and (best is None or r["rhymed"] > best["rhymed"]):
            best = r
        if best and best["rhymed"] == cal.STANZAS:
            break
    if best is None:
        print("no verse came back", file=sys.stderr)
        return 1
    print(f"{best['rhymed']}/{cal.STANZAS} stanzas rhymed\n")
    t = ticket.verse_ticket(0, args.first, args.house, best["stanzas"], place=args.place, now=datetime.now())
    print(ticket.preview(ticket.layout(t)), flush=True)
    p = printer.make_printer(cfg.printer)
    if p is None or not p.submit(t):
        print("the printer did not take it", file=sys.stderr)
        return 1
    done = p.wait(90)
    snap = p.snapshot()
    print("printer:", done, snap.get("state"), snap.get("why"), snap.get("bytes"), snap.get("seconds"))
    p.close()
    return 0 if snap.get("state") == "printed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
