"""The scripted visit in the turn loop (FISH_SHOW, ADR 0015): no model, no live voice.

    greeting + Q1 -> reaction + Q2 -> reaction + Q3 -> [two houses] + suspense + reason +
    house + future + fair line + farewell

Each stage is a list of canned phrases said back to back (`Speaker.say_sequence`), only from
WAVs rendered ahead. What the visitor said is matched against the question's options
(show.match_option); anything unclear gets the question once more, narrower, then a bridge
line and the next question: a visit never waits for an answer and never says an error. The
house comes from show.decide. Everything runs on the turn loop's thread.
"""
from __future__ import annotations

import time

from dataclasses import dataclass

from . import canned, cloud, debug, show, show_bank, voice_guard
from .show import ShowState


@dataclass
class ShowInput:
    """The operator's tap on the page (POST /show), an input item for the turn loop:
    `answer` an option of the open question, `force` a house now, `skip` to the next question."""
    action: str
    value: str = ""


class ShowRun:
    def __init__(self, convo):
        self.c = convo
        self.cfg = convo.cfg.show
        self.state = ShowState(self.cfg.state, seed=self.cfg.seed or None)
        if self.state.recovered:
            print("[show] the state file could not be read: a fresh one", flush=True)
        self.v: dict | None = None            # the open scripted visit
        self._model_failed_at: float | None = None
        self.force: str | None = None          # the operator's "Forzar casa" for this visit
        self._last: dict = {}                    # the last verdict, for the page

    # ---- which visit ----------------------------------------------------------------------
    def mode_now(self) -> tuple[str, str]:
        """("script" | "llm", why), decided at a visit's start."""
        mode = self.cfg.mode
        if mode == "script":
            return "script", "forced"
        if mode != "auto":
            return "llm", "off"
        if self.c.echo:
            return "script", "echo"
        if not cloud.is_online():
            return "script", "offline"
        key = self.c.cfg.llm.api_key_env
        if key and cloud.missing_keys({key}):
            return "script", "no key"
        if voice_guard.state() == voice_guard.TAINTED:
            return "script", "voice"
        if self._model_failed_at is not None and \
                time.monotonic() - self._model_failed_at < self.cfg.back_s:
            return "script", "model failed"
        return "llm", "online"

    @property
    def open(self) -> bool:
        return self.v is not None

    def model_failed(self) -> None:
        self._model_failed_at = time.monotonic()

    # ---- picking lines --------------------------------------------------------------------
    def _pick(self, slot: str) -> str:
        names = show_bank.pool_names(slot)
        ready = [n for n in names if canned.cached(n, self.c.cfg)]
        return self.state.pick(slot, ready or names)

    def _say(self, names: list[str]) -> bool:
        said = self.c.speaker.say_sequence(names)
        if not said:
            print(f"[show] the speaker was busy: {names} not said", flush=True)
        self.c._push_visit()                     # the page shows the question now open
        return said

    def view(self) -> dict:
        """For the operator's sheet: the open question and its options, what was heard last,
        why the script runs. Never sent to /status."""
        v = self.v
        out = {"mode": self.cfg.mode, "open": v is not None, "last": self._last}
        if v is not None:
            qid = v["qs"][v["i"]]
            out.update(n=v["n"], set=v["set"], qid=qid, q=v["i"] + 1, of=len(v["qs"]),
                       why=v["why"],
                       options=[{"id": o["id"], "label": show_bank.label(o["id"])}
                                for o in show_bank.question(qid)["options"]],
                       heard=[str(x) for x in v["heard"][-1]] if v["heard"] else [])
        return out

    def operator(self, item: ShowInput) -> bool:
        """The operator's tap. Ignored when no scripted visit is open."""
        if self.v is None:
            print(f"[show] operator {item.action} {item.value}: no scripted visit open", flush=True)
            return True
        print(f"[show] operator {item.action} {item.value}", flush=True)
        if item.action == "answer":
            return self.operator_answer(item.value)
        if item.action == "force" and item.value in show_bank.HOUSES:
            self.force = item.value
            return self._verdict([])
        if item.action == "skip":
            self.v["tries"] = 1                  # no second ask: the bridge and the next one
            return self.no_answer()
        return True

    # ---- a visit --------------------------------------------------------------------------
    def start(self, why: str, *, at_question: int = 0, greet: bool = True,
              lead: list[str] | None = None) -> bool:
        n = self.state.next_visit()
        set_id = show.question_set(n)
        visit = self.c.visit
        qs = [q["id"] for q in show_bank.SETS[set_id]]
        if visit is not None and visit.pending().get("edad") == "niño":
            qs = qs[:2]                        # small children: the two either/or questions
        at = min(max(at_question, 0), len(qs) - 1)
        self.v = {"n": n, "set": set_id, "qs": qs, "i": at, "answers": {}, "tries": 0,
                  "reprompts": 0, "pref": None, "vetoes": set(), "why": why, "heard": [],
                  "t0": time.monotonic()}
        self.force = None
        if visit is not None:
            visit.start("", self.c._clock())
            self.c._push_visit()
        clips = list(lead or []) + ([self._pick("greet")] if greet else [])
        clips.append(show_bank.prompt_name(qs[at]))
        print(f"[show] visit #{n} set {set_id} questions {','.join(qs)} why={why}", flush=True)
        debug.turn_set(trigger="show", show=f"#{n} {set_id} start ({why})")
        self._say(clips)
        return True

    def hand_over(self, stage: int, why: str) -> bool:
        """A model visit that failed mid-way goes on as the script, in the same voice: a bridge
        line, then the question that matches where the model was."""
        self.model_failed()
        print(f"[show] hand-over from the model at stage {stage}: {why}", flush=True)
        return self.start(f"hand-over: {why}", at_question=max(stage - 2, 0), greet=False,
                          lead=[self._pick("bridge")])

    def answer(self, text: str) -> bool:
        """What the visitor said for the open question ("" = nothing usable)."""
        v = self.v
        if v is None:
            return False
        qid = v["qs"][v["i"]]
        q = show_bank.question(qid)
        pref, vetoes = show.houses_in(text)
        v["vetoes"] |= vetoes
        if pref:
            v["pref"] = pref
            v["heard"].append((qid, text, "preference"))
            return self._verdict([])
        heard = show.match_option(q, text)
        v["heard"].append((qid, text, heard.kind, heard.option, heard.how))
        debug.turn_set(show=f"#{v['n']} {qid} {heard.kind} {heard.option or ''}")
        print(f"[show] #{v['n']} {qid} heard={text!r} -> {heard.kind} {heard.option or ''}"
              f" {heard.how}", flush=True)
        if heard.kind == "option":
            v["answers"][qid] = heard.option
            return self._next([show_bank.reaction_name(qid, heard.option)])
        if heard.kind == "not_sure":
            v["answers"][qid] = None
            return self._next([self._pick("nose")])
        return self.no_answer()

    def operator_answer(self, option: str) -> bool:
        v = self.v
        if v is None:
            return False
        qid = v["qs"][v["i"]]
        if option not in [o["id"] for o in show_bank.question(qid)["options"]]:
            return False
        v["answers"][qid] = option
        v["heard"].append((qid, "", "operator", option))
        return self._next([show_bank.reaction_name(qid, option)])

    def no_answer(self) -> bool:
        """Nothing usable for the open question: once more, narrower; then move on."""
        v = self.v
        if v is None:
            return False
        qid = v["qs"][v["i"]]
        if v["tries"] == 0 and v["reprompts"] < self.cfg.reprompts:
            v["tries"] += 1
            v["reprompts"] += 1
            return self._say([show_bank.reprompt_name(qid)]) or True
        v["answers"].setdefault(qid, None)
        return self._next([self._pick("bridge")])

    def _next(self, clips: list[str]) -> bool:
        v = self.v
        v["i"] += 1
        v["tries"] = 0
        if v["i"] < len(v["qs"]):
            clips.append(show_bank.prompt_name(v["qs"][v["i"]]))
            self._say(clips)
            return True
        return self._verdict(clips)

    def _verdict(self, lead: list[str]) -> bool:
        v = self.v
        visit = self.c.visit
        cues = visit.pending() if visit is not None else {}
        house, how = show.decide(v["answers"], cues, force=self.force, preference=v["pref"],
                                 vetoes=v["vetoes"], bag=self.state.house_bag)
        clips = list(lead)
        if how == "preference":
            clips.append(self._pick(f"pref_{house}"))
        else:
            if how.startswith("tie") and any(v["answers"].values()):
                clips.append(self._pick("tie"))
            clips.append(self._pick("suspense"))
        clips += [self._pick(f"reason_{house}"), self._pick(f"house_{house}"),
                  self._pick(f"future_{house}"), self._pick("fair"), self._pick("farewell")]
        name = show_bank.HOUSES[house]
        print(f"[show] visit #{v['n']} house={name} by={how} answers={v['answers']} "
              f"cues={cues} seed={self.state.seed[:6]}", flush=True)
        debug.emit("show", visit=v["n"], set=v["set"], answers=v["answers"], cues=cues,
                   house=name, how=how, why=v["why"], heard=[list(h) for h in v["heard"]],
                   clips=clips, seconds=round(time.monotonic() - v["t0"], 1))
        debug.turn_set(show=f"#{v['n']} {name} ({how})", outcome="show: verdict")
        self._last = {"n": v["n"], "house": name, "how": how}
        self._say(clips)
        self.v = None
        if visit is not None:
            visit.delivered(name, None, self.c._clock())
        self.c._push_visit()
        return True

    def close_quietly(self) -> None:
        """Something broke mid-visit: finish it kindly (a house, the farewell)."""
        if self.v is not None:
            try:
                self._verdict([self._pick("bridge")])
            except Exception as e:
                print(f"[show] could not close the visit: {e}", flush=True)
                self.v = None
