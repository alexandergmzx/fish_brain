"""FISH_PERSONA: the body's words (the fish by default, the Sorting Hat for the fair)."""
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
    assert set(hat) - set(fish) == VISIT_PHRASES       # and only the visit's greeting added
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


def test_the_hats_future_bank_is_full_and_clean(monkeypatch):
    monkeypatch.setenv("FISH_PERSONA", "hat")
    bank = VisitConfig().future
    for kind in ("lugar", "cosa", "noche", "antojo", "acción", "carta"):
        assert len(bank[kind]) >= 5, kind
    words = " ".join(" ".join(v) for v in bank.values() if isinstance(v, list)).lower()
    for bad in ("pájaro", "chile", "plátano", "huevo", "muerte", "calavera", "diablito", "borracho",
                "inundación", "rayo", "biblioteca", "pato", "ardilla", "cartón"):
        assert bad not in words, bad
    monkeypatch.setenv("FISH_PERSONA", "fish")
    assert VisitConfig().future == {}
