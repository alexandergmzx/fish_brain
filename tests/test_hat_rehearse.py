"""tools/hat_rehearse.py: the script parser and one visit against a fake model."""
import os
import sys
from pathlib import Path

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
                    "steps": [("cues", {"edad": "niño", "color": "azul"}), ("say", "Hola")],
                    "name": "", "then": [], "then_reading": ""}
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
            "sueño: Soñé con agua.\ndeseo: Venganza.\ncarta: Sí.\n")
    v = hat_rehearse.parse_script(text)[0]
    assert v["place"] == "casa" and v["steps"] == [("cues", {"edad": "adulto"}), ("say", "Hola")]
    assert v["fortune"] == [("fecha", "Tres de marzo."), ("sueno", "Soñé con agua."),
                            ("deseo", "Venganza."), ("carta", "Sí.")]


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
        ("deseo", "Que regrese mi ex."), ("carta", "Sí."), ("taza", "un corazón")]}
    vrec = {"house": "Hufflepuff", "first": "Albert", "cues": {"lleva": "capa negra"}}
    rec = hat_rehearse.run_fortune(llm, cfg, visitor, vrec, seed=1,
                                   now=datetime(2026, 10, 27, tzinfo=timezone.utc))
    kinds = [(a["q"], a["kind"]) for a in rec["answers"]]
    assert kinds[0] == ("fecha", "sign")
    assert kinds[3] == ("sueno", "not asked again") and kinds[-1] == ("taza", "not asked (off)")
    assert llm.extra_rules == cfg.fortune.rules and llm.resets == 1
    tag = llm.sent[0]
    assert tag == rec["tag"] and tag.startswith("[ADIVINACIÓN: nombre=Albert; lugar=fiesta;")
    assert "casa=Hufflepuff" in tag and "luna=" in tag and "palabra=" in tag
    assert kinds[1] == ("sueno", "theme") and 'sueño=volar ("Soñé que flotaba.")' in tag
    assert kinds[4] == ("deseo", "wish") and 'deseo=amor ("Que regrese mi ex.")' in tag
    assert kinds[5] == ("carta", "draw") and "la saqué yo" in tag
    assert "hoy=martes 27 de octubre" in tag
    assert "pistas=lleva: capa negra; visión=" in tag and "; forma=" in tag
    assert tag.endswith("] Haz la lectura.")
    assert not any(" s > " in p for p in rec["problems"])      # the rehearsal does not time
    assert not any("death" in p for p in rec["problems"])      # no word list (ADR 0025)
    assert rec["used"] == ["lleva"]
    assert "L A   A D I V I N A C I Ó N" in rec["ticket"] and "p a r a   A l b e r t" in rec["ticket"]
    assert "Pediste ................... amor" in rec["ticket"]


def test_a_question_back_is_asked_again_as_the_act_does(monkeypatch):
    monkeypatch.setenv("FISH_PERSONA", "hat")
    monkeypatch.delenv("FISH_FORTUNE_DECK", raising=False)
    monkeypatch.setenv("FISH_FORTUNE_CUP", "false")
    cfg = Config()
    llm = ScriptLLM(["Lo leí en tu cabeza. Tu palabra mágica es Zumbalí."])
    visitor = {"place": "fiesta", "name": "Ana", "fortune": [
        ("fecha", "mmm"), ("fecha", "Tauro."), ("sueno", "emm"), ("sueno", "Soñé que volaba."),
        ("deseo", "¿Y cómo que muerte?"), ("deseo", "Dinero."), ("carta", "¿Qué?"),
        ("carta", "emm"), ("carta", "Sí.")]}
    rec = hat_rehearse.run_fortune(llm, cfg, visitor, {"house": None, "first": "Fernando", "cues": {}},
                                   seed=1)
    kinds = [(a["q"], a["kind"]) for a in rec["answers"]]
    assert kinds[4:] == [("deseo", "ask_back"), ("deseo", "wish"), ("carta", "ask_back"),
                         ("carta", "none"), ("carta", "not asked again")]
    assert 'deseo=dinero ("Dinero.")' in rec["tag"] and "carta" not in rec["tag"]
    assert rec["tag"].startswith("[ADIVINACIÓN: nombre=Ana;")      # typed first, as the act


