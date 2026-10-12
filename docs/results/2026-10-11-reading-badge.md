# The reading: a badge photo read by gpt-6-luna from the board — 2026-10-11

Host: the board `segunda` on the home Wi-Fi, fish_brain at commit `575ba1f` (synced, the service
still running the previous code; the one-shot does not open the motor link), the board's `.env`
(`FISH_LLM_PROFILE=luna`, no `FISH_READING_PROFILE`). Level 1. Pass line, set before measuring:
"the name on a synthetic badge comes back with the given names and surnames split, confidence high,
in under 10 s".

Badge: a synthetic 1000x650 JPEG (58 KB) with "FERIA DE CIENCIAS 2026 / VISITANTE / GARCIA LOPEZ /
MARIA JOSE / Escuela Benito Juarez - 2o B" in DejaVu Sans Bold (surnames first, capitals, no accents,
as Mexican badges print them). Command, three times:

```
.venv/bin/python -m fish_brain.app --dry-run --text --no-audio --tts openai --read-badge /tmp/badge.jpg
```

| Call | Seconds | Prompt tokens | Result |
|---|---|---|---|
| 1 (new schema) | 6.7 | 1163 | `given_names` "Maria Jose", `surnames` "Garcia Lopez", `name_for_speech` "María José", `look` null, confidence high |
| 2 | 4.3 | 1163 | same |
| 3 | 5.5 | 1163 | same |

Reading: Luna takes images on this organization; the strict schema is honoured; the surnames-first
layout is split by the model as the prompt asks and the given name comes back with its accents. At
$0.10 per million input tokens the image call costs about $0.00012 plus the reply. Pass.

Not measured: a real fair badge (glossy sleeve, logo, photo of the visitor), the time over the
phone hotspot, the whole act with the Loquendo voice (the question and the prophecy), the look
line. A `[reading]` line without the name is printed by the one-shot and by the page path alike.
