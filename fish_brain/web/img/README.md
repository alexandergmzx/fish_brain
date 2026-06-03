# On-screen fish sprites (`web/img/`)

Drop your **transparent PNGs** here. They are served at `/img/<name>.png` and composited by
[`../fish.js`](../fish.js) (see the `LAYERS` array there). All PNGs should be the **same
dimensions** (full canvas) so the layers line up; they're drawn "contain"-scaled and centered
on a solid `#91b9bc` background. Missing files are skipped — if none are present the stage
shows a hint, so you can add them incrementally.

The fish moves by **swapping frames** (no rotation/scaling):

| Layer | Type | Files (default names) | When shown |
|-------|------|------------------------|------------|
| plaque | static | `plaque.png` | always (optional backdrop: wood + chains + button) |
| tail | tail | `tail_rest.png`, `tail_flap.png` | `flap` while a **TAIL** gesture fires |
| body | static | `body.png` | always (optional non-moving body) |
| head | neck | `head_rest.png`, `head_out.png` | `out` while a **NECK** gesture fires |
| mouth | mouth | `mouth0.png` … `mouth3.png` | indexed by audio loudness (closed → open) |

## Two ways to use it

**A) Simplest — full-composite mouth frames.** Make each `mouthN.png` a *whole fish+plaque*
in a progressively more open-mouthed pose, and don't provide the other files. Only the mouth
layer renders; loudness picks the frame. This matches the four poses you pasted (use them as
`mouth0.png`=closed … `mouth3.png`=widest). Add more frames for smoother talking.

**B) Layered — cut parts.** Provide transparent cut-outs (plaque/body/head/tail/mouth) so the
mouth and tail can move at the same time. Edit the `LAYERS` order in `fish.js` if your art
stacks differently.

## Notes
- More/fewer mouth frames? Just edit the `frames: [...]` list in `fish.js`.
- File names are arbitrary — they only need to match what's in `fish.js`.
- PNGs are **not** committed to the repo; they're yours to drop in here.
