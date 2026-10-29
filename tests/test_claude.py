"""Claude: the chat conversation, the error mapping, the badge call and the reading's schema.
No network, no key and (but for the last test) no `anthropic` package: the SDK is a fake."""
from __future__ import annotations

import json
import subprocess
import sys
import types
from types import SimpleNamespace

import pytest

from fish_brain import ab, claude, cloud, debug, llm, reading
from fish_brain.config import LLM_PROFILES, Config, LLMConfig

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60
GOOD = {"badge_found": True, "full_name": "GARCIA LOPEZ MARIA JOSE", "given_names": "MARIA JOSE",
        "surnames": "GARCIA LOPEZ", "name_for_speech": "María José", "look": None,
        "confidence": "high"}


# ---- stand-ins for the SDK: errors named like its own -------------------------------------------

class AnthropicError(Exception):
    pass


class APIError(AnthropicError):
    pass


class APIConnectionError(APIError):
    pass


class APITimeoutError(APIConnectionError):
    pass


class APIStatusError(APIError):
    def __init__(self, message="boom", status=500):
        super().__init__(message)
        self.status_code = status


class BadRequestError(APIStatusError):
    def __init__(self, message="bad request"):
        super().__init__(message, 400)


class AuthenticationError(APIStatusError):
    def __init__(self, message="invalid x-api-key"):
        super().__init__(message, 401)


class PermissionDeniedError(APIStatusError):
    def __init__(self, message="forbidden"):
        super().__init__(message, 403)


class NotFoundError(APIStatusError):
    def __init__(self, message="model not found"):
        super().__init__(message, 404)


class RateLimitError(APIStatusError):
    def __init__(self, message="rate limited"):
        super().__init__(message, 429)


class InternalServerError(APIStatusError):
    def __init__(self, message="overloaded", status=529):
        super().__init__(message, status)


def response(text="Hola.", *, stop="end_turn", thinking=False, usage=(10, 5), cache=(0, 0),
             category=None):
    """A Messages response: optional thinking block first, one text block."""
    content = [SimpleNamespace(type="thinking", thinking="")] if thinking else []
    if text is not None:
        content.append(SimpleNamespace(type="text", text=text))
    return SimpleNamespace(
        content=content, stop_reason=stop,
        stop_details=SimpleNamespace(category=category) if category else None,
        usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1],
                              cache_read_input_tokens=cache[0],
                              cache_creation_input_tokens=cache[1]))


