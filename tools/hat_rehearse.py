#!/usr/bin/env python3
"""Rehearse the hat's visit against the model, without a voice, a microphone or motors.

    .venv/bin/python tools/hat_rehearse.py tools/hat_visitors.txt
    .venv/bin/python tools/hat_rehearse.py --profiles luna,groq tools/hat_visitors.txt
    .venv/bin/python tools/hat_rehearse.py --only 3 tools/hat_visitors.txt     # one visitor

Runs each scripted visitor through the same steps as the turn loop (fish_brain/visit.py):
a new visit resets the model and attaches the visit's rules, the opener is seeded as the hat's
first turn, every visitor line is tagged "[ETAPA n/4] [PISTAS: ...]", the reply is split
from its "CASA:" line, and the pair is remembered as if spoken. FISH_PERSONA is forced to
"hat". Keys come from .env and are never printed.

Script: visitors separated by a blank line. In a block:
    # a comment
    gafete: Sofía                 the visit opens with "¿Tú eres Sofía?" (the badge)
    sin saludo                    no opener: the model does stage 1 itself (an idle start)
    pistas: edad=niño; color=azul the operator's cues, from here on (keys: visit.CUE_ORDER)
    anything else                 what the visitor says, one turn per line
Without "gafete:" or "sin saludo" the visit opens with the canned greeting (Nuevo visitante).

Checks per reply: no tag spoken ("[", "CASA", "ETAPA", "PISTAS"), sentences and words; per
visit: a house at the verdict. A summary per profile gives the seconds per stage.
"""
from __future__ import annotations

import argparse
import os
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_LEAKS = ("[", "CASA", "ETAPA", "PISTAS")
_SENTENCE = re.compile(r"[^.!?…]+[.!?…]+|[^.!?…]+$")


def parse_script(text: str) -> list[dict]:
    """Blocks -> [{"badge": str|None, "greet": bool, "steps": [("cues", dict)|("say", str)]}]."""
    visitors, cur = [], None
    for raw in text.splitlines() + [""]:
        line = raw.strip()
        if not line:
            if cur and cur["steps"]:
                visitors.append(cur)
            cur = None
            continue
        if line.startswith("#"):
            continue
        cur = cur or {"badge": None, "greet": True, "steps": []}
        low = line.lower()
        if low.startswith("gafete:"):
            cur["badge"] = line.split(":", 1)[1].strip()
        elif low == "sin saludo":
            cur["greet"] = False
        elif low.startswith("pistas:"):
            cues = {}
            for part in line.split(":", 1)[1].split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    cues[k.strip()] = v.strip()
            cur["steps"].append(("cues", cues))
        else:
            cur["steps"].append(("say", line))
    return visitors


def check(spoken: str, *, verdict: bool) -> list[str]:
    """What is wrong with one spoken reply ([] = nothing)."""
    out = [f"spoken tag {w!r}" for w in _LEAKS if w in spoken]
    sentences = [s for s in _SENTENCE.findall(spoken) if s.strip()]
    words = len(spoken.split())
    if not spoken:
        out.append("empty")
    if len(sentences) > (4 if verdict else 2):
        out.append(f"{len(sentences)} sentences")
    if words > (70 if verdict else 35):
        out.append(f"{words} words")
    return out


def run_visit(llm, cfg, visitor: dict, *, clock=None) -> dict:
    """One scripted visitor through the visit's steps; returns its record."""
    import time
    from fish_brain import reading, visit
    clock = clock or time.monotonic
    v = visit.Visit(cfg.visit.stages, idle_s=0, clock=clock, future=cfg.visit.future)
    first = visitor["badge"] or ""
    v.start(first)
    visit.begin_model(llm, cfg.visit.rules)
    turns = []
    if visitor["badge"]:
        question = reading.echo_question(first)
        llm.remember(f"[ETAPA 1/{v.stages}] " + visit.note(cfg.visit.badge_note, first), question)
        v.delivered()
        turns.append({"stage": 1, "you": "(gafete)", "hat": question, "s": 0.0, "problems": []})
    elif visitor["greet"]:
        greeting = cfg.canned.phrases.get(cfg.visit.greeting, "")
        llm.remember(f"[ETAPA 1/{v.stages}] " + cfg.visit.arrival_note, greeting)
        v.delivered()
        turns.append({"stage": 1, "you": "(nuevo visitante)", "hat": greeting, "s": 0.0,
                      "problems": []})
    skipped = 0
    for kind, value in visitor["steps"]:
        if kind == "cues":
            v.set_cues(value)
            continue
        if v.done:
            skipped += 1
            continue
        stage = v.stage
        tagged, snap = v.prepare(value)
        raw = llm.reply(tagged, remember=False)
        spoken, house = visit.split_reply(raw)
        turn = {"stage": stage, "you": value, "sent": tagged, "hat": spoken, "house": house,
                "s": getattr(llm, "last_latency_s", 0.0), "error": llm.last_error,
                "usage": getattr(llm, "last_usage", None),
                "problems": check(spoken, verdict=stage == v.stages)}
        turns.append(turn)
        if llm.last_error or not spoken:
            continue                            # not delivered: the stage stays
        if house and house.lower() not in spoken.lower():
            turn["problems"].append("the house is not said aloud")
        llm.remember(tagged, raw)
        v.delivered(house, snap)
    verdict = v.done
    return {"turns": turns, "house": v.house, "done": verdict, "skipped": skipped,
            "problems": [] if v.house else ["no house at the verdict" if verdict
                                            else "the visit did not reach the verdict"]}


