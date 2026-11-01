"""La calaverita, the act (ADR 0034): after a House verdict the operator taps the skull and the hat
composes three stanzas from what the visit knows, says them and prints them.

It asks the visitor nothing, so it is one blocking call on the turn loop's thread and nothing stays
open between turns. It never touches the visit's state: the fortune carries name, house and cues as
if it had not run. The model's job starts first and the clips play over the wait; anything that goes
wrong ends in the house's rhymed clip, never an error line. Only "not asked", a timeout before the
reply and a real model error tell the show the model is down: a refusal, a bad poem, a slow voice or
a busy speaker say nothing about the next visit."""
from __future__ import annotations

import importlib
import os
import threading
import time
import traceback
from datetime import datetime

from . import calaverita, canned, debug, show, ticket
from .fortune_run import _drop_wav
from .show_run import model_trusted
from .visit import clean_cue_text, place_word


class CalaveritaRun:
    def __init__(self, fortune_run):
        self.f = fortune_run
        self.c = fortune_run.c
        self.cfg = fortune_run.cfg
        self.busy = False
        self._last: dict = {}                 # the last verse, for the page (this visit's only)
        self._own_llms: list = []             # the act's own model, one client a version
        self._own_stale = None                # its job given up on, still running
        self._warm()

    # ---- may it start ----------------------------------------------------------------------------
    def _lines_ready(self, letter: str) -> bool:
        """Every clip the act can say. An unrendered clip is skipped in silence and still counts
        as said, so a missing one would consume the verse and fire the ticket."""
        names = [n for slot in ("lead", "suspense", "suspense_mas", "cierre")
                 for n in calaverita.pool_names(slot)] + calaverita.fallback_names(letter)
        return all(canned.cached(n, self.c.cfg) for n in names)

    def refusal(self, now: float | None = None) -> str | None:
        """Why a tap now would be refused; None when it may start. Any thread."""
        visit = self.c.visit
        if self.f.open:
            return "act open"
        letter = show.HOUSE_LETTERS.get(visit.house) if visit is not None else None
        since = visit.since_verdict(self.c._clock() if now is None else now) if letter else None
        if since is None:
            return "no house"
        if since > self.cfg.carry_s:
            return "too late"
        if not self._lines_ready(letter):
            return "lines not ready"
        return None

    def view(self) -> dict:
        """For the operator's page, inside the fortune's view."""
        why = self.refusal()
        visit = self.c.visit
        same = visit is not None and self._last.get("visit") == visit.n
        return {"lit": why is None and not self.busy, "why": why, "busy": self.busy,
                "first": visit.first_name if visit is not None and why is None else "",
                "last": self._last if same else None}

    # ---- which model -------------------------------------------------------------------------------
    def _own_profile(self) -> str:
        """The act's own profile, even when the visit runs on the same one: the versions need a
        client each. "" = the visit's model (`main`, or no key)."""
        from .config import LLM_PROFILES
        name = self.cfg.calaverita_profile
        if name not in LLM_PROFILES:
            return ""
        return name if os.environ.get(LLM_PROFILES[name]["api_key_env"], "").strip() else ""

    def _warm(self) -> None:
        """The SDK's first import took 7.0 and 17.4 s on the board: at start-up, in the background,
        so the first tap does not spend its wait on it."""
        from .config import LLM_PROFILES
        own = self._own_profile()
        if own and LLM_PROFILES[own].get("provider") == "anthropic":
            threading.Thread(target=lambda: importlib.import_module("anthropic"),
                             name="calaverita-warm", daemon=True).start()

    def _clients(self, own: str) -> list:
        """In the worker: a first SDK import must not be silence before the lead. The visit's
        model is one client, so it writes one version at a time."""
        if not own:
            return [self.c.llm]
        if not self._own_llms:
            from .config import LLMConfig
            from .llm import make_conversation
            # The cap the rehearsal ran with (thinking shares it); a call that hangs must not
            # eat the passes.
            self._own_llms = [make_conversation(LLMConfig(profile=own, max_completion_tokens=2000,
                                                          timeout_s=self.cfg.calaverita_compose_s))
                              for _ in range(max(1, self.cfg.calaverita_versions))]
        return self._own_llms

    def _mode(self) -> tuple[str, str]:
        """("llm" | "script", why): the model whenever it can be trusted, even under a scripted
        house (FISH_SHOW=script on the board): a verse from clips is not this visitor's."""
        if self.c.echo:
            return "script", "echo"
        show_run = self.c.show
        ok, why = show_run.model_ok() if show_run is not None else model_trusted(self.c)
        return ("llm" if ok else "script"), why

    # ---- clips -------------------------------------------------------------------------------------
    def _pick(self, slot: str, names: list[str]) -> str:
        ready = [n for n in names if canned.cached(n, self.c.cfg)]
        return self.f.state.pick(slot, ready or names)

    def _pool(self, slot: str) -> str:
        return self._pick(f"calaverita_{slot}", calaverita.pool_names(slot))

    def _next_n(self) -> int:
        n = int(self.f.state.data.get("calaverita", 0)) + 1
        self.f.state.data["calaverita"] = n
        self.f.state.save()
        return n

    # ---- the act -----------------------------------------------------------------------------------
    def run(self, value: str = "") -> bool:
        """The operator's tap. The loop always goes on: any exception ends in the record, and a
        ticket goes out only on this normal path, so a stop signal never starts a print."""
        why = self.refusal()
        if why:
            print(f"[calaverita] refused: {why}", flush=True)
            self.c._push_visit()
            return True
        rec = self._begin(value)
        self.busy = True
        mark = debug.seq()
        ok = False
        try:
            self.c._push_visit()
            self._compose(rec)
            ok = True
        except Exception as e:
            print(f"[calaverita] act #{rec['n']} failed: {type(e).__name__}: {e}\n"
                  f"{traceback.format_exc()}", flush=True)
            rec["how"], rec["why"] = "error", f"{type(e).__name__}: {e}"
            debug.turn_set(error={"where": "calaverita", "type": type(e).__name__})
        finally:
            self.busy = False
            debug.turn_adopt(mark)
        if ok and rec["said"]:
            self._ticket(rec)                     # the closing line never started: now
        self._finish(rec)
        return True

    def _begin(self, value: str) -> dict:
        visit = self.c.visit
        first = clean_cue_text(visit.first_name, 40) or clean_cue_text(value, 40)
        used = visit.view()["used"]               # the cues this visitor's verdict filed
        return {"n": self._next_n(), "visit": visit.n, "first": first, "house": visit.house,
                "letter": show.HOUSE_LETTERS[visit.house], "place": self.c.cfg.place.place,
                "tag": calaverita.verse_tag(first, visit.house, place_word(self.c.cfg.place),
                                            used, list(visit.heard)),
                "own": "", "how": "", "why": "", "said": False, "stanzas": None, "ticket": None,
                "clips": [], "model_s": None, "tts_s": None, "passes": None, "versions": None, "rhymed": None, "t0": time.monotonic()}

    def _compose(self, rec: dict) -> None:
        self.f._probe_printer()
        lead = [self._pool("lead")]
        mode, why = self._mode()
        rec["own"] = self._own_profile()
        stale = self._own_stale if rec["own"] else self.c._stale.get("llm")
        if mode == "llm" and stale is not None and not stale.done.is_set():
            mode, why = "script", "the model is still busy with an older turn"
        if mode != "llm":
            rec["why"] = why
            return self._fallback(rec, lead, "clips")
        job, box = self._start(rec)
        try:
            rec["clips"] += lead + [self._pool("suspense")]
            self.f._say(lead + [rec["clips"][-1]])
            waited = self._wait(rec, job, box)
        except BaseException:                     # the clips failed: the job must not be left loose
            self._let_go(rec, job, box)
            raise
        if not waited:
            return self._fallback(rec, [], "clips")
        raw, wav, stanzas, err = job.result
        if err or not stanzas or wav is None:
            _drop_wav(job.result)
            if err and not err.startswith(("refusal", "empty reply")):
                self._model_failed(rec, f"error: {err}")
            else:
                rec["why"] = err or ("no voice" if stanzas else box.get("why") or "the verse broke the rules: "
                                     + "; ".join(calaverita.verse_problems(calaverita.stanzas_of(raw))))
                print(f"[calaverita] the verse gave way to the clips: {rec['why']}", flush=True)
            return self._fallback(rec, [], "clips")
        text = calaverita.spoken_verse(stanzas)
        rec["stanzas"] = stanzas
        self._show(rec)                           # the page has it while the hat recites it
        print(f"fish> {text}", flush=True)
        debug.turn_set(reply=text)
        if not self.c.speaker.perform(wav, text, box["timing"]):
            rec["why"] = "the speaker was busy"
            return self._fallback(rec, [], "clips")   # the page and the paper move with the voice
        rec["said"], rec["how"] = True, "model"
        rec["tts_s"] = box["timing"].get("tts")
        self._close(rec, [])

    def _start(self, rec: dict):
        """The model's job, then its voice. The client is touched in the worker: a first SDK
        import (7.0 and 17.4 s on the board) must not be silence before the lead. The act's own
        client never touches the visit's history."""
        from .conversation import _Job
        box = {"timing": {}, "reply": False, "gone": False}
        tag, thinking = rec["tag"], self.cfg.calaverita_thinking
        speaker, rules = self.c.speaker, self.cfg.calaverita_rules
        own = rec["own"]

        def work():
            clients = self._clients(own)
            if box["gone"]:                       # given up on during the import: the rules and
                return "", None, None, "gone"     # the history are the next act's by now
            t0 = time.monotonic()
            r = calaverita.compose(clients, rules, tag, thinking=thinking or None,
                                   passes=self.cfg.calaverita_passes,
                                   budget_s=self.cfg.calaverita_compose_s,
                                   gone=lambda: box["gone"])
            raw, err = r["raw"], r["error"]
            box.update(reply=True, model_s=round(time.monotonic() - t0, 2), passes=r["passes"],
                       versions=r["versions"], rhymed=r["rhymed"])
            stanzas = r["stanzas"] if r["rhymed"] == calaverita.STANZAS else None
            if r["stanzas"] and not stanzas:
                box["why"] = f"only {r['rhymed']} of {calaverita.STANZAS} stanzas rhymed in {r['versions']} versions"
            wav = None
            if stanzas and not box["gone"]:
                try:
                    wav = speaker.synthesize(calaverita.spoken_verse(stanzas), box["timing"])
                except Exception as e:
                    print(f"[calaverita] no voice for the verse: {type(e).__name__}: {e}", flush=True)
            return raw, wav, stanzas, err

        return _Job("llm", work, discard=_drop_wav), box

    def _wait(self, rec: dict, job, box: dict) -> bool:
        """Up to `calaverita_s` from the end of the lead, one more line at `suspense_more_s`.
        True when the job finished without raising."""
        c = self.c
        start = c._clock()
        deadline, more = start + self.cfg.calaverita_s, start + self.cfg.suspense_more_s
        while not job.done.is_set():
            now = c._clock()
            if more is not None and now >= more and now < deadline:
                more = None
                name = self._pool("suspense_mas")
                rec["clips"].append(name)
                self.f._say([name])
                continue
            if now >= deadline:
                self._let_go(rec, job, box)
                why = f"timeout after {self.cfg.calaverita_s:g} s"
                if box["reply"]:                  # the model answered, the voice was slow
                    rec["why"] = why + " (the voice)"
                    print(f"[calaverita] the verse gave way to the clips: {rec['why']}", flush=True)
                else:
                    self._model_failed(rec, why)
                return False
            c._wait_on(job.done, min(deadline - now, 0.25))
        rec.update(model_s=box.get("model_s"), passes=box.get("passes"), versions=box.get("versions"),
                   rhymed=box.get("rhymed"))
        if job.exc is not None:
            self._model_failed(rec, f"error: {type(job.exc).__name__}")
            return False
        return True

    def _let_go(self, rec: dict, job, box: dict) -> None:
        """Give up on a running job: its voice is dropped and nothing asks the model beside it."""
        box["gone"] = True
        job.abandon()
        if rec["own"]:
            self._own_stale = job                 # the next tap goes to the clips while it runs
        else:
            self.c._stale["llm"] = job            # the next turn waits for it, never asks twice

    def _model_failed(self, rec: dict, why: str) -> None:
        print(f"[calaverita] the model gave way to the clips: {why}", flush=True)
        rec["why"] = why
        if self.c.show is not None and not rec["own"]:
            self.c.show.model_failed()            # the next visits stay scripted a while

    def _fallback(self, rec: dict, lead: list, how: str) -> None:
        name = self._pick(f"calaverita_verso_{rec['letter']}",
                          calaverita.fallback_names(rec["letter"]))
        rec["stanzas"] = calaverita.fallback_stanzas(name)
        self._show(rec)
        rec["how"] = how
        self._close(rec, lead + [name])

    def _close(self, rec: dict, names: list) -> None:
        """What is left to say, the closing line last: the ticket goes as it starts."""
        cierre = self._pool("cierre")
        names = names + [cierre]
        rec["clips"] += names
        gate = (cierre, lambda: self._ticket(rec)) if self.c.printer is not None else None
        said = self.f._say(names, at=gate)
        rec["said"] = rec["said"] or said
        if not said and rec["how"] != "model":
            rec["stanzas"] = None                 # nobody heard it: not on the page, not on paper
            rec["how"], rec["why"] = "not said", rec["why"] or "the speaker was busy"
            self._last = {}

    def _show(self, rec: dict) -> None:
        self._last = {"visit": rec["visit"], "n": rec["n"], "first": rec["first"],
                      "house": rec["house"], "verse": calaverita.page_verse(rec["stanzas"])}
        self.c._push_visit()

    # ---- paper ---------------------------------------------------------------------------------------
    def _ticket(self, rec: dict) -> None:
        """Once a verse; with tickets off only kept for Reprint. Never the act's problem."""
        p = self.c.printer
        if p is None or rec["ticket"] or not rec["stanzas"]:
            return
        rec["ticket"] = "error"
        try:
            t = ticket.verse_ticket(rec["n"], rec["first"], rec["house"], rec["stanzas"],
                                    place=ticket.place_said(rec["place"], self.c.cfg.place),
                                    now=datetime.now())
            if not self.cfg.ticket:
                p.keep(t)
                rec["ticket"] = "kept"
            elif p.submit(t):
                rec["ticket"] = "queued"
            else:
                rec["ticket"] = "refused"
                print(f"[calaverita] #{rec['n']}: the printer did not take the ticket "
                      "(Reprint prints it)", flush=True)
        except Exception as e:
            print(f"[calaverita] #{rec['n']}: no ticket: {type(e).__name__}: {e}", flush=True)

    # ---- the record ------------------------------------------------------------------------------------
    def _finish(self, rec: dict) -> None:
        """Print, record, tell the page. A failure here must not reach the turn, which would say
        an error line."""
        try:
            verse = calaverita.page_verse(rec["stanzas"]) if rec["stanzas"] else None
            seconds = round(time.monotonic() - rec["t0"], 1)
            print(f"[calaverita] #{rec['n']} how={rec['how']} ({rec['why']}) house={rec['house']} "
                  f"versions={rec['versions']} rhymed={rec['rhymed']} model={rec['model_s']} tts={rec['tts_s']} ticket={rec['ticket']} {seconds}s",
                  flush=True)
            debug.emit("calaverita", n=rec["n"], how=rec["how"], why=rec["why"], first=rec["first"],
                       house=rec["house"], place=rec["place"], profile=rec["own"] or self.c.cfg.llm.profile,
                       tag=rec["tag"], verse=verse,
                       clips=list(rec["clips"]), model_s=rec["model_s"], tts_s=rec["tts_s"],
                       passes=rec["passes"], versions=rec["versions"], rhymed=rec["rhymed"],
                       ticket=rec["ticket"], seconds=seconds)
            debug.turn_set(calaverita=f"#{rec['n']} {rec['how']}",
                           outcome=f"calaverita: {rec['how']}", times=self.c.speaker.last_timing)
            self.c._push_visit()
        except Exception as e:
            print(f"[calaverita] could not finish the record: {type(e).__name__}: {e}", flush=True)
