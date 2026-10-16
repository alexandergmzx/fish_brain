# 0008 — The phone is the fish's face in the visitor's hands; the remote is the control

**Status:** replaced by [0011](0011-one-page-for-the-operator.md) · **Date:** 2026-10-12

## Context

ADR 0006 made the page on the operator's phone the fair's interface and drew it as an operator
console: the fish small, a round target, and a strip of status words, the transcript and the
reading row always in sight. Since 2026-10-12 the 2.4 GHz remote is the trigger and the
microphone ([results](../results/2026-10-12-remote-microphone.md)), so the target on the page is
only a status sign. The visitors are school children (ADR 0007), and at the stand the phone ends
up in their hands. What they saw was a developer's page: a dark card, small grey words, and the
fish on a flat rectangle of a different colour than the page (the canvas was filled with the
sprites' old matte, `#91b9bc`).

## Decision

1. The default view is the fish's face, for the visitor: one sea from edge to edge, the plaque
   hanging from a sign that reads "El Pez Adivino", what the fish said and what it heard as
   speech bubbles, and the state of the turn on a sign in the sand, in words, with a drawing, a
   colour and a motion per state. The view keeps its code names (`html.kiosk.console`).
2. The remote is the control. With a remote on the board the talk target cannot be pressed and
   its idle line says what to do with the remote. Without one, or with `?talk=1`, the same
   element in the same place is a hold-to-talk button.
3. Everything of the operator's is in one sheet: the status words, the reading (badge photo,
   gallery, consent tick, typed name), wait-to-speak, the text box, the technical block. It opens
   by holding the corner shell for 0.8 s (a tap does nothing but wobble it) and closes by itself
   once a badge or a name was accepted, on "Cerrar", on a touch outside, or 45 s after the last
   touch in it. The five-tap corner is off in this view and stays in `?kiosk=1`.
4. What the operator must notice without opening the sheet is on the shell: the connection as
   its pearl (green, amber, red) and a red mark when the link is not `ok`, the internet is down,
   `/status` does not answer or wait-to-speak is on.
5. The drawing is original (CSS and inline SVG in the page). Nothing is taken from the cartoon
   that inspired the look: no character, logo, lettering or font. The two fonts are open ones,
   embedded in `fish.css` and recorded in `fish_brain/web/FONTS.md`.
6. The sprites are cleaned of their matte once, in the files (`tools/sprite_clean.py`), and the
   canvas is transparent: the page has one background.
7. No change to `viz.py`: the page is still five files and `img/*.png`, so it reaches the board
   with `deploy/unoq_setup.sh sync` and a reload.

## Alternatives

- **Restyle the console and keep it the operator's**: the least work, but the screen a child
  holds would still be a strip of operator words.
- **The visitor view (`?kiosk=1`) on the phone and the console on a second device**: two devices
  to keep alive at a stand run by one person.
- **The child presses the phone's button and talks to the phone**: needs the phone's microphone
  over HTTPS, built but not yet tried on the phone (ADR 0006); the remote is measured.
- **A second, child-facing camera button for the badge**: fits the welcome line, but the photo
  goes to a cloud model and the consent tick is the operator's, so the camera stays in the sheet.
- **Fonts and drawings as files with a route in `viz.py`**: cleaner files, but a Python change
  and a service restart on the board in fair week for no visible gain.

## Consequences

- The operator no longer sees the status words at a glance: the pearl and the red mark stand in
  for them, the words are one hold away.
- A child can still open the sheet by holding the shell. Nothing in it is destructive, but the
  text box makes the fish say whatever is typed.
- The page never rests as the console did: about ten small loops run all the time, on
  `transform` and `opacity` only (a test holds this). Nothing is measured on a phone; `?lite=1`
  stops every loop if it runs hot.
- The laptop as the spare console shows the sign too while the remote is on the board: `?talk=1`
  or the space bar there.
- The fair-day matrix in `deploy/README.md` names the new words and marks.
