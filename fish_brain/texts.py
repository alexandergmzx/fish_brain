"""The hat's words as files he edits (fish_brain/prompts/, ADR 0029): the rules sent to the model
and every line the fortune says word for word. Read once; a broken file stops the start-up with
the file and line named, never a fish with half its lines."""
from __future__ import annotations

import os
import re
import tomllib
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).resolve().parent / "prompts"


def folder() -> Path:
    """FISH_PROMPTS_DIR for a rehearsal on other words; the package's files otherwise."""
    return Path(os.environ.get("FISH_PROMPTS_DIR") or DIR)


def rules(name: str) -> str:
    """A rules file as the model gets it, all of it (visit.md, ask.md, reading.md)."""
    return (folder() / name).read_text(encoding="utf-8").rstrip("\n")


def parse_lines(path: Path) -> dict:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"{path}: {e}") from e


@lru_cache(maxsize=1)
def lines() -> dict:
    """lines.toml."""
    return check_lines(parse_lines(folder() / "lines.toml"))


def check_lines(d: dict) -> dict:
    """Every section there and every line a non-empty text, naming what is wrong. What each table
    must hold (every sign, card…) is checked by fortune_bank, which knows them."""
    def bad(what: str):
        raise ValueError(f"lines.toml: {what}")
    for key in ("visit_greeting", "reversed"):
        if not (isinstance(d.get(key), str) and d[key].strip()):
            bad(f"{key} must be a text")
    for key in ("ganchos", "ritos"):
        if not (isinstance(d.get(key), list) and d[key] and all(isinstance(x, str) and x.strip() for x in d[key])):
            bad(f"{key} must be a list of texts")
    for key in ("pools", "questions", "wishes", "signs", "dreams", "shapes", "numbers", "moons",
                "card_names", "cards"):
        if not isinstance(d.get(key), dict):
            bad(f"[{key}] is missing")
    for slot, pool in d["pools"].items():
        if not (isinstance(pool, list) and pool and all(isinstance(x, str) and x.strip() for x in pool)):
            bad(f"pools.{slot} must be a list of texts, even of one")
    for key, q in d["questions"].items():
        if not (isinstance(q.get("prompt"), str) and isinstance(q.get("reprompt"), str)):
            bad(f"questions.{key} needs a prompt and a reprompt")
    return d


@lru_cache(maxsize=1)
def house() -> dict:
    """house.toml."""
    return check_house(parse_lines(folder() / "house.toml"))


@lru_cache(maxsize=1)
def calaverita() -> dict:
    """calaverita.toml. A rehearsal folder from before it existed keeps working on the package's."""
    path = folder() / "calaverita.toml"
    return check_calaverita(parse_lines(path if path.exists() else DIR / "calaverita.toml"))


def check_calaverita(d: dict) -> dict:
    """The rules, the word list, its four pools and two kinds of fallback, naming what is wrong.
    Whether a fallback is a verse is checked by calaverita.py, which knows the shape."""
    def bad(what: str):
        raise ValueError(f"calaverita.toml: {what}")

    def texts_in(value) -> bool:
        return isinstance(value, list) and bool(value) and all(isinstance(x, str) and x.strip() for x in value)
    if not (isinstance(d.get("rules"), str) and d["rules"].strip()):
        bad("rules must be a text")
    if not texts_in(d.get("nunca")):
        bad("nunca must be a list of texts")
    pools, fallback = d.get("pools"), d.get("fallback")
    if not (isinstance(pools, dict) and isinstance(fallback, dict)):
        bad("[pools] and [fallback] are needed")
    for slot in ("lead", "suspense", "suspense_mas", "cierre"):
        if not texts_in(pools.get(slot)):
            bad(f"pools.{slot} must be a list of texts, even of one")
    for letter in "GHRS":
        if not texts_in(fallback.get(letter)):
            bad(f"fallback.{letter} must be a list of verses, even of one")
    return d


def check_house(d: dict) -> dict:
    """Three questions in each set, 2, 2 and 4 options, every text there, naming what is wrong.
    Which house an option serves is its position (show_bank.SHAPE)."""
    def bad(what: str):
        raise ValueError(f"house.toml: {what}")
    if not (isinstance(d.get("questions"), dict) and isinstance(d.get("pools"), dict)):
        bad("[questions] and [pools] are needed")
    for s in "ABC":
        for i, size in ((1, 2), (2, 2), (3, 4)):
            qid = f"{s}{i}"
            q = d["questions"].get(qid)
            if not isinstance(q, dict):
                bad(f"questions.{qid} is missing")
            for key in ("prompt", "reprompt"):
                if not (isinstance(q.get(key), str) and q[key].strip()):
                    bad(f"questions.{qid} needs a {key}")
            opts = q.get("options")
            if not (isinstance(opts, list) and len(opts) == size):
                bad(f"questions.{qid} needs {size} options")
            ids = [o.get("id") for o in opts]
            for n, o in enumerate(opts, 1):
                where = f"questions.{qid} option {n}"
                if not (isinstance(o.get("id"), str) and re.fullmatch(r"[a-z]+", o["id"])):
                    bad(f"{where} needs an id of one lower-case word")
                if ids.count(o["id"]) > 1:
                    bad(f"{where}: the id {o['id']} is repeated")
                if not (isinstance(o.get("words"), list) and o["words"]
                        and all(isinstance(w, str) and w.strip() for w in o["words"])):
                    bad(f"{where} needs words")
                if not (isinstance(o.get("reaction"), str) and o["reaction"].strip()):
                    bad(f"{where} needs a reaction")
    for slot, pool in d["pools"].items():
        if not (isinstance(pool, list) and pool and all(isinstance(x, str) and x.strip() for x in pool)):
            bad(f"pools.{slot} must be a list of texts, even of one")
    return d
