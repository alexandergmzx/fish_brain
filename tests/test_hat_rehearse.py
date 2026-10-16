"""tools/hat_rehearse.py: the script parser and one visit against a fake model."""
import os
import sys

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)

import hat_rehearse  # noqa: E402

from fish_brain.config import Config  # noqa: E402


class ScriptLLM:
    def __init__(self, replies):
        self.replies, self.sent, self.remembered = list(replies), [], []
        self.extra_rules, self.last_error, self.resets = "", None, 0
        self.last_latency_s, self.last_usage = 0.5, None

    def reset(self):
        self.resets += 1
        self.extra_rules = ""

    def remember(self, user, answer):
        self.remembered.append((user, answer))

    def reply(self, text, remember=True):
        assert remember is False
        self.sent.append(text)
        return self.replies.pop(0)


def test_parse_script_blocks_badges_cues_and_comments():
    text = "# top\n\n# 1\ngafete: Sofía\npistas: edad=niño; color=azul\nHola\n\nsin saludo\nHey\n"
    v = hat_rehearse.parse_script(text)
    assert len(v) == 2
    assert v[0] == {"badge": "Sofía", "greet": True,
                    "steps": [("cues", {"edad": "niño", "color": "azul"}), ("say", "Hola")]}
    assert v[1]["greet"] is False and v[1]["steps"] == [("say", "Hey")]


def test_a_visit_reaches_its_house(monkeypatch):
    monkeypatch.setenv("FISH_PERSONA", "hat")
    cfg = Config()
    llm = ScriptLLM(["Ana, veo algo. ¿Mapa o libro?", "Libros, sí. ¿Abres o investigas?",
                     "¡Ravenclaw! Hoy verás un robot.\nCASA: Ravenclaw"])
    visitor = {"badge": None, "greet": True,
               "steps": [("cues", {"color": "azul"}), ("say", "Ana"), ("say", "Libro"),
                         ("say", "Investigo"), ("say", "gracias")]}
    rec = hat_rehearse.run_visit(llm, cfg, visitor)
    assert rec["house"] == "Ravenclaw" and rec["done"] and rec["problems"] == []
    assert rec["skipped"] == 1
    assert llm.extra_rules == cfg.visit.rules and llm.resets == 1
    assert llm.remembered[0][0].startswith("[ETAPA 1/4]")
    assert llm.sent[0] == "[ETAPA 2/4] [PISTAS: color=azul] Ana"
    assert llm.sent[1] == "[ETAPA 3/4] Libro"
    assert rec["turns"][-1]["hat"] == "¡Ravenclaw! Hoy verás un robot."


def test_a_spoken_tag_and_a_missing_house_are_problems(monkeypatch):
    monkeypatch.setenv("FISH_PERSONA", "hat")
    llm = ScriptLLM(["Veo CASA grande.", "Bien.", "Eres valiente."])
    visitor = {"badge": "Leo", "greet": True,
               "steps": [("say", "Sí"), ("say", "a"), ("say", "b")]}
    rec = hat_rehearse.run_visit(llm, Config(), visitor)
    assert rec["turns"][0]["hat"] == "¿Tú eres Leo?"
    assert any("CASA" in p for p in rec["turns"][1]["problems"])
    assert rec["house"] is None and rec["problems"] == ["no house at the verdict"]


def test_a_house_only_on_the_tag_line_is_a_problem(monkeypatch):
    monkeypatch.setenv("FISH_PERSONA", "hat")
    llm = ScriptLLM(["a?", "b?", "Eres valiente.\nCASA: Gryffindor"])
    visitor = {"badge": None, "greet": True, "steps": [("say", "x"), ("say", "y"), ("say", "z")]}
    rec = hat_rehearse.run_visit(llm, Config(), visitor)
    assert rec["house"] == "Gryffindor"
    assert "the house is not said aloud" in rec["turns"][-1]["problems"]
