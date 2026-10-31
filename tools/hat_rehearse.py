#!/usr/bin/env python3
"""Rehearse the hat's visit and its fortune against the model, without a voice, a microphone
or motors.

    .venv/bin/python tools/hat_rehearse.py tools/hat_visitors.txt
    .venv/bin/python tools/hat_rehearse.py --profiles claude,luna tools/hat_visitors.txt
    .venv/bin/python tools/hat_rehearse.py --only 3 tools/hat_visitors.txt     # one visitor
    .venv/bin/python tools/hat_rehearse.py --only 3 --repeat 20 tools/hat_visitors.txt   # collapse check
    .venv/bin/python tools/hat_rehearse.py --log rehearsals rehearsals/real_visitors.txt  # keep the run

Runs each scripted visitor through the same steps as the turn loop (fish_brain/visit.py):
a new visit resets the model and attaches the visit's rules, the opener is seeded as the hat's
first turn, every visitor line is tagged "[ETAPA n/4] [PISTAS: ...]", the reply is split
from its "CASA:" line, and the pair is remembered as if spoken. A "fortuna:" block then runs
the same person's fortune through the act's own steps (fish_brain/fortune_run.py:
parse_answer, hat_draw, deal_seeds, fortune_of, reading_request, reading_result) with
tonight's moon, today's date and a magic word seeded by the visitor's number; the draws, the
seeds and the last readings' openings come from one in-memory state for the whole run, as the
act's state file carries them from visitor to visitor. FISH_PERSONA is forced to "hat". Keys come from .env and
are never printed.

Script: visitors separated by a blank line. In a block:
    # a comment
    gafete: Sofía                 the visit opens with "¿Tú eres Sofía?" (the badge)
    nombre: Alberto               the name the operator typed for the fortune (no badge)
    # then: …                     what the hat said then to the line above (tools/hat_records.py);
    # then reading: …             the reading said then; both only shown beside today's
    sin saludo                    no opener: the model does stage 1 itself (an idle start)
    lugar: casa                   the place for this visitor (else FISH_PLACE's)
    pistas: edad=adulto; color=azul   the operator's cues, from here on (keys: visit.CUE_ORDER);
                                  a value today's code refuses is reported, not sent
    anything else                 what the visitor says, one turn per line
    fortuna:                      from here on, the same person's fortune:
    fecha: Diecisiete de junio.   one answer per line, keyed by the question (fecha, sueno,
    sueno: Soñé con ...           deseo, carta, taza); a second line for the same question
    deseo: Venganza.              is the answer to its re-ask
    carta: Sí.                    a yes: the hat draws; a card's name: the visitor's; no: none
Without "gafete:" or "sin saludo" the visit opens with the canned greeting (New visitor).

Checks per reply: no tag spoken ("[", "CASA", "ETAPA", "PISTAS"), sentences, words, long
questions; per visit: a house at the verdict; per reading: why the act would refuse it
(fortune.reading_problems: empty or too long; no word list since ADR 0025), and a reading
slower than the act waits for it ("would fall back to clips"). Per profile, the readings'
variety (ADR 0026): distinct openings, readings that use a stale phrase the rules name. Per visitor, information
only: which cues show up in the visit's replies and in the reading. Per profile: phrases repeated across verdicts
and across readings, words per reply.
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
FORTUNE_QS = ("fecha", "sueno", "deseo", "carta", "taza")
_Q_ALIASES = {"sueño": "sueno", "fecha": "fecha", "sueno": "sueno", "deseo": "deseo",
              "carta": "carta", "taza": "taza"}
# The stale phrases FORTUNE_RULES names (folded); a reading that uses one is counted.
STALE = ("esta noche", "algo viejo", "no te asustes", "todo va a salir bien", "energia",
         "nueva etapa", "abundancia", "transformacion", "tu camino", "el universo", "salio derech",
         "gancho", "tu vision", "la verdad que pica", "tu verdad incomoda", "tu tarea",
         "los astros", "las estrellas", "el universo", "todo esta escrito", "mucho amor",
         "por ciento", "tu aviso:", "el sombrero")
OPENING_WORDS = 3               # readings that open with the same words count as one opening
QUESTION_WORDS = 10             # the rules' limit for one question ("¿…?")
_QUESTION = re.compile(r"¿([^?]*)\?")
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
        if line.startswith("# then reading:") and cur is not None:
            cur["then_reading"] = line.split(":", 1)[1].strip()
            continue
        if line.startswith("# then:") and cur is not None:
            cur["then"].append(line.split(":", 1)[1].strip())
            continue
        if line.startswith("#"):
            continue
        cur = cur or {"badge": None, "greet": True, "place": None, "steps": [], "fortune": None,
                      "name": "", "then": [], "then_reading": ""}
        low = line.lower()
        if cur["fortune"] is not None:
            key, sep, value = line.partition(":")
            qid = _Q_ALIASES.get(key.strip().lower())
            if not sep or qid is None:
                raise ValueError(f"a fortune line must be 'fecha|sueno|deseo|carta|taza: "
                                 f"...': {line!r}")
            cur["fortune"].append((qid, value.strip()))
        elif low in ("fortuna:", "fortuna"):
            cur["fortune"] = []
        elif low.startswith("gafete:"):
            cur["badge"] = line.split(":", 1)[1].strip()
        elif low.startswith("nombre:") and cur["fortune"] is None:
            cur["name"] = line.split(":", 1)[1].strip()
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
    if len(sentences) > (4 if verdict else 3):
        out.append(f"{len(sentences)} sentences")
    if words > (55 if verdict else 30):
        out.append(f"{words} words")
    for q in _QUESTION.findall(spoken):
        if len(q.split()) > QUESTION_WORDS:
            out.append(f"question of {len(q.split())} words")
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
        tagged, snap = v.prepare(value, place_of(cfg, visitor))
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
        if not v.first_name and stage <= 2:      # as the loop: the name the hat echoed
            v.first_name = visit.heard_name(value, spoken)
    verdict = v.done
    said = [t["hat"] for t in turns if "sent" in t]
    used, unused = coverage(cues, said)
    return {"turns": turns, "house": v.house, "done": verdict, "skipped": skipped,
            "first": v.first_name, "refused": refused, "cues": cues, "used": used, "unused": unused,
            "verdict": next((t["hat"] for t in reversed(turns)
                             if "sent" in t and t["stage"] == v.stages and t["hat"]), ""),
            "problems": [] if v.house else ["no house at the verdict" if verdict
                                            else "the visit did not reach the verdict"]}


def place_of(cfg, visitor: dict) -> str:
    """The place word the visit and the act send: the visitor's "lugar:", else FISH_PLACE's
    as the fish says it (visit.place_word)."""
    from fish_brain import visit
    if visitor.get("place"):
        return visitor["place"]
    return visit.place_word(cfg.place)


def run_fortune(llm, cfg, visitor: dict, visit_rec: dict | None, *, seed: int = 0,
                now=None, state=None, thinking: str | None = None) -> dict:
    """The visitor's "fortuna:" block through the act's steps; returns its record. The
    reading is the model's, timed against the act's wait (cfg.fortune.reading_s). `state` (a
    ShowState) carries the draws, the seeds and the last openings across visitors. The
    reading thinks as the act's does (cfg.fortune.thinking) unless `thinking` says otherwise."""
    from fish_brain import fortune, fortune_run, visit
    from fish_brain.show import ShowState
    state = state if state is not None else ShowState(None, seed=f"rehearse-{seed}")
    deck = fortune.DECKS.get(cfg.fortune.deck)
    data: dict = {}
    answers, heard = [], []
    # As the act: fortune_run.reask decides whether a question is asked again (an unclear
    # answer within the budget, a question back outside it); a line the act would not have
    # asked for is shown and skipped.
    st = {"tries": 0, "reprompts": 0, "asked_back": set()}
    current, more = None, False
    for qid, text in visitor["fortune"] or []:
        if (qid == "carta" and deck is None) or (qid == "taza" and not cfg.fortune.cup):
            answers.append({"q": qid, "you": text, "kind": "not asked (off)", "value": None})
            continue
        if qid == current and not more:
            answers.append({"q": qid, "you": text, "kind": "not asked again", "value": None})
            continue
        if qid != current:
            current, st["tries"] = qid, 0
        heard.append((qid, text))
        words = fortune.strip_notes(text)
        kind, value = fortune_run.parse_answer(qid, words, deck, data)
        if kind == "draw":                       # the model reads it: a reversed draw may come
            value = fortune_run.hat_draw(state, deck, data, reversible=True)
            if data.get("carta_reves"):
                value = f"{value} reversed"
        more = kind in ("none", "ask_back") and fortune_run.reask(kind, qid, st,
                                                                  cfg.fortune.reprompts)
        answers.append({"q": qid, "you": text, "kind": kind, "value": value})
    told = fortune_run.told_dream(heard)
    if told and "sueno" not in data:            # as no_answer does: a dream told, never clear
        data.update(sueno="otro", sueno_vago=True,
                    sueno_txt=visit.clean_cue_text(told, fortune_run.DREAM_TEXT_MAX))
    data["luna"] = fortune.moon_tonight(now)
    data["palabra"] = random.Random(seed).choice(fortune.MAGIC_WORDS)
    house = visit_rec["house"] if visit_rec else None
    # As the act: the typed name first, else the visit's (a badge, or the name it heard) when
    # its verdict carries over (a house).
    nombre = visitor.get("name", "") or (visit_rec["first"] if visit_rec and visit_rec.get("house")
                                         else "")
    cues = visit_rec["cues"] if visit_rec else {}
    seeds = fortune_run.deal_seeds(state, data, has=fortune_run.reading_has(data))
    recent = list(state.data.get("recent", []))[-fortune_run.FortuneRun.RECENT:]
    f = fortune_run.fortune_of(data, nombre=nombre, lugar=place_of(cfg, visitor), casa=house,
                               pistas=accepted_cues(cues)[0],   # as the act: refused ones never lit
                               seeds=seeds, hoy=fortune.today_words(now), evita=recent)
    tag = fortune_run.reading_request(llm, cfg.fortune.rules, f, deck,
                                      thinking=thinking or cfg.fortune.thinking)
    raw = llm.reply(tag, remember=False)
    seconds = getattr(llm, "last_latency_s", 0.0)
    error = llm.last_error
    spoken, _house = visit.split_reply(raw or "")
    text = fortune_run.reading_result(raw)
    problems = [] if error else fortune.reading_problems(spoken) + magic_word_problems(
        spoken, data["palabra"])
    if text and not error:                       # as the act: a said reading is remembered
        state.data["recent"] = (recent + [fortune.opening(text)])[-fortune_run.FortuneRun.RECENT:]
    used, unused = coverage(cues, [spoken])
    paper = ticket_preview(cfg, data, deck, nombre=nombre, place=visitor.get("place") or cfg.place.place,
                           reading=None if error else text, now=now)
    return {"answers": answers, "tag": tag, "reading": spoken, "said": text, "s": seconds,
            "error": error, "usage": getattr(llm, "last_usage", None), "problems": problems,
            "used": used, "unused": unused, "ticket": paper}


