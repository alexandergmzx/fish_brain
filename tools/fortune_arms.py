#!/usr/bin/env python3
"""The fortune's arms on real visitors: with or without a card, on each model, through the act's
own steps (hat_rehearse.run_fortune), every model call timed. The real model, no voice, no board.

    .venv/bin/python tools/fortune_arms.py --out rehearsals/arms SCRIPT [SCRIPT ...] --takes 2
Writes OUT/arms.json (the visitors' own words: keep it under rehearsals/) and prints the totals.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# profile, the reading's thinking (Sonnet answers a 400 to "disabled"), the deck
ARMS = {"haiku+card": ("claude", "disabled", "tarot"), "haiku-nocard": ("claude", "disabled", "off"),
        "sonnet+card": ("claude-sonnet", "between_tools", "tarot"), "sonnet-nocard": ("claude-sonnet", "between_tools", "off")}


def run_arm(name: str, visitors: list[dict], takes: int) -> list[dict]:
    import hat_rehearse
    from fish_brain.config import Config, LLMConfig
    from fish_brain.llm import make_conversation
    from fish_brain.show import ShowState
    profile, thinking, deck = ARMS[name]
    cfg = Config()
    cfg.fortune.deck, cfg.fortune.thinking = deck, thinking
    llm = make_conversation(LLMConfig(profile=profile))
    calls: list[float] = []
    plain = llm.reply

    def timed(*a, **k):
        t0 = time.monotonic()
        out = plain(*a, **k)
        calls.append(round(time.monotonic() - t0, 2))
        return out
    llm.reply = timed
    state, out = ShowState(None, seed=f"arms-{name}"), []
    for take in range(takes):
        for i, visitor in enumerate(visitors):
            del calls[:]
            try:
                rec = hat_rehearse.run_fortune(llm, cfg, visitor, None, seed=i, state=state)
            except Exception as e:
                out.append({"arm": name, "visitor": i, "take": take, "crash": f"{type(e).__name__}: {e}"})
                continue
            out.append({"arm": name, "visitor": i, "take": take, "answers": rec["answers"], "tag": rec["tag"],
                        "reading": rec["said"], "reading_s": round(rec["s"], 2), "ask_s": list(calls[:-1]),
                        "error": rec["error"], "problems": rec["problems"], "usage": str(rec["usage"])})
            print(f"{name} v{i} t{take}: {len((rec['said'] or '').split())} words {rec['s']:.1f}s", flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("scripts", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--takes", type=int, default=2)
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv()
    os.environ["FISH_PERSONA"] = "hat"
    import hat_rehearse
    visitors = [v for s in args.scripts for v in hat_rehearse.parse_script(s.read_text(encoding="utf-8")) if v.get("fortune")]
    args.out.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(len(ARMS)) as pool:
        rows = [r for rs in pool.map(lambda n: run_arm(n, visitors, args.takes), ARMS) for r in rs]
    (args.out / "arms.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for name in ARMS:
        rs = [r for r in rows if r["arm"] == name and "crash" not in r]
        good = [r for r in rs if r["reading"]]
        asks = [s for r in rs for s in r["ask_s"]]
        words = [len(r["reading"].split()) for r in good]
        clips = sum(a.get("hat", {}).get("mark") == "H → clip" for r in rs for a in r["answers"])
        print(name, f"acts {len(rs)} readings {len(good)} crashes {sum(r['arm'] == name and 'crash' in r for r in rows)}",
              f"reading s med {statistics.median(r['reading_s'] for r in good):.2f} max {max(r['reading_s'] for r in good):.2f}",
              f"ask s med {statistics.median(asks):.2f} max {max(asks):.2f}" if asks else "",
              f"words med {statistics.median(words):.0f} max {max(words)} refused asks {clips}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
