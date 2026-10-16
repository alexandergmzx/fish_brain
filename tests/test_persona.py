"""FISH_PERSONA: the body's words (the fish by default, the Sorting Hat for the fair)."""
import pytest

from fish_brain.config import PERSONAS, CannedConfig, LLMConfig, ReadingConfig


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
    assert set(hat) == set(fish)                       # the same phrase names, nothing lost
    assert "pez" not in hat["welcome"] and "Sombrero" in hat["welcome"]
    assert hat["filler_first_1"] == fish["filler_first_1"]
    assert hat["no_mic"] == fish["no_mic"]
    assert "burbujas" not in hat["timeout_stt_2"]
    assert "Sombrero" in LLMConfig().system_prompt
    assert "Glub" not in LLMConfig().fallback_reply
    assert "casa" in ReadingConfig().rules


def test_a_persona_lists_only_known_phrase_names():
    fish = PERSONAS["fish"]; hat = PERSONAS["hat"]
    assert fish == {}
    names = set(CannedConfig().phrases)
    assert set(hat["phrases"]) <= names


def test_unknown_persona_is_refused(monkeypatch):
    monkeypatch.setenv("FISH_PERSONA", "goat")
    with pytest.raises(ValueError):
        CannedConfig()
    with pytest.raises(ValueError):
        LLMConfig()
