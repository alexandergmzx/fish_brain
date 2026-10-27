# 0011 — One page for the operator: the debug view on his phone, with the hat that shows what the fish does

**Status:** proposed · **Date:** 2026-10-16

## Context

ADR 0008 made the phone the fish's face in the visitor's hands, with the operator's controls in
a sheet behind a held shell, and ADR 0009 made `/debug` a separate desktop page. For the fair of
2026-10-17 the visitors never hold a screen: they talk to the Sorting Hat through the remote.
The only screen is the operator's own phone (a Galaxy S24 Ultra in Chrome, about 384×832 CSS
px), and what he needs on it is the debug view, plus the turn's tools (a new visitor, the
cues, the badge) and a hat whose motion tells him at a glance what the fish is doing.

On that phone, Chrome gives the Screen Wake Lock and the microphone only to a secure context
(the https listener, once its certificate warning is accepted), drops the event stream when
the screen sleeps, and allows a few connections per host.

## Decision

1. `/` (and `/index.html`, `/debug`) serves the debug view, `debug.html`. Visitors have no page.
2. The drawn hat of the old face replaces the debug view's fish sprite. Its mouth follows the
   reply's loudness track; NECK bends its tip, TAIL wags its brim, the burble perks it. Around
   it:
   - a pose and a colour for what the fish is doing: waiting, listening, thinking (with the
     seconds against the turn's budget and whether it is still hearing or at the model),
     speaking;
   - a grey slump when the page's stream is down;
   - the visit's stage, with a reveal in the house's colour at the verdict;
   - a shake and the stage a turn died in;
   - the lamps for every line the link really sent, and after each phrase whether MOUTH lines
     went out.
3. On a phone (≤ 700 px) the hat and the tabs stay on top and one column shows at a time. The
   tabs are Visit (first), Turns, Checks, Live, Model, Voice, Switches, System and Log. A thumb
   bar holds "Nuevo visitante" and a hold-to-talk button (the board records, a backup for the
   remote).
4. The page keeps the screen on through the wake lock over https and says when it cannot. It
   closes its stream when hidden and resumes on return. It names itself, so a reconnect
   replaces its own stream on the board instead of waiting for a dead one to free one of the
   four places.
5. The phone's microphone is a switch in the Voice tab, off by default:
   - on: it asks for permission, sets the board to take phone recordings and announces the
     page while its stream is live;
   - off, or the screen sleeping: the board records again.

   Switches are allowed while a phone is the microphone (tests and motor pulses are not).
6. The old face stays reachable at `/face` until the fair is over and is then removed. The
   parked kiosk points at `/face?kiosk=1`, never at the operator's page.

This replaces ADR 0008 and amends ADR 0006 (the interface is the operator's phone, not a
visitor screen) and ADR 0009 (the debug view is no longer desktop-only; it is the main page).

## Alternatives

- **Keep the face at `/` and the debug view at `/debug`.** Two pages to keep in step, and the
  face's child-proofing (the held shell, the bubbles) protects nobody when no visitor holds the
  phone.
- **Delete the face tonight.** It is the only page proven on a phone until now; without the
  laptop at the fair a broken new page would leave no fallback. It goes after the fair.
- **A separate phone page built from the face.** It would duplicate the debug view's stream,
  state and tools; the debug view already has them.

## Consequences

- Everything of the debug view is now at the address everyone types. With `FISH_VIZ_TOKEN`
  empty (his password-protected hotspot, ADR 0006), anyone on the hotspot can open it, arm the
  motors for 60 s and restart the service, as with `/debug` until now (ADR 0009). Set the token
  on any other network.
- The page polls `/debug/state` (33 KB, 75 ms on the board) every 5 s while shown, every 20 s
  when hidden; the sound checks behind it run on the same cadence.
  *Amended 2026-10-27:* by then the state was 59 KB and 1.1 to 1.3 s on the board
  ([results](../results/2026-10-27-fortune-on-the-board.md)). It now carries the device table,
  its summary and its own `timing` ([0021](0021-one-device-table.md)); the page reads parts only
  from the table, and a stale state keeps its rows, dimmed, under "No answer from the hat for
  N s". The size and time after that change are not measured yet.
- Over plain http the page works, but the screen may sleep and there is no phone microphone;
  the band says so and links to the https address.
- `/face`, `fish.js`, `fish.css` and `index.html` are kept until after the fair; the browser
  microphone's server routes stay for the switch.
- Measured on the board without motors: [results](../results/2026-10-16-hat-phone-page.md).
  Not yet shown on his phone.
