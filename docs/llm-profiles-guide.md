# fish\_brain on Groq GPT-OSS, with a GPT-6 Luna A/B — Setup Guide

Sep 29, 2026 · @Alexander Gomez

## Overview

[fish\_brain](https://github.com/alexandergmzx/fish_brain) gets two switchable LLM profiles from one patch: `groq` (`openai/gpt-oss-20b` on Groq, the default) and `luna` (`gpt-6-luna` on OpenAI), plus a blind A/B script to pick between them. Both speak the OpenAI API, so the repo's existing `openai` SDK serves either one.

| Profile | Model | Price per 1M tokens (in / out) | Speed | Reasoning sent |
| --- | --- | --- | --- | --- |
| `groq` (default) | [GPT-OSS-20B](https://console.groq.com/docs/models) | $0.075 / $0.30 | \~1,000 tok/s | `low` (the minimum) |
| `luna` | [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) | $0.10 / $0.50 | \~144 tok/s with reasoning off ([Artificial Analysis](https://artificialanalysis.ai/models/releases/gpt-6-luna)) | `none` (its default is `medium`) |

One conversation turn in the current repo, with the one stage that changes marked:

1. **Push-to-talk**: hold a key (or the `--viz` button) and record the mic.
2. **STT**: local faster-whisper turns the recording into Spanish text.
3. **LLM** (changes): `llm.py` sends persona + history and gets the whole reply back. **Groq by default; GPT-6 Luna with FISH\_LLM\_PROFILE=luna.**
4. **TTS**: `loq -o reply.wav` renders the full reply through the warm Loquendo daemon.
5. **Motion**: the WAV's loudness envelope becomes `MOUTH <pwm> <ms>` pulses plus random `NECK`/`TAIL` gestures.
6. **Playback**: audio and serial commands stream on one clock to the fish's firmware.

The repo precomputes the full motor schedule from the finished WAV, so replies don't need token streaming; Groq's speed makes the LLM step well under a second anyway. On the UNO Q, the heavier stages will be faster-whisper and Loquendo under Wine on its A53 cores, not the LLM.

## Step 1: Accounts and keys

Groq is required; OpenAI is only for the Luna A/B test and can wait until Groq works. Create each key once, cap its spending, and keep both in `.env`.

**Groq** (required, free tier available)

- [ ] Sign in at [console.groq.com](https://console.groq.com/home).
- [ ] Create a key named `fish-brain` under [API Keys](https://console.groq.com/keys). Copy it now; Groq shows it only once.
- [ ] Set a low monthly cap (for example $2) under [Spend Limits](https://console.groq.com/docs/spend-limits).
- [ ] Optional: try the model in the [Playground](https://console.groq.com/playground) with the fish persona prompt.

**OpenAI** (only for the Luna A/B test, prepaid, $5 minimum)

The OpenAI API is a separate, pay-as-you-go service; a ChatGPT subscription doesn't include it ([OpenAI community FAQ](https://community.openai.com/t/faq-getting-started-with-the-openai-api-quickstart-billing-verification-prepayment-credits-429-errors/1360980)). At about $0.00006 per fish reply, $5 covers tens of thousands of replies.

- [ ] Sign up at [platform.openai.com](https://platform.openai.com/signup) with an email you'll keep. This creates an organization with a default project.
- [ ] Rename the default project to `fish-brain` (or create one) under Settings → Projects, so this key and its spending stay separate.
- [ ] Add credit under Settings → Billing: "Add payment details", then buy the $5 minimum. Use a regular debit or credit card; the FAQ notes prepaid and virtual cards often fail. Credits expire after 1 year ([OpenAI prepaid billing](https://help.openai.com/en/articles/8264644-how-can-i-set-up-prepaid-billing)).
- [ ] **Turn off auto-recharge** in that same dialog. It's on by default and would buy more credit whenever the balance runs low.
- [ ] Optional: set a monthly budget on the `fish-brain` project under Settings → Limits.
- [ ] Create a key under [API keys](https://platform.openai.com/api-keys): "Create new secret key", project `fish-brain`, name `fish-brain`. Copy it now; it's shown only once.
- [ ] Wait before testing. The balance can take a few minutes to update, and the FAQ says a new account can take up to a few hours to be fully provisioned.
- [ ] If the dashboard asks you to verify your organization (government ID + selfie) before using `gpt-6-luna`, do it. OpenAI requires this for some models; I couldn't confirm whether Luna is one of them.

Check the OpenAI key before touching the repo. A short Spanish reply means the account, credit and model access all work; `insufficient_quota` means the credit isn't active yet.

```bash
curl https://api.openai.com/v1/chat/completions \
  -H "Authorization: Bearer sk-your-key-here" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-6-luna", "reasoning_effort": "none", "max_completion_tokens": 60,
       "messages": [{"role": "user", "content": "Di hola como un pez."}]}'
```

## Step 2: Apply the patch

The patch adds two LLM profiles, `groq` (the default) and `luna`, plus a blind A/B script; the repo's `.venv` already has every dependency. Copy the full diff from the Patch tab into `groq-luna-ab.patch` in the repo root, then:

```bash
cd ~/Development/fish_brain && source .venv/bin/activate
git apply -R groq.patch 2>/dev/null   # only undoes the earlier Groq-only patch, if you applied it
git apply --check groq-luna-ab.patch && git apply groq-luna-ab.patch
```

Put both keys from Step 1 in `.env` (already gitignored). Leave `OPENAI_API_KEY` out until you set up OpenAI; the fish runs on Groq without it.

```bash
echo 'GROQ_API_KEY=gsk_your_key_here' >> .env
echo 'OPENAI_API_KEY=sk-your_key_here' >> .env   # only for the luna profile / A/B test
```

What it changes:

| File | Change |
| --- | --- |
| `fish_brain/config.py` | New `LLM_PROFILES`: `groq` = `openai/gpt-oss-20b`, reasoning `low`; `luna` = `gpt-6-luna`, reasoning `none`. `LLMConfig` picks one with `FISH_LLM_PROFILE` (default `groq`) and gains `max_completion_tokens` (400), `timeout_s` (8) and `fallback_reply` |
| `fish_brain/llm.py` | One OpenAI-SDK client for either backend, sending only the options its profile defines; logs `[llm] <profile> <model> <seconds>` per reply; any API error returns `fallback_reply` instead of crashing the loop |
| `fish_brain/ab.py` (new) | Blind A/B script: same prompts to both profiles, you vote, it reports wins, latency and cost (Step 5) |
| `.env.example`, `.gitignore` | Documents `GROQ_API_KEY` and `FISH_LLM_PROFILE`; ignores `ab_results.csv` |

## Step 3: Test with the repo's own flags

Go from no hardware to the full fish, one layer at a time. Stop at the first step that fails.

1. **LLM only, no fish, no audio**: type a turn and read the reply and the commands it prints.

   ```bash
   python -m fish_brain.app --dry-run --text --no-audio
   ```
2. **Add Loquendo and speakers**: same, but hear Jorge say Groq's reply.

   ```bash
   python -m fish_brain.app --dry-run --text
   ```
3. **Add the mic and the on-screen fish**: hold-to-talk in the browser at `http://127.0.0.1:8723`.

   ```bash
   python -m fish_brain.app --dry-run --viz
   ```
4. **Full system**: real serial, mic and fish.

   ```bash
   python -m fish_brain.app
   ```

In step 1, a reply in Spanish within about a second means the key, URL and model are right. The patch was checked against a mock Groq server: the request goes to `/openai/v1/chat/completions` with the Bearer key, `reasoning_effort: low` and `include_reasoning: false`.

## Step 4: Check the fallback

Before the patch, any API error escaped `turn()` and ended the conversation (goodbye, then exit). Now `llm.py` catches it, logs `[llm] <error>` to stderr, and the fish speaks `fallback_reply` through Loquendo, which works offline. The failed turn isn't added to history, so the next one retries cleanly.

| Failure | How to test it (`--dry-run --text`) | Expected |
| --- | --- | --- |
| No internet | Disconnect Wi-Fi, type a turn | Fallback line after about 1 s |
| Groq slow | Set `timeout_s = 0.01` in `config.py` | Fallback line, `APITimeoutError` in the log |
| Bad or missing key | Put a wrong `GROQ_API_KEY` in `.env` | Fallback line, `AuthenticationError` in the log |
| Wrong model ID | `FISH_LLM_MODEL=nope` in `.env` | Fallback line, `NotFoundError` in the log |

The mock test confirmed the offline row: the client raised `APIConnectionError`, the fish got the fallback line, and history stayed empty. Undo the `timeout_s` change after testing.

## Step 5: A/B test GPT-6 Luna

Run the same prompts through both profiles, judge the replies blind, then pick a default from wins and latency. Two rounds cover it: a quick blind vote at the keyboard, then a live check on the real fish.

**Round 1: blind vote.** The script sends 10 built-in Spanish prompts to both profiles, each with no history, after one untimed warm-up call each. It prints the two replies as `1)` and `2)` in random order. Type `1`, `2` or `=` for a tie, and it reveals which was which.

```bash
python -m fish_brain.ab                     # 10 built-in prompts, blind voting
python -m fish_brain.ab --speak             # also hear each reply in Jorge's voice (slower, closer to real use)
python -m fish_brain.ab --prompts mine.txt  # your own prompts, one per line
python -m fish_brain.ab --no-vote           # latency and cost only
```

It ends with a summary like this (mock-server numbers; yours will differ):

```text
profile  model                   wins  median s  worst s  errors   cost USD
groq     openai/gpt-oss-20b         1      0.05     0.05       0   0.000063
luna     gpt-6-luna                 1      0.30     0.30       0   0.000096
ties: 1
saved 6 rows to ab_results.csv
```

Every run appends to `ab_results.csv` (prompt, profile, model, latency, tokens, error, reply, winner), so several sessions add up. Try 20 or more prompts before deciding; 10 votes can go either way by chance.

**Round 2: live on the fish.** Switch the whole app with `FISH_LLM_PROFILE` (in `.env`, or inline as below) and hold a real conversation; the terminal logs each reply's time as `[llm] luna gpt-6-luna 1.12s`.

```bash
FISH_LLM_PROFILE=luna python -m fish_brain.app --dry-run --viz   # Luna, on-screen fish
python -m fish_brain.app --dry-run --viz                          # back to Groq (default)
```

How to decide:

| If the results show | Then |
| --- | --- |
| Luna wins clearly and its median stays under \~1.5 s | Set `FISH_LLM_PROFILE=luna` in `.env` |
| Luna wins, but pauses feel long on the fish | Keep `groq`; try `FISH_LLM_MODEL=openai/gpt-oss-120b` for a smarter Groq model |
| Close to even | Keep `groq`: faster and cheaper |
| Either profile shows errors | Fix those first (Troubleshooting) and rerun |

## Tuning cheatsheet

Each profile's settings live in `LLM_PROFILES` in `fish_brain/config.py`; shared limits live in `LLMConfig`. The env vars override only the profile the fish is using, so an A/B run always compares the profiles as defined.

| Setting | `groq` | `luna` | Env var | Change it when |
| --- | --- | --- | --- | --- |
| Profile in use | default | opt-in | `FISH_LLM_PROFILE` | The A/B test picks a winner |
| `model` | `openai/gpt-oss-20b` | `gpt-6-luna` | `FISH_LLM_MODEL` | You want the bigger sibling, such as `openai/gpt-oss-120b` ($0.15 / $0.60 per 1M, \~500 tok/s) |
| `reasoning_effort` | `low` | `none` | `FISH_LLM_REASONING` | Replies are off-topic: `medium`. GPT-OSS can't go below `low`; Luna's own default is `medium` |
| `temperature` | 0.8 | not sent | none | Luna jokes feel flat: add `"temperature": 0.8` to its profile, test once, and remove it if Luna returns a 400 |
| `max_completion_tokens` | 400 | 400 | none | Empty or cut-off replies: raise it, since reasoning tokens share this cap |
| `timeout_s` | 8.0 | 8.0 | none | Fallback fires on a working connection: raise it |
| `max_history_turns` | 8 | 8 | none | The fish forgets the conversation: raise it |

Reasoning options: [Groq Reasoning](https://console.groq.com/docs/reasoning) for GPT-OSS; the [GPT-6 Luna model page](https://developers.openai.com/api/docs/models/gpt-6-luna) lists `none` through `max`.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `git apply --check` fails on `.env.example` | The earlier Groq-only patch is still applied | `git apply -R groq.patch`, then apply `groq-luna-ab.patch` |
| `corrupt patch at line ...` | Copying from the Patch tab dropped the final newline or changed spaces | Use the attached `groq-luna-ab.patch` file, or add an empty line at the end of your copy |
| `can't start profile 'luna': set OPENAI_API_KEY` from the A/B script | OpenAI key missing | Add `OPENAI_API_KEY` to `.env` (Step 1), or run `--profiles groq` alone |
| Luna: `429` with `insufficient_quota` | No active credit yet, or the key is in a project without billing | Check the balance under Settings → Billing; wait a few minutes (up to a few hours on a new account); recreate the key in the funded project |
| Luna: `NotFoundError` / model not found, or a verification message | Your organization can't use `gpt-6-luna` yet | Complete organization verification if the dashboard offers it; check the model page for your tier |
| `OpenAIError: Missing credentials` on the fish's first turn | The active profile's key is missing (`GROQ_API_KEY` for `groq`) | Add the key; run from the repo root so `load_dotenv()` finds `.env` |
| Every turn speaks the fallback line | Wrong key, URL or model | Read the `[llm] <profile> ...` line in the terminal; it names the error |
| Luna: `400` about `temperature` | Luna rejects the temperature you added | Remove `temperature` from the `luna` profile |
| `400` mentioning `reasoning_effort` | A model that doesn't take that option (set via `FISH_LLM_MODEL`) | Set `FISH_LLM_REASONING=` (empty) in `.env` |
| Fish says nothing, no error | Reasoning used up `max_completion_tokens` | Raise it to 600 |
| Speech, serial or mic problems | Not LLM-related | See the repo README's Troubleshooting section |

## References

| Topic | Link |
| --- | --- |
| The repo this patch targets | [alexandergmzx/fish\_brain](https://github.com/alexandergmzx/fish_brain) |
| Using the OpenAI SDK against Groq | [Groq OpenAI Compatibility](https://console.groq.com/docs/openai) |
| GPT-OSS IDs, speed and prices | [Groq Supported Models](https://console.groq.com/docs/models) |
| GPT-OSS reasoning controls | [Groq Reasoning](https://console.groq.com/docs/reasoning) |
| GPT-6 Luna ID, reasoning values, prices, limits | [OpenAI: GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) |
| OpenAI prepaid credit and auto-recharge | [OpenAI Help: prepaid billing](https://help.openai.com/en/articles/8264644-how-can-i-set-up-prepaid-billing) |
| OpenAI signup, verification and `429` errors | [OpenAI community FAQ](https://community.openai.com/t/faq-getting-started-with-the-openai-api-quickstart-billing-verification-prepayment-credits-429-errors/1360980) |
| Independent speed and quality numbers | [Artificial Analysis: GPT-6 Luna](https://artificialanalysis.ai/models/releases/gpt-6-luna), [OpenRouter: GPT-6 Luna](https://openrouter.ai/openai/gpt-6-luna) |
| Cloud STT if faster-whisper is too slow on the UNO Q | [Groq Speech to Text](https://console.groq.com/docs/speech-to-text) |
