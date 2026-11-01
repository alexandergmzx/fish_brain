"""La consulta (ADR 0032): one real question, one card, one reading, in the warm voice of
prompts/consulta.md, on its own model (FISH_CONSULTA_PROFILE, Sonnet). It lives in the fortune's
one slot (`FortuneRun.v`, `v["act"] == "consulta"`), so the two acts exclude each other and every
seam that calls the fortune reaches it. No clip can answer a question: without the model the act
does not start, and a reading that fails says so. A reading goes on paper; no house, no cues.

    parse_question(text) -> (kind, words)     parse_card_answer(words, deck, data) -> (kind, value)
    tag(question, data, deck, nombre) -> str  clean_reply(raw) -> str | None
"""
from __future__ import annotations

import re
import time

from datetime import datetime

from . import cloud, debug, fortune, fortune_bank, texts, ticket
from .fortune import _AGAIN_ONLY, _ASK_AGAIN, _ASK_ALONE, _ASK_NO_MARK, _ASK_SAID, _FILLERS, _LEADS, _RAW_WORD, _fold

QUESTION_MAX = 700          # characters kept, from the end: a long story ends in its question (estimate)
MAX_WORDS = 180             # Sonnet on "cinco oraciones": 121 to 160 (docs/results/2026-11-01-consulta-trial.md)
MAX_SENTENCES = 8
QUESTION_REASKS = 3
CARD_REASKS = 1
MINOR_REASKS = 2
QUIET_S = 300.0             # a real question takes pondering (estimate)
AFTER_S = 60.0              # words this soon after the reading are not a new visitor (estimate)
STALE_WAIT_S = 8.0          # an older reading still running: this long, then the failure line
WAIT_S = 20.0               # the reading, from the end of the lead: model about 4 s + voice about 9 s (estimates)
MORE_S = 7.0

# A question about the question, whole piece, folded.
_ABOUT_ASKING = re.compile(r"^(?:(?:que|cual|una)\b.*\bpregunt\w*|"
                           r"puedo preguntar(?: lo que sea| cualquier cosa| algo)?|"
                           r"(?:que|como) (?:digo|hago|pregunto|dices|dijiste)|"
                           r"a que te refieres.*|de que)$")
# What holds no question, whichever way it is put: every word of the answer is one of these.
_NOT_SURE_WORDS = frozenset("no se todavia aun que te le puedo pregunto preguntar decir decirte me ocurre nada".split())
_DECLINE_WORDS = frozenset("no mejor nada ninguna ninguno tengo quiero pregunta preguntas preguntar que gracias "
                           "ya me voy adios hasta luego".split())
_NEGATIVE = frozenset("no nada ninguna ninguno adios voy".split())
_UNCLEAR_WORDS = frozenset("hola buenas buenos noches tardes dias gracias muchas si claro que ok okay ya bueno listo "
                           "va sale a ver espera esperame dejame pensar pensarlo un momento una pregunta tengo quiero "
                           "te voy hacer hacerte preguntar preguntarte algo saber".split())
_MARKDOWN = re.compile(r"[*_#`]|^\s*(?:[-•]|\d+\.)\s+", re.M)
_OWN_CARD = re.compile(r"\b(?:ya la saque|(?:tengo|traigo) (?:una|mis|la)|dejame sacar\w*|esperame|a ver)\b")
# Thoth's names, said alone or as the card drawn, to the Rider-Waite number. Not deck aliases:
# "Quiero saber mi fortuna" and "que decida el universo" are not cards in the fortune act.
THOTH = {"arte": (14, "Arte"), "ajuste": (11, "Ajuste"), "lujuria": (8, "Lujuria"), "eon": (20, "Eón"),
         "aeon": (20, "Eón"), "universo": (21, "Universo"), "fortuna": (10, "La Fortuna")}
_REVERSED_WORDS = frozenset("de cabeza invertida invertido al reves".split())