def magic_word_problems(spoken: str, word: str) -> list[str]:
    """The magic word said anywhere but its closing "tu palabra mágica es X" (as the
    visitor's name, 3 of 18 on 2026-10-31), or more than once."""
    said, w = _fold(spoken or ""), re.escape(_fold(word or ""))
    if not w:
        return []
    n = len(re.findall(rf"\b{w}\b", said))
    if n > 1 or (n == 1 and not re.search(rf"palabra magica es {w}\b", said)):
        return ["the magic word used outside its closing"]
    return []


def ticket_preview(cfg, data: dict, deck, *, nombre: str, place: str, reading: str | None,
                   now=None) -> str:
    """The paper the visitor would take home (fish_brain/ticket.py), as the 32 columns the mock
    printer shows: the act's own ticket_of with the reading as said (trimmed), or, when the
    model failed, the clips' ending the act falls back to."""
    from fish_brain import fortune, fortune_bank, ticket
    from fish_brain.fortune_run import FortuneRun
    words = list(fortune.MAGIC_WORDS)
    magic = (fortune_bank.pool_names("magic")[words.index(data["palabra"])]
             if data.get("palabra") in words else None)
    v = {"n": 0, "first": nombre, "deck": deck, "place": place if place in fortune.PLACES else "otro",
         "reading": reading, "magic": magic, "clips": [], "data": data}
    t = ticket.ticket_of(v, FortuneRun._said_data(v), phrases=cfg.canned.phrases, place=cfg.place,
                         now=now)
    return ticket.preview(ticket.layout(t))


