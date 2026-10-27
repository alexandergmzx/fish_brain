# The Anthropic SDK, checked offline — 2026-10-26

Host: the desktop (Linux Mint, Python 3.12), `anthropic` 2.3.0 in `.venv`, fish_brain at commit
`fb6d0a6` plus the uncommitted Claude change ([ADR 0018](../adr/0018-claude-through-its-own-sdk.md)).
Level 0: no network, no key, no model call (a mock HTTP transport where a response was needed).
Question: what does the SDK do that the Claude code must allow for?

## Import time

    for m in openai anthropic; do for i in 1 2 3; do .venv/bin/python -X importtime -c "import $m" 2>&1 | tail -1; done; done

| Package | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| `openai` 2.41.0 | 0.35 s | 0.35 s | 0.35 s |
| `anthropic` 2.3.0 | 0.78 s | 0.78 s | 0.78 s |

The first Claude call pays this (on the board's CPU it will be longer: not measured). The call
logs `[claude] sdk imported in …` once, so the board's figure comes from its journal.

## The client

Probe (`ANTHROPIC_AUTH_TOKEN=tok` and `ANTHROPIC_BASE_URL=https://evil.example` in the environment):

    c = anthropic.Anthropic(api_key="sk-ant-test-0000", base_url="https://api.anthropic.com",
                            timeout=anthropic.Timeout(8.0, connect=3.0), max_retries=1)
    c.auth_headers; c.base_url; inspect.signature(c.messages.create)

| Question | Result |
|---|---|
| Credentials sent | `Authorization: Bearer sk-ant-test-0000` only; the token in the environment is not used |
| Host | `https://api.anthropic.com`; the explicit `base_url` beats `ANTHROPIC_BASE_URL` |
| API version header | `anthropic-version: 2026-10-21` |
| `temperature`, `top_p`, `top_k` in `messages.create` | none of the three exists |
| `system`, `thinking`, `output_config` | all three exist; `output_config` takes `effort` and `format` |
| `anthropic.transform_schema(BADGE_SCHEMA)` | `AssertionError` on `{"type": ["string", "null"]}`; the schema after `claude.anthropic_schema` passes |

## A rate-limited call

Mock transport: the first response is `429` with `retry-after: 3600`, the second is a normal
message; the SDK's `time.sleep` is replaced by a recorder.

| `max_retries` | Outcome | Requests | Sleeps asked for |
|---|---|---|---|
| 1 | the call succeeds | 2 | `[3600.0]` |
| 0 | `RateLimitError` at once | 1 | none |

The SDK honours the header with no cap (the `openai` SDK stops at 60 s) and the sleep is outside
the read timeout, so a Claude call could outlive the turn's 12 s or hold a badge request. Every
Claude client therefore runs with `max_retries=0` (`claude.SDK_RETRIES`), pinned by
`tests/test_claude.py::test_a_rate_limit_is_never_waited_out_inside_the_sdk`.

## Not measured

The latency and accuracy of any Claude call; whether the API accepts the `anyOf` form of the
badge schema and `thinking: disabled` on Haiku 5.5 (the code drops a setting the API refuses
once, by name); the import time on the board; the cost of a turn. These wait for the key.
