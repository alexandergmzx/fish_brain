#!/usr/bin/env python3
"""Rehearse the hat's visit and its fortune against the model, without a voice, a microphone
or motors.

    .venv/bin/python tools/hat_rehearse.py tools/hat_visitors.txt
    .venv/bin/python tools/hat_rehearse.py --profiles luna,groq tools/hat_visitors.txt
    .venv/bin/python tools/hat_rehearse.py --only 3 tools/hat_visitors.txt     # one visitor

Runs each scripted visitor through the same steps as the turn loop (fish_brain/visit.py):
a new visit resets the model and attaches the visit's rules, the opener is seeded as the hat's
first turn, every visitor line is tagged "[ETAPA n/4] [PISTAS: ...]", the reply is split
from its "CASA:" line, and the pair is remembered as if spoken. A "fortuna:" block then runs
the same person's fortune through the act's own steps (fish_brain/fortune_run.py:
parse_answer, fortune_of, reading_request, reading_result) with tonight's moon and a magic
word seeded by the visitor's number. FISH_PERSONA is forced to "hat". Keys come from .env and
are never printed.

Script: visitors separated by a blank line. In a block:
    # a comment
    gafete: Sofía                 the visit opens with "¿Tú eres Sofía?" (the badge)
    sin saludo                    no opener: the model does stage 1 itself (an idle start)
    lugar: casa                   the place for this visitor (else FISH_PLACE's)
    pistas: edad=adulto; color=azul   the operator's cues, from here on (keys: visit.CUE_ORDER);
                                  a value today's code refuses is reported, not sent
    anything else                 what the visitor says, one turn per line
    fortuna:                      from here on, the same person's fortune:
    fecha: Diecisiete de junio.   one answer per line, keyed by the question (fecha, sueno,
    sueno: Soñé con ...           carta, taza, animal); a second line for the same question
    animal: Un gato.              is the answer to its re-ask
Without "gafete:" or "sin saludo" the visit opens with the canned greeting (New visitor).

Checks per reply: no tag spoken ("[", "CASA", "ETAPA", "PISTAS"), sentences, words, banned
words (fortune.banned_in); per visit: a house at the verdict; per reading: why the act would
refuse it (fortune.reading_problems), a death said plainly, and a reading slower than the
act waits for it ("would fall back to clips"). Per visitor, information only: which cues show
up in the visit's replies and in the reading. Per profile: phrases repeated across verdicts
and across readings, words per reply, seconds per stage.
"""
from __future__ import annotations

import argparse
import os
import random
import re
import statistics
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_LEAKS = ("[", "CASA", "ETAPA", "PISTAS")
_SENTENCE = re.compile(r"[^.!?…]+[.!?…]+|[^.!?…]+$")
FORTUNE_QS = ("fecha", "sueno", "carta", "taza", "animal")
_Q_ALIASES = {"sueño": "sueno", "fecha": "fecha", "sueno": "sueno", "carta": "carta",
              "taza": "taza", "animal": "animal"}
# A death said plainly in a reading (folded): the rules ask for an image, never this.
_DEATH = ("murio", "fallecio", "se murio", "fallecido", "fallecida")
REPEAT_N = 4                    # words in a phrase that counts as repeated across verdicts

