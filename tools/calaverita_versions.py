"""How many versions a calaverita needs: batches of parallel calls per visitor, each scored with the
act's scanner. Text only. .venv/bin/python tools/calaverita_versions.py [--batch 3] [--rounds 3]"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

VISITORS = [("Mónica", "Hufflepuff", ["Por mi perro", "Porque me deja mis calcetines en la cama"]),
            ("Rodrigo", "Slytherin", ["La estudio primero", "Un negocio con un amigo"]),
            ("Albert", "Gryffindor", ["A mi novia", "Toco la puerta"]),
            ("", "Ravenclaw", ["No sé por qué se apaga el refri", "Le echo la culpa al gato"])]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=3)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--profile", default="claude-sonnet")
    args = ap.parse_args()
    from dotenv import load_dotenv
    for env in (ROOT / ".env", Path.home() / "Development/fish_brain/.env"):
        if env.exists():
            load_dotenv(env)
            break
    import os
    os.environ["FISH_PERSONA"] = "hat"
    from fish_brain import calaverita as cal
    from fish_brain.config import Config, LLMConfig
    from fish_brain.llm import make_conversation
    from fish_brain.visit import begin_model
    rules = Config().fortune.calaverita_rules
    clients = [make_conversation(LLMConfig(profile=args.profile, max_completion_tokens=2000))
               for _ in range(args.batch)]

    cfg = Config().fortune
    results = []
    for first, house, heard in VISITORS * args.rounds:
        t0 = time.monotonic()
        r = cal.compose(clients, rules, cal.verse_tag(first, house, "", {}, heard), passes=cfg.calaverita_passes,
                        budget_s=cfg.calaverita_compose_s)
        wall = time.monotonic() - t0
        results.append((wall, r["rhymed"] == cal.STANZAS, r["versions"]))
        print(f"### {first or '(no name)'}, {house}: {wall:.1f} s, {r['passes']} passes, {r['versions']} versions, "
              f"{r['rhymed']}/3 stanzas rhymed\n", flush=True)
        if r["stanzas"]:
            print("\n\n".join("  \n".join(x) for x in r["stanzas"]) + "\n", flush=True)
    print(f"fully rhymed: {sum(x[1] for x in results)}/{len(results)}; seconds median "
          f"{statistics.median(x[0] for x in results):.1f}, max {max(x[0] for x in results):.1f}; "
          f"versions median {statistics.median(x[2] for x in results):.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
