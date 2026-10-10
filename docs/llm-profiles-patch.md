# Patch: groq-luna-ab.patch

Copy everything in the block below into `groq-luna-ab.patch` in the `fish_brain` repo root, then follow Step 2 on the Guide tab. It applies to a clean checkout of `main` (commit `73289ff`) and was tested against mock Groq and OpenAI servers.

```diff
diff --git a/.env.example b/.env.example
index d2fa053..130d842 100644
--- a/.env.example
+++ b/.env.example
@@ -1,8 +1,14 @@
 # Copy to .env and fill in. .env is gitignored.
+GROQ_API_KEY=gsk_...
+# only needed for the luna profile / A/B tests:
 OPENAI_API_KEY=sk-...
 
+# Which LLM the fish uses: groq (GPT-OSS-20B, fastest) or luna (GPT-6 Luna on OpenAI)
+# FISH_LLM_PROFILE=groq
+
 # Optional overrides (defaults live in fish_brain/config.py)
 # FISH_SERIAL_PORT=/dev/ttyACM0
-# FISH_LLM_MODEL=gpt-4o-mini
+# FISH_LLM_MODEL=openai/gpt-oss-120b   # override the profile's model
+# FISH_LLM_REASONING=low                 # override the profile's reasoning effort; empty = don't send
 # FISH_STT_MODEL=small
 # FISH_MIC_SOURCE=lavalier      # mic: PipeWire source name or substring; unset = system default
diff --git a/.gitignore b/.gitignore
index 9d28de6..be4b094 100644
--- a/.gitignore
+++ b/.gitignore
@@ -12,3 +12,4 @@ venv/
 # runtime artifacts
 *.wav
 /tmp_audio/
+ab_results.csv
diff --git a/fish_brain/ab.py b/fish_brain/ab.py
new file mode 100644
index 0000000..330cbe6
--- /dev/null
+++ b/fish_brain/ab.py
@@ -0,0 +1,158 @@
+"""A/B test the fish's LLM backends (e.g. Groq GPT-OSS vs GPT-6 Luna) on the same prompts.
+
+    python -m fish_brain.ab                       # built-in prompts, groq vs luna, blind voting
+    python -m fish_brain.ab --no-vote             # just latency/cost, no voting
+    python -m fish_brain.ab --prompts mine.txt    # one prompt per line
+    python -m fish_brain.ab --speak               # also hear each reply through loq (no fish)
+
+Each prompt is sent fresh (no history) to every profile. You see the replies in random
+order labelled 1/2, pick the better one (or = for a tie), and at the end get a table of
+wins, median/worst latency and cost per profile. Every row is saved to ab_results.csv.
+"""
+from __future__ import annotations
+
+import argparse
+import csv
+import random
+import statistics
+from datetime import datetime
+from pathlib import Path
+
+from .config import LLMConfig, LLM_PROFILES
+from .llm import Conversation
+
+PROMPTS = [
+    "Hola Billy, ¿cómo estás?",
+    "Cuéntame un chiste de peces.",
+    "¿Qué opinas de los lunes?",
+    "¿Cuál es tu comida favorita?",
+    "Dame un consejo para mi entrevista de trabajo.",
+    "¿Te gusta vivir colgado en la pared?",
+    "¿Quién ganó el último mundial?",
+    "Dime algo sarcástico sobre los gatos.",
+    "¿Qué harías si te soltaran en el río?",
+    "Despídete como si fueras un pirata.",
+]
+
+
+def _cost(cfg: LLMConfig, usage) -> float:
+    if usage is None:
+        return 0.0
+    return (usage.prompt_tokens * cfg.price_in + usage.completion_tokens * cfg.price_out) / 1e6
+
+
+def main(argv: list[str] | None = None) -> int:
+    ap = argparse.ArgumentParser(prog="fish-brain-ab", description=__doc__.split("\n")[0])
+    ap.add_argument("--profiles", default="groq,luna",
+                    help=f"comma-separated, from {list(LLM_PROFILES)} (default groq,luna)")
+    ap.add_argument("--prompts", type=Path, help="text file, one prompt per line")
+    ap.add_argument("--no-vote", action="store_true", help="skip blind voting")
+    ap.add_argument("--speak", action="store_true", help="also play each reply via loq")
+    ap.add_argument("--out", type=Path, default=Path("ab_results.csv"))
+    args = ap.parse_args(argv)
+
+    try:
+        from dotenv import load_dotenv
+        load_dotenv()
+    except Exception:
+        pass
+
+    names = [n.strip() for n in args.profiles.split(",") if n.strip()]
+    convs = {}
+    for n in names:
+        cfg = LLMConfig(profile=n)
+        try:
+            convs[n] = Conversation(cfg)
+        except Exception as e:                  # e.g. missing API key
+            print(f"can't start profile {n!r}: set {cfg.api_key_env} in .env ({e})")
+            return 1
+    # Warm-up call per profile (not timed or saved) so connection setup doesn't skew latency.
+    for conv in convs.values():
+        conv.reply("hola")
+        conv.reset()
+    prompts = (args.prompts.read_text(encoding="utf-8").splitlines() if args.prompts else PROMPTS)
+    prompts = [p.strip() for p in prompts if p.strip()]
+
+    speaker = None
+    if args.speak:
+        from .config import load
+        from .conductor import make_player
+        from .tts import synthesize             # renders a WAV with loq
+        tts_cfg, player = load().tts, make_player()
+
+        def speaker(text: str) -> None:
+            wav = synthesize(text, tts_cfg)
+            try:
+                player.play(wav)
+                player.wait()
+            finally:
+                wav.unlink(missing_ok=True)
+
+    stats = {n: {"lat": [], "cost": 0.0, "wins": 0, "errors": 0} for n in names}
+    ties = 0
+    rows = []
+    stamp = datetime.now().isoformat(timespec="seconds")
+
+    for i, prompt in enumerate(prompts, 1):
+        print(f"\n[{i}/{len(prompts)}] you> {prompt}")
+        replies = {}
+        for n, conv in convs.items():
+            conv.reset()                        # every prompt starts with no history
+            text = conv.reply(prompt)
+            s = stats[n]
+            if conv.last_error:
+                s["errors"] += 1
+            else:
+                s["lat"].append(conv.last_latency_s)
+                s["cost"] += _cost(conv.cfg, conv.last_usage)
+            replies[n] = text
+            rows.append({"time": stamp, "prompt": prompt, "profile": n, "model": conv.cfg.model,
+                         "latency_s": f"{conv.last_latency_s:.3f}",
+                         "completion_tokens": getattr(conv.last_usage, "completion_tokens", ""),
+                         "error": conv.last_error or "", "reply": text, "winner": ""})
+
+        order = names[:]
+        random.shuffle(order)                   # blind: you don't know which is which
+        for k, n in enumerate(order, 1):
+            print(f"  {k}) {replies[n]}")
+            if speaker:
+                speaker(replies[n])
+
+        winner = ""
+        if not args.no_vote and len(order) == 2:
+            pick = ""
+            while pick not in {"1", "2", "="}:
+                pick = input("  better? [1/2/=] ").strip()
+            if pick == "=":
+                ties += 1
+                winner = "tie"
+            else:
+                winner = order[int(pick) - 1]
+                stats[winner]["wins"] += 1
+            print(f"  (1 = {order[0]}, 2 = {order[1]})")
+        for r in rows[-len(names):]:
+            r["winner"] = winner
+
+    new_file = not args.out.exists()
+    with args.out.open("a", newline="", encoding="utf-8") as f:
+        w = csv.DictWriter(f, fieldnames=list(rows[0]))
+        if new_file:
+            w.writeheader()
+        w.writerows(rows)
+
+    print(f"\n{'profile':<8} {'model':<22} {'wins':>5} {'median s':>9} {'worst s':>8} "
+          f"{'errors':>7} {'cost USD':>10}")
+    for n in names:
+        s = stats[n]
+        med = f"{statistics.median(s['lat']):.2f}" if s["lat"] else "-"
+        worst = f"{max(s['lat']):.2f}" if s["lat"] else "-"
+        print(f"{n:<8} {convs[n].cfg.model:<22} {s['wins']:>5} {med:>9} {worst:>8} "
+              f"{s['errors']:>7} {s['cost']:>10.6f}")
+    if not args.no_vote:
+        print(f"ties: {ties}")
+    print(f"saved {len(rows)} rows to {args.out}")
+    return 0
+
+
+if __name__ == "__main__":
+    raise SystemExit(main())
diff --git a/fish_brain/config.py b/fish_brain/config.py
index 2b144c7..0a96dab 100644
--- a/fish_brain/config.py
+++ b/fish_brain/config.py
@@ -113,11 +113,47 @@ class STTConfig:
     compute_type: str = "int8"      # CPU-friendly faster-whisper setting
 
 
+# LLM backends you can switch between with FISH_LLM_PROFILE (or A/B with `python -m fish_brain.ab`).
+# All are OpenAI-compatible, so one client serves them all. `temperature: None` = don't send it.
+LLM_PROFILES: dict[str, dict] = {
+    "groq": {                                   # GPT-OSS-20B on Groq: fastest
+        "base_url": "https://api.groq.com/openai/v1",
+        "api_key_env": "GROQ_API_KEY",
+        "model": "openai/gpt-oss-20b",
+        "reasoning_effort": "low",              # GPT-OSS can't go lower
+        "extra_body": {"include_reasoning": False},   # Groq-only option
+        "temperature": 0.8,
+        "price_in": 0.075, "price_out": 0.30,   # USD per 1M tokens, for the A/B cost column
+    },
+    "luna": {                                   # GPT-6 Luna on OpenAI: smarter, slower
+        "base_url": "",                         # empty -> api.openai.com
+        "api_key_env": "OPENAI_API_KEY",
+        "model": "gpt-6-luna",
+        "reasoning_effort": "none",             # default is "medium"; must be explicit
+        "extra_body": {},
+        "temperature": None,                    # not confirmed for Luna; send only if you add it
+        "price_in": 0.10, "price_out": 0.50,
+    },
+}
+
+
 @dataclass
 class LLMConfig:
-    model: str = field(default_factory=lambda: _env("FISH_LLM_MODEL", "gpt-4o-mini"))
+    profile: str = field(default_factory=lambda: _env("FISH_LLM_PROFILE", "groq"))
+    # Filled from LLM_PROFILES[profile] in __post_init__; env vars below override one field.
+    base_url: str | None = None
+    api_key_env: str | None = None
+    model: str | None = None
+    reasoning_effort: str | None = None
+    extra_body: dict | None = None
+    temperature: float | None = None
+    price_in: float = 0.0
+    price_out: float = 0.0
+    max_completion_tokens: int = 400   # reasoning tokens count toward this cap too
+    timeout_s: float = 8.0
     max_history_turns: int = 8      # user+assistant pairs kept for context
-    temperature: float = 0.8
+    # Spoken instead of crashing when the API is unreachable / errors out.
+    fallback_reply: str = "¡Glub! Se me fue la señal. Pregúntame otra vez."
     system_prompt: str = (
         "Eres un pez animatrónico parlante (un Big Mouth Billy Bass) con mucha "
         "personalidad: simpático, bromista y un poco sarcástico. Respondes en español "
@@ -125,6 +161,19 @@ class LLMConfig:
         "listas, emojis y texto que no se pueda pronunciar."
     )
 
+    def __post_init__(self) -> None:
+        if self.profile not in LLM_PROFILES:
+            raise ValueError(f"FISH_LLM_PROFILE={self.profile!r}; choose one of {list(LLM_PROFILES)}")
+        for key, value in LLM_PROFILES[self.profile].items():
+            if getattr(self, key) in (None, 0.0):
+                setattr(self, key, value)
+        # Single-field overrides from .env, applied only to the profile the fish is using
+        # (so an A/B run keeps the other profile as defined). Empty FISH_LLM_REASONING = don't send.
+        if self.profile == _env("FISH_LLM_PROFILE", "groq"):
+            self.model = os.environ.get("FISH_LLM_MODEL") or self.model
+            if "FISH_LLM_REASONING" in os.environ:
+                self.reasoning_effort = os.environ["FISH_LLM_REASONING"]
+
 
 @dataclass
 class CannedConfig:
diff --git a/fish_brain/llm.py b/fish_brain/llm.py
index 467177b..ec692df 100644
--- a/fish_brain/llm.py
+++ b/fish_brain/llm.py
@@ -1,10 +1,14 @@
-"""Cloud LLM (OpenAI) with a bounded conversation history and a fish persona.
+"""Cloud LLM (any OpenAI-compatible API: Groq, OpenAI, ...) with bounded history + fish persona.
 
-Only text leaves the machine. The API key comes from the environment (.env →
-OPENAI_API_KEY), loaded by the entry point before this is constructed.
+Only text leaves the machine. Which backend is used comes from LLMConfig.profile
+(FISH_LLM_PROFILE in .env); its API key is read from the env var the profile names.
 """
 from __future__ import annotations
 
+import os
+import sys
+import time
+
 from .config import LLMConfig
 
 
@@ -12,9 +16,18 @@ class Conversation:
     def __init__(self, cfg: LLMConfig):
         self.cfg = cfg
         from openai import OpenAI  # lazy import so --text/--dry-run without the key is fine
-        self._client = OpenAI()
+        self._client = OpenAI(
+            base_url=cfg.base_url or None,           # None -> api.openai.com
+            api_key=os.environ.get(cfg.api_key_env),
+            timeout=cfg.timeout_s,
+            max_retries=1,
+        )
         # Rolling history of {"role","content"} (user/assistant only; system is fixed).
         self._history: list[dict[str, str]] = []
+        # Stats from the last reply() call (used by `python -m fish_brain.ab`).
+        self.last_latency_s: float = 0.0
+        self.last_usage = None
+        self.last_error: str | None = None
 
     def _messages(self, user_text: str) -> list[dict[str, str]]:
         msgs = [{"role": "system", "content": self.cfg.system_prompt}]
@@ -22,13 +35,39 @@ class Conversation:
         msgs.append({"role": "user", "content": user_text})
         return msgs
 
+    def reset(self) -> None:
+        self._history.clear()
+
     def reply(self, user_text: str) -> str:
         """Send a user turn, return the assistant reply, and update history."""
-        resp = self._client.chat.completions.create(
-            model=self.cfg.model,
-            temperature=self.cfg.temperature,
-            messages=self._messages(user_text),
-        )
+        from openai import APIError  # base of connection/timeout/status errors
+        kwargs: dict = {}
+        if self.cfg.reasoning_effort:
+            kwargs["reasoning_effort"] = self.cfg.reasoning_effort
+        if self.cfg.extra_body:
+            kwargs["extra_body"] = self.cfg.extra_body
+        if self.cfg.temperature is not None:
+            kwargs["temperature"] = self.cfg.temperature
+        self.last_error, self.last_usage = None, None
+        t0 = time.monotonic()
+        try:
+            resp = self._client.chat.completions.create(
+                model=self.cfg.model,
+                max_completion_tokens=self.cfg.max_completion_tokens,
+                messages=self._messages(user_text),
+                **kwargs,
+            )
+        except APIError as e:
+            # Offline / timeout / bad key / rate limit: say something instead of crashing
+            # the loop. Not added to history, so the next turn retries cleanly.
+            self.last_latency_s = time.monotonic() - t0
+            self.last_error = f"{type(e).__name__}: {e}"
+            print(f"[llm] {self.cfg.profile} {self.last_error}", file=sys.stderr)
+            return self.cfg.fallback_reply
+        self.last_latency_s = time.monotonic() - t0
+        self.last_usage = resp.usage
+        print(f"[llm] {self.cfg.profile} {self.cfg.model} {self.last_latency_s:.2f}s",
+              file=sys.stderr)
         answer = (resp.choices[0].message.content or "").strip()
         self._history.append({"role": "user", "content": user_text})
         self._history.append({"role": "assistant", "content": answer})
```