def _is_protest(piece: str) -> tuple[bool, str]:
    """(this piece asks about the question, what is left of it). Never by the interrogative:
    "¿Qué piensa él?" is the question."""
    raw = _RAW_WORD.findall(piece)
    folded = [_fold(w) for w in raw]
    if folded and all(w in _ASK_ALONE for w in folded):
        return True, ""
    i = 0
    while i < len(folded) and folded[i] in _LEADS:
        i += 1
    raw, folded = raw[i:], folded[i:]
    if not folded:
        return False, ""
    joined = " ".join(folded)
    said = _ASK_SAID.match(joined)
    if said:
        rest = " ".join(raw[len(said.group(0).split()):])     # "No te oí, otra vez": all protest
        return True, _is_protest(rest)[1] if rest else ""
    if _ASK_AGAIN.match(joined) and set(folded) <= _AGAIN_ONLY:
        return True, ""
    if (len(folded) <= 6 and _ABOUT_ASKING.match(joined)
            or " ".join(w.lower() for w in raw).startswith("cómo que ")):   # accented: "Como que me engaña" tells
        return True, ""
    return False, piece


def parse_question(text: str) -> tuple[str, str]:
    """What was said to "¿qué me quieres preguntar?": ("question", the words), ("ask_back", ""),
    ("none", "") for nothing usable, ("not_sure", "") or ("decline", "")."""
    words = fortune.strip_notes(text or "")
    if all(w in _FILLERS and w not in _ASK_NO_MARK for w in fortune.tokens(words)):
        return "none", ""
    asked, kept = False, []
    for piece in fortune._pieces(words):
        protest, rest = _is_protest(piece)
        asked = asked or protest
        if rest:
            kept.append(rest)
    left = " ".join(kept)
    ws = [w for w in fortune.tokens(left) if w not in _FILLERS or w in ("si", "no")]
    if not ws:
        return ("ask_back" if asked else "none"), ""
    words_said = set(ws)
    if " ".join(ws).startswith(("no se", "todavia no se", "aun no se")) and words_said <= _NOT_SURE_WORDS:
        return "not_sure", ""
    if words_said <= _DECLINE_WORDS and words_said & _NEGATIVE:
        return "decline", ""
    if words_said <= _UNCLEAR_WORDS:
        return "none", ""
    left = left.strip()
    if len(left) > QUESTION_MAX:
        left = left[-QUESTION_MAX:].split(" ", 1)[-1]
    return "question", left


def _one_card(text: str, deck: dict) -> int | None:
    named = _thoth(text)
    return named[0] if named else fortune.parse_card(text, deck)


def _two_cards(words: str, deck: dict) -> bool:
    """Two different cards ("La Muerte, la trece" is one)."""
    parts = re.split(r"\by\b|\bo\b|,", fortune.strip_notes(words).lower())
    return len({n for n in (_one_card(p, deck) for p in parts) if n is not None}) >= 2


def _thoth(words: str) -> tuple[int, str] | None:
    """A Thoth name said alone, with a yes or a no ("Sí, Arte"), or as the card drawn."""
    ws = [w for w in fortune.tokens(words) if w not in fortune._CARRIERS and w not in _REVERSED_WORDS
          and w not in fortune._YES and w not in fortune._NO]
    named = [THOTH[w] for w in ws if w in THOTH]
    drawn = fortune._DRAWN.search(" ".join(fortune.tokens(words)))
    return named[0] if len(named) == 1 and (len(ws) == 1 or drawn) else None


