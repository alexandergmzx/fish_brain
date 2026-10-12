# On-screen fish sprites (`web/img/`)

Drop your **transparent PNGs** here. They are served at `/img/<name>.png` and drawn by
[`../fish.js`](../fish.js), which runs a small **state machine**: each frame it picks **one
whole-fish composite PNG** for the current `(neck, mouth, tail)` state. All PNGs should be the
**same dimensions** (full canvas) so successive poses line up; they're drawn "contain"-scaled
and centered on a transparent canvas, over the page's sea. The nail must sit at the top
centre: the page swings the canvas around it.

A cut-out with leftovers of its old background (a rim, specks) shows on the sea:
`python tools/sprite_clean.py` reports them and `--write` clears them (it only ever makes
pixels transparent). The committed set was keyed out of `#91b9bc` and cleaned that way.

We use whole-fish composites (not stacked layers) on purpose: an **open mouth looks different
when the neck is also out** (the head pose moves the mouth), so each pose is its own image.

## Naming

```
neck{Rest|Out}_mouth{0..3}_tail{Rest|Flap}.png
```

| Dimension | Values | Driven by |
|-----------|--------|-----------|
| `neck` | `Rest`, `Out` | `Out` while a **NECK** gesture fires, else `Rest` |
| `mouth` | `0` `1` `2` `3` | audio loudness (closed → widest), spring-smoothed |
| `tail` | `Rest`, `Flap` | `Flap` while a **TAIL** gesture fires, else `Rest` |

The full set is 2 × 4 × 2 = **16 sprites**, e.g.:

```
neckRest_mouth0_tailRest.png   neckRest_mouth1_tailRest.png   …  neckRest_mouth3_tailRest.png
neckRest_mouth0_tailFlap.png   …
neckOut_mouth0_tailRest.png    …                              neckOut_mouth3_tailFlap.png
```

## Add art incrementally (graceful fallback)

You don't need all 16 at once. If the exact sprite for a state is missing, `fish.js` falls back
to a simpler pose — first dropping the tail flap, then the neck-out, then lowering the mouth —
so the **mouth openness is preserved as long as possible**. The final fallback is always
`neckRest_mouth0_tailRest.png`.

So a good order is:
1. **The four base poses** `neckRest_mouth{0..3}_tailRest.png` — mouth already animates with audio.
2. `neckOut_mouth{0..3}_tailRest.png` — head-out talking poses.
3. The `*_tailFlap.png` variants — tail flaps during TAIL gestures.

If **no** PNGs load, the stage shows a hint so the page never looks broken.

## Notes
- More/fewer mouth levels? Change `MOUTH_LEVELS` (and the `NECK`/`TAIL` arrays) in `fish.js`.
- The default 16-sprite set is committed here; replace any PNG to reskin the fish.
