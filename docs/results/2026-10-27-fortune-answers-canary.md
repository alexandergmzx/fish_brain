# 2026-10-27 — How Canary hears the fortune's answers (Loquendo-voiced clips)

Before the fortune act (ADR 0019) was wired, eleven visitor answers were rendered with `loq`
on the board, resampled to 16 kHz mono, padded with 0.8 s of silence on each side (the show's
rule: Canary loses tight-cut clips) and transcribed by the board's own Canary through
`tools/stt_bench.py`. A synthesized voice is a floor: his voice will do worse, not better
(`docs/results/2026-10-13-unoq-stt-his-takes.md`).

- Board: UNO Q `segunda`, the fish running (`de10074`+ uncommitted fortune work), model
  `sherpa-onnx-nemo-canary-180m-flash-en-es-de-fr-int8`, 4 threads.
- Command: `tools/stt_bench.py run --clips /tmp/fbench --cand canary:dir=<model> --runs 1`
  (clips in `~/.local/share/fish_brain/showtest/f_*.wav`, their padded copies in `/tmp/fbench`).
- Load 9.5 s; median 1.81 s a clip, worst 3.91 s (the 5 s dream); peak 412 MB; 43 to 56 C.

| Clip | Said | Canary wrote | Errors | For the parser |
|---|---|---|---|---|
| f_fecha | Veintitrés de octubre. | Veintitrés de octubre. | 0/3 | **dates come as words**, not digits |
| f_fecha_digits | El cinco de marzo. | El cinco de marzo. | 0/4 | idem |
| f_signo | Soy escorpión. | Soy Escorpión. | 0/2 | the sign alias |
| f_sueno | Soñé que se me caían los dientes en la boda de mi prima. | So a que se me caían los dientes en la boda de mi prima. | 2/13 | "soñé" is lost; the theme (`dientes`) is not |
| f_sueno_ex | Soñé con mi ex, que me buscaba en una fiesta. | So e con mi ex que me buscaba en una fiesta. | 2/10 | `ex` heard |
| f_carta | La muerte. | La Muerte. | 0/2 | the Spanish card name |
| f_carta_en | The moon. | De Mong. | 2/2 | an English name needs the Spanish-ear aliases ("de mong", "mong", "de mon") |
| f_carta_num | La dieciocho. | La Dieciocho. | 0/2 | the number word |
| f_taza | Una estrella. | Una extraída. | 1/2 | a miss: the reprompt is the floor |
| f_animal | Un gato negro. | Un gato negro. | 0/3 | `match_option` exact |
| f_nose | No sé. | No sé. | 0/2 | `NOT_SURE` |

Conclusions for `fortune.py`: the Spanish number-word parser is required (nothing came back as
digits); card names in Spanish and by number are safe, English names need Spanish-ear aliases
and the hat's question should ask for the number; the dream theme survives a lost first word;
one-word cup shapes can be mangled by the voice itself, so the narrower reprompt lists them.