# The words that show a cue was used (folded prefixes of a word). Information, not a pass
# mark: the hat need not name every cue, and a cue said as a vision may use other words.
_CUE_STEMS: dict[str, tuple[str, ...]] = {
    "niño": ("nin", "pequen", "chiquit"), "adolescente": ("adolesc", "joven", "chav"),
    "adulto": ("adult",), "joven": ("joven", "juvent", "chav"),
    "mayor": ("mayor", "sabidur", "experienc", "anos vivid"),
    "solo": ("solo", "sola", "soledad", "solitar"), "amigos": ("amig", "cuate", "compa", "banda"),
    "familia": ("famili",), "pareja": ("pareja", "amor", "enamor", "novi", "corazon"),
    "rojo": ("roj",), "azul": ("azul",), "verde": ("verde",), "amarillo": ("amarill",),
    "negro": ("negr",), "blanco": ("blanc",), "rosa": ("rosa",), "morado": ("morad",),
    "tímido": ("timid", "callad", "silenci"), "sonriente": ("sonri", "risa", "alegr"),
    "curioso": ("curios", "pregunt"), "escéptico": ("esceptic", "duda", "incredul", "no crees"),
    "fiestero": ("fiest", "parrand", "baila", "bailar", "pachang", "reventon"),
    "tenebroso": ("tenebr", "disfraz", "oscur"), "chistoso": ("chist", "disfraz", "gracios"),
    "elegante": ("elegan", "disfraz"),
    "casa": ("ofrenda", "hogar", "los que se fueron"), "fiesta": ("fiest", "brind", "cancion"),
    "universidad": ("universi", "clase", "escuela", "examen"),
}
_STOP = frozenset("con una uno unos unas los las del que por para como pero muy mas sus "
                  "este esta esto tus".split())


def _fold(text: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", text or "")
                if unicodedata.category(c) != "Mn").lower()
    return " ".join(re.sub(r"[^a-z0-9ñ ]", " ", s).split())


def parse_script(text: str) -> list[dict]:
    """Blocks -> [{"badge": str|None, "greet": bool, "place": str|None,
    "steps": [("cues", dict)|("say", str)], "fortune": [(qid, str)] | None}]."""
    visitors, cur = [], None
    for raw in text.splitlines() + [""]:
        line = raw.strip()
        if not line:
            if cur and (cur["steps"] or cur["fortune"]):
                visitors.append(cur)
            cur = None
            continue
        if line.startswith("#"):
            continue
        cur = cur or {"badge": None, "greet": True, "place": None, "steps": [], "fortune": None}
        low = line.lower()
        if cur["fortune"] is not None:
            key, sep, value = line.partition(":")
            qid = _Q_ALIASES.get(key.strip().lower())
            if not sep or qid is None:
                raise ValueError(f"a fortune line must be 'fecha|sueno|carta|taza|animal: "
                                 f"...': {line!r}")
            cur["fortune"].append((qid, value.strip()))
        elif low in ("fortuna:", "fortuna"):
            cur["fortune"] = []
        elif low.startswith("gafete:"):
            cur["badge"] = line.split(":", 1)[1].strip()
        elif low.startswith("lugar:"):
            cur["place"] = line.split(":", 1)[1].strip()
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
    from fish_brain import fortune
    out = [f"spoken tag {w!r}" for w in _LEAKS if w in spoken]
    sentences = [s for s in _SENTENCE.findall(spoken) if s.strip()]
    words = len(spoken.split())
    if not spoken:
        out.append("empty")
    if len(sentences) > (4 if verdict else 2):
        out.append(f"{len(sentences)} sentences")
    if words > (70 if verdict else 35):
        out.append(f"{words} words")
    out += [f"banned {w!r}" for w in fortune.banned_in(spoken)]
    return out


def accepted_cues(cues: dict) -> tuple[dict, list[str]]:
    """The cues today's code takes, and the refused ones as "key=value" (never a crash)."""
    from fish_brain import visit
    ok, refused = {}, []
    for k, v in cues.items():
        try:
            visit.Visit(idle_s=0).set_cues({k: v})
        except ValueError:
            refused.append(f"{k}={v}")
            continue
        ok[k] = v
    return ok, refused


def cue_stems(value: str) -> tuple[str, ...]:
    """The folded word prefixes that show `value` was used: a known chip's own list; for free
    text its content words of four letters or more."""
    if value in _CUE_STEMS:
        return _CUE_STEMS[value]
    words = [w for w in _fold(value).split() if len(w) >= 4 and w not in _STOP]
    return tuple(words) or (_fold(value),)