def parse_card_answer(words: str, deck: dict, data: dict) -> tuple[str, object]:
    """("card", n) into `data`, ("draw", None) for anything that leaves it to the hat, ("minor", None),
    ("two", None), or ("ask_back" | "none", None). The fortune's parser, its yes, no and not sure
    all ending in the hat's draw: here a card is never declined."""
    from .fortune_run import parse_answer
    if fortune.names_minor(words):
        return "minor", None
    if fortune.several_cards(words) or _two_cards(words, deck):
        return "two", None
    said = fortune.tokens(words)
    if said and said[-1] == "no" and fortune.parse_card(words, deck) is not None:
        return "none", None                      # "La Muerte no": that card is the one refused
    found: dict = {}
    kind, value = parse_answer("carta", words, deck, found)
    if kind == "card":
        data.update(found)
        return kind, value
    named = _thoth(words)
    if named:
        data.update(carta=named[0], carta_de="visitante", carta_reves=fortune.said_reversed(words),
                    carta_thoth=named[1])
        return "card", named[0]
    joined = " ".join(said)
    if _OWN_CARD.search(joined) and "no tengo" not in joined:
        return "none", None                      # holding a card of their own: which one?
    return ("draw", None) if kind in ("draw", "no_card", "not_sure") else (kind, None)


def tag(question: str, data: dict, deck: dict, nombre: str = "") -> str:
    """The line the model gets. Only the question and the card: no sign, moon, seeds or cues."""
    how = ["de cabeza"] if data.get("carta_reves") else []
    how.append("la saqué yo" if data.get("carta_de") == "sombrero" else "la sacó de su baraja")
    if data.get("carta_thoth"):
        how.append(f"la llamó {data['carta_thoth']}")
    parts = [f"nombre={nombre}"] if nombre else []
    parts += [f'pregunta="{fortune._quoted(question)}"',
              f"carta={fortune.card_by_n(deck, data['carta']).said} ({'; '.join(how)})"]
    return "[CONSULTA: " + "; ".join(parts) + "] Lee la carta para esa pregunta."


def clean_reply(raw: str) -> str | None:
    """The reading fit to be said, or None: no markdown (it reaches the voice), one paragraph, no
    unterminated last fragment (a reply cut by its tokens), no closing question (nobody is there
    to answer it: the act is over), then the length. Not `split_reply`: its CASA line means
    nothing here, and "Casa:" could open a line about a house."""
    text = " ".join(fortune.strip_notes(_MARKDOWN.sub("", raw or "")).split())
    parts = [p.strip() for p in re.split(r"(?<=[.!?…])\s+", text) if p.strip()]
    if len(parts) > 1 and parts[-1].rstrip("\"'”»)")[-1:] not in (".", "!", "?", "…"):
        parts.pop()
    while len(parts) > 1 and "?" in parts[-1].rstrip("\"'”»)")[-2:]:
        parts.pop()
    return fortune.clean_reading(" ".join(parts), max_words=MAX_WORDS, max_sentences=MAX_SENTENCES)


