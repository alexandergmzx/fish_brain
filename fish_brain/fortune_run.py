"""The fortune act in the turn loop ("la adivinación", ADR 0019, 0026): the scripted visit's
sibling for an adult audience, started from the page.

    intro + Q1 fecha -> reaction + Q2 sueño -> reaction + vision + Q3 deseo -> reaction
    + Q4 carta (deck on: a card named, or a yes and the hat draws, or a no) -> reaction
    + Q5 taza (cup on) -> reaction + suspense
    -> [clips] number + moon + magic word + closing
    -> [model] the model's reading of the [ADIVINACIÓN: …] tag, said live, then the closing

In model mode (the mode now, at each answer) an answer gets a short beat and a card its name
beat; the reaction it would have had is held, and said first if the reading falls to the clips.
The model's tag carries the act's seeds (a tema when no wish was heard, a gancho, a forma, the
day, the openings of the last readings), dealt before repeat from the act's state file.

Every answer comes by voice and is parsed by fortune.py; anything unclear gets the question
once more, narrower, then a bridge line and the next question (at most `reprompts` re-asks
an act). Every datum is optional: the act always reaches the closing and never says an error
line. The reading comes from the clips or, when the model can be trusted
(show_run.model_trusted), from the model: its job starts first, the suspense line covers it,
and a reading that is not clean within `reading_s` of the end of that line gives way to the
clips; one that is still running `suspense_more_s` after it gets one more suspense line. The dream is the one open question; its recording, like every other, is capped by
`FISH_PTT_MAX_S` alone (ADR 0020). Everything here runs on the turn loop's thread; the page's taps arrive as `FortuneInput` items through the inbox.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import canned, debug, fortune, fortune_bank, show, ticket
from .show import ShowState
from .show_run import model_trusted
from .visit import begin_model, clean_cue_text, place_word, split_reply

DREAM_TEXT_MAX = 120     # characters of the visitor's own words that reach the model
NAME_MAX = 20            # the typed first name, as the page sends it

_THEMES = {t.id: t for t in fortune.DREAM_THEMES}
_SHAPES = {s.id: s for s in fortune.CUP_SHAPES}


@dataclass
class FortuneInput:
    """The operator's tap on the page (POST /fortune), an input item for the turn loop:
    `start` the act (`value`: the typed first name), `skip` the open question, `end` it now."""
    action: str
    value: str = ""


def _not_sure(text: str) -> bool:
    """"No sé" and friends (show.NOT_SURE): an answer with no evidence, never asked again."""
    joined = " ".join(show.words(text))
    return any(re.search(rf"\b{p}\b", joined) for p in show.NOT_SURE)


# ---- the act's pure steps (shared with tools/hat_rehearse.py) ---------------------------------
def parse_answer(qid: str, words: str, deck: dict | None, data: dict) -> tuple[str, object]:
    """One answer (notes stripped) into `data`: (what was found, its id), ("not_sure", None)
    or ("none", None). At the card: ("card", n) for a card named (drawn by the visitor),
    ("draw", None) for a yes (the run draws), ("no_card", None) for a no. "No sé" is the
    bridge, except at the dream: "no me acuerdo" is a theme of its own (`nada`, a line that
    needs no content), so its parser decides."""
    if qid != "sueno" and _not_sure(words):
        return "not_sure", None
    if qid == "fecha":
        birth = fortune.parse_birth(words)
        if birth is not None:
            day, month = birth
            sid = fortune.sign_of(day, month)
            data.update(fecha=birth, signo=sid, numero=fortune.lucky_number(day, month))
            return "sign", sid
        sid = fortune.parse_sign(words)
        if sid is not None:
            data["signo"] = sid
            return "sign", sid
        return "none", None
    if qid == "sueno":
        theme = fortune.dream_theme(words)
        if theme is None:
            return "none", None
        data.update(sueno=theme, sueno_txt=clean_cue_text(words, DREAM_TEXT_MAX))
        return "theme", theme
    if qid == "deseo":
        wish = fortune.parse_wish(words)
        if wish is None:
            return "none", None
        data.update(deseo=wish, deseo_txt=clean_cue_text(words, fortune.WISH_TEXT_MAX))
        return "wish", wish
    if qid == "carta":
        n = fortune.parse_card(words, deck)
        if n is not None:
            data.update(carta=n, carta_de="visitante", carta_reves=fortune.said_reversed(words))
            return "card", n
        yes_no = fortune.parse_yes_no(words)
        if yes_no == "yes":
            return "draw", None
        if yes_no == "no":
            data["sin_carta"] = True
            return "no_card", None
        return "none", None
    if qid == "taza":
        shape = fortune.parse_shape(words)
        if shape is None:
            return "none", None
        data["taza"] = shape
        return "shape", shape
    return "none", None


def hat_draw(state, deck: dict, data: dict, *, reversible: bool) -> int:
    """The hat draws the card itself (a yes, no card named): every card of the deck once and
    the dark ones twice (fortune_bank.HAT_DRAW_EXTRA), dealt before repeat from `state` (a
    ShowState); reversed one draw in three, only when `reversible` (model mode: the clips read
    upright). Into `data`; returns the card's number."""
    did = deck.get("id", "tarot")
    names = [f"{c.n}" for c in deck["cards"]]
    names += [f"{n}_bis" for n in fortune_bank.HAT_DRAW_EXTRA.get(did, ())]
    n = int(state.pick(f"carta_{did}", names).split("_")[0])
    reves = reversible and state.pick("reves", list(fortune_bank.REVERSED_BAG)) == "cabeza"
    data.update(carta=n, carta_de="sombrero", carta_reves=reves)
    return n