def cue_used(value: str, texts: list[str]) -> bool:
    joined = " " + " ".join(_fold(t) for t in texts) + " "
    return any(f" {stem}" in joined for stem in cue_stems(value))


def coverage(cues: dict, texts: list[str]) -> tuple[list[str], list[str]]:
    """(used, unused) cue keys for the hat's `texts`."""
    used = [k for k, v in cues.items() if cue_used(v, texts)]
    return used, [k for k in cues if k not in used]


def repeats(texts: list[str], n: int = REPEAT_N) -> dict[str, list[int]]:
    """Phrases of `n` words or more that two or more of `texts` share: {phrase: [indexes]}.
    A phrase needs two words of four letters or more ("de la casa de" is not a repeat)."""
    folded = [_fold(t).split() for t in texts]
    grams: dict[tuple, set[int]] = {}
    for i, ws in enumerate(folded):
        for j in range(len(ws) - n + 1):
            g = tuple(ws[j:j + n])
            if sum(len(w) >= 4 and w not in _STOP for w in g) >= 2:
                grams.setdefault(g, set()).add(i)
    shared = {g for g, who in grams.items() if len(who) > 1}
    out: dict[str, list[int]] = {}
    for i, ws in enumerate(folded):           # runs of shared grams become one phrase
        j = 0
        while j <= len(ws) - n:
            if tuple(ws[j:j + n]) not in shared:
                j += 1
                continue
            k = j
            while k + 1 <= len(ws) - n and tuple(ws[k + 1:k + 1 + n]) in shared:
                k += 1
            phrase = " ".join(ws[j:k + n])
            if phrase not in out and not any(phrase in p for p in out):
                out[phrase] = sorted(x for x, w in enumerate(folded)
                                     if f" {phrase} " in " " + " ".join(w) + " ")
            j = k + n
    return {p: who for p, who in out.items() if len(who) > 1}


def run_visit(llm, cfg, visitor: dict, *, clock=None) -> dict:
    """One scripted visitor through the visit's steps; returns its record."""
    import time
    from fish_brain import reading, visit
    clock = clock or time.monotonic
    v = visit.Visit(cfg.visit.stages, idle_s=0, clock=clock, future=cfg.visit.future)
    first = visitor["badge"] or ""
    v.start(first)
    visit.begin_model(llm, cfg.visit.rules)
    turns, refused, cues = [], [], {}
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
            ok, bad = accepted_cues(value)
            refused += [r for r in bad if r not in refused]
            cues = dict(value)                  # what the operator lit, refused ones too
            v.set_cues(ok)
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
    said = [t["hat"] for t in turns if "sent" in t]
    used, unused = coverage(cues, said)
    return {"turns": turns, "house": v.house, "done": verdict, "skipped": skipped,
            "first": first, "refused": refused, "cues": cues, "used": used, "unused": unused,
            "verdict": next((t["hat"] for t in reversed(turns)
                             if "sent" in t and t["stage"] == v.stages and t["hat"]), ""),
            "problems": [] if v.house else ["no house at the verdict" if verdict
                                            else "the visit did not reach the verdict"]}


def place_of(cfg, visitor: dict) -> str:
    """The place word the act sends: the visitor's "lugar:", else FISH_PLACE's (with the
    free text for "otro", as fortune_run does)."""
    if visitor.get("place"):
        return visitor["place"]
    place = cfg.place
    return place.text.strip() if place.place == "otro" and place.text.strip() else place.place