class _Tee:
    """stdout to the terminal and to the run's log."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for s in self.streams:
            s.write(text)
        return len(text)

    def flush(self):
        for s in self.streams:
            s.flush()


def _git(*args: str) -> str:
    import subprocess
    try:
        return subprocess.run(["git", *args], cwd=Path(__file__).resolve().parent.parent,
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def log_header(script: Path, cfg, argv: list[str] | None, now=None) -> str:
    """What a run was: when, which commit (and whether the tree was dirty), which script and
    which rules (a short hash of each, so two logs can be told apart when the rules change)."""
    import hashlib
    from datetime import datetime, timezone
    now = now or datetime.now(timezone.utc)
    dirty = " + uncommitted changes" if _git("status", "--porcelain", "--", "fish_brain", "tools") else ""
    def h(text: str) -> str:
        return hashlib.sha256((text or "").encode()).hexdigest()[:8]
    args = " ".join(argv if argv is not None else sys.argv[1:])
    return (f"# hat_rehearse run {now.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"# commit {_git('rev-parse', '--short', 'HEAD') or '?'}{dirty}\n"
            f"# script {script} · args {args}\n"
            f"# rules: visit {h(cfg.visit.rules)} · fortune {h(cfg.fortune.rules)} · "
            f"reading thinking {cfg.fortune.thinking or 'the profile'}\n\n")


def open_log(folder: Path, script: Path, cfg, argv: list[str] | None):
    """A new log file under `folder` (made private), its header written."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{now.strftime('%Y%m%d-%H%M%S')}-{script.stem}.txt"
    f = open(path, "w", encoding="utf-8")
    os.chmod(path, 0o600)
    f.write(log_header(script, cfg, argv, now))
    print(f"[rehearse] logging to {path}", file=sys.stderr)
    return f


