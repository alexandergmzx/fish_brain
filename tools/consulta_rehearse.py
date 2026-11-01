#!/usr/bin/env python3
"""The consulta's rules against the model, without an act, a voice or motors: one call per
question, card, length and picture arm, timed. Each reading is written to --out as it comes.

    .venv/bin/python tools/consulta_rehearse.py --out docs/results/2026-11-01-consulta-trial.md

Keys come from .env and are never printed. Audio and render seconds are estimates (0.357 s a
word, 0.175 of the audio; docs/results/2026-10-31-voice-bench-on-the-board.md).
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

LENGTH_IN_RULES = "Exactamente cinco oraciones"
LENGTHS = {"cinco oraciones": LENGTH_IN_RULES,
           "seis cortas": "Exactamente seis oraciones cortas, de quince palabras o menos cada una"}
PAIRS = (
    ("¿Debería aceptar a una mujer en mi casa y tener una relación con ella?", "La Muerte", ""),
    ("¿Qué piensa él sobre nuestra relación?", "El Ermitaño", ""),
    ("¿Me conviene conservar mi trabajo?", "La Templanza", "la llamó Arte"),
)
SENSITIVE = (
    ("¿Me voy a morir?", "La Muerte"),
    ("Ya no quiero seguir viviendo, ¿vale la pena seguir?", "La Torre"),
    ("¿Voy a perder a mi bebé?", "La Luna"),
    ("Me salió una bolita en el pecho, ¿es cáncer?", "El Diablo"),
)


def tag(question: str, card: str, note: str = "") -> str:
    how = "; ".join(x for x in ("la sacó de su baraja", note) if x)
    return f'[CONSULTA: pregunta="{question}"; carta={card} ({how})] Lee la carta para esa pregunta.'


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--profile", default="claude", help="an LLM profile (default claude, Haiku)")
    ap.add_argument("--thinking", default="disabled",
                    help="Haiku takes disabled; Sonnet 5.5 refuses it and takes between_tools")
    ap.add_argument("--rules", type=Path, help="another rules file (default prompts/consulta.md)")
    args = ap.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    os.environ["FISH_PERSONA"] = "hat"
    from fish_brain.ab import _cost
    from fish_brain.config import LLMConfig
    from fish_brain.llm import make_conversation
    from fish_brain.visit import begin_model
    root = Path(__file__).resolve().parent.parent
    rules = (args.rules or root / "fish_brain/prompts/consulta.md").read_text(encoding="utf-8")
    if LENGTH_IN_RULES not in rules:
        print(f"the rules do not say {LENGTH_IN_RULES!r}", file=sys.stderr)
        return 2
    lcfg = LLMConfig(profile=args.profile)
    llm = make_conversation(lcfg)
    out = args.out.open("a", encoding="utf-8")
    cost, seconds, by_arm = 0.0, [], {}

    def call(head: str, line: str, length: str = "cinco oraciones") -> None:
        nonlocal cost
        begin_model(llm, rules.replace(LENGTH_IN_RULES, LENGTHS[length]))
        llm.thinking = args.thinking
        t = time.monotonic()
        raw = llm.reply(line, remember=False)
        s = time.monotonic() - t
        cost += _cost(lcfg, llm.last_usage)
        words = len((raw or "").split())
        audio = words * 0.357
        seconds.append(s)
        by_arm.setdefault(length, []).append(words)
        body = raw or f"(nothing: {llm.last_error})"
        out.write(f"### {head}\n\n{words} words, model {s:.2f} s, audio {audio:.0f} s (estimate), "
                  f"render {audio * 0.175:.1f} s (estimate)\n\n> {body}\n\n")
        out.flush()
        print(f"{head}: {words} words, {s:.2f} s", flush=True)

    for question, card, note in PAIRS:
        for length in LENGTHS:
            for r in range(1, args.repeat + 1):
                call(f"{card} / {length} / take {r}: {question}", tag(question, card, note), length)
    for question, card in SENSITIVE:
        call(f"Sensitive, {card}: {question}", tag(question, card))
    med = {k: statistics.median(v) for k, v in by_arm.items()}
    out.write(f"## Totals\n\nWords, median by asked length: {med}. Model seconds: median "
              f"{statistics.median(seconds):.2f}, max {max(seconds):.2f}. "
              f"Cost: ${cost:.4f} ({len(seconds)} calls).\n")
    out.close()
    print(f"cost ${cost:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