def run_fortune(llm, cfg, visitor: dict, visit_rec: dict | None, *, seed: int = 0,
                now=None) -> dict:
    """The visitor's "fortuna:" block through the act's steps; returns its record. The
    reading is the model's, timed against the act's wait (cfg.fortune.reading_s)."""
    from fish_brain import fortune, fortune_run, visit
    deck = fortune.DECKS.get(cfg.fortune.deck)
    data: dict = {}
    answers = []
    reprompts = 0
    for qid, text in visitor["fortune"] or []:
        if (qid == "carta" and deck is None) or (qid == "taza" and not cfg.fortune.cup):
            answers.append({"q": qid, "you": text, "kind": "not asked (off)", "value": None})
            continue
        before = [a for a in answers if a["q"] == qid]
        # As the act: a question is asked again only after "none", once, within the budget.
        if before and (before[-1]["kind"] != "none" or len(before) > 1
                       or reprompts >= cfg.fortune.reprompts):
            answers.append({"q": qid, "you": text, "kind": "not asked again", "value": None})
            continue
        reprompts += bool(before)
        words = fortune.strip_notes(text)
        kind, value = fortune_run.parse_answer(qid, words, deck, data)
        answers.append({"q": qid, "you": text, "kind": kind, "value": value})
    told = [a["you"] for a in answers if a["q"] == "sueno" and a["you"].strip()
            and not a["kind"].startswith("not asked")]
    if told and "sueno" not in data:            # as no_answer does: a dream told, never clear
        data.update(sueno="otro", sueno_txt=visit.clean_cue_text(
            fortune.strip_notes(told[-1]), fortune_run.DREAM_TEXT_MAX))
    data["luna"] = fortune.moon_tonight(now)
    data["palabra"] = random.Random(seed).choice(fortune.MAGIC_WORDS)
    house = visit_rec["house"] if visit_rec else None
    nombre = visit_rec["first"] if visit_rec else ""
    f = fortune_run.fortune_of(data, nombre=nombre, lugar=place_of(cfg, visitor), casa=house)
    tag = fortune_run.reading_request(llm, cfg.fortune.rules, f, deck)
    raw = llm.reply(tag, remember=False)
    seconds = getattr(llm, "last_latency_s", 0.0)
    error = llm.last_error
    spoken, _house = visit.split_reply(raw or "")
    text = fortune_run.reading_result(raw)
    problems = [] if error else fortune.reading_problems(spoken)
    folded = " " + _fold(spoken) + " "
    problems += [f"death said plainly {w!r}" for w in _DEATH if f" {w} " in folded]
    if seconds > cfg.fortune.reading_s:
        problems.append(f"{seconds:.1f} s > {cfg.fortune.reading_s:g} s: would fall back "
                        f"to clips")
    cues = visit_rec["cues"] if visit_rec else {}
    used, unused = coverage(cues, [spoken])
    return {"answers": answers, "tag": tag, "reading": spoken, "said": text, "s": seconds,
            "error": error, "usage": getattr(llm, "last_usage", None), "problems": problems,
            "used": used, "unused": unused}


def _print_visit(i: int, profile: str, rec: dict) -> None:
    print(f"\n=== visitor {i} · {profile} ===")
    if rec["refused"]:
        print(f"  refused cues (not sent): {', '.join(rec['refused'])}")
    for t in rec["turns"]:
        flag = ("  !! " + ", ".join(t["problems"])) if t["problems"] else ""
        err = f"  !! {t['error']}" if t.get("error") else ""
        print(f"  you> {t['you']}")
        print(f"  [{t['stage']}] hat ({t['s']:.1f}s)> {t['hat']}{flag}{err}")
    end = f"CASA: {rec['house']}" if rec["house"] else "no house"
    more = f", {rec['skipped']} line(s) after the verdict not sent" if rec["skipped"] else ""
    probs = ("  !! " + "; ".join(rec["problems"])) if rec["problems"] else ""
    print(f"  -> {end}{more}{probs}")


def _print_fortune(rec: dict) -> None:
    print("  -- fortuna --")
    for a in rec["answers"]:
        shown = "" if a["value"] is None else f" {a['value']}"
        print(f"  {a['q']}> {a['you']}  -> {a['kind']}{shown}")
    print(f"  tag> {rec['tag']}")
    flag = ("  !! " + ", ".join(rec["problems"])) if rec["problems"] else ""
    err = f"  !! {rec['error']}" if rec.get("error") else ""
    print(f"  reading ({rec['s']:.1f}s, {len(rec['reading'].split())} words)> "
          f"{rec['reading']}{flag}{err}")


