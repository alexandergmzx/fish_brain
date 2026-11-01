# 2026-11-01: the house act's rollback checked, finished and on the board

Base `aab3dc4` plus the working tree of lapG7, synced to `segunda` at 18:38 UTC. No sound was played
and no visitor was run: everything here is level 0, plus level 5 read-only. His voice through a house
visit and a fortune is not measured yet.

## Before (read 2026-11-01)

| Check | How | Result |
|---|---|---|
| `house.toml` against `show_bank.py` at `52cacd1^` | line by line on the laptop, tomllib against the old literals | 143 spoken lines, 0 differ; ids, words and labels the same |
| The board's mode | `/debug/state`, `show_tab.show` | `setting=auto now=llm why=online`: visits were Haiku under `visit.md` |
| The board's code | sha256 of the files | `fortune_run.py`, `show_run.py`, `config.py` at `aab3dc4`; no `FISH_FORTUNE_MODEL` |
| La burla in the fortune | `grep -ic burl prompts/reading.md` | desktop 0, laptop 8, board 8: his erasure was only on the desktop, uncommitted |

## What the fakes showed (FakeLLM, level 0, before the fix)

| Case under `FISH_SHOW=script` | Model calls | Then |
|---|---|---|
| Voice turns, a whole house | 0 | The house fixed by the answers |
| A typed name, nothing open | 1, under `visit.md` | The next press greets again and the name is lost |
| A typed name, mid-visit | 1 | The old question goes on |
| A typed name, after a verdict | 1 | As with nothing open |

After the fix all three typed-name cases make 0 calls (`tests/test_fortune_conversation.py`).

## After

| Check | Command | Result |
|---|---|---|
| Laptop suite | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests` | 1433 passed in 154.81 s |
| `compileall` | `.venv/bin/python -m compileall -q fish_brain` | no output |
| Sync dry run | `rsync -an --delete` with the sync's excludes | 17 files changed, 0 deleted |
| The board's mode | `/debug/state` | `setting=script now=script why=forced` |
| Clips, ready | `/debug/state` | 143 of 143 show, 183 of 183 fortune, about 75 s after the restart |
| Clips, exact text and voice | `canned._cache_path` for every phrase, under the service's environment | 143, 183 and 23 of 23: none stale |
| La burla in the fortune, board | `grep -ic burl prompts/reading.md` | 0 |
| Words and rules | `grep -iE` for burl, mofa, roast, ridicul, pulla, sarcas, insult, humill, mala lengua, cruel in `reading.md`, `ask.md`, `lines.toml` | no match |

`burlón` is left in `config.py`'s `tts_instructions`, the OpenAI voice's. The board's voice is `loq`,
which does not read it.
