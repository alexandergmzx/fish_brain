"""FISH_PERSONA: the body's words (the fish by default, the Sorting Hat for the fair)."""
import re

import pytest

from fish_brain.config import (PERSONAS, VISIT_PHRASES, CannedConfig, LLMConfig, ReadingConfig,
                               STTConfig, TTSConfig, VisitConfig)


def test_fish_is_the_default(monkeypatch):
    monkeypatch.delenv("FISH_PERSONA", raising=False)
    assert "pez" in CannedConfig().phrases["welcome"]
    assert "pez" in LLMConfig().system_prompt
    assert "futuro" in ReadingConfig().rules


def test_hat_overrides_only_its_own_words(monkeypatch):
    monkeypatch.setenv("FISH_PERSONA", "hat")
    fish = {}
    monkeypatch.setenv("FISH_PERSONA", "fish"); fish = CannedConfig().phrases
    monkeypatch.setenv("FISH_PERSONA", "hat"); hat = CannedConfig().phrases
    assert set(fish) <= set(hat)                       # nothing lost
    from fish_brain.fortune_bank import FORTUNE_PHRASES
    # And only the visit's greeting and the fortune act's lines added.
    assert set(hat) - set(fish) == VISIT_PHRASES | set(FORTUNE_PHRASES)
    assert "pez" not in hat["welcome"] and "Sombrero" in hat["welcome"]
    assert hat["filler_first_1"] != fish["filler_first_1"]       # the hat waits in its own words
    assert hat["no_mic"] == fish["no_mic"]
    assert "burbujas" not in hat["timeout_stt_2"]
    assert "Sombrero" in LLMConfig().system_prompt
    assert "Glub" not in LLMConfig().fallback_reply
    assert "casa" in ReadingConfig().rules


def test_a_persona_lists_only_known_phrase_names():
    fish = PERSONAS["fish"]; hat = PERSONAS["hat"]
    assert fish == {}
    names = set(CannedConfig().phrases) | VISIT_PHRASES
    assert set(hat["phrases"]) <= names


def test_unknown_persona_is_refused(monkeypatch):
    monkeypatch.setenv("FISH_PERSONA", "goat")
    with pytest.raises(ValueError):
        CannedConfig()
    with pytest.raises(ValueError):
        LLMConfig()


def test_the_hat_hears_and_speaks_as_a_hat(monkeypatch):
    monkeypatch.delenv("FISH_STT_PROMPT", raising=False)
    monkeypatch.delenv("FISH_TTS_INSTRUCTIONS", raising=False)
    monkeypatch.setenv("FISH_PERSONA", "hat")
    assert "sombrero" in STTConfig().prompt and "sombrero" in TTSConfig().openai_instructions
    monkeypatch.setenv("FISH_STT_PROMPT", "otra cosa")
    assert STTConfig().prompt == "otra cosa"                 # the env var still wins
    monkeypatch.delenv("FISH_STT_PROMPT")
    monkeypatch.setenv("FISH_PERSONA", "fish")
    assert "pez" in STTConfig().prompt and "pez" in TTSConfig().openai_instructions


def test_the_visit_is_the_hats_only(monkeypatch):
    monkeypatch.setenv("FISH_VISIT", "true")
    monkeypatch.setenv("FISH_PERSONA", "fish")
    fish = VisitConfig()
    assert not fish.enabled and fish.rules == "" and "visit_greeting" not in CannedConfig().phrases
    monkeypatch.setenv("FISH_PERSONA", "hat")
    hat = VisitConfig()
    assert hat.enabled and hat.stages == 4 and "CASA:" in hat.rules and hat.idle_s == 30.0
    assert "{first}" in hat.badge_note and "{first}" in hat.name_note
    assert "visit_greeting" in CannedConfig().phrases
    monkeypatch.setenv("FISH_VISIT", "false")
    assert not VisitConfig().enabled and VisitConfig().rules       # off, the texts kept
    monkeypatch.setenv("FISH_VISIT", "")
    assert VisitConfig().enabled                                     # blank = the default
    monkeypatch.setenv("FISH_VISIT_IDLE_S", "45")
    assert VisitConfig().idle_s == 45.0