def test_the_magic_word_is_said_only_at_its_closing():
    assert hat_rehearse.magic_word_problems("Algo. Tu palabra mágica es Zumbalí.", "Zumbalí") == []
    assert hat_rehearse.magic_word_problems("Zumbalí, ven acá. Tu palabra mágica es Zumbalí.",
                                            "Zumbalí")
    assert hat_rehearse.magic_word_problems("Tenebrumba, ven acá.", "Tenebrumba")
    assert "el sombrero" in hat_rehearse.STALE


def test_variety_counts_openings_and_stale_phrases():
    line = hat_rehearse.variety(["Escorpio, tú no perdonas. Esta noche sí.",
                                 "Escorpio, tú no olvidas.", "Suelta la quijada, que la energía…"])
    assert line.startswith("variety: 2 distinct openings in 3 readings")
    assert "'esta noche' 1" in line and "'energia' 1" in line


def test_the_act_state_carries_the_draws_and_the_openings_across_visitors(monkeypatch):
    from fish_brain.show import ShowState
    monkeypatch.setenv("FISH_PERSONA", "hat")
    monkeypatch.delenv("FISH_FORTUNE_DECK", raising=False)
    cfg = Config()
    state = ShowState(None, seed="r")
    visitor = {"place": "fiesta", "fortune": [("deseo", "Dinero."), ("carta", "Sí.")]}
    cards = []
    for i in range(3):
        llm = ScriptLLM([f"Lectura número {i} y algo más. Tu palabra mágica es X."])
        rec = hat_rehearse.run_fortune(llm, cfg, visitor, None, seed=i, state=state)
        cards.append(rec["answers"][1]["value"])
        if i:
            assert "evita=Lectura número 0" in rec["tag"] and f"Lectura número {i - 1}" in rec["tag"]
    assert len(set(cards)) == 3


def test_a_logged_run_names_its_commit_script_and_rules(tmp_path, monkeypatch):
    monkeypatch.setenv("FISH_PERSONA", "hat")
    cfg = Config()
    f = hat_rehearse.open_log(tmp_path / "logs", Path("rehearsals/real.txt"), cfg, ["--log", "x"])
    f.write("reading> hola\n")
    f.close()
    (log,) = (tmp_path / "logs").iterdir()
    text = log.read_text()
    assert log.name.endswith("-real.txt") and oct(log.stat().st_mode)[-3:] == "600"
    assert text.startswith("# hat_rehearse run ") and "# commit " in text
    assert "# script rehearsals/real.txt · args --log x" in text
    assert "fortune " in text and "reading thinking disabled" in text and text.endswith("reading> hola\n")


def test_hat_records_self_test():
    import subprocess
    import sys as _sys
    tool = Path(__file__).resolve().parent.parent / "tools" / "hat_records.py"
    assert subprocess.run([_sys.executable, str(tool), "--self-test"], capture_output=True).returncode == 0


def test_the_then_lines_and_the_typed_name_reach_the_markdown():
    text = ("nombre: Alberto\nHola, soy Albert.\n# then: ¡Albert! ¿Mapa o libro?\nfortuna:\n"
            "fecha: Tres de marzo.\n# then reading: Veo borregos.\n")
    (v,) = hat_rehearse.parse_script(text)
    assert v["name"] == "Alberto" and v["then"] == ["¡Albert! ¿Mapa o libro?"]
    assert v["then_reading"] == "Veo borregos." and v["fortune"] == [("fecha", "Tres de marzo.")]
    rec = {"first": "", "cues": {}, "house": "Hufflepuff", "done": True,
           "turns": [{"you": "(nuevo visitante)", "hat": "¡Hola!"},
                     {"you": "Hola, soy Albert.", "hat": "Albert, veo.", "s": 1.2, "problems": []}]}
    frec = {"answers": [{"q": "fecha", "you": "Tres de marzo.", "kind": "sign", "value": "piscis"}],
            "tag": "[ADIVINACIÓN: x]", "reading": "Piscis, ya.", "said": "Piscis, ya.", "s": 2.0,
            "problems": [], "error": None, "ticket": "  L A\n"}
    md = hat_rehearse.visitor_markdown(1, v, rec, frec, "# hat_rehearse run X\n# commit abc\n")
    assert md.startswith("# Visitor 1 · Alberto\n\nhat_rehearse run X\ncommit abc")
    assert "**Visitor:** Hola, soy Albert." in md and "**Hat now**: Albert, veo." in md
    assert "*Hat then:* ¡Albert! ¿Mapa o libro?" in md and "> Veo borregos." in md
    assert "- **fecha:** Tres de marzo. (sign → piscis)" in md and "```\n  L A\n```" in md
