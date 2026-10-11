"""The LLM conversation's history helpers: per-visitor rules and seeded pairs (no network)."""
from __future__ import annotations

import pytest

from fish_brain import llm
from fish_brain.config import LLMConfig


@pytest.fixture
def convo(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    return llm.Conversation(LLMConfig(profile="groq", max_history_turns=2))


def test_extra_rules_follow_the_persona(convo):
    assert [m["role"] for m in convo._messages("hola")] == ["system", "user"]
    convo.extra_rules = "Reglas del visitante."
    msgs = convo._messages("hola")
    assert [m["role"] for m in msgs] == ["system", "system", "user"]
    assert msgs[0]["content"] == convo.cfg.system_prompt
    assert msgs[1]["content"] == "Reglas del visitante."
    assert msgs[-1] == {"role": "user", "content": "hola"}


def test_remember_seeds_a_pair_before_the_history_tail(convo):
    convo.remember("[Lectura] se llama Ana.", "¿Tú eres Ana?")
    msgs = convo._messages("sí")
    assert msgs[1:] == [{"role": "user", "content": "[Lectura] se llama Ana."},
                        {"role": "assistant", "content": "¿Tú eres Ana?"},
                        {"role": "user", "content": "sí"}]


def test_remember_trims_to_the_last_pairs(convo):
    for i in range(5):
        convo.remember(f"u{i}", f"a{i}")
    assert [m["content"] for m in convo._history] == ["u3", "a3", "u4", "a4"]


def test_reset_clears_rules_and_history(convo):
    convo.extra_rules = "x"
    convo.remember("u", "a")
    convo.reset()
    assert convo.extra_rules == "" and convo._history == []
    assert [m["role"] for m in convo._messages("hola")] == ["system", "user"]