def _print_visit(i: int, profile: str, rec: dict) -> None:
    print(f"\n=== visitor {i} · {profile} ===")
    for t in rec["turns"]:
        flag = ("  !! " + ", ".join(t["problems"])) if t["problems"] else ""
        err = f"  !! {t['error']}" if t.get("error") else ""
        print(f"  you> {t['you']}")
        print(f"  [{t['stage']}] hat ({t['s']:.1f}s)> {t['hat']}{flag}{err}")
    end = f"CASA: {rec['house']}" if rec["house"] else "no house"
    more = f", {rec['skipped']} line(s) after the verdict not sent" if rec["skipped"] else ""
    probs = ("  !! " + "; ".join(rec["problems"])) if rec["problems"] else ""
    print(f"  -> {end}{more}{probs}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("script", type=Path)
    ap.add_argument("--profiles", default="luna", help="comma-separated LLM profiles (default luna)")
    ap.add_argument("--only", type=int, help="run only visitor N (from 1)")
    args = ap.parse_args(argv)

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    os.environ["FISH_PERSONA"] = "hat"
    os.environ.pop("FISH_VISIT", None)
    from fish_brain.ab import _cost
    from fish_brain.config import Config, LLMConfig
    from fish_brain.llm import Conversation

    cfg = Config()
    if not cfg.visit.rules:
        print("the hat persona has no visit rules", file=sys.stderr)
        return 2
    visitors = parse_script(args.script.read_text(encoding="utf-8"))
    if args.only:
        visitors = [visitors[args.only - 1]]
    worst = 0
    for name in [n.strip() for n in args.profiles.split(",") if n.strip()]:
        lcfg = LLMConfig(profile=name)
        try:
            llm = Conversation(lcfg)
        except Exception as e:                  # a missing key: name the variable only
            print(f"can't start profile {name!r}: set {lcfg.api_key_env} in .env "
                  f"({type(e).__name__})", file=sys.stderr)
            return 1
        by_stage: dict[int, list[float]] = {}
        houses = problems = cost = 0
        futures: dict[tuple, int] = {}            # (lugar, cosa) of each verdict: repeats?
        for i, visitor in enumerate(visitors, args.only or 1):
            rec = run_visit(llm, cfg, visitor)
            _print_visit(i, name, rec)
            for t in rec["turns"]:
                if "sent" in t:
                    by_stage.setdefault(t["stage"], []).append(t["s"])
                    cost += _cost(lcfg, t.get("usage"))
                problems += bool(t["problems"] or t.get("error"))
            for t in rec["turns"]:
                m = re.search(r"\[FUTURO:([^\]]*)\]", t.get("sent", ""))
                if m:
                    kv = dict(p.split("=", 1) for p in m.group(1).strip().split("; ") if "=" in p)
                    key = (kv.get("lugar"), kv.get("cosa"))
                    futures[key] = futures.get(key, 0) + 1
            houses += bool(rec["house"])
            problems += bool(rec["problems"])
        print(f"\n### {name}: {houses} of {len(visitors)} visits with a house; "
              f"{problems} problem(s); cost ${cost:.4f}")
        repeats = {k: n for k, n in futures.items() if n > 1}
        if repeats:
            print(f"    same place and thing twice: {repeats}")
        for stage in sorted(by_stage):
            xs = by_stage[stage]
            print(f"    stage {stage}: median {statistics.median(xs):.1f} s, "
                  f"max {max(xs):.1f} s ({len(xs)} calls)")
        worst = max(worst, problems)
    return 1 if worst else 0


if __name__ == "__main__":
    raise SystemExit(main())