def _md_quote(text: str) -> str:
    return "\n".join("> " + line if line else ">" for line in (text or "").split("\n"))


def who(visitor: dict, rec: dict | None) -> str:
    """A name for the file and its title: the badge or the typed name, else the first word of
    the visitor's first line when it reads like a name ("Juan. Juan Delgado.", "Hola, soy Albert.")."""
    name = (rec or {}).get("first") or visitor.get("name") or ""
    if name:
        return name
    said = next((v for k, v in visitor.get("steps", []) if k == "say"), "")
    words = re.sub(r"^(hola,?\s+)?(soy|me llamo)\s+", "", said.strip(), flags=re.I).split()
    first = words[0].strip(".,;:!¡¿?") if words else ""
    return first if first[:1].isupper() and len(words) <= 3 else ""


def visitor_markdown(i: int, visitor: dict, rec: dict | None, frec: dict | None, header: str) -> str:
    """One visitor of a run as markdown: the place and cues, every line said, the hat's answer
    now beside the one it gave then (when the script has it), the fortune's answers, the tag,
    the reading now and then, and the ticket."""
    name = who(visitor, rec)
    out = [f"# Visitor {i}" + (f" · {name}" if name else ""), "",
           "\n".join(l.replace("# ", "", 1) for l in header.strip().splitlines()), ""]
    facts = [f"place: {visitor.get('place') or '(the setting)'}"]
    if rec and rec["cues"]:
        facts.append("cues: " + ", ".join(f"{k}={v}" for k, v in rec["cues"].items()))
    if rec:
        facts.append(f"house now: {rec['house'] or 'none'}" + ("" if rec["done"] else " (the visit did not reach the verdict)"))
    out += ["- " + f for f in facts] + [""]
    then = list(visitor.get("then") or [])
    if rec:
        out += ["## The visit", ""]
        said = 0
        for t in rec["turns"]:
            if t["you"].startswith("("):
                out += [f"**Hat** ({t['you'][1:-1]}): {t['hat']}", ""]
                continue
            out += [f"**Visitor:** {t['you']}", ""]
            label = "**Hat now**"
            if t.get("error"):
                label += f" · error: {t['error'].split(':')[0]}"
            out += [f"{label}: {t['hat']}", ""]
            if said < len(then) and (not out or not t.get("error")):
                out += [f"*Hat then:* {then[said]}", ""]
            if not t.get("error"):
                said += 1
            if t.get("problems"):
                out += [f"*checks:* {', '.join(t['problems'])}", ""]
    if frec:
        out += ["## The fortune", ""]
        for a in frec["answers"]:
            value = "" if a["value"] is None else f" → {a['value']}"
            out.append(f"- **{a['q']}:** {a['you']} ({a['kind']}{value})")
        out += ["", "**The tag:**", "", "```", frec["tag"], "```", ""]
        out += [f"**Reading now** ({len(frec['reading'].split())} words):", "",
                _md_quote(frec["reading"]), ""]
        if frec["said"] and frec["said"] != frec["reading"]:
            out += ["**As the act would say it** (trimmed to fit):", "", _md_quote(frec["said"]), ""]
        if frec.get("problems") or frec.get("error"):
            out += [f"*checks:* {', '.join(frec.get('problems') or [])} {frec.get('error') or ''}".rstrip(), ""]
        if visitor.get("then_reading"):
            out += ["**Reading then:**", "", _md_quote(visitor["then_reading"]), ""]
        if frec.get("ticket"):
            out += ["## The ticket", "", "```", frec["ticket"].rstrip("\n"), "```", ""]
    return "\n".join(out)


