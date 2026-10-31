#!/usr/bin/env python3
"""Turn the board's records (fish_brain/record.py) into a script for tools/hat_rehearse.py: the
real visitors' own words, replayed against today's rules.

    tools/hat_records.py rehearsals/records/*.jsonl --since 2026-10-27T17:00 > rehearsals/real.txt
    tools/hat_records.py --self-test

One visitor per "New visitor" that said something: its place and the cues its fortune was given
(`pistas`), the name the operator typed (`nombre:`), every line the visitor said before the
fortune (the visit's turns, a turn whose voice timed out, an answer to the scripted act: as the
speech-to-text wrote it), each followed by what the hat answered then (`# then: …`, a comment the
rehearsal shows beside today's answer), then "fortuna:", the act's answers in the order heard and
the reading said then (`# then reading: …`). A visitor who never reached a fortune is the visit
alone. An
answer to a question today's act no longer asks (the animal, ADR 0026) is kept as a comment, so
the act the script replays asks only what it still asks. A wish the visitor was never asked is
left out (the rehearsal deals a tema, as the act would); a card never asked is a "Sí." (his word,
2026-10-29: give them a random card), so the hat draws one as it does on a yes.

The output holds real people's first names and dreams: keep it in rehearsals/ (ignored by git).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ASKED = ("fecha", "sueno", "deseo", "carta", "taza")     # fortune_bank.QIDS, without the import


def read(paths: list[Path]) -> list[dict]:
    """Every line of the files, in wall-clock order; lines that do not parse are skipped."""
    lines = []
    for p in paths:
        for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            if isinstance(d, dict) and "wall" in d:
                lines.append(d)
    return sorted(lines, key=lambda d: d["wall"])


def _when(wall: float) -> str:
    return datetime.fromtimestamp(wall, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _one_line(text: str) -> str:
    return " ".join(str(text or "").split())


def visitors(lines: list[dict], *, since: float = 0.0) -> list[dict]:
    """[{when, n, place, house, mode, first, cues, turns: [(said, hat then)], answers, reading}]:
    one per visitor after `since`, with or without a fortune."""
    out: list[dict] = []
    cur: dict | None = None

    def close():
        if cur and (cur["turns"] or cur["answers"]) and cur["wall"] >= since:
            out.append(cur)

    for d in lines:
        kind = d.get("kind")
        if kind == "visitor":                    # "New visitor": the last one is done
            close()
            cur = None
        elif kind == "turn" and d.get("user") and not d.get("fortune"):
            if cur is None or cur["answers"]:
                close()
                cur = {"wall": d["wall"], "when": _when(d["wall"]), "n": None, "place": "",
                       "house": None, "mode": None, "first": "", "cues": {}, "turns": [],
                       "answers": [], "reading": ""}
            cur["turns"].append((_one_line(d["user"]), _one_line(d.get("reply"))))
        elif kind == "fortune" and d.get("heard") and not d.get("dropped"):
            if cur is None or cur["answers"]:
                close()
                cur = {"wall": d["wall"], "turns": []}
            cur.update(when=_when(d["wall"]), n=d.get("n"), place=d.get("place") or "",
                       house=d.get("house"), mode=d.get("how") or d.get("mode"),
                       first=_one_line(d.get("first")), cues=dict(d.get("pistas") or {}),
                       answers=[(q, _one_line(t)) for q, t in d["heard"]],
                       reading=_one_line(d.get("reading")))
    close()
    return out


def script(found: list[dict]) -> str:
    """The visitors as a hat_rehearse.py script."""
    out = ["# Real visitors from the board's records (tools/hat_records.py), their own words as",
           "# speech-to-text wrote them. Private: names and dreams; keep under rehearsals/.", ""]
    for v in found:
        act = (f"act #{v['n']}, {v['when']}, {v['place'] or 'no place'}, house {v['house'] or '-'}, "
               f"reading by {v['mode'] or '-'}" if v["answers"] else f"{v['when']}, a visit with no fortune")
        out.append(f"# {act}")
        if v["place"]:
            out.append(f"lugar: {v['place']}")
        if v["first"]:
            out.append(f"nombre: {v['first']}")
        if v["cues"]:
            out.append("pistas: " + "; ".join(f"{k}={_one_line(val)}" for k, val in v["cues"].items()))
        for said, then in v["turns"]:
            out.append(said)
            out.append(f"# then: {then}" if then else "# then: (nothing said: the scripted act took it)")
        if not v["answers"]:
            out.append("")
            continue
        out.append("fortuna:")
        for q, text in v["answers"]:
            out.append(f"{q}: {text}" if q in ASKED else f"# {q}: {text}   (no longer asked)")
        if not any(q == "carta" for q, _t in v["answers"]):
            out += ["# carta: not asked then; a yes, so the hat draws", "carta: Sí."]
        if v["reading"]:
            out.append(f"# then reading: {v['reading']}")
        out.append("")
    return "\n".join(out)


def _self_test() -> int:
    lines = [
        {"kind": "visitor", "wall": 1.0},
        {"kind": "turn", "wall": 2.0, "visit": "2/4", "user": "Hola,  soy Albert.", "reply": "¡Albert!"},
        {"kind": "turn", "wall": 3.0, "outcome": "visit: greeting"},
        {"kind": "turn", "wall": 4.0, "outcome": "timeout: tts", "user": "A mi novia."},
        {"kind": "turn", "wall": 5.0, "fortune": "#5 fecha sign geminis", "user": "Diecisiete de junio."},
        {"kind": "fortune", "wall": 6.0, "n": 5, "how": "llm", "place": "fiesta", "house": "Hufflepuff",
         "first": "Alberto", "reading": "Veo  borregos.",
         "pistas": {"edad": "adulto"}, "heard": [["fecha", "Diecisiete de junio."],
                                                 ["animal", "Un perrito."]]},
        {"kind": "fortune", "wall": 7.0, "n": 6, "dropped": "new visitor", "heard": [["fecha", "x"]]},
        {"kind": "fortune", "wall": 8.0, "n": 7},
        {"kind": "visitor", "wall": 9.0},
        {"kind": "turn", "wall": 10.0, "visit": "2/4", "user": "Alex.", "reply": "Alex, veo."},
    ]
    found = visitors(lines)
    text = script(found)
    checks = [
        len(found) == 2 and found[0]["turns"] == [("Hola, soy Albert.", "¡Albert!"), ("A mi novia.", "")],
        ("lugar: fiesta\nnombre: Alberto\npistas: edad=adulto\nHola, soy Albert.\n# then: ¡Albert!\n"
         "A mi novia.\n# then: (nothing said: the scripted act took it)\nfortuna:\n") in text,
        "fecha: Diecisiete de junio." in text and "# animal: Un perrito.   (no longer asked)" in text,
        "# then reading: Veo borregos." in text,
        "a visit with no fortune\nAlex.\n# then: Alex, veo.\n" in text,
        [v["turns"] for v in visitors(lines, since=8.5)] == [[("Alex.", "Alex, veo.")]],
    ]
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import hat_rehearse
    parsed = hat_rehearse.parse_script(text)
    checks.append(parsed[0]["fortune"] == [("fecha", "Diecisiete de junio."), ("carta", "Sí.")])
    checks.append(parsed[0].get("name") == "Alberto" and parsed[0].get("then") == ["¡Albert!", "(nothing said: the scripted act took it)"]
                  and parsed[0].get("then_reading") == "Veo borregos.")
    print("[self-test] all passed" if all(checks) else f"[self-test] FAILED {checks}")
    return 0 if all(checks) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("records", nargs="*", type=Path, help="record files (.jsonl)")
    ap.add_argument("--since", help="only fortunes from this UTC time on (2026-10-27T17:00)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if not args.records:
        ap.error("give the record files")
    since = 0.0
    if args.since:
        since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc).timestamp()
    found = visitors(read(args.records), since=since)
    print(script(found))
    print(f"[hat_records] {len(found)} visitor(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