def deal_seeds(state, data: dict, *, has: set) -> dict:
    """The model's seeds for one reading, dealt before repeat from `state`: a tema when no wish
    was heard, a gancho, a rito, a forma that fits the data `has` ("signo", "sueno", "carta")."""
    seeds: dict = {}
    if not data.get("deseo"):
        seeds["tema"] = state.pick("tema", list(fortune.WISH_IDS))
    i = int(state.pick("gancho", [f"{i:02d}" for i in range(len(fortune_bank.GANCHOS))]))
    seeds["gancho"] = fortune_bank.GANCHOS[i]
    i = int(state.pick("rito", [f"{i:02d}" for i in range(len(fortune_bank.RITOS))]))
    seeds["rito"] = fortune_bank.RITOS[i]
    have = has | {"deseo"}
    fit = [f"{i}" for i, (need, _t) in enumerate(fortune_bank.FORMAS) if need is None or need in have]
    seeds["forma"] = fortune_bank.FORMAS[int(state.pick("forma", fit))][1]
    return seeds


def fortune_of(data: dict, *, nombre: str = "", lugar: str = "",
               casa: str | None = None, pistas: dict | None = None,
               seeds: dict | None = None, hoy: str = "", evita=()) -> fortune.Fortune:
    """The act's data (parse_answer's dict, plus the moon and the magic word) as a Fortune;
    `pistas` are the operator's lit cues (visit.pending()), `seeds` deal_seeds' dict."""
    d, sd = data, seeds or {}
    return fortune.Fortune(nombre=nombre, lugar=lugar, casa=casa, pistas=dict(pistas or {}),
                           fecha=d.get("fecha"), signo=d.get("signo"), numero=d.get("numero"),
                           sueno=d.get("sueno"), sueno_txt=d.get("sueno_txt", ""),
                           deseo=d.get("deseo"), deseo_txt=d.get("deseo_txt", ""),
                           tema=sd.get("tema"), carta=d.get("carta"),
                           carta_de=d.get("carta_de", ""), carta_reves=bool(d.get("carta_reves")),
                           sin_carta=bool(d.get("sin_carta")), taza=d.get("taza"),
                           luna=d.get("luna"), palabra=d.get("palabra", ""), hoy=hoy,
                           gancho=sd.get("gancho", ""), rito=sd.get("rito", ""),
                           forma=sd.get("forma", ""),
                           evita=tuple(evita))


