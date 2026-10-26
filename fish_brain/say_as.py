"""What Loquendo is given to say: the shown text, rewritten for the voice only.

Loquendo's "Jorge" is a voice from Spain (`Jorge.vde`: "Castilian Spanish male voice") that
`loqd` loads with no language, so it reads with Spain's rules; a word with no vowel ("Mmm")
it spells out ("eme eme eme"); English names it reads with Spanish letter rules. Its engine
takes control tags in the text (`\\command ` ended by a space; measured on the board
2026-10-16: `\\pause=1500` adds 1.5 s, `\\item=Hmh` a recorded hum, `\\language=SpanishMx`
is silent). So, for `loq` only and in this order:

1. every backslash in the text is removed (neither the model nor a phrase injects a tag);
2. whole words of the persona's `say_as` map are replaced (the houses' respellings);
3. a hum with no vowel ("Mmm…", "Hmm", "Mjm") becomes `loq_hum` (a recorded hum, a tag);
4. `loq_prefix` goes in front (`\\language=SpanishMx `: Mexican reading rules on Jorge).

The bubble, the page and the logs keep the original text; /debug shows both.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

# A hum with no vowel, as a whole word, with the dots after it: Mmm, Mmmm…, Hmm, Mjm, Mhm, Mmh.
_HUM = re.compile(r"(?<![\w])(?:[hj]?m{2,}h?|h+m+|m+[hj]m*)(?![\w])(?:\s?(?:…|\.{2,}))?", re.IGNORECASE)


def _fold1(c: str) -> str:
    """One character without its accent, lower case; always one character back."""
    base = "".join(x for x in unicodedata.normalize("NFD", c) if unicodedata.category(x) != "Mn")
    return (base or c)[:1].lower()


def _replace_word(text: str, word: str, spoken: str) -> str:
    """Every whole-word `word` in `text`, any case, with or without accents, becomes `spoken`.
    Matched on a copy folded character by character, so the positions are the original's."""
    folded = "".join(_fold1(c) for c in text)
    target = "".join(_fold1(c) for c in word)
    spans = [m.span() for m in re.finditer(r"(?<!\w)" + re.escape(target) + r"(?!\w)", folded)]
    for a, b in reversed(spans):
        text = text[:a] + spoken + text[b:]
    return text


def voice_text(text: str, prefix: str = "", hum: str = "", say_as: dict | None = None) -> str:
    out = (text or "").replace("\\", " ")          # the text's own: never a tag
    for word, spoken in (say_as or {}).items():     # the config's may hold one (\\SAMPA=…)
        out = _replace_word(out, word, spoken)
    if hum:
        def one(m):
            if hum.startswith("\\"):                # a tag ends at a space; its sound is the pause
                return hum.strip() + " "
            return hum + ("…" if m.group(0).rstrip().endswith(("…", "..")) else "")
        out = _HUM.sub(one, out)
    out = " ".join(out.split())
    return (prefix + out) if prefix else out


def rules_hash(prefix: str = "", hum: str = "", say_as: dict | None = None) -> str:
    """Short and stable: part of the canned cache's key, so a change re-renders the phrases."""
    if not (prefix or hum or say_as):
        return ""
    blob = repr((prefix, hum, sorted((say_as or {}).items())))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:8]


# Lines to judge by ear (the page's Pronunciation list and tools/pron_render.py). Each is said
# exactly as written: the rewrite above is not applied to them.
MX = "\\language=SpanishMx "
CANDIDATES: list[tuple[str, str]] = [
    ("accent, as now", "Gracias, el cielo de la ciudad hace zigzag. ¿Qué tal, Jorge?"),
    ("accent, Mexican rules", MX + "Gracias, el cielo de la ciudad hace zigzag. ¿Qué tal, Jorge?"),
    ("hum, as now", MX + "Mmm… difícil."),
    ("hum: item Hmh", MX + "\\item=Hmh difícil."),
    ("hum: item Hmh_02", MX + "\\item=Hmh_02 difícil."),
    ("hum: item Hmh_03", MX + "\\item=Hmh_03 difícil."),
    ("hum: item Mhm", MX + "\\item=Mhm claro."),
    ("hum: item Ehm", MX + "\\item=Ehm a ver."),
    ("hum: Emmm", MX + "Emmm… difícil."),
    ("hum: Hum", MX + "Hum… difícil."),
]
# The first after each name is the hat's default (PERSONAS["hat"]["say_as"], 2026-10-26: the
# candidates that transcribed back as the English word).
for _group in (("Hufflepuff", "Jófl paf", "Jafel paf", "Jáfelpaf", "Jáflepaf", "Jófelpof"),
               ("Gryffindor", "Grifindór", "Grífindor"),
               ("Ravenclaw", "Réivenclo", "Rávenclo"),
               ("Slytherin", "Slízerin", "Slíderin", "Eslíderin"),
               ("Hogwarts", "Jógwarts", "Jóguarts")):
    for _w in _group:
        CANDIDATES.append((f"{_group[0]}: {_w}", MX + f"¡Eres de {_w}!" if _group[0] != "Hogwarts"
                           else MX + f"Bienvenido a {_w}."))
for _w in ("Halloween", "Jálouin", "Jalouín", "Jálowin"):
    CANDIDATES.append((f"Halloween: {_w}", MX + f"¡Feliz {_w}!"))
