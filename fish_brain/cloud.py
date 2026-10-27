"""Shared plumbing for every cloud call (speech-to-text, text-to-speech, the LLM's online check).

- `client(profile)`: one cached OpenAI-SDK client per service, with a short connect timeout
  and no hidden retries, so a dead phone hotspot costs seconds, not minutes.
- `is_online()`: a flag kept fresh by a background probe; reading it never blocks.
- `guard()`: turns any SDK error into one of two exceptions the conversation loop handles:
  `CloudUnavailable` (no signal, try again later) or `CloudMisconfigured` (bad key/model).

`configure()` is called once by the entry point; without it the defaults apply.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
from contextlib import contextmanager

from .config import CloudConfig


class CloudUnavailable(RuntimeError):
    """Transient: offline, timeout, rate limit, server error."""


class CloudMisconfigured(RuntimeError):
    """Not going to fix itself: missing/bad key, unknown model, rejected request."""


_cfg = CloudConfig()
_clients: dict[tuple, object] = {}
_lock = threading.Lock()
_online = True                 # optimistic until the probe (or a failed call) says otherwise
_probe_started = False
_first_probe = threading.Event()
_warned: set[str] = set()


def configure(cfg: CloudConfig) -> None:
    global _cfg
    with _lock:
        _cfg = cfg
        _clients.clear()


def _log(msg: str) -> None:
    print(f"[cloud] {msg}", file=sys.stderr, flush=True)


# --- online probe -----------------------------------------------------------------------
def _probe_once() -> bool:
    host, _, port = _cfg.online_check_host.partition(":")
    try:
        with socket.create_connection((host, int(port or 443)), timeout=2.0):
            return True
    except (OSError, ValueError):
        return False


def _probe_loop() -> None:
    global _online
    while True:
        ok = _probe_once()
        if ok != _online:
            _log("online" if ok else "offline")
        _online = ok
        _first_probe.set()
        time.sleep(5.0)


def start_probe(wait_s: float = 0.0) -> None:
    """Start the background connectivity probe (idempotent). Optionally wait for its first result."""
    global _probe_started
    with _lock:
        if not _probe_started:
            _probe_started = True
            threading.Thread(target=_probe_loop, name="cloud-probe", daemon=True).start()
    if wait_s > 0:
        _first_probe.wait(wait_s)


def is_online() -> bool:
    """Last known connectivity. Always True when the probe was never started."""
    return _online


def mark_offline() -> None:
    global _online
    if _online and _probe_started:
        _log("offline (a call failed)")
        _online = False


def mark_online() -> None:
    """Take back a `mark_offline` that came from a service the flag does not speak for
    (the probe watches one host); the probe's next pass has the last word."""
    global _online
    if not _online:
        _log("online (the failed call was another service's)")
        _online = True


# --- clients ----------------------------------------------------------------------------
def client(base_url: str = "", api_key_env: str = "OPENAI_API_KEY",
           timeout_s: float | None = None):
    """Cached OpenAI-SDK client for one service. Raises CloudMisconfigured without a key."""
    if api_key_env == "ANTHROPIC_API_KEY":
        # An empty base_url means api.openai.com: Anthropic's key must never be sent there.
        raise CloudMisconfigured("ANTHROPIC_API_KEY belongs to the Anthropic client (claude.py)")
    key = (base_url, api_key_env, timeout_s)
    with _lock:
        if key in _clients:
            return _clients[key]
    api_key = os.environ.get(api_key_env, "").strip()
    if not api_key:
        raise CloudMisconfigured(f"{api_key_env} is not set (put it in .env)")
    import openai  # lazy: dry runs and local backends never import it
    c = openai.OpenAI(
        base_url=base_url or None,
        api_key=api_key,
        timeout=openai.Timeout(timeout_s or _cfg.timeout_s, connect=_cfg.connect_timeout_s),
        max_retries=_cfg.max_retries,
    )
    with _lock:
        _clients[key] = c
    return c


def classify(exc: BaseException) -> RuntimeError:
    """Map an OpenAI-SDK exception to CloudUnavailable / CloudMisconfigured."""
    import openai
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    if isinstance(exc, (openai.APIConnectionError, openai.RateLimitError)) or (
            isinstance(status, int) and status >= 500):
        if isinstance(exc, openai.APIConnectionError):
            mark_offline()
        return CloudUnavailable(f"{name}: {exc}")
    detail = f"{name} status={status} code={getattr(exc, 'code', None)}: {exc}"
    return config_error(detail)


def config_error(detail: str) -> CloudMisconfigured:
    """The exception for a call that will not work until someone fixes the set-up. Logged
    loudly, but only once per distinct detail."""
    if detail not in _warned:
        _warned.add(detail)
        _log(f"CONFIG ERROR {detail}")
    return CloudMisconfigured(detail)


@contextmanager
def guard():
    """Run a cloud call; SDK errors come out as CloudUnavailable / CloudMisconfigured."""
    try:
        yield
    except (CloudUnavailable, CloudMisconfigured):
        raise
    except Exception as e:
        try:
            import openai
        except ImportError:
            raise e
        if isinstance(e, openai.OpenAIError):
            raise classify(e) from e
        import httpx
        if isinstance(e, httpx.TransportError):     # the connection died while reading a body
            mark_offline()
            raise CloudUnavailable(f"{type(e).__name__}: {e}") from e
        raise


def missing_keys(env_names: set[str]) -> list[str]:
    return sorted(n for n in env_names if not os.environ.get(n, "").strip())