def reading_request(llm, rules: str, f: fortune.Fortune, deck: dict | None, *,
                    thinking: str = "") -> str:
    """The model set up for a reading (a fresh history: the data travel in the tag, the
    fortune's rules after the persona, `thinking` over the profile's until the next visitor's
    reset); returns the tag to send."""
    begin_model(llm, rules)
    llm.thinking = thinking or None
    return fortune.reading_tag(f, deck)


def reading_result(raw: str) -> str | None:
    """The model's reply as the reading to say, or None when it is empty or breaks the rules
    (fortune.reading_problems says why)."""
    spoken, _house = split_reply(raw or "")
    return fortune.clean_reading(spoken)


def _drop_wav(result) -> None:
    """The voice of a reading that is not said: its file goes."""
    wav = result[1] if result else None
    if wav is not None:
        Path(wav).unlink(missing_ok=True)


class FortuneRun:
    def __init__(self, convo):
        self.c = convo
        self.cfg = convo.cfg.fortune
        # Its own file: the act counter and the deal-before-repeat bags of its pools.
        self.state = ShowState(self.cfg.state, seed=convo.cfg.show.seed or None)
        if self.state.recovered:
            print("[fortune] the state file could not be read: a fresh one", flush=True)
        self.v: dict | None = None            # the open act
        self._last: dict = {}                 # the last reading or drop, for the page

    # ---- which reading ---------------------------------------------------------------------
    def mode_now(self) -> tuple[str, str]:
        """("llm" | "script", why): echo is the clips; with the show on, its word; else the
        model whenever it can be trusted right now."""
        if self.c.echo:
            return "script", "echo"
        show_run = self.c.show
        if show_run is not None:
            return show_run.mode_now()
        ok, why = model_trusted(self.c)
        return ("llm" if ok else "script"), why

    @property
    def open(self) -> bool:
        return self.v is not None

    def _deck(self) -> dict | None:
        return fortune.DECKS.get(self.cfg.deck)

    def _questions(self, deck: dict | None) -> list[str]:
        qs = ["fecha", "sueno", "deseo"]
        if deck is not None:
            qs.append("carta")
        if self.cfg.cup:
            qs.append("taza")
        return qs

    def lines_ready(self) -> bool:
        """The prompt clips of the questions the toggles ask are rendered. Without them the
        act cannot start: its lines are rendered at start-up, never at show time."""
        deck = self._deck()
        return all(canned.cached(fortune_bank.prompt_name(q, deck), self.c.cfg)
                   for q in self._questions(deck))

    # ---- picking lines ---------------------------------------------------------------------
    def _pick(self, slot: str) -> str | None:
        names = fortune_bank.pool_names(slot)
        ready = [n for n in names if canned.cached(n, self.c.cfg)]
        return self.state.pick(slot, ready or names)

    def _say(self, names: list, at=None) -> bool:
        """`at=(name, fn)`: `fn()` just before that clip plays (the ticket's gate). Passed
        only when set, so a speaker without it keeps the old call."""
        names = [n for n in names if n]
        if not names:
            said = False
        elif at is not None:
            said = self.c.speaker.say_sequence(names, at=at)
        else:
            said = self.c.speaker.say_sequence(names)
        if names and not said:
            print(f"[fortune] the speaker was busy: {names} not said", flush=True)
        if self.v is not None:
            self.v["last_s"] = self.c._clock()
            self.v["clips"] += names
        self.c._push_visit()                     # the page shows the question now open
        return said

    def _next_n(self) -> int:
        n = int(self.state.data.get("fortune", 0)) + 1
        self.state.data["fortune"] = n
        self.state.save()
        return n

    # ---- the page ----------------------------------------------------------------------------
    def view(self) -> dict:
        """For the operator's page: the open question, what was heard, the data so far in
        their said forms, the last reading. Never sent to /status."""
        v = self.v
        out = {"on": True, "ready": self.lines_ready(), "open": v is not None,
               "deck": self.cfg.deck, "cup": bool(self.cfg.cup),
               "place": self.c.cfg.place.place, "last": self._last}
        if v is not None:
            asking = v["stage"] == "ask" and v["i"] < len(v["qs"])
            qid = v["qs"][v["i"]] if asking else None
            heard = [fortune.strip_notes(t) for q, t in v["heard"] if q == qid] if asking else []
            out.update(n=v["n"], stage=v["stage"], q=min(v["i"] + 1, len(v["qs"])),
                       of=len(v["qs"]), qid=qid, tries=v["tries"],
                       question=fortune_bank.question_text(qid, v["deck"]) if asking else "",
                       heard=heard[-1] if heard else "", data=self._said_data(v),
                       first=v["first"], house=v["house"], why=v["why"])
        return out

    @staticmethod
    def _said_data(v: dict) -> dict:
        """The data found so far as the page and the record show them (said forms)."""
        d, deck = v["data"], v["deck"]
        out: dict = {}
        sign = fortune.SIGN_BY_ID.get(d.get("signo"))
        if sign is not None:
            out["signo"], out["elemento"] = sign.name, sign.element
        if d.get("numero"):
            out["numero"] = d["numero"]
        theme = _THEMES.get(d.get("sueno"))
        if theme is not None:
            out["sueno"] = theme.label
        wish = fortune.WISH_BY_ID.get(d.get("deseo"))
        if wish is not None:
            out["deseo"] = wish.label.lower()
        elif d.get("deseo"):
            out["deseo"] = d.get("deseo_txt") or d["deseo"]
        if d.get("carta") is not None and deck is not None:
            card = fortune.card_by_n(deck, d["carta"]).es
            if d.get("carta_reves"):
                card += ", de cabeza"
            if d.get("carta_de") == "sombrero":
                card += " (la sacó el sombrero)"
            out["carta"] = card
        elif d.get("sin_carta"):
            out["carta"] = "sin carta"
        shape = _SHAPES.get(d.get("taza"))
        if shape is not None:
            out["taza"] = shape.label
        if d.get("luna"):
            out["luna"] = d["luna"].replace("_", " ")
        if d.get("palabra"):
            out["palabra"] = d["palabra"]
        return out

    def operator(self, item: FortuneInput) -> bool:
        """The operator's tap. The loop always goes on."""
        print(f"[fortune] operator {item.action}" + (" (with a name)" if item.value else ""),
              flush=True)
        if item.action == "start":
            visit, now = self.c.visit, self.c._clock()
            if self.v is not None:
                print("[fortune] start: an act is already open", flush=True)
            elif visit is not None and not visit.needs_new(now):
                # The page was told the same (409 "visit open"); this is the loop's own check.
                print("[fortune] start refused: visit open", flush=True)
                self._last = {**self._last, "refused": "visit open"}
                self.c._push_visit()
            else:
                show_run = self.c.show
                if show_run is not None and show_run.open:
                    print("[fortune] the open scripted visit went quiet: let go", flush=True)
                    show_run.v = None
                self.start("operator", first=item.value)
            return True
        if self.v is None:
            print(f"[fortune] operator {item.action}: no act open", flush=True)
            return True
        if item.action == "skip" and self.v["stage"] == "ask":
            self.v["tries"] = 1                  # no second ask: the bridge and the next one
            self.no_answer()
        elif item.action == "end" and self.v["stage"] == "ask":
            self._ending([])
        return True

    # ---- an act --------------------------------------------------------------------------------
    def start(self, why: str, *, first: str = "") -> bool:
        """A new act. Refused while its lines are not rendered. The house act's name and
        house carry over when its verdict was given within `carry_s`."""
        if self.v is not None:
            print("[fortune] start: an act is already open", flush=True)
            return False
        if not self.lines_ready():
            print("[fortune] start refused: lines not ready (the question clips are still "
                  "rendering)", flush=True)
            self._last = {**self._last, "refused": "lines not ready"}
            self.c._push_visit()
            return False
        deck = self._deck()
        qs = self._questions(deck)
        place = self.c.cfg.place.place
        first = clean_cue_text(first, NAME_MAX)
        house = None
        visit, now = self.c.visit, self.c._clock()
        if visit is not None and visit.open and visit.done and visit.house:
            since = visit.last_s if visit.last_s is not None else visit.started_at
            if since is not None and now - since <= self.cfg.carry_s:
                house = visit.house
                first = first or clean_cue_text(visit.first_name, NAME_MAX)
        if visit is not None:
            # The house act's visitor: its cues lit again; anyone else: a new visitor's prune.
            visit.next_act(carry=house is not None, now=now)
        n = self._next_n()
        self.v = {"n": n, "qs": qs, "i": 0, "tries": 0, "reprompts": 0, "data": {}, "heard": [],
                  "why": why, "deck": deck, "place": place, "first": first, "house": house,
                  "stage": "ask", "mode": None, "mode_why": "", "clips": [], "reading": None,
                  "held": [], "seeds": {},
                  "t0": time.monotonic(), "last_s": now, "pistas": self._pistas()}
        self._last.pop("refused", None)
        self._probe_printer()
        letter = show.HOUSE_LETTERS.get(house) if house else None
        intro = self._pick(f"intro_{letter}") if letter else None
        clips = [intro or self._pick(f"intro_{place}"), fortune_bank.prompt_name(qs[0], deck)]
        print(f"[fortune] #{n} start ({why}): questions={','.join(qs)} place={place}"
              + (f" house={house}" if house else "") + (" named" if first else ""), flush=True)
        debug.turn_set(fortune=f"#{n} start ({why})")
        self._say(clips)
        return True

    def answer(self, text: str) -> bool:
        """What the visitor said for the open question ("" = nothing usable)."""
        v = self.v
        if v is None or v["stage"] != "ask":
            return False
        qid = v["qs"][v["i"]]
        text = text or ""
        v["heard"].append((qid, text))
        words = fortune.strip_notes(text)
        kind, value = parse_answer(qid, words, v["deck"], v["data"])
        beats = self.mode_now()[0] == "llm"      # model mode: a beat now, the meaning read once
        if kind == "draw":
            value = hat_draw(self.state, v["deck"], v["data"], reversible=beats)
        shown = "" if value is None else value
        if kind in ("card", "draw") and v["data"].get("carta_reves"):
            shown = f"{shown} reversed"
        debug.turn_set(fortune=f"#{v['n']} {qid} {kind} {shown}")
        print(f"[fortune] #{v['n']} {qid} heard={text!r} -> {kind} {shown}", flush=True)
        if kind == "not_sure":
            return self._next([self._pick("bridge")])
        if kind == "none":
            return self.no_answer()
        if kind == "no_card":
            return self._next([self._pick("sin_carta")])
        if kind == "wish" and value == "otro":   # a wish outside the four: no clip by name
            reaction = [self._pick("re_deseo_otro")]
        elif kind == "draw":
            reaction = [fortune_bank.reaction_name("carta", value, v["deck"])]
        else:
            reaction = [fortune_bank.reaction_name(qid, value, v["deck"])]
        if qid == "sueno":
            reaction.append(self._pick("vision"))   # a mentalist line that needs no content
        lead = [self._pick("barajo")] if kind == "draw" else []
        if not beats:
            return self._next(lead + reaction)
        if kind in ("card", "draw"):
            clips = lead + [fortune_bank.card_name_name(value, v["deck"])]
            if v["data"].get("carta_reves"):
                clips.append(fortune_bank.REVERSED_NAME)
            else:                                # an upright line would contradict "de cabeza"
                v["held"] += reaction
        else:
            clips = [self._pick("beat")]
            v["held"] += reaction
        return self._next(clips)

    def no_answer(self) -> bool:
        """Nothing usable for the open question: once more, narrower; then the bridge line
        and the next question. A dream that was told but never came clear is "otro"."""
        v = self.v
        if v is None or v["stage"] != "ask":
            return False
        qid = v["qs"][v["i"]]
        if v["tries"] == 0 and v["reprompts"] < self.cfg.reprompts:
            v["tries"] += 1
            v["reprompts"] += 1
            return self._say([fortune_bank.reprompt_name(qid, v["deck"])]) or True
        if qid == "sueno" and "sueno" not in v["data"]:
            told = [fortune.strip_notes(t) for q, t in v["heard"] if q == qid]
            told = [t for t in told if t.strip()]
            if told:
                v["data"].update(sueno="otro", sueno_txt=clean_cue_text(told[-1], DREAM_TEXT_MAX))
        return self._next([self._pick("bridge")])

    def _next(self, clips: list) -> bool:
        v = self.v
        v["i"] += 1
        v["tries"] = 0
        if v["i"] < len(v["qs"]):
            nxt = v["qs"][v["i"]]
            clips.append(fortune_bank.prompt_name(nxt, v["deck"]))
            self._say(clips)
            return True
        return self._ending(clips)

    # ---- the reading ---------------------------------------------------------------------------
    def _pistas(self) -> dict:
        """The lit cues now (the latest win), for the reading and the record."""
        visit = self.c.visit
        return visit.pending() if visit is not None else {}

    def _fortune(self) -> fortune.Fortune:
        v = self.v
        v["pistas"] = self._pistas()     # the record keeps what the reading was given
        d = v["data"]
        has = {k for k in ("signo", "sueno", "carta") if d.get(k) is not None}
        v["seeds"] = deal_seeds(self.state, d, has=has)
        return fortune_of(d, nombre=v["first"], lugar=place_word(self.c.cfg.place),
                          casa=v["house"], pistas=v["pistas"], seeds=v["seeds"],
                          hoy=fortune.today_words(), evita=self._recent())

    # ---- the last readings' openings (the model is told not to open like them) ---------------
    RECENT = 6

    def _recent(self) -> list[str]:
        return list(self.state.data.get("recent", []))[-self.RECENT:]

    def _remember(self, reading: str) -> None:
        recent = self._recent() + [fortune.opening(reading)]
        self.state.data["recent"] = recent[-self.RECENT:]
        self.state.save()

    def _ending(self, lead: list, *, clips_only: bool = False) -> bool:
        """The reading: the moon and the magic word join the data; the model's reading when
        it can be trusted and arrives clean in time, else the clips."""
        v = self.v
        v["stage"] = "reading"
        data = v["data"]
        data["luna"] = fortune.moon_tonight()
        magic = self._pick("magic")
        data["palabra"] = fortune_bank.MAGIC_WORD_OF.get(magic, "") if magic else ""
        v["magic"] = magic
        mode, why = ("script", "closing") if clips_only else self.mode_now()
        v["mode"], v["mode_why"] = mode, why
        self.c._push_visit()                     # the page: "Reading the future…"
        clips = list(lead) + [self._pick("suspense")]
        if mode == "llm":
            if self._model_reading(clips):       # the lead and the suspense line are said inside
                cierre = self._pick(f"cierre_{v['place']}")
                self._say([cierre], at=self._gate(v, cierre))
                return self._close("llm")
            clips = []
        return self._finish_clips(clips)

    def _finish_clips(self, lead: list) -> bool:
        """The scripted ending after `lead`: the number, the moon, the magic word and the
        closing, each only when the act has it."""
        v = self.v
        data = v["data"]
        clips = list(lead) + v.get("held", [])   # the reactions model mode held back
        v["held"] = []
        if data.get("numero"):
            clips.append(fortune_bank.num_name(data["numero"]))
        if data.get("luna"):
            clips.append(fortune_bank.moon_name(data["luna"]))
        if v.get("magic"):
            clips.append(v["magic"])
        cierre = self._pick(f"cierre_{v['place']}")
        clips.append(cierre)
        self._say(clips, at=self._gate(v, cierre))
        return self._close("clips")

    def _model_reading(self, lead: list) -> bool:
        """The model's reading: its job starts first, then the lead and the suspense line are
        said, then up to `reading_s` more is waited. True when it came clean and was said
        (and remembered); False, after the lead, when it did not: the clips take over, and
        the show (if on) counts a model failure. Never an error line."""
        from .conversation import TurnTimeout, _Job
        v = self.v
        job, tag, llm, mark = None, "", None, debug.seq()
        # In a voice turn the reading's voice is rendered by the same worker, while the lead
        # and the suspense line play: the turn's 12 s went on those, and a long reading
        # rendered after them ran out (2026-10-27).
        speaker, timing = self.c.speaker, {}
        ahead = self.c._wait is not None and hasattr(speaker, "synthesize")
        try:
            self.c._settle("llm")                # a stale job on the same model ends first
            llm = self.c.llm                     # the client is built here, on this thread
            tag = reading_request(llm, self.cfg.rules, self._fortune(), v["deck"],
                                  thinking=self.cfg.thinking)
            ask = llm.reply

            def work():
                raw = ask(tag, remember=False)
                text = None if llm.last_error else reading_result(raw)
                return raw, (speaker.synthesize(text, timing) if ahead and text else None)

            job = _Job("llm", work, discard=_drop_wav)
        except TurnTimeout:
            print("[fortune] the model is still busy with an older turn", flush=True)
        except Exception as e:
            print(f"[fortune] the model could not be asked: {type(e).__name__}: {e}", flush=True)
        self._say(lead)
        if job is None:
            self._model_failed("not asked")
            return False
        start = self.c._clock()
        deadline, more = start + self.cfg.reading_s, start + self.cfg.suspense_more_s
        while not job.done.is_set():
            now = self.c._clock()
            if more is not None and now >= more and now < deadline:
                more = None                      # once: a slow reading gets one more line
                self._say([self._pick("suspense_mas")])
                continue
            if now >= deadline:
                job.abandon()
                self.c._stale["llm"] = job       # the next turn waits for it, never asks twice
                debug.turn_adopt(mark)
                self._model_failed(f"timeout after {self.cfg.reading_s:g} s")
                return False
            self.c._wait_on(job.done, min((more or deadline) - now, deadline - now, 0.25))
        debug.turn_adopt(mark)                   # the worker's model record, to this turn
        if job.exc is not None or llm.last_error:
            _drop_wav(job.result)
            self._model_failed(f"error: {job.exc or llm.last_error}")
            return False
        raw, wav = job.result or ("", None)
        text = reading_result(raw or "")
        if not text:
            _drop_wav((raw, wav))
            self._model_failed("the reply was empty or broke the rules")
            return False
        print(f"fish> {text}", flush=True)
        debug.turn_set(reply=text)
        said = (speaker.perform(wav, text, timing) if wav is not None
                else self.c._speak_reply(text))
        if not said:
            self._model_failed("the speaker was busy")
            return False
        llm.remember(tag, raw)
        v["reading"] = text
        self._remember(text)
        return True

    def _model_failed(self, why: str) -> None:
        print(f"[fortune] the model's reading gave way to the clips: {why}", flush=True)
        self.v["mode_why"] = why
        if self.c.show is not None:
            self.c.show.model_failed()           # the next visits stay scripted a while

    # ---- the ticket (printer.py, the visitor takes it home) ---------------------------------------
    def _gate(self, v: dict, cierre: str | None):
        """The `at` of the closing line: the ticket goes to the printer as the hat starts
        saying it. None without a printer, so the call stays as it was."""
        if self.c.printer is None or not cierre:
            return None
        return cierre, lambda: self._ticket(v)

    def _ticket(self, v: dict) -> None:
        """The act's ticket to the printer, at most once an act (a fault can run the clips'
        ending again); with tickets off only kept for Reprint. The act must never be the
        problem: anything that fails here is one line."""
        p = self.c.printer
        if p is None or v.get("ticket"):
            return
        v["ticket"] = "error"                    # one try an act, whatever happens below
        try:
            t = ticket.ticket_of(v, self._said_data(v), phrases=self.c.cfg.canned.phrases,
                                 place=self.c.cfg.place, now=datetime.now())
            if not self.cfg.ticket:
                p.keep(t)
                v["ticket"] = "kept"
            elif p.submit(t):
                v["ticket"] = "queued"
            else:
                v["ticket"] = "refused"
                print(f"[fortune] act #{v['n']}: the printer did not take the ticket "
                      "(Reprint prints it)", flush=True)
        except Exception as e:
            print(f"[fortune] act #{v['n']}: no ticket: {type(e).__name__}: {e}", flush=True)

    def _probe_printer(self) -> None:
        """At the act's start: is the printer there (the page warns while the visitor is
        still answering)? Skipped by the printer when it was reached lately."""
        p = self.c.printer
        if p is None or not self.cfg.ticket:
            return
        try:
            p.probe()
        except Exception as e:
            print(f"[fortune] printer probe: {type(e).__name__}: {e}", flush=True)

    def _close(self, how: str) -> bool:
        v = self.v
        self._ticket(v)                          # the closing line never started: now
        data = self._said_data(v)
        seconds = round(time.monotonic() - v["t0"], 1)
        print(f"[fortune] act #{v['n']} reading={how} mode={v['mode']} ({v['mode_why']}) "
              f"data={data} seed={self.state.seed[:6]}", flush=True)
        debug.emit("fortune", n=v["n"], mode=v["mode"], why=v["mode_why"], how=how,
                   place=v["place"], data=data, heard=[list(h) for h in v["heard"]],
                   clips=list(v["clips"]), reading=v["reading"], house=v["house"],
                   first=v["first"], pistas=v.get("pistas", {}), seeds=v.get("seeds", {}),
                   seconds=seconds, ticket=v.get("ticket"))
        debug.turn_set(fortune=f"#{v['n']} reading ({how})", outcome=f"fortune: reading ({how})")
        self._last = {"n": v["n"], "mode": how, "why": v["mode_why"], "data": data}
        self.v = None
        self._close_cues(v)
        self.c._push_visit()
        return True

    def _close_cues(self, v: dict) -> None:
        """The act's cues are filed, cut at the end of its last line (never "now": a drop
        comes when the next visitor is already there, with chips tapped for them)."""
        visit = self.c.visit
        if visit is not None:
            visit.close(v["last_s"])

    # ---- ends that are not the reading --------------------------------------------------------
    def went_quiet(self, at: float) -> bool:
        """The hat was quiet longer than the show's idle time before the visitor spoke at
        `at`: whoever talks now is a new visitor, and the act is dropped."""
        v, idle = self.v, self.c.cfg.show.idle_s
        return v is not None and idle > 0 and at - v["last_s"] > idle

    def drop(self, why: str) -> None:
        """The act ends in silence: a new visitor, a typed name, a long quiet, a switch."""
        v = self.v
        if v is None:
            return
        self.v = None
        data = self._said_data(v)
        print(f"[fortune] act #{v['n']} dropped ({why}) at question "
              f"{min(v['i'] + 1, len(v['qs']))}/{len(v['qs'])}", flush=True)
        debug.emit("fortune", n=v["n"], dropped=why, place=v["place"], data=data,
                   heard=[list(h) for h in v["heard"]], clips=list(v["clips"]),
                   house=v["house"], first=v["first"], pistas=v.get("pistas", {}),
                   seconds=round(time.monotonic() - v["t0"], 1))
        debug.turn_set(fortune=f"#{v['n']} dropped ({why})", outcome=f"dropped ({why})")
        self._last = {"n": v["n"], "mode": "dropped", "why": why, "data": data}
        self._close_cues(v)
        self.c._push_visit()

    def fault(self, kind: str) -> None:
        """A turn failed with the act open: never an error line. Mid-question it counts as
        no answer; mid-reading the clips finish it."""
        v = self.v
        if v is None:
            return
        try:
            if v["stage"] == "reading":
                print(f"[fortune] {kind} during the reading: the clips finish it", flush=True)
                self._finish_clips([])
            else:
                self.no_answer()
        except Exception as e:                   # the act must never be the problem
            print(f"[fortune] fault while handling {kind}: {type(e).__name__}: {e}", flush=True)
            self.v = None

    def close_quietly(self) -> None:
        """Something broke mid-act: finish it kindly from the clips (a bridge, the ending)."""
        if self.v is None:
            return
        try:
            if self.v["stage"] == "ask":
                self._ending([self._pick("bridge")], clips_only=True)
            else:
                self._finish_clips([])
        except Exception as e:
            print(f"[fortune] could not close the act: {e}", flush=True)
            self.v = None
