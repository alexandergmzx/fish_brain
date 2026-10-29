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
    assert v[0] == {"badge": "Sofía", "greet": True, "place": None, "fortune": None,
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
    assert llm.sent[1] == "[ETAPA 3/4] [PISTAS: color=azul] Libro"   # every turn carries them
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


def test_the_cost_of_a_claude_call_comes_from_its_profile_prices():
    from fish_brain import claude
    from fish_brain.ab import _cost
    from fish_brain.config import LLMConfig
    usage = claude.Usage(prompt_tokens=1000, completion_tokens=100)
    assert _cost(LLMConfig(profile="claude"), usage) == (1000 * 0.10 + 100 * 0.50) / 1e6
    assert _cost(LLMConfig(profile="claude-sonnet"), usage) == (1000 * 2.0 + 100 * 10.0) / 1e6


# ---- the fortune block, coverage, banned words, repeats, refused cues ------------------------
def test_parse_script_reads_a_fortune_block_and_the_place():
    text = ("lugar: casa\npistas: edad=adulto\nHola\nfortuna:\nfecha: Tres de marzo.\n"
            "sueño: Soñé con agua.\nanimal: Un gato.\n")
    v = hat_rehearse.parse_script(text)[0]
    assert v["place"] == "casa" and v["steps"] == [("cues", {"edad": "adulto"}), ("say", "Hola")]
    assert v["fortune"] == [("fecha", "Tres de marzo."), ("sueno", "Soñé con agua."),
                            ("animal", "Un gato.")]


def test_a_bad_fortune_line_is_named():
    import pytest
    with pytest.raises(ValueError, match="fortune line"):
        hat_rehearse.parse_script("Hola\nfortuna:\nqué tal\n")


def test_refused_cue_values_are_reported_not_raised(monkeypatch):
    monkeypatch.setenv("FISH_PERSONA", "hat")
    llm = ScriptLLM(["a?", "b?", "¡Ravenclaw!\nCASA: Ravenclaw"])
    visitor = {"badge": None, "greet": True, "place": None, "fortune": None,
               "steps": [("cues", {"edad": "niño", "color": "azul", "disfraz": "monstruo"}),
                         ("say", "x"), ("say", "y"), ("say", "z")]}
    rec = hat_rehearse.run_visit(llm, Config(), visitor)
    assert rec["refused"] == ["edad=niño", "disfraz=monstruo"]
    assert llm.sent[0] == "[ETAPA 2/4] [PISTAS: color=azul] x"


def test_the_visitors_place_rides_every_visit_turn(monkeypatch):
    monkeypatch.setenv("FISH_PERSONA", "hat")
    llm = ScriptLLM(["a?", "b?"])
    visitor = {"badge": None, "greet": True, "place": "casa", "fortune": None,
               "steps": [("cues", {"compania": "pareja"}), ("say", "x"), ("say", "y")]}
    hat_rehearse.run_visit(llm, Config(), visitor)
    assert llm.sent == ["[ETAPA 2/4] [PISTAS: lugar=casa; compañía=pareja] x",
                        "[ETAPA 3/4] [PISTAS: lugar=casa; compañía=pareja] y"]


def test_no_word_is_a_problem_in_a_visit_reply():
    # ADR 0025: no word list; only the shape of a reply is checked
    assert hat_rehearse.check("Eres un pendejo.", verdict=False) == []
    assert hat_rehearse.check("Algo muere esta noche.", verdict=False) == []


def test_cue_coverage_finds_stems_and_free_text_words():
    cues = {"color": "amarillo", "impresion": "sonriente", "lleva": "capa negra",
            "edad": "adulto"}
    used, unused = hat_rehearse.coverage(cues, ["Esa sonrisa y tu capa me dicen todo.",
                                                "Veo algo amarillo."])
    assert used == ["color", "impresion", "lleva"] and unused == ["edad"]


def test_repeats_finds_a_phrase_shared_by_two_verdicts():
    rep = hat_rehearse.repeats(["Esta noche una vela de colores hará bailar tu sombra.",
                                "Ya verás: una vela de colores hará bailar algo.",
                                "Nada que ver aquí."])
    assert rep == {"una vela de colores hara bailar": [0, 1]}
    assert hat_rehearse.repeats(["de la casa de ella", "de la casa de él"]) == {}


def test_a_fortune_block_runs_the_acts_steps(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setenv("FISH_PERSONA", "hat")
    monkeypatch.delenv("FISH_FORTUNE_DECK", raising=False)
    monkeypatch.delenv("FISH_FORTUNE_CUP", raising=False)
    cfg = Config()

    class Clock(ScriptLLM):
        def reply(self, text, remember=True):
            self.last_latency_s = 9.5
            return super().reply(text, remember)

    llm = Clock(["Tu tío se murió, Albert, pero los borregos te guían. Veo una capa negra."])
    visitor = {"place": "fiesta", "fortune": [
        ("fecha", "Diecisiete de junio."), ("sueno", "Soñé que flotaba."),
        ("sueno", "Soñé con mi tío y un rebaño de borreguitos."), ("sueno", "otra vez"),
        ("taza", "un corazón"), ("animal", "Un perrito xoloitzcuintle.")]}
    vrec = {"house": "Hufflepuff", "first": "Albert", "cues": {"lleva": "capa negra"}}
    rec = hat_rehearse.run_fortune(llm, cfg, visitor, vrec, seed=1,
                                   now=datetime(2026, 10, 27, tzinfo=timezone.utc))
    kinds = [(a["q"], a["kind"]) for a in rec["answers"]]
    assert kinds[0] == ("fecha", "sign")
    assert kinds[3] == ("sueno", "not asked again") and kinds[4] == ("taza", "not asked (off)")
    assert llm.extra_rules == cfg.fortune.rules and llm.resets == 1
    tag = llm.sent[0]
    assert tag == rec["tag"] and tag.startswith("[ADIVINACIÓN: nombre=Albert; lugar=fiesta;")
    assert "casa=Hufflepuff" in tag and "luna=" in tag and "palabra=" in tag
    assert kinds[1] == ("sueno", "theme") and 'sueño=volar ("Soñé que flotaba.")' in tag
    assert kinds[-1] == ("animal", "free") and "animal=un perrito xoloitzcuintle" in tag
    assert tag.endswith("pistas=lleva: capa negra] Haz la lectura.")
    assert "would fall back to clips" in " ".join(rec["problems"])
    assert not any("death" in p for p in rec["problems"])      # no word list (ADR 0025)
    assert rec["used"] == ["lleva"]