def write_markdown(folder: Path, header: str, runs: list) -> list[Path]:
    """One markdown file per visitor under `folder` (made private)."""
    import re as _re
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    paths = []
    for i, visitor, rec, frec in runs:
        name = who(visitor, rec)
        slug = _re.sub(r"[^a-z0-9]+", "-", _fold(name)).strip("-") or "visitante"
        path = folder / f"{i:02d}-{slug}.md"
        path.write_text(visitor_markdown(i, visitor, rec, frec, header), encoding="utf-8")
        os.chmod(path, 0o600)
        paths.append(path)
    return paths


def variety(readings: list[str]) -> str:
    """The readings' variety in one line: distinct openings (the first OPENING_WORDS words,
    folded) and how many readings use each stale phrase."""
    openings = {" ".join(_fold(r).split()[:OPENING_WORDS]) for r in readings}
    stale = {p: sum(bool(re.search(rf"\b{p}", _fold(r))) for r in readings) for p in STALE}
    used = ", ".join(f"{p!r} {n}" for p, n in stale.items() if n) or "none"
    return (f"variety: {len(openings)} distinct openings in {len(readings)} readings; "
            f"stale phrases: {used}")


def _print_visit(i: int, profile: str, rec: dict) -> None:
    print(f"\n=== visitor {i} · {profile} ===")
    if rec["refused"]:
        print(f"  refused cues (not sent): {', '.join(rec['refused'])}")
    for t in rec["turns"]:
        flag = ("  !! " + ", ".join(t["problems"])) if t["problems"] else ""
        err = f"  !! {t['error']}" if t.get("error") else ""
        print(f"  you> {t['you']}")
        print(f"  [{t['stage']}] hat> {t['hat']}{flag}{err}")
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
    print(f"  reading ({len(rec['reading'].split())} words)> "
          f"{rec['reading']}{flag}{err}")
    if rec.get("ticket"):
        print("  -- the ticket --")
        for line in rec["ticket"].rstrip("\n").split("\n"):
            print(f"  | {line}")


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
    ap.add_argument("--profiles", default="claude", help="comma-separated LLM profiles (default claude)")
    ap.add_argument("--only", type=int, help="run only visitor N (from 1)")
    ap.add_argument("--thinking", choices=("disabled", "adaptive", "between_tools"),
                    help="the thinking of every call, the visit's and the reading's (default: "
                         "the profile's for the visit, cfg.fortune.thinking for the reading)")
    ap.add_argument("--log", type=Path, metavar="DIR",
                    help="also write the run to DIR/<UTC time>-<script>.txt with a header naming "
                         "the commit and the rules (rehearsals/ is ignored by git)")
    ap.add_argument("--repeat", type=int, default=1,
                    help="run the visitors N times over (the collapse check: --only 3 --repeat 20)")
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
    header, log_file = "", None
    if args.log:
        log_file = open_log(args.log, args.script, cfg, argv)
        header = log_header(args.script, cfg, argv)
        sys.stdout = _Tee(sys.stdout, log_file)
    runs: list = []
    if not cfg.visit.rules:
        print("the hat persona has no visit rules", file=sys.stderr)
        return 2
    visitors = parse_script(args.script.read_text(encoding="utf-8"))
    if args.only:
        visitors = [visitors[args.only - 1]]
    visitors = visitors * max(1, args.repeat)
    worst = 0
    for name in [n.strip() for n in args.profiles.split(",") if n.strip()]:
        lcfg = LLMConfig(profile=name)
        if args.thinking:
            lcfg.thinking = args.thinking
        try:
            llm = make_conversation(lcfg)
        except Exception as e:                  # a missing key: name the variable only
            print(f"can't start profile {name!r}: set {lcfg.api_key_env} in .env "
                  f"({type(e).__name__})", file=sys.stderr)
            return 1
        from fish_brain.show import ShowState
        state = ShowState(None, seed=f"rehearse-{name}")   # one act state for the whole run
        houses = problems = readings = clean = 0
        cost = 0.0
        verdicts, reading_texts, reply_words, reading_words = [], [], [], []
        for i, visitor in enumerate(visitors, args.only or 1):
            rec = run_visit(llm, cfg, visitor) if visitor["steps"] else None
            if rec is not None:
                _print_visit(i, name, rec)
                for t in rec["turns"]:
                    if "sent" in t:
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
                frec = run_fortune(llm, cfg, visitor, rec, seed=i, state=state,
                                   thinking=args.thinking)
                _print_fortune(frec)
                readings += 1
                clean += not (frec["problems"] or frec["error"])
                problems += bool(frec["problems"] or frec["error"])
                cost += _cost(lcfg, frec.get("usage"))
                if frec["reading"]:
                    reading_texts.append((i, frec["reading"]))
                    reading_words.append(len(frec["reading"].split()))
            if rec is not None:
                _print_coverage(rec, frec)
            runs.append((i, visitor, rec, frec))
        n_visits = sum(bool(v["steps"]) for v in visitors)
        print(f"\n### {name}: {houses} of {n_visits} visits with a house; {clean} of "
              f"{readings} readings clean and in time; {problems} problem(s); cost ${cost:.4f}")
        print(f"    words per reply: visit median {_median(reply_words)}, "
              f"reading median {_median(reading_words)}")
        if reading_texts:
            print("    " + variety([t for _i, t in reading_texts]))
        for label, items in (("verdicts", verdicts), ("readings", reading_texts)):
            rep = repeats([t for _i, t in items])
            if rep:
                print(f"    repeated phrasing across {label}:")
                for phrase, who in sorted(rep.items(), key=lambda kv: -len(kv[1])):
                    print(f"      {phrase!r} in visitors {', '.join(str(items[w][0]) for w in who)}")
            else:
                print(f"    repeated phrasing across {label}: none")
        worst = max(worst, problems)
    if log_file is not None:
        folder = Path(log_file.name).with_suffix("")
        paths = write_markdown(folder, header, runs)
        print(f"[rehearse] {len(paths)} visitor file(s) in {folder}/", file=sys.stderr)
    return 1 if worst else 0


if __name__ == "__main__":
    raise SystemExit(main())
