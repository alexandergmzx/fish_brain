# On-screen sprites (`web/img/`)

The page draws the Sorting Hat itself (`svg#hat` in [`../index.html`](../index.html)) until
sprites are here. Drop **transparent PNGs** in this folder; they are served at
`/img/<name>.png` and drawn by [`../fish.js`](../fish.js), which picks **one whole-hat
composite** per frame for the current `(neck, mouth, tail)` state.

## Naming (the names are the fish's; on the hat neck = tip and tail = brim)

```
neck{Rest|Out}_mouth{0..3}_tail{Rest|Flap}.png
```

| Part of the name | On the hat | Values | Driven by |
|---|---|---|---|
| `neck` | the tip | `Rest` drooping, `Out` raised | a NECK hold in the turn, and the burble's "mmm?" |
| `mouth` | the mouth | `0` closed … `3` widest | the voice's loudness, spring-smoothed |
| `tail` | the brim | `Rest`, `Flap` tilted | a TAIL chain in the turn |

## The frame

- 600 × 500 px, transparent, every file the same size, so poses line up.
- The hat stands centred with its brim resting at about 86 % of the height: the page draws the
  stool under it, and the drawn hat uses the same frame.
- Leftovers of an old background show on the dark study: `python tools/sprite_clean.py` reports
  them and `--write` clears them (it only makes pixels transparent).

## When the sprites take over

- The canvas replaces the drawn hat once the **four base poses**
  `neckRest_mouth{0..3}_tailRest.png` have loaded. Fewer than four: the drawn hat stays.
- Missing poses fall back: first the brim, then the tip, then a lower mouth; the last fallback is
  `neckRest_mouth0_tailRest.png`. Four files start the mouth; sixteen move the whole hat.
- Check a pose without a turn: `/?pose=speaking&mouth=1&tip=1&brim=1` (also `ready`,
  `listening`, `thinking`, `reading`; `mouth` from 0 to 1).

The operator's page (`/`, `debug.js`) draws the same four base poses once they have all loaded:
the frame picks the mouth, and the tip (NECK) and the brim (TAIL) tilt the whole picture, since
those poses have no sprites of their own. `/?hat=speaking&mouth=1` shows a still there.

The fish's sixteen sprites are parked in `fish/` (not served: `/img/` takes bare names only).