class FakeClient:
    """Records every `messages.create`; answers with the scripted outcomes in order (an
    exception is raised, anything else returned), then repeats the last."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes) or [response()]
        self.calls: list[dict] = []
        self.options: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        out = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(out, BaseException):
            raise out
        return out

    def with_options(self, **kw):
        self.options.append(kw)
        return self


@pytest.fixture
def convo():
    return claude.Conversation(LLMConfig(profile="claude"), client=FakeClient())


def chat(*outcomes, profile="claude", **cfg):
    return claude.Conversation(LLMConfig(profile=profile, **cfg), client=FakeClient(*outcomes))


def fake_sdk(monkeypatch):
    """Put a fake `anthropic` module in place; returns what its constructors were given."""
    seen: dict = {}

    class Timeout:
        def __init__(self, timeout=None, *, connect=None):
            self.timeout, self.connect = timeout, connect

    class Anthropic:
        def __init__(self, **kw):
            seen["client"] = kw
            self.kw = kw
            self.messages = SimpleNamespace(create=lambda **k: response())

        def with_options(self, **kw):
            return self

    mod = types.ModuleType("anthropic")
    mod.Anthropic, mod.Timeout = Anthropic, Timeout
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    monkeypatch.setattr(claude, "_shared", {})
    return seen


@pytest.fixture
def hub():
    h = debug.install(Config())
    try:
        yield h
    finally:
        debug.uninstall()


# ---- the profile -----------------------------------------------------------------------------------

def test_the_claude_profiles_are_anthropic_and_never_carry_a_sampling_setting():
    for name, model in (("claude", "claude-haiku-5-5"), ("claude-sonnet", "claude-sonnet-5-5")):
        cfg = LLMConfig(profile=name)
        assert (cfg.provider, cfg.model, cfg.api_key_env) == ("anthropic", model, "ANTHROPIC_API_KEY")
        assert cfg.temperature is None and cfg.vision is True
        assert cfg.base_url == "https://api.anthropic.com"
    assert LLMConfig(profile="claude").max_completion_tokens == 2000
    assert LLMConfig(profile="claude").thinking == "adaptive"
    assert LLMConfig(profile="claude-sonnet").thinking == "between_tools"


def test_the_openai_profiles_are_as_they_were():
    for name, vision in (("groq", False), ("luna", True)):
        cfg = LLMConfig(profile=name)
        assert (cfg.provider, cfg.vision, cfg.thinking) == ("openai", vision, None)
        assert (cfg.max_completion_tokens, cfg.timeout_s) == (400, 8.0)


def test_an_unknown_thinking_mode_is_refused(monkeypatch):
    monkeypatch.setitem(LLM_PROFILES, "odd", {**LLM_PROFILES["claude"], "thinking": "always"})
    with pytest.raises(ValueError, match="thinking"):
        LLMConfig(profile="odd")


def test_the_model_and_effort_overrides_reach_only_the_active_profile(monkeypatch):
    monkeypatch.setenv("FISH_LLM_PROFILE", "claude")
    monkeypatch.setenv("FISH_LLM_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("FISH_LLM_REASONING", "medium")
    assert LLMConfig().model == "claude-sonnet-5-5" and LLMConfig().reasoning_effort == "medium"
    assert LLMConfig(profile="claude-sonnet").model == "claude-sonnet-5-5"
    assert LLMConfig(profile="luna").model == LLM_PROFILES["luna"]["model"]


# ---- the request -------------------------------------------------------------------------------------

def test_the_request_is_the_persona_the_history_and_the_turn(convo):
    assert convo.reply("hola") == "Hola."
    (call,) = convo._client.calls
    assert call["model"] == "claude-haiku-5-5" and call["max_tokens"] == 2000
    assert call["system"] == [{"type": "text", "text": convo.cfg.system_prompt}]
    assert call["messages"] == [{"role": "user", "content": "hola"}]
    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"] == {"effort": "low"}
    assert not {"temperature", "top_p", "top_k"} & set(call)


def test_the_fortunes_reading_turns_thinking_off_until_the_next_visitor():
    """ADR 0026: the reading's call sets `thinking` over the profile's; the visit's reset clears it."""
    from fish_brain import fortune
    from fish_brain.fortune_run import reading_request
    from fish_brain.visit import begin_model
    c = chat(response("Lectura."), response("Visita."))
    reading_request(c, "reglas", fortune.Fortune(), None, thinking="disabled")
    c.reply("[ADIVINACIÓN: ] Haz la lectura.", remember=False)
    begin_model(c, "reglas de la visita")
    c.reply("hola")
    first, second = c._client.calls
    assert first["thinking"] == {"type": "disabled"} and first["output_config"] == {"effort": "low"}
    assert second["thinking"] == {"type": "adaptive"} and c.thinking is None
    reading_request(c, "reglas", fortune.Fortune(), None)          # "" = the profile's own
    assert c.thinking is None


def test_the_visitors_rules_are_a_second_system_block(convo):
    convo.extra_rules = "Reglas del visitante."
    convo.remember("[Lectura] se llama Ana.", "¿Tú eres Ana?")
    convo.reply("sí")
    call = convo._client.calls[0]
    assert [b["text"] for b in call["system"]] == [convo.cfg.system_prompt, "Reglas del visitante."]
    assert call["messages"][0]["role"] == "user"                    # the first turn is the visitor's
    assert [m["role"] for m in call["messages"]] == ["user", "assistant", "user"]


def test_no_effort_is_sent_when_the_setting_is_empty_or_none(monkeypatch):
    for value in ("", "none"):
        monkeypatch.setenv("FISH_LLM_PROFILE", "claude")
        monkeypatch.setenv("FISH_LLM_REASONING", value)
        c = claude.Conversation(LLMConfig(), client=FakeClient())
        c.reply("hola")
        assert "output_config" not in c._client.calls[0]