class Consulta:
    def __init__(self, run):
        self.run = run
        self._llm = None
        self._job = None                  # a reading given up on: never asked twice at once
        self._after_until: float | None = None
        self._took_turn = False           # this turn was the act's: the house visit's clock stays

    def take_turn(self) -> bool:
        """Whether this turn was the act's (once). A visitor here is not the open visit's."""
        took, self._took_turn = self._took_turn, False
        return took

    @property
    def c(self):
        return self.run.c

    @property
    def llm(self):
        if self._llm is None:
            from .config import LLMConfig
            from .llm import make_conversation
            self._llm = make_conversation(LLMConfig(profile=self.run.cfg.consulta_profile))
        return self._llm

    def lines_ready(self) -> bool:
        from . import canned
        return all(canned.cached(fortune_bank.prompt_name(q), self.c.cfg) for q in ("consulta", "consulta_carta"))

    def refusal(self) -> str | None:
        """Why the act cannot start now, or None. No clip can answer a question, so unlike the
        fortune it has no scripted mode."""
        from .config import LLMConfig
        from .show_run import model_trusted
        if not self.lines_ready():
            return "lines not ready"
        show = self.c.show
        if self.c.cfg.show.mode == "script" and not (show is not None and self.run.cfg.model):
            return "scripted show"
        ok, why = show.model_ok() if show is not None else model_trusted(self.c)
        if not ok and why != "no key":
            return why
        key = LLMConfig(profile=self.run.cfg.consulta_profile).api_key_env
        if key and cloud.missing_keys({key}):
            return "no key"
        return None

    # ---- the act ---------------------------------------------------------------------------
    def start(self, why: str, *, first: str = "") -> bool:
        run = self.run
        if run.v is not None:
            print("[consulta] start: an act is already open", flush=True)
            return False
        refused = self.refusal()
        if refused:
            print(f"[consulta] start refused: {refused}", flush=True)
            run._last = {**run._last, "refused": refused}
            self.c._push_visit()
            return False
        from .fortune_run import NAME_MAX, clean_cue_text
        self._after_until = None
        n = int(run.state.data.get("consulta", 0)) + 1
        run.state.data["consulta"] = n
        run.state.save()
        run.v = {"act": "consulta", "n": n, "qs": ["consulta", "consulta_carta"], "i": 0, "tries": 0, "reprompts": 0,
                 "minors": 0, "asked_back": set(), "data": {}, "heard": [], "said": "", "asked": [],
                 "why": why, "deck": fortune.DECKS["tarot"], "place": self.c.cfg.place.place,
                 "first": clean_cue_text(first, NAME_MAX), "house": None, "stage": "ask", "mode": None, "mode_why": "",
                 "clips": [], "reading": None, "pregunta": "", "t0": time.monotonic(), "last_s": self.c._clock(),
                 "quiet_s": QUIET_S}
        run._last.pop("refused", None)
        run._probe_printer()
        self._took_turn = True
        print(f"[consulta] #{n} start ({why})", flush=True)
        debug.turn_set(fortune=f"#{n} consulta start ({why})")
        run._say([fortune_bank.prompt_name("consulta")])
        return True

    def operator(self, item) -> bool:
        v = self.run.v
        if v["stage"] != "ask":
            return True
        if item.action == "skip":
            if v["i"] == 0:
                self._end("sin pregunta", "consulta_sin_pregunta")
            else:
                self._draw()
        elif item.action == "end":
            self._end("ended", "consulta_fin")
        return True

    def answer(self, text: str) -> bool:
        run, v = self.run, self.run.v
        if v["stage"] != "ask":
            return False
        self._took_turn = True
        qid = v["qs"][v["i"]]
        v["heard"].append((qid, text or ""))
        words = fortune.strip_notes(text or "")
        if v["i"] == 0:
            kind, value = parse_question(words)
        else:
            kind, value = parse_card_answer(words, v["deck"], v["data"])
        debug.turn_set(fortune=f"#{v['n']} consulta {qid} {kind}")
        print(f"[consulta] #{v['n']} {qid} heard={text!r} -> {kind}", flush=True)
        if v["i"] == 0:
            return self._on_question(kind, value)
        return self._on_card(kind, value)

    def _on_question(self, kind: str, words: str) -> bool:
        run, v = self.run, self.run.v
        if kind == "question":
            v["pregunta"] = words
            v["i"], v["tries"] = 1, 0
            return run._say([fortune_bank.prompt_name("consulta_carta")]) or True
        if kind == "decline" or v["reprompts"] >= QUESTION_REASKS:
            return self._end("sin pregunta", "consulta_sin_pregunta")
        v["reprompts"] += 1
        return run._say([fortune_bank.reprompt_name("consulta")]) or True

    def _on_card(self, kind: str, value) -> bool:
        run, v = self.run, self.run.v
        if kind == "card":
            return self._read([])
        if kind == "draw":
            return self._draw()
        if kind in ("minor", "two") and v["minors"] < MINOR_REASKS:
            v["minors"] += 1
            return run._say([run._pick("consulta_menor" if kind == "minor" else "consulta_una")]) or True
        if kind in ("ask_back", "none") and v["tries"] < CARD_REASKS:
            v["tries"] += 1
            return run._say([fortune_bank.reprompt_name("consulta_carta")]) or True
        return self._draw()

    def _draw(self) -> bool:
        """The hat draws, fair and upright: every card once, from a bag of its own; the fortune's
        draw counts the dark cards twice and turns one in three."""
        run, v = self.run, self.run.v
        n = int(run.state.pick("consulta_carta", [str(c.n) for c in v["deck"]["cards"]]))
        v["data"].update(carta=n, carta_de="sombrero", carta_reves=False)
        return self._read([run._pick("consulta_saco")])

    # ---- the reading -------------------------------------------------------------------------
    def _read(self, lead: list) -> bool:
        """Job first, then the lead and the suspense line, then up to WAIT_S more with one cover
        line. A failure says so; it never poisons the show or the fortune. Its own loop, not
        FortuneRun._model_reading: another client, another stale job, the voice rendered ahead on
        every path, nothing remembered."""
        from .conversation import _Job
        from .fortune_run import _drop_wav
        run, v, c = self.run, self.run.v, self.c
        v["stage"], v["mode"] = "reading", "llm"
        c._push_visit()
        lead = list(lead) + [run._pick("consulta_suspense")]
        if self._job is not None and not c._wait_on(self._job.done, STALE_WAIT_S) and not self._job.done.is_set():
            return self._failed(lead, "an older reading is still running")
        self._job = None
        speaker, timing = c.speaker, {}
        try:
            rules = texts.rules("consulta.md")
        except Exception as e:
            return self._failed(lead, f"not asked: {type(e).__name__}: {e}")
        line = tag(v["pregunta"], v["data"], v["deck"], v["first"])

        def work():
            llm = self.llm                    # here: the SDK's first import took 7 to 17 s on the board
            llm.reset()
            llm.extra_rules = rules
            llm.thinking = run.cfg.consulta_thinking or None
            raw = llm.reply(line, remember=False)
            if llm.last_error:
                raise RuntimeError(llm.last_error)
            text = clean_reply(raw)
            wav = speaker.synthesize(text, timing) if text and hasattr(speaker, "synthesize") else None
            return raw, text, wav

        mark = debug.seq()
        job = _Job("consulta", work, discard=lambda r: _drop_wav((None, r[2])) if r else None)
        try:
            run._say(lead)
        except Exception:                        # the turn's fault path closes the act
            job.abandon()
            self._job = job
            raise
        start = c._clock()
        deadline, more = start + WAIT_S, start + MORE_S
        while not job.done.is_set():
            now = c._clock()
            if more is not None and now >= more and now < deadline:
                more = None
                try:
                    run._say([run._pick("consulta_mas")])
                except Exception:
                    job.abandon()
                    self._job = job
                    raise
                continue
            if now >= deadline:
                job.abandon()
                self._job = job
                debug.turn_adopt(mark)
                return self._failed([], f"timeout after {WAIT_S:g} s")
            c._wait_on(job.done, min((more or deadline) - now, deadline - now, 0.25))
        debug.turn_adopt(mark)                   # the worker's model record, to this turn
        if job.exc is not None:
            return self._failed([], f"error: {job.exc}")
        raw, text, wav = job.result
        if not text:
            return self._failed([], "the reply was empty or too long")
        print(f"fish> {text}", flush=True)
        debug.turn_set(reply=text)
        said = (speaker.perform(wav, text, timing, wait_s=5.0) if wav is not None
                else speaker.speak(text))
        if not said:
            return self._failed([], "the speaker was busy")
        v["reading"] = text
        v["last_s"] = c._clock()
        return self._close("reading", [run._pick("consulta_cierre")])

    def _failed(self, lead: list, why: str) -> bool:
        print(f"[consulta] the reading failed: {why}", flush=True)
        self.run.v["mode_why"] = why
        return self._close("failed", list(lead) + [self.run._pick("consulta_falla")])

    def _end(self, how: str, slot: str) -> bool:
        return self._close(how, [self.run._pick(slot)])

    def _close(self, how: str, clips: list) -> bool:
        """No `visit.close` (it would overwrite the cues the fortune relights). The ticket goes
        as the closing line starts, or now when there is none."""
        run, v = self.run, self.run.v
        printer = self.c.printer is not None and how == "reading"
        if printer and clips:
            run._say(clips, at=(clips[-1], lambda: self._ticket(v)))
        else:
            run._say(clips)
        if printer:
            self._ticket(v)
        data = run._said_data(v)
        debug.emit("consulta", n=v["n"], how=how, why=v["mode_why"], data=data, pregunta=v["pregunta"],
                   heard=[list(h) for h in v["heard"]], clips=list(v["clips"]), reading=v["reading"],
                   first=v["first"], ticket=v.get("ticket"), seconds=round(time.monotonic() - v["t0"], 1))
        debug.turn_set(fortune=f"#{v['n']} consulta ({how})", outcome=f"consulta: {how}")
        print(f"[consulta] act #{v['n']} {how} data={data}", flush=True)
        run._last = {"act": "consulta", "n": v["n"], "mode": how, "why": v["mode_why"], "data": data}
        run.v = None
        self._after_until = self.c._clock() + AFTER_S if how == "reading" else None
        self.c._push_visit()
        return True

    def _ticket(self, v: dict) -> None:
        """Once an act; with tickets off only kept for Reprint. Never the act's problem."""
        p = self.c.printer
        if p is None or v.get("ticket") or not v["reading"]:
            return
        v["ticket"] = "error"
        try:
            t = ticket.consulta_ticket(v["n"], v["first"], v["deck"], v["data"]["carta"], bool(v["data"].get("carta_reves")),
                                       v["pregunta"], v["reading"], place=ticket.place_said(v["place"], self.c.cfg.place),
                                       now=datetime.now())
            if not self.run.cfg.ticket:
                p.keep(t)
                v["ticket"] = "kept"
            elif p.submit(t):
                v["ticket"] = "queued"
            else:
                v["ticket"] = "refused"
                print(f"[consulta] #{v['n']}: the printer did not take the ticket (Reprint prints it)", flush=True)
        except Exception as e:
            print(f"[consulta] #{v['n']}: no ticket: {type(e).__name__}: {e}", flush=True)

    def drop(self, why: str) -> None:
        run, v = self.run, self.run.v
        run.v = None
        self._after_until = None
        data = run._said_data(v)
        print(f"[consulta] act #{v['n']} dropped ({why})", flush=True)
        debug.emit("consulta", n=v["n"], dropped=why, data=data, pregunta=v["pregunta"],
                   heard=[list(h) for h in v["heard"]], clips=list(v["clips"]), first=v["first"],
                   seconds=round(time.monotonic() - v["t0"], 1))
        debug.turn_set(fortune=f"#{v['n']} consulta dropped ({why})", outcome=f"dropped ({why})")
        run._last = {"act": "consulta", "n": v["n"], "mode": "dropped", "why": why, "data": data}
        self.c._push_visit()

    def fault(self, kind: str) -> None:
        """A turn failed with the act open. A reading already said only closes; never an error line."""
        run, v = self.run, self.run.v
        try:
            if v["stage"] == "reading":
                if v["reading"]:
                    self._close("reading", [])
                else:
                    self._failed([], kind)
            elif v["i"] == 0:
                self._on_question("none", "")
            else:
                self._on_card("none", None)
        except Exception as e:                   # the act must never be the problem
            print(f"[consulta] fault while handling {kind}: {type(e).__name__}: {e}", flush=True)
            run.v = None

    # ---- after the reading -------------------------------------------------------------------
    def forget(self) -> None:
        self._after_until = None

    def after(self, user: str, at: float) -> bool:
        """Words right after a reading ("Gracias", "¿Y qué más?") get one closing line; they must
        not start a house act at someone who just asked about their life."""
        if not (user or "").strip():
            return False                         # a bumped button keeps the window
        until, self._after_until = self._after_until, None
        if until is None or at > until:
            return False
        self._took_turn = True
        debug.turn_set(fortune="consulta: words after the reading")
        self.run._say([self.run._pick("consulta_despues")])
        return True