def test_the_fortune_is_the_hats_only(monkeypatch):
    from fish_brain.config import PERSONAS, FortuneConfig, PlaceConfig
    from fish_brain.fortune_bank import FORTUNE_PHRASES, FORTUNE_RULES
    monkeypatch.delenv("FISH_SHOW", raising=False)
    monkeypatch.setenv("FISH_PERSONA", "fish")
    assert FortuneConfig().rules == ""
    assert not any(n.startswith("fortune_") for n in CannedConfig().phrases)
    monkeypatch.setenv("FISH_PERSONA", "hat")
    assert FortuneConfig().rules == FORTUNE_RULES and PERSONAS["hat"]["fortune"]["rules"] == FORTUNE_RULES
    assert set(FORTUNE_PHRASES) <= set(CannedConfig().phrases)      # with or without the show
    assert FortuneConfig().deck == "tarot" and FortuneConfig().cup is False
    assert FortuneConfig().reprompts == 2 and FortuneConfig().reading_s == 8.0
    assert FortuneConfig().state.endswith("fish_brain/fortune.json")
    monkeypatch.setenv("FISH_FORTUNE_DECK", "off")
    monkeypatch.setenv("FISH_FORTUNE_CUP", "true")
    monkeypatch.setenv("FISH_FORTUNE_STATE", "/tmp/f.json")
    assert FortuneConfig().deck == "off" and FortuneConfig().cup is True
    assert FortuneConfig().state == "/tmp/f.json"
    monkeypatch.setenv("FISH_FORTUNE_DECK", "loteria")
    assert FortuneConfig().deck == "tarot"                           # unknown: the default
    assert PlaceConfig().place == "otro" and PlaceConfig().text == ""
    monkeypatch.setenv("FISH_PLACE", "Fiesta")
    monkeypatch.setenv("FISH_PLACE_TEXT", "x" * 80)
    assert PlaceConfig().place == "fiesta" and len(PlaceConfig().text) == 60
    monkeypatch.setenv("FISH_PLACE", "mars")
    assert PlaceConfig().place == "otro"


def test_the_hat_has_no_ingredient_bank(monkeypatch):
    monkeypatch.setenv("FISH_PERSONA", "hat")
    assert VisitConfig().future == {}           # the verdict comes from the visitor, not a bank
    monkeypatch.setenv("FISH_PERSONA", "fish")
    assert VisitConfig().future == {}


def test_the_visit_rules_are_the_adult_ones(monkeypatch):
    monkeypatch.setenv("FISH_PERSONA", "hat")
    r = VisitConfig().rules
    assert "FORMATO" in r and "REGLAS FIJAS" in r and "BANCO DE PREGUNTAS" in r and "CASA:" in r
    assert "público adulto" in r and "tenebroso y pícaro" in r and "humor negro" in r
    for move in ("Eco", "Arcoíris"):
        assert move in r
    # the cues: all material, never the age, the latest win, themes not names
    assert "LAS PISTAS" in r and "todas son material" in r and "no hace falta decirla" in r
    assert "valen las últimas" in r and "el tema, nunca el nombre" in r
    # the place, as the fortune has it
    assert "EL LUGAR" in r and "brindis" in r and "ofrenda" in r and "pasillos" in r and "profesor" in r
    # the verdict: one prediction from their words, a cue and the place; no list, hour or venue
    assert "una sola predicción" in r and "algo que dijo, una pista y el lugar" in r
    assert "ni hora" not in r and "solo si el visitante lo dijo" in r
    assert "30 palabras" in r and "10 palabras" in r
    assert "[FUTURO" not in r and "ingredientes" not in r
    # the question bank kept, with the adult questions
    assert "una isla" in r and "puerta cerrada" in r and "fantasma" in r and "quidditch" in r and "EL CASTILLO" in r
    # the kid register gone
    for kid in ("Público familiar", "niños", "niño o niña", "calaverita", "con el adulto",
                "nada da miedo"):
        assert kid not in r, kid
    assert "enfermedades" in r and "lotería" in r and "hombre o mujer" in r
    # the example has no clock time and no named venue (small models copy examples)
    example = re.sub(r"\[ETAPA \d/\d\]", "", r[r.index("EJEMPLO"):])
    assert not re.search(r"\d|\ba las\b|en punto", example)
    assert "Plaza" not in example


def test_the_hat_spells_its_english_right_and_jorge_hears_a_respelling(monkeypatch):
    from fish_brain.say_as import voice_text
    monkeypatch.setenv("FISH_PERSONA", "hat")
    cfg = TTSConfig()
    shown = "¡Hufflepuff! ¡Feliz Halloween! Mis costuras no mienten: ¡Slytherin!"
    spoken = voice_text(shown, cfg.loq_prefix, cfg.loq_hum, cfg.say_as)
    assert "Jafel paf" in spoken and "Jálowin" in spoken and "Slíderin" in spoken
    assert "Grifindór" in voice_text("¡Gryffindor!", cfg.loq_prefix, cfg.loq_hum, cfg.say_as)
    assert "Réivenclo" in voice_text("¡Ravenclaw!", cfg.loq_prefix, cfg.loq_hum, cfg.say_as)