def test_a_reply_the_caller_remembers_leaves_the_history(convo):
    assert convo.reply("[ETAPA 1/4] hola", remember=False) == "Hola."
    assert convo._history == []
    assert convo.reply("hola") == "Hola."                       # the default remembers
    assert convo._history == [{"role": "user", "content": "hola"},
                              {"role": "assistant", "content": "Hola."}]


def test_an_empty_turn_in_the_history_is_never_sent(convo):
    convo._history = [{"role": "user", "content": "uno"}, {"role": "assistant", "content": " "},
                      {"role": "user", "content": "dos"}, {"role": "assistant", "content": "Ya."}]
    convo.reply("tres")
    assert [m["content"] for m in convo._client.calls[0]["messages"]] == ["uno", "dos", "Ya.", "tres"]


def test_the_text_is_read_by_block_type_after_a_thinking_block():
    c = chat(response("Hola, viajero.", thinking=True))
    assert c.reply("hola") == "Hola, viajero."


# ---- what is not a reply -----------------------------------------------------------------------------

def test_a_thinking_only_reply_is_the_fallback_and_leaves_the_history():
    c = chat(response(None, stop="max_tokens", thinking=True, usage=(40, 600)))
    assert c.reply("hola") == c.cfg.fallback_reply
    assert c.last_error == "empty reply (stop_reason=max_tokens)"
    assert c._history == [] and c.last_usage.completion_tokens == 600       # billed all the same


def test_a_refusal_is_the_fallback_with_its_category_and_the_history_untouched():
    c = chat(response(None, stop="refusal", category="cyber"))
    assert c.reply("hola") == c.cfg.fallback_reply
    assert c.last_error == "refusal:cyber" and c._history == []


def test_a_cut_reply_is_still_spoken():
    c = chat(response("Hola, viajero que", stop="max_tokens"))
    assert c.reply("hola") == "Hola, viajero que" and c.last_error is None


def test_usage_is_the_openai_shape_with_cached_tokens_counted(convo):
    convo._client.outcomes = [response(usage=(100, 40), cache=(20, 5))]
    convo.reply("hola")
    u = convo.last_usage
    assert (u.prompt_tokens, u.completion_tokens) == (125, 40)
    assert vars(u) == {"prompt_tokens": 125, "completion_tokens": 40,
                       "cache_read_tokens": 20, "cache_write_tokens": 5}      # debug_state reads __dict__
    assert ab._cost(convo.cfg, u) == pytest.approx((125 * 0.10 + 40 * 0.50) / 1e6)


# ---- errors ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("exc,unavailable", [
    (APIConnectionError("Connection error."), True),
    (APITimeoutError("Request timed out."), True),
    (RateLimitError(), True),
    (InternalServerError(), True),                      # 529, overloaded
    (APIStatusError("gateway", 502), True),
    (APIStatusError("timeout", 408), True),
    (AuthenticationError(), False),
    (PermissionDeniedError(), False),
    (NotFoundError(), False),
    (APIStatusError("payment required", 402), False),
    (APIStatusError("too large", 413), False),
    (BadRequestError(), False),
])
def test_sdk_errors_map_to_the_two_cloud_errors(exc, unavailable, monkeypatch):
    monkeypatch.setattr(cloud, "mark_offline", lambda: pytest.fail("a Claude error is not the net's"))
    got = claude.classify(exc)
    assert isinstance(got, cloud.CloudUnavailable if unavailable else cloud.CloudMisconfigured)
    assert claude.is_sdk_error(exc) and not claude.is_sdk_error(RuntimeError("x"))


def test_an_api_error_is_the_fallback_not_a_crash_and_never_marks_the_net_offline(monkeypatch):
    monkeypatch.setattr(cloud, "mark_offline", lambda: pytest.fail("a Claude error is not the net's"))
    c = chat(APIConnectionError("Connection error."))
    assert c.reply("hola") == c.cfg.fallback_reply
    assert c.last_error == "APIConnectionError: Connection error." and c._history == []
    c = chat(AuthenticationError())
    assert c.reply("hola") == c.cfg.fallback_reply and "AuthenticationError" in c.last_error