def _print_coverage(rec: dict, frec: dict | None) -> None:
    if not rec["cues"]:
        print("  cues: none lit")
        return
    lit = ", ".join(f"{k}={v}" for k, v in rec["cues"].items())
    line = (f"  cues ({lit}): visit used {len(rec['used'])}/{len(rec['cues'])}"
            f" [{', '.join(rec['used']) or '-'}]")
    if frec is not None:
        line += (f"; reading used {len(frec['used'])}/{len(rec['cues'])}"
                 f" [{', '.join(frec['used']) or '-'}]")
    print(line)


def _median(xs: list) -> str:
    return f"{statistics.median(xs):.0f}" if xs else "-"


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
    from fish_brain.llm import make_conversation

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
            llm = make_conversation(lcfg)
        except Exception as e:                  # a missing key: name the variable only
            print(f"can't start profile {name!r}: set {lcfg.api_key_env} in .env "
                  f"({type(e).__name__})", file=sys.stderr)
            return 1
        by_stage: dict[str, list[float]] = {}
        houses = problems = readings = clean = 0
        cost = 0.0
        verdicts, reading_texts, reply_words, reading_words = [], [], [], []
        for i, visitor in enumerate(visitors, args.only or 1):
            rec = run_visit(llm, cfg, visitor) if visitor["steps"] else None
            if rec is not None:
                _print_visit(i, name, rec)
                for t in rec["turns"]:
                    if "sent" in t:
                        by_stage.setdefault(f"stage {t['stage']}", []).append(t["s"])
                        cost += _cost(lcfg, t.get("usage"))
                        if t["hat"]:
                            reply_words.append(len(t["hat"].split()))
                    problems += bool(t["problems"] or t.get("error"))
                houses += bool(rec["house"])
                problems += bool(rec["problems"])
                verdicts.append((i, rec["verdict"]))
            else:
                print(f"\n=== visitor {i} · {name} ===")
            frec = None
            if visitor["fortune"] is not None:
                frec = run_fortune(llm, cfg, visitor, rec, seed=i)
                _print_fortune(frec)
                readings += 1
                clean += not (frec["problems"] or frec["error"])
                problems += bool(frec["problems"] or frec["error"])
                by_stage.setdefault("reading", []).append(frec["s"])
                cost += _cost(lcfg, frec.get("usage"))
                if frec["reading"]:
                    reading_texts.append((i, frec["reading"]))
                    reading_words.append(len(frec["reading"].split()))
            if rec is not None:
                _print_coverage(rec, frec)
        n_visits = sum(bool(v["steps"]) for v in visitors)
        print(f"\n### {name}: {houses} of {n_visits} visits with a house; {clean} of "
              f"{readings} readings clean and in time; {problems} problem(s); cost ${cost:.4f}")
        print(f"    words per reply: visit median {_median(reply_words)}, "
              f"reading median {_median(reading_words)}")
        for label, items in (("verdicts", verdicts), ("readings", reading_texts)):
            rep = repeats([t for _i, t in items])
            if rep:
                print(f"    repeated phrasing across {label}:")
                for phrase, who in sorted(rep.items(), key=lambda kv: -len(kv[1])):
                    print(f"      {phrase!r} in visitors {', '.join(str(items[w][0]) for w in who)}")
            else:
                print(f"    repeated phrasing across {label}: none")
        for stage in sorted(by_stage, key=lambda s: (s == "reading", s)):
            xs = by_stage[stage]
            print(f"    {stage}: median {statistics.median(xs):.1f} s, "
                  f"max {max(xs):.1f} s ({len(xs)} calls)")
        worst = max(worst, problems)
    return 1 if worst else 0


if __name__ == "__main__":
    raise SystemExit(main())
