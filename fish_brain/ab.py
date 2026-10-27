"""A/B test the fish's LLM backends (e.g. Groq GPT-OSS vs GPT-6 Luna) on the same prompts.

    python -m fish_brain.ab                       # built-in prompts, groq vs luna, blind voting
    python -m fish_brain.ab --no-vote             # just latency/cost, no voting
    python -m fish_brain.ab --prompts mine.txt    # one prompt per line
    python -m fish_brain.ab --speak               # also hear each reply through loq (no fish)

Each prompt is sent fresh (no history) to every profile. You see the replies in random
order labelled 1/2, pick the better one (or = for a tie), and at the end get a table of
wins, median/worst latency and cost per profile. Every row is saved to ab_results.csv.
"""
from __future__ import annotations

import argparse
import csv
import random
import statistics
from datetime import datetime
from pathlib import Path

from .config import LLMConfig, LLM_PROFILES
from .llm import make_conversation

PROMPTS = [
    "Hola Billy, ¿cómo estás?",
    "Cuéntame un chiste de peces.",
    "¿Qué opinas de los lunes?",
    "¿Cuál es tu comida favorita?",
    "Dame un consejo para mi entrevista de trabajo.",
    "¿Te gusta vivir colgado en la pared?",
    "¿Quién ganó el último mundial?",
    "Dime algo sarcástico sobre los gatos.",
    "¿Qué harías si te soltaran en el río?",
    "Despídete como si fueras un pirata.",
]


def _cost(cfg: LLMConfig, usage) -> float:
    if usage is None:
        return 0.0
    return (usage.prompt_tokens * cfg.price_in + usage.completion_tokens * cfg.price_out) / 1e6


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fish-brain-ab", description=__doc__.split("\n")[0])
    ap.add_argument("--profiles", default="groq,luna",
                    help=f"comma-separated, from {list(LLM_PROFILES)} (default groq,luna)")
    ap.add_argument("--prompts", type=Path, help="text file, one prompt per line")
    ap.add_argument("--no-vote", action="store_true", help="skip blind voting")
    ap.add_argument("--speak", action="store_true", help="also play each reply via loq")
    ap.add_argument("--out", type=Path, default=Path("ab_results.csv"))
    args = ap.parse_args(argv)

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    names = [n.strip() for n in args.profiles.split(",") if n.strip()]
    convs = {}
    for n in names:
        cfg = LLMConfig(profile=n)
        try:
            convs[n] = make_conversation(cfg)
        except Exception as e:                  # e.g. missing API key
            print(f"can't start profile {n!r}: set {cfg.api_key_env} in .env ({e})")
            return 1
    # Warm-up call per profile (not timed or saved) so connection setup doesn't skew latency.
    for conv in convs.values():
        conv.reply("hola")
        conv.reset()
    prompts = (args.prompts.read_text(encoding="utf-8").splitlines() if args.prompts else PROMPTS)
    prompts = [p.strip() for p in prompts if p.strip()]

    speaker = None
    if args.speak:
        from .config import load
        from .conductor import make_player
        from .tts import synthesize             # renders a WAV with loq
        tts_cfg, player = load().tts, make_player()

        def speaker(text: str) -> None:
            wav = synthesize(text, tts_cfg)
            try:
                player.play(wav)
                player.wait()
            finally:
                wav.unlink(missing_ok=True)

    stats = {n: {"lat": [], "cost": 0.0, "wins": 0, "errors": 0} for n in names}
    ties = 0
    rows = []
    stamp = datetime.now().isoformat(timespec="seconds")

    for i, prompt in enumerate(prompts, 1):
        print(f"\n[{i}/{len(prompts)}] you> {prompt}")
        replies = {}
        for n, conv in convs.items():
            conv.reset()                        # every prompt starts with no history
            text = conv.reply(prompt)
            s = stats[n]
            if conv.last_error:
                s["errors"] += 1
            else:
                s["lat"].append(conv.last_latency_s)
                s["cost"] += _cost(conv.cfg, conv.last_usage)
            replies[n] = text
            rows.append({"time": stamp, "prompt": prompt, "profile": n, "model": conv.cfg.model,
                         "latency_s": f"{conv.last_latency_s:.3f}",
                         "completion_tokens": getattr(conv.last_usage, "completion_tokens", ""),
                         "error": conv.last_error or "", "reply": text, "winner": ""})

        order = names[:]
        random.shuffle(order)                   # blind: you don't know which is which
        for k, n in enumerate(order, 1):
            print(f"  {k}) {replies[n]}")
            if speaker:
                speaker(replies[n])

        winner = ""
        if not args.no_vote and len(order) == 2:
            pick = ""
            while pick not in {"1", "2", "="}:
                pick = input("  better? [1/2/=] ").strip()
            if pick == "=":
                ties += 1
                winner = "tie"
            else:
                winner = order[int(pick) - 1]
                stats[winner]["wins"] += 1
            print(f"  (1 = {order[0]}, 2 = {order[1]})")
        for r in rows[-len(names):]:
            r["winner"] = winner

    new_file = not args.out.exists()
    with args.out.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        if new_file:
            w.writeheader()
        w.writerows(rows)

    print(f"\n{'profile':<8} {'model':<22} {'wins':>5} {'median s':>9} {'worst s':>8} "
          f"{'errors':>7} {'cost USD':>10}")
    for n in names:
        s = stats[n]
        med = f"{statistics.median(s['lat']):.2f}" if s["lat"] else "-"
        worst = f"{max(s['lat']):.2f}" if s["lat"] else "-"
        print(f"{n:<8} {convs[n].cfg.model:<22} {s['wins']:>5} {med:>9} {worst:>8} "
              f"{s['errors']:>7} {s['cost']:>10.6f}")
    if not args.no_vote:
        print(f"ties: {ties}")
    print(f"saved {len(rows)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