def test_an_error_of_our_own_is_not_swallowed():
    with pytest.raises(RuntimeError, match="mine"):
        chat(RuntimeError("mine")).reply("hola")


def test_claude_is_not_held_back_by_the_openai_probe(monkeypatch):
    monkeypatch.setattr(cloud, "is_online", lambda: False)         # api.openai.com unreachable
    c = chat()
    assert c.reply("hola") == "Hola." and len(c._client.calls) == 1


def test_a_400_that_names_thinking_is_retried_once_without_it_and_remembered():
    c = chat(BadRequestError("thinking.type: disabled is not supported for this model"),
             response("Hola."))
    assert c.reply("hola") == "Hola."
    first, second = c._client.calls
    assert "thinking" in first and "thinking" not in second and "output_config" in second
    assert c._dropped == {"thinking"}
    c.reply("otra")
    assert "thinking" not in c._client.calls[-1]


def test_a_second_400_is_the_fallback_one_retry_only():
    c = chat(BadRequestError("thinking is not supported"),
             BadRequestError("output_config.effort is not supported"))
    assert c.reply("hola") == c.cfg.fallback_reply and len(c._client.calls) == 2
    assert c._dropped == {"thinking"} and c.last_error.startswith("BadRequestError")
    assert c.reply("otra") == c.cfg.fallback_reply          # the next turn drops what it names
    assert c._dropped == {"thinking", "effort"}


def test_a_400_that_names_nothing_is_not_retried_and_nothing_is_dropped():
    c = chat(BadRequestError("messages.0.content: text content blocks must be non-empty"))
    assert c.reply("hola") == c.cfg.fallback_reply
    assert len(c._client.calls) == 1 and c._dropped == set()


# ---- /debug -------------------------------------------------------------------------------------------

def test_the_call_is_recorded_for_the_debug_page_in_the_openai_shape(hub, convo):
    convo.extra_rules = "Reglas."
    convo.reply("hola")
    rec = hub.recent("llm")[-1]
    assert [m["role"] for m in rec["messages"]] == ["system", "system", "user"]
    assert rec["reply"] == "Hola." and rec["finish"] == "stop" and rec["stop_reason"] == "end_turn"
    assert rec["tokens"] == {"prompt": 10, "completion": 5} and rec["model"] == "claude-haiku-5-5"
    assert rec["params"] == {"max_tokens": 2000, "thinking": {"type": "adaptive"},
                             "output_config": {"effort": "low"}}


def test_a_refusal_and_an_error_are_recorded_too(hub):
    chat(response(None, stop="refusal", category="bio")).reply("hola")
    rec = hub.recent("llm")[-1]
    assert rec["reply"] == "" and rec["finish"] == "content_filter"
    chat(RateLimitError()).reply("hola")
    assert hub.recent("llm")[-1]["error"] == {"type": "RateLimitError", "status": 429,
                                              "text": "rate limited"}


def test_an_anthropic_key_in_an_error_text_is_scrubbed(hub, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-FAKEFAKEFAKE1234")
    hub2 = debug.install(Config())               # the hub collects the keys of the environment
    try:
        chat(AuthenticationError("invalid x-api-key: sk-ant-api03-FAKEFAKEFAKE1234")).reply("hola")
        assert "FAKEFAKE" not in repr(hub2.recent("llm"))
    finally:
        debug.uninstall()


def test_probe_leaves_state_alone_and_does_not_retry(convo):
    convo.remember("u", "a")
    assert convo.probe() == {"seconds": pytest.approx(0, abs=1), "model": "claude-haiku-5-5",
                             "reply": "Hola."}
    assert convo._client.options == [{"max_retries": 0, "timeout": 6.0}]
    assert convo._client.calls[0]["max_tokens"] == 64
    assert convo._client.calls[0]["messages"] == [{"role": "user", "content": "Responde solo: ok"}]
    assert len(convo._history) == 2 and convo.last_usage is None and convo.last_error is None


# ---- construction and the leak guards -------------------------------------------------------------

def test_without_a_key_it_says_so_before_it_needs_the_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)         # not installed either
    with pytest.raises(cloud.CloudMisconfigured, match="ANTHROPIC_API_KEY is not set"):
        claude.Conversation(LLMConfig(profile="claude"))


def test_without_the_package_it_says_so(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-0000")
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(cloud.CloudMisconfigured, match="anthropic package is not installed"):
        claude.Conversation(LLMConfig(profile="claude"))
    with pytest.raises(cloud.CloudMisconfigured, match="not installed"):
        claude.ready("ANTHROPIC_API_KEY")


def test_the_client_gets_the_key_the_host_and_the_short_timeouts_explicitly(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-0000")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://evil.example")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "another-credential")
    seen = fake_sdk(monkeypatch)
    c = llm.make_conversation(LLMConfig(profile="claude"))
    assert isinstance(c, claude.Conversation)
    kw = seen["client"]
    assert kw["api_key"] == "sk-ant-test-0000" and kw["base_url"] == "https://api.anthropic.com"
    assert kw["max_retries"] == 0                       # the SDK would honour any Retry-After
    assert (kw["timeout"].timeout, kw["timeout"].connect) == (8.0, 3.0)
    assert set(kw) == {"api_key", "base_url", "timeout", "max_retries"}


def test_each_provider_refuses_the_others_profile(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-0000")
    with pytest.raises(cloud.CloudMisconfigured, match="make_conversation"):
        claude.Conversation(LLMConfig(profile="groq"), client=FakeClient())
    with pytest.raises(cloud.CloudMisconfigured, match="make_conversation"):
        llm.Conversation(LLMConfig(profile="claude"))              # its key would go to api.openai.com
    assert isinstance(llm.make_conversation(LLMConfig(profile="groq")), llm.Conversation)
    with pytest.raises(ValueError, match="unknown LLM provider"):
        llm.make_conversation(SimpleNamespace(provider="x", profile="x"))


def test_the_anthropic_key_is_never_handed_to_an_openai_client():
    with pytest.raises(cloud.CloudMisconfigured, match="Anthropic client"):
        cloud.client("", "ANTHROPIC_API_KEY")


def test_importing_the_fish_does_not_import_the_sdk():
    code = ("import sys; import fish_brain.llm, fish_brain.claude, fish_brain.reading, "
            "fish_brain.config, fish_brain.cloud, fish_brain.ab; "
            "sys.exit(1 if 'anthropic' in sys.modules else 0)")
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


# ---- the badge ------------------------------------------------------------------------------------------

def test_the_nullable_fields_become_anyof_and_the_original_is_untouched():
    before = json.dumps(reading.BADGE_SCHEMA, sort_keys=True)
    out = claude.anthropic_schema(reading.BADGE_SCHEMA)
    assert json.dumps(reading.BADGE_SCHEMA, sort_keys=True) == before
    props = out["properties"]
    assert props["full_name"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert props["badge_found"] == {"type": "boolean"}
    assert props["confidence"] == {"type": "string", "enum": ["high", "medium", "low"]}
    assert out["required"] == reading.BADGE_SCHEMA["required"] and out["additionalProperties"] is False
    assert "null\"]" not in json.dumps(out)                            # no type list is left


def test_a_json_object_is_found_in_a_fence_or_a_sentence():
    obj = '{"badge_found": true}'
    for wrapped in (obj, "```json\n" + obj + "\n```", "Aquí está: " + obj + " Listo."):
        assert claude._json_object(wrapped) == obj
    assert claude._json_object("no hay nada") == "no hay nada"


@pytest.fixture
def vision(monkeypatch):
    """Claude's vision call against a fake client; returns that client."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-0000")
    fake_sdk(monkeypatch)
    monkeypatch.setattr(claude, "_vision_rejected", set())
    client = FakeClient(response(json.dumps(GOOD), usage=(777, 60)))
    client.asked_for = []                         # (key variable, host) of every shared_client call

    def shared(api_key_env, base_url, *a, **k):
        client.asked_for.append((api_key_env, base_url))
        return client

    monkeypatch.setattr(claude, "shared_client", shared)
    return client


def ask(**kw):
    args = dict(system="SISTEMA", jpeg=JPEG, ask="Lee el gafete.", schema=reading.BADGE_SCHEMA,
                timeout_s=7.0)
    return claude.ask_badge(LLM_PROFILES["claude"], **{**args, **kw})


def test_the_badge_request_is_an_image_a_question_and_the_schema(vision):
    answer = ask()
    (call,) = vision.calls
    assert call["model"] == "claude-haiku-5-5" and call["system"] == "SISTEMA"
    assert call["max_tokens"] == claude.VISION_MAX_TOKENS
    image, text = call["messages"][0]["content"]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/jpeg"
    assert image["source"]["type"] == "base64" and image["source"]["data"].startswith("/9j/")
    assert "data:" not in image["source"]["data"]
    assert text == {"type": "text", "text": "Lee el gafete."}
    fmt = call["output_config"]["format"]
    assert fmt["type"] == "json_schema" and set(fmt) == {"type", "schema"}          # no name, no strict
    assert fmt["schema"] == claude.anthropic_schema(reading.BADGE_SCHEMA)
    assert call["output_config"]["effort"] == "low" and call["thinking"] == {"type": "adaptive"}
    assert not {"temperature", "top_p", "top_k"} & set(call)
    assert json.loads(answer.text) == GOOD and answer.usage.prompt_tokens == 777
    assert vision.asked_for == [("ANTHROPIC_API_KEY", "https://api.anthropic.com")]   # the key and host
    (opts,) = vision.options
    assert (opts["timeout"].timeout, opts["timeout"].connect) == (7.0, 3.0) and opts["max_retries"] == 0


@pytest.mark.parametrize("response_,found", [
    (response("", stop="refusal", category="general_harms"), False),
    (response(json.dumps(GOOD), stop="max_tokens"), False),
    (response("{not json"), False),
    (response("```json\n" + json.dumps(GOOD) + "\n```"), True),
])
def test_what_the_reader_makes_of_each_kind_of_answer(vision, response_, found):
    vision.outcomes = [response_]
    parsed = reading._parse_badge(ask(), 1.0, want_look=False)
    assert parsed.found is found
    assert parsed.tokens == 10


def test_a_schema_the_api_refuses_is_asked_again_in_words_and_remembered(vision):
    vision.outcomes = [BadRequestError("output_config.format: unsupported type list"),
                       response("```json\n" + json.dumps(GOOD) + "\n```")]
    answer = ask()
    first, second = vision.calls
    assert "format" in first["output_config"] and "format" not in second["output_config"]
    assert second["messages"][0]["content"][1]["text"].startswith("Lee el gafete. Responde solo con un objeto JSON")
    assert json.loads(answer.text) == GOOD                                  # the fence is gone
    vision.outcomes = [response(json.dumps(GOOD))]
    ask()
    assert "format" not in vision.calls[-1]["output_config"]                # not tried again
    assert ("format", "claude-haiku-5-5") in claude._vision_rejected


def test_several_refused_settings_are_dropped_one_retry_at_a_time(vision):
    vision.outcomes = [BadRequestError("thinking is not supported"),
                       BadRequestError("output_config.effort is not supported"),
                       response(json.dumps(GOOD))]
    ask()
    assert len(vision.calls) == 3
    last = vision.calls[-1]
    assert "thinking" not in last and "effort" not in last["output_config"] and "format" in last["output_config"]


def test_a_400_about_the_image_does_not_cost_the_schema(vision):
    vision.outcomes = [BadRequestError("messages.0.content.0.image: could not process image format")]
    with pytest.raises(cloud.CloudMisconfigured, match="BadRequestError"):
        ask()
    assert len(vision.calls) == 1 and claude._vision_rejected == set()


@pytest.mark.parametrize("exc,expected", [
    (APITimeoutError("Request timed out."), cloud.CloudUnavailable),
    (RateLimitError(), cloud.CloudUnavailable),
    (AuthenticationError(), cloud.CloudMisconfigured),
    (APIStatusError("payment required", 402), cloud.CloudMisconfigured),
])
def test_the_badge_call_raises_only_the_two_cloud_errors(vision, exc, expected, monkeypatch):
    monkeypatch.setattr(cloud, "mark_offline", lambda: pytest.fail("a Claude error is not the net's"))
    vision.outcomes = [exc]
    with pytest.raises(expected):
        ask()


def test_an_error_of_our_own_in_the_badge_call_is_not_swallowed(vision):
    vision.outcomes = [RuntimeError("mine")]
    with pytest.raises(RuntimeError, match="mine"):
        ask()


def test_a_sonnet_profile_sends_its_own_thinking_mode(vision):
    claude.ask_badge(LLM_PROFILES["claude-sonnet"], system="S", jpeg=JPEG, ask="Lee.",
                     schema=reading.BADGE_SCHEMA, timeout_s=7.0)
    call = vision.calls[-1]
    assert call["model"] == "claude-sonnet-5-5" and call["thinking"] == {"type": "between_tools"}
    assert vision.options[-1]["max_retries"] == 0


def test_the_shared_client_is_one_per_key_and_follows_a_new_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-one")
    seen = fake_sdk(monkeypatch)
    a = claude.shared_client("ANTHROPIC_API_KEY", "https://api.anthropic.com")
    assert claude.shared_client("ANTHROPIC_API_KEY", "https://api.anthropic.com") is a
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-two")
    b = claude.shared_client("ANTHROPIC_API_KEY", "https://api.anthropic.com")
    assert b is not a and seen["client"]["api_key"] == "sk-ant-two"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(cloud.CloudMisconfigured, match="not set"):
        claude.shared_client("ANTHROPIC_API_KEY", "https://api.anthropic.com")


# ---- against the real SDK (skipped where it is not installed) ----------------------------------------------

def test_the_real_sdk_agrees_with_the_stand_ins(monkeypatch):
    anthropic = pytest.importorskip("anthropic")
    import inspect
    import httpx2
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-0000")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "another-credential")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://evil.example")
    client = claude._make_client("ANTHROPIC_API_KEY", "https://api.anthropic.com", 8.0)
    assert str(client.base_url).rstrip("/") == "https://api.anthropic.com"
    assert client.auth_headers == {"Authorization": "Bearer sk-ant-test-0000"}        # one credential
    assert client.max_retries == 0
    params = inspect.signature(client.messages.create).parameters
    assert {"system", "thinking", "output_config", "max_tokens"} <= set(params)
    assert not {"temperature", "top_p", "top_k"} & set(params)
    # The schema in the form the API takes (the SDK's own check refuses a type list).
    anthropic.transform_schema(claude.anthropic_schema(reading.BADGE_SCHEMA))
    with pytest.raises(AssertionError):
        anthropic.transform_schema(reading.BADGE_SCHEMA)
    # Real responses and errors, built offline.
    msg = anthropic.types.Message.model_validate({
        "id": "m", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
        "content": [{"type": "thinking", "thinking": "", "signature": "s"},
                    {"type": "text", "text": "Hola"}],
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5}})
    got = claude.answer_from(msg)
    assert got.text == "Hola" and (got.usage.prompt_tokens, got.usage.completion_tokens) == (10, 5)
    refusal = anthropic.types.Message.model_validate({
        "id": "m", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
        "content": [], "stop_reason": "refusal", "stop_sequence": None,
        "stop_details": {"type": "refusal", "category": "cyber", "explanation": "x"},
        "usage": {"input_tokens": 10, "output_tokens": 0}})
    assert claude.answer_from(refusal).refusal == "refusal:cyber"
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    for exc, kind in ((anthropic.APIConnectionError(request=req), cloud.CloudUnavailable),
                      (anthropic.APITimeoutError(request=req), cloud.CloudUnavailable),
                      (anthropic.RateLimitError("m", response=httpx2.Response(429, request=req), body=None),
                       cloud.CloudUnavailable),
                      (anthropic.InternalServerError("m", response=httpx2.Response(529, request=req), body=None),
                       cloud.CloudUnavailable),
                      (anthropic.AuthenticationError("m", response=httpx2.Response(401, request=req), body=None),
                       cloud.CloudMisconfigured)):
        assert isinstance(claude.classify(exc), kind) and claude.is_sdk_error(exc)
    bad = anthropic.BadRequestError("thinking: not supported",
                                    response=httpx2.Response(400, request=req), body=None)
    assert claude._rejected(bad, claude._CHAT_WORDS) == ["thinking"]


# ---- what the real SDK puts on the wire (mock transport: no network) -------------------------------

def wire_client(monkeypatch, handler):
    """A real `anthropic.Anthropic` whose HTTP goes to `handler`, installed as the shared client
    and the chat's; returns the requests the handler saw."""
    anthropic = pytest.importorskip("anthropic")
    import httpx2
    seen: list = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-0000")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "another-credential")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://evil.example")

    def make(api_key_env, base_url, timeout_s):
        return anthropic.Anthropic(
            api_key="sk-ant-test-0000", base_url=base_url, max_retries=claude.SDK_RETRIES,
            http_client=httpx2.Client(transport=httpx2.MockTransport(wrapped)))

    monkeypatch.setattr(claude, "_make_client", make)
    monkeypatch.setattr(claude, "_shared", {})
    monkeypatch.setattr(claude, "_vision_rejected", set())
    return seen


def ok_message(text="Hola."):
    import httpx2
    return httpx2.Response(200, json={
        "id": "m", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
        "stop_sequence": None, "usage": {"input_tokens": 12, "output_tokens": 3}})


def test_the_chat_request_on_the_wire_has_one_credential_the_right_host_and_no_sampling(monkeypatch):
    seen = wire_client(monkeypatch, lambda request: ok_message("Hola, viajero."))
    c = claude.Conversation(LLMConfig(profile="claude"))
    c.extra_rules = "Reglas."
    assert c.reply("hola") == "Hola, viajero."
    (req,) = seen
    assert req.url.host == "api.anthropic.com" and req.url.path == "/v1/messages"
    assert req.headers["authorization"] == "Bearer sk-ant-test-0000" and "x-api-key" not in req.headers
    assert req.headers["anthropic-version"] == "2026-10-21"
    body = json.loads(req.content)
    assert body["model"] == "claude-haiku-5-5" and body["max_tokens"] == 2000
    assert [b["text"] for b in body["system"]] == [c.cfg.system_prompt, "Reglas."]
    assert body["messages"] == [{"role": "user", "content": "hola"}]
    assert body["thinking"] == {"type": "adaptive"} and body["output_config"] == {"effort": "low"}
    assert not {"temperature", "top_p", "top_k"} & set(body)


def test_the_badge_request_on_the_wire_is_an_image_and_the_converted_schema(monkeypatch):
    seen = wire_client(monkeypatch, lambda request: ok_message(json.dumps(GOOD)))
    answer = claude.ask_badge(LLM_PROFILES["claude"], system="SISTEMA", jpeg=JPEG,
                              ask="Lee el gafete.", schema=reading.BADGE_SCHEMA, timeout_s=7.0)
    (req,) = seen
    assert req.url.host == "api.anthropic.com" and "x-api-key" not in req.headers
    body = json.loads(req.content)
    image, text = body["messages"][0]["content"]
    assert image["source"]["data"].startswith("/9j/") and image["source"]["media_type"] == "image/jpeg"
    assert text["text"] == "Lee el gafete." and body["system"] == "SISTEMA"
    assert body["output_config"]["format"]["schema"] == claude.anthropic_schema(reading.BADGE_SCHEMA)
    assert json.loads(answer.text) == GOOD


@pytest.mark.parametrize("retry_after", ["3", "3600"])
def test_a_rate_limit_is_never_waited_out_inside_the_sdk(monkeypatch, retry_after):
    import httpx2
    import time as time_module
    slept: list = []
    monkeypatch.setattr(time_module, "sleep", lambda s: slept.append(s))     # the SDK's own sleep
    seen = wire_client(monkeypatch, lambda request: httpx2.Response(
        429, headers={"retry-after": retry_after},
        json={"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}))
    c = claude.Conversation(LLMConfig(profile="claude"))
    assert c.reply("hola") == c.cfg.fallback_reply and c.last_error.startswith("RateLimitError")
    assert len(seen) == 1 and slept == []                    # one request, no sleep, the turn goes on
    with pytest.raises(cloud.CloudUnavailable):
        claude.ask_badge(LLM_PROFILES["claude"], system="S", jpeg=JPEG, ask="Lee.",
                         schema=reading.BADGE_SCHEMA, timeout_s=7.0)
    assert len(seen) == 2 and slept == []
