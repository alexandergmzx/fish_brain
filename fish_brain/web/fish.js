/* On-screen Billy Bass — whole-fish sprite STATE MACHINE.
 *
 * Each frame we pick ONE composite PNG of the whole fish from the state tuple
 * (neck, mouth, tail) — because an open mouth looks different when the neck is also out, so
 * the poses can't be composed from independent layers.
 *   Mouth (0..3): the precomputed loudness envelope sent with each reply, played on the
 *                 browser's own clock (eased by a spring) -> quantized to 4 openness steps.
 *                 So the mouth animates even with browser sound off / autoplay blocked (e.g.
 *                 the startup greeting). Falls back to live AnalyserNode amplitude for the
 *                 manual "probar con un WAV" test, which has no precomputed envelope.
 *   Neck (Rest|Out) : Out while a NECK gesture is firing, else Rest.
 *   Tail (Rest|Flap): Flap while a TAIL gesture is firing, else Rest.
 * Sprite name: `neck{Rest|Out}_mouth{0..3}_tail{Rest|Flap}.png` (see web/img/README.md).
 * Bubbles: drawn on top. Connection: a corner dot (#conn-dot) — green/red/amber.
 *
 * Assets live in fish_brain/web/img/ and are served at /img/<name>.png. Missing sprites fall
 * back to a simpler pose (see currentSprite); if none load, the stage shows a hint so the page
 * never looks broken — drop the four neckRest_mouth{0..3}_tailRest poses in first.
 */
(() => {
  "use strict";

  const canvas = document.getElementById("stage");
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  const BG = "#91b9bc";

  const statusEl = document.getElementById("status");
  const dot = document.getElementById("conn-dot");
  const sens = document.getElementById("sensitivity");
  const sensVal = document.getElementById("sensitivityValue");
  const toggleBubbles = document.getElementById("toggleBubbles");
  const toggleAudio = document.getElementById("toggleAudio");
  const fileInput = document.getElementById("audioFile");
  const micSelect = document.getElementById("micSelect");
  const micMeter = document.getElementById("micMeter");
  const pttButton = document.getElementById("pttButton");
  const tUser = document.getElementById("tUser");
  const tFish = document.getElementById("tFish");
  const speakText = document.getElementById("speakText");
  const speakBtn = document.getElementById("speakBtn");
  const toggleWait = document.getElementById("toggleWait");

  // Show STT (what you said) / reply (what the fish says) under the level meter.
  function setTranscript(role, text) {
    const span = role === "fish" ? tFish : tUser;
    span.textContent = text || "…";
    const p = span.parentElement;
    p.classList.remove("updated");
    void p.offsetWidth;                 // restart the flash animation
    p.classList.add("updated");
  }

  sens.addEventListener("input", () => (sensVal.textContent = sens.value));

  // ---- hold-to-talk: drive the host's push-to-talk from the browser ----
  // POST /ptt {down} on press/release edges; the host records while held. Works with the
  // button (mouse/touch) or the spacebar, so you don't need terminal focus or pynput.
  // When the host sets FISH_VIZ_TOKEN, open the page as /?token=... and every POST carries it.
  const PARAMS = new URLSearchParams(location.search);
  // The token leaves the address bar (history, screenshots, a shared link) and lives in
  // sessionStorage for this tab; a reload keeps it, a new tab needs the link again.
  let TOKEN = PARAMS.get("token") || "";
  if (TOKEN) {
    try { sessionStorage.setItem("fishToken", TOKEN); } catch (_) {}
    PARAMS.delete("token");
    const qs = PARAMS.toString();
    try { history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + location.hash); } catch (_) {}
  } else {
    try { TOKEN = sessionStorage.getItem("fishToken") || ""; } catch (_) {}
  }
  const tokenQuery = () => (TOKEN ? "?token=" + encodeURIComponent(TOKEN) : "");
  // Visitor view for a touch display (/?kiosk=1): fish and one talk target, the rest behind
  // an operator corner. The operator console (/?console=1) is the same machine on a phone in
  // portrait: the kiosk layout plus a status strip, muted. The default page is unchanged.
  const CONSOLE = PARAMS.get("console") === "1";
  const KIOSK = PARAMS.get("kiosk") === "1" || CONSOLE;
  if (KIOSK) document.documentElement.classList.add("kiosk");
  if (CONSOLE) document.documentElement.classList.add("console");
  if (KIOSK && PARAMS.get("lite") === "1") document.documentElement.classList.add("lite");
  function jsonHeaders() {
    const h = { "Content-Type": "application/json" };
    if (TOKEN) h["X-Fish-Token"] = TOKEN;
    return h;
  }
  let pttDown = false;
  // Leaving the page while holding (phone locks, tab switch) must still release: a normal
  // fetch can be cancelled as the page hides, a beacon is not.
  function releasePttNow() {
    needRelease = false;
    if (!pttDown) return;
    pttDown = false;
    pttButton.classList.remove("recording");
    const url = "/ptt" + tokenQuery();         // a beacon carries no header: the query form
    const body = new Blob([JSON.stringify({ down: false })], { type: "application/json" });
    if (!(navigator.sendBeacon && navigator.sendBeacon(url, body))) {
      fetch(url, { method: "POST", headers: jsonHeaders(), body: JSON.stringify({ down: false }),
                   keepalive: true }).catch(() => {});
    }
  }
  window.addEventListener("pagehide", releasePttNow);
  window.addEventListener("blur", releasePttNow);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") releasePttNow();
  });
  // The host can end a press itself (recording limit reached): follow it, or the next
  // press would be ignored as "already down".
  // After the host ends a press, a key that is still physically down keeps auto-repeating;
  // those repeats must not count as a new press until the key has really been released.
  let needRelease = false;
  function hostReleasedPtt() {
    if (pttDown) needRelease = true;
    pttDown = false;
    pttButton.classList.remove("recording");
  }
  function setPtt(down) {
    if (!down) needRelease = false;            // a real release (before the edge check)
    else if (needRelease) return;
    if (down === pttDown) return;              // edges only (keydown auto-repeats)
    pttDown = down;
    pttButton.classList.toggle("recording", down);
    fetch("/ptt", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ down }),
    }).catch(() => {});
  }
  if (!KIOSK) {
    pttButton.addEventListener("mousedown", (e) => { e.preventDefault(); setPtt(true); });
    pttButton.addEventListener("touchstart", (e) => { e.preventDefault(); setPtt(true); }, { passive: false });
    pttButton.addEventListener("touchend", (e) => { e.preventDefault(); setPtt(false); });
    pttButton.addEventListener("touchcancel", () => setPtt(false));
    window.addEventListener("mouseup", () => setPtt(false));   // release anywhere, not just on the button
  } else {
    // A long press on iOS raises the text loupe over the target; pointer events still
    // fire with the touch default cancelled, so the hold below is untouched.
    pttButton.addEventListener("touchstart", (e) => e.preventDefault(), { passive: false });
  }
  const typingTag = (t) => t && /^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName);
  // X11/Linux auto-repeat fires keyup+keydown PAIRS while a key is held, which would flap the
  // recording on/off. Debounce the release: a keyup schedules stop, but the auto-repeat keydown
  // right after cancels it — so the hold stays continuous; a real release has no following keydown.
  let spaceUpTimer = null;
  window.addEventListener("keydown", (e) => {
    if (e.code !== "Space" || typingTag(e.target)) return;
    e.preventDefault();
    if (spaceUpTimer) { clearTimeout(spaceUpTimer); spaceUpTimer = null; }
    setPtt(true);
  });
  window.addEventListener("keyup", (e) => {
    if (e.code !== "Space" || typingTag(e.target)) return;
    e.preventDefault();
    if (spaceUpTimer) clearTimeout(spaceUpTimer);
    spaceUpTimer = setTimeout(() => { spaceUpTimer = null; setPtt(false); }, 80);
  });

  // ---- mic picker + live level meter (only fed while the host is recording) ----
  // The host enumerates its own input devices (sounddevice) and records from the chosen
  // one; we just list/select them and draw the RMS levels it streams over SSE.
  async function loadMics() {
    try {
      const r = await fetch("/mics");
      const { devices = [], current = null, error } = await r.json();
      if (error) return;                       // host can't enumerate mics; keep "Predeterminado"
      micSelect.innerHTML = '<option value="">Predeterminado</option>';
      for (const d of devices) {
        const o = document.createElement("option");
        o.value = d.id;                        // stable PipeWire source name (or sounddevice index)
        o.textContent = d.name + (d.default ? " (predeterminado)" : "");
        if (current !== null && String(current) === d.id) o.selected = true;
        micSelect.appendChild(o);
      }
    } catch (e) { /* offline: leave the default option */ }
  }
  micSelect.addEventListener("change", () => {
    fetch("/mic", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ device: micSelect.value || null }),
    }).catch(() => {});
  });

  // ---- text box: make the fish say typed text verbatim (POST /speak) ----
  function sendSpeak() {
    const text = speakText.value.trim();
    if (!text) return;
    fetch("/speak", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ text }),
    }).catch(() => {});
    speakText.value = "";
  }
  speakBtn.addEventListener("click", sendSpeak);
  speakText.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendSpeak(); }
  });

  // ---- "esperar para hablar": gate auto-speak of replies (POST /wait) ----
  toggleWait.addEventListener("change", () => {
    fetch("/wait", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ on: toggleWait.checked }),
    }).catch(() => {});
  });

  const mctx = micMeter.getContext("2d");
  const MW = micMeter.width, MH = micMeter.height;
  const MIC_GAIN = 4.0;                         // RMS is small; scale for display
  const micHist = new Array(140).fill(0);       // scrolling loudness history
  let micPeak = 0;                              // eased peak for the level bar
  function pushMicLevel(rms) {
    const v = Math.min(1, rms * MIC_GAIN);
    micHist.push(v); micHist.shift();
  }
  function drawMicMeter() {
    // Decay toward silence so the meter settles after the key is released.
    micHist[micHist.length - 1] *= 0.92;
    let cur = micHist[micHist.length - 1];
    micPeak += ((cur > micPeak ? cur : micPeak * 0.9) - micPeak) * 0.35;  // snappy up, soft down
    mctx.clearRect(0, 0, MW, MH);
    // scrolling waveform (centered bars)
    const n = micHist.length, bw = MW / n, mid = MH / 2;
    for (let i = 0; i < n; i++) {
      const h = micHist[i] * (MH - 4);
      mctx.fillStyle = `rgba(99,179,237,${0.25 + 0.6 * micHist[i]})`;
      mctx.fillRect(i * bw, mid - h / 2, Math.max(1, bw - 1), h);
    }
    // peak level bar along the bottom
    mctx.fillStyle = micPeak > 0.85 ? "#f56565" : "#48bb78";
    mctx.fillRect(0, MH - 3, micPeak * MW, 3);
  }

  // ---- sprite state machine (edit to match your PNGs) --------------------
  // Whole-fish composites named by the (neck, mouth, tail) state. Drop the PNGs in web/img/.
  const MOUTH_LEVELS = 4;                 // mouth openness steps 0..3
  const NECK = ["Rest", "Out"];           // index 0 = rest/closed, 1 = head-out
  const TAIL = ["Rest", "Flap"];          // index 0 = rest, 1 = flapped
  const stateName = (n, m, t) => `neck${NECK[n]}_mouth${m}_tail${TAIL[t]}.png`;

  // ---- image preloading --------------------------------------------------
  const images = new Map();            // name -> HTMLImageElement (only if it loaded)
  let anyLoaded = false;
  let baseW = 0, baseH = 0;            // natural size of the first loaded image (for "contain")

  function load(name) {
    if (!name || images.has(name)) return;
    const img = new Image();
    img.onload = () => {
      images.set(name, img);
      anyLoaded = true;
      if (!baseW) { baseW = img.naturalWidth; baseH = img.naturalHeight; }
      wakeDraw();                         // a dozing console must show the new pose
    };
    img.onerror = () => { /* missing PNG: skip silently */ };
    img.src = "/img/" + name;
  }
  for (let n = 0; n < NECK.length; n++)
    for (let m = 0; m < MOUTH_LEVELS; m++)
      for (let t = 0; t < TAIL.length; t++) load(stateName(n, m, t));

  // ---- spring (eases the mouth level so frames don't chatter) ------------
  // Critically damped (d = 2*sqrt(k)) so it never overshoots or chatters. Smooths every path
  // (envelope replies + the manual WAV test), since both feed mouthTarget through step().
  // Tune k for snappier/softer mouth; raise -> snappier, lower -> smoother.
  const mouth = { value: 0, vel: 0, k: 104, d: 20 };
  function step(s, target, dt) {
    const f = -s.k * (s.value - target) - s.d * s.vel;
    s.vel += f * dt;
    s.value += s.vel * dt;
    if (s.value < 0) { s.value = 0; s.vel = 0; }
    if (s.value > 1) { s.value = 1; s.vel = 0; }
  }

  // ---- audio -------------------------------------------------------------
  let audioCtx = null, analyser = null, freqData = null, currentSource = null;
  let playing = false, mouthTarget = 0;

  function ensureCtx() {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    return audioCtx;
  }
  async function playBuffer(arrayBuffer, offsetS = 0) {
    const actx = ensureCtx();
    if (actx.state === "suspended") await actx.resume();
    const buf = await actx.decodeAudioData(arrayBuffer);
    if (currentSource) { try { currentSource.stop(); } catch (e) {} }
    analyser = actx.createAnalyser();
    analyser.fftSize = 256;
    freqData = new Uint8Array(analyser.frequencyBinCount);
    const src = actx.createBufferSource();
    src.buffer = buf;
    src.connect(analyser);
    if (toggleAudio.checked) analyser.connect(actx.destination);
    src.start(0, Math.max(0, offsetS));
    currentSource = src;
    playing = true;
    src.onended = () => { if (currentSource === src) { playing = false; mouthTarget = 0; } };
  }
  // Mouth envelope sent with the reply: [[t_ms, level0to1], ...] on the browser's own clock.
  let mouthTrackData = null, mouthClock = 0, mouthTrackEnd = 0;
  // ageMs: how long ago the host announced the reply (a replay to a page that just
  // connected); the track starts that far in, so a mid-phrase reconnect animates the rest.
  function startMouthTrack(track, ageMs = 0) {
    if (track && track.length && ageMs <= track[track.length - 1][0]) {
      mouthTrackData = track;
      mouthClock = performance.now() - ageMs;
      mouthTrackEnd = track[track.length - 1][0];
    } else {
      mouthTrackData = null;
    }
  }
  function envelopeLevel(now) {
    if (!mouthTrackData) return null;
    const t = now - mouthClock;
    if (t > mouthTrackEnd + 150) { mouthTrackData = null; return 0; }  // done -> closed
    let lvl = 0;
    for (let i = 0; i < mouthTrackData.length; i++) {
      if (mouthTrackData[i][0] <= t) lvl = mouthTrackData[i][1]; else break;
    }
    return lvl;
  }
  async function handleSpeak(ev) {
    const age = Math.max(0, Number(ev.age_ms) || 0);   // 0 live; replayed: time already gone
    scheduleGestures(ev.gestures || [], age);
    startMouthTrack(ev.mouth || null, age);   // drives the mouth even with sound off
    wakeDraw();
    if (age > (ev.duration_ms || 0)) return;  // an old reply: nothing left to hear
    if (!toggleAudio.checked || CONSOLE) return;  // sound off, or the console (always muted)
    try {
      const headers = TOKEN ? { "X-Fish-Token": TOKEN } : {};
      const resp = await fetch(ev.audio, { headers });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      await playBuffer(await resp.arrayBuffer(), age / 1000);
    } catch (e) { console.error("speak audio failed:", e); }
  }
  function sampleMouth(now) {
    const env = envelopeLevel(now);           // precomputed envelope wins when present
    if (env !== null) return Math.min(1, env * parseFloat(sens.value));
    if (!playing || !analyser) return 0;      // fallback: live analyser (manual WAV test)
    analyser.getByteFrequencyData(freqData);
    let sum = 0;
    for (let i = 0; i < freqData.length; i++) sum += freqData[i];
    const avg = sum / freqData.length / 255;
    return Math.min(1, avg * parseFloat(sens.value));
  }

  // ---- gestures (NECK / TAIL) -------------------------------------------
  // Body "v1 ms1 v2 ms2 ..."; + = out, - = return. We only need WHEN a channel is "out".
  // TAIL (and any self-contained out+return chain) is a transient window = sum of its ms.
  // NECK in speech mode comes as single-direction strokes: a pure-positive body means "swing
  // out and HOLD" (the head stays out, motor off) until a pure-negative "return" stroke — so
  // the head can stay open across words/sentences. We track those as a baseline timeline.
  let activeGestures = [];          // {channel, start, end} transient windows
  let neckBaseline = [];            // {start, out} hold/return transitions (sorted by start)
  function scheduleGestures(list, ageMs = 0) {
    const now = performance.now();
    pruneNeckBaseline(now);
    const base = now - ageMs;         // a replayed reply started ageMs ago
    for (const [tMs, channel, body] of list) {
      const ch = String(channel).toUpperCase();
      const nums = String(body).trim().split(/\s+/).map(Number);
      let total = 0, hasPos = false, hasNeg = false;
      for (let i = 0; i + 1 < nums.length; i += 2) {
        total += nums[i + 1] || 0;
        if (nums[i] > 0) hasPos = true; else if (nums[i] < 0) hasNeg = true;
      }
      const start = base + tMs;
      if (ch === "NECK" && hasPos !== hasNeg) {
        // single-direction stroke -> hold-open / return baseline transition
        neckBaseline.push({ start, out: hasPos });
      } else {
        // self-contained chain (out+return) or tail flap -> transient window
        activeGestures.push({ channel: ch, start, end: start + total });
      }
    }
    neckBaseline.sort((a, b) => a.start - b.start);
  }
  function pruneNeckBaseline(now) {
    // Drop already-applied transitions but keep the most recent one (it holds current state).
    let lastPast = -1;
    for (let i = 0; i < neckBaseline.length; i++) {
      if (neckBaseline[i].start <= now) lastPast = i; else break;
    }
    if (lastPast > 0) neckBaseline = neckBaseline.slice(lastPast);
  }
  function gestureActive(channel, now) {
    for (const g of activeGestures) {
      if (g.channel === channel && now >= g.start && now < g.end) return true;
    }
    return false;
  }
  function neckOut(now) {
    let out = false;
    for (const e of neckBaseline) { if (e.start <= now) out = e.out; else break; }
    return out || gestureActive("NECK", now);   // baseline hold OR a transient out chain
  }

  // ---- bubbles -----------------------------------------------------------
  const bubbles = [];
  function updateBubbles(dt) {
    if (toggleBubbles.checked && Math.random() < dt * 3.0) {
      bubbles.push({ x: W * (0.25 + Math.random() * 0.5), y: H - 8,
                     r: 2 + Math.random() * 6, v: 25 + Math.random() * 40 });
    }
    for (const b of bubbles) { b.y -= b.v * dt; b.x += Math.sin(b.y * 0.05) * 0.3; }
    for (let i = bubbles.length - 1; i >= 0; i--) if (bubbles[i].y < -10) bubbles.splice(i, 1);
  }
  function drawBubbles() {
    ctx.save();
    ctx.strokeStyle = "rgba(255,255,255,0.5)";
    ctx.fillStyle = "rgba(255,255,255,0.18)";
    for (const b of bubbles) {
      ctx.beginPath();
      ctx.arc(b.x, b.y, b.r, 0, Math.PI * 2);
      ctx.fill(); ctx.stroke();
    }
    ctx.restore();
  }

  // ---- compositing -------------------------------------------------------
  function containRect(iw, ih) {
    const s = Math.min(W / iw, H / ih);
    const dw = iw * s, dh = ih * s;
    return [(W - dw) / 2, (H - dh) / 2, dw, dh];
  }
  // Pick the loaded sprite for the current state, degrading gracefully when art is missing:
  // keep mouth openness as long as possible, then shed neck/tail nuance. Final fallback is
  // neckRest_mouth0_tailRest, so the four base poses alone already animate the mouth.
  function currentSprite(now) {
    const neck = neckOut(now) ? 1 : 0;
    const tail = gestureActive("TAIL", now) ? 1 : 0;
    const mouth0 = Math.max(0, Math.min(MOUTH_LEVELS - 1, Math.round(mouth.value * (MOUTH_LEVELS - 1))));
    for (let m = mouth0; m >= 0; m--) {
      for (const [n, t] of [[neck, tail], [neck, 0], [0, tail], [0, 0]]) {
        const img = images.get(stateName(n, m, t));
        if (img) return img;
      }
    }
    return null;
  }
  function draw(now) {
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = BG;
    ctx.fillRect(0, 0, W, H);

    if (!anyLoaded) {
      ctx.fillStyle = "rgba(20,50,55,0.7)";
      ctx.font = "16px 'Segoe UI', sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("Coloca PNGs en web/img/ (ver README)", W / 2, H / 2);
    } else {
      const img = currentSprite(now);
      if (img) {
        const rect = containRect(baseW, baseH);
        ctx.drawImage(img, rect[0], rect[1], rect[2], rect[3]);
      }
    }
    drawBubbles();
  }

  // ---- main loop ---------------------------------------------------------
  let last = performance.now();
  // On the board's own display the browser shares four small cores with the voice: draw
  // the visitor view at about 24 frames a second instead of the display's 60. The console
  // runs on a phone that is also the hotspot: 20 a second, and none at all while the fish
  // is still (then a 250 ms poll stands in for requestAnimationFrame until something moves).
  const FRAME_MIN_MS = KIOSK ? 1000 / (Number(PARAMS.get("fps")) || (CONSOLE ? 20 : 24)) - 3 : 0;
  let dozing = false, dozeTimer = null, stillDrawn = false;
  function nothingMoves(now) {
    if (mouthTrackData || playing || mouth.value >= 0.01 || bubbles.length) return false;
    if (activeGestures.length) return false;
    for (const e of neckBaseline) if (e.start > now) return false;   // a neck move is due
    return true;
  }
  function wakeDraw() {                        // something changed: back to animation frames
    stillDrawn = false;
    if (!dozing) return;
    dozing = false;
    clearTimeout(dozeTimer);
    last = performance.now();
    requestAnimationFrame(frame);
  }
  function frame(now) {
    if (!dozing && now - last < FRAME_MIN_MS) { requestAnimationFrame(frame); return; }
    let dt = (now - last) / 1000;
    last = now;
    if (dt > 0.05) dt = 0.05;

    if (CONSOLE && nothingMoves(now)) {
      if (!stillDrawn) {                       // draw the resting pose once, then doze
        try { draw(now); } catch (e) { console.error("draw frame error:", e); }
        stillDrawn = true;
      }
      dozing = true;
      dozeTimer = setTimeout(() => frame(performance.now()), 250);
      return;
    }
    dozing = false;
    stillDrawn = false;

    mouthTarget = sampleMouth(now);
    step(mouth, mouthTarget, dt);
    if (activeGestures.length) activeGestures = activeGestures.filter((g) => now < g.end + 50);
    updateBubbles(dt);

    try {
      draw(now);
      // The meter is behind the operator corner in the visitor view, and hidden in the console.
      if (!KIOSK || (!CONSOLE && document.documentElement.classList.contains("ops-open"))) drawMicMeter();
    } catch (e) { console.error("draw frame error:", e); }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  // ---- visitor view (kiosk) ------------------------------------------------
  // What the visitor sees is what the host is doing, not what the finger is doing: the
  // target shows "listening" only while level events arrive (they flow only while the host
  // records), "thinking" from the release to the reply, "speaking" for the length of the
  // reply. All of it comes from events the page already receives.
  const kiosk = (() => {
    if (!KIOSK) return { conn() {}, event() {} };
    const root = document.documentElement;
    const HINT = {
      ready: "Mantén para hablar",
      listening: "Te escucho…",
      waiting: "Un momento…",
      thinking: "Pensando…",
      speaking: "Estoy hablando…",
      offline: "Vuelvo enseguida…",
    };
    const label = document.createElement("span");
    label.id = "kioskHint";
    pttButton.textContent = "";
    pttButton.appendChild(label);
    // Transcript lines: over the fish in the kiosk, in the bottom strip in the console.
    let heard, reply;
    if (CONSOLE) {
      heard = document.getElementById("cHeard");
      reply = document.getElementById("cReply");
    } else {
      const say = document.createElement("div");
      say.id = "kioskSay";
      say.innerHTML = '<p id="kioskHeard"></p><p id="kioskReply"></p>';
      document.querySelector(".stage-wrap").appendChild(say);
      heard = say.querySelector("#kioskHeard"); reply = say.querySelector("#kioskReply");
    }

    let online = false, state = "", pressedAt = 0, lastLevel = 0, speakUntil = 0;
    let thinkTimer = null;
    function show(next) {
      if (next === state) return;
      state = next;
      for (const k of Object.keys(HINT)) root.classList.toggle("k-" + k, k === next);
      label.textContent = HINT[next];
    }
    function settle() {                         // the state when nothing else is going on
      if (!online) return show("offline");
      if (performance.now() < speakUntil) return show("speaking");
      show("ready");
    }
    function nudge() {                          // a press that cannot be taken right now
      pttButton.classList.remove("k-nudge");
      void pttButton.offsetWidth;               // restart the animation
      pttButton.classList.add("k-nudge");
    }

    // One hold = from the first finger down to the last finger up. A second finger, a palm
    // or a finger sliding off the target must not end it.
    const fingers = new Set();
    function down(e) {
      e.preventDefault();
      fingers.add(e.pointerId);
      try { pttButton.setPointerCapture(e.pointerId); } catch (_) {}
      if (fingers.size > 1) return;
      if (!online || performance.now() < speakUntil || state === "thinking") { nudge(); return; }
      pressedAt = performance.now();
      lastLevel = 0;
      setPtt(false);                            // clears a "host ended the last press" latch
      setPtt(true);
      show("waiting");
    }
    function up(e) {
      if (!fingers.delete(e.pointerId) || fingers.size) return;
      if (!pttDown) { settle(); return; }
      const held = performance.now() - pressedAt;
      setPtt(false);
      if (lastLevel && held > 350) {
        show("thinking");
        clearTimeout(thinkTimer);
        thinkTimer = setTimeout(settle, 45000);  // a turn that never answers must not stick
      } else {
        nudge();                                 // a tap, or the host was not recording
        settle();
      }
    }
    pttButton.addEventListener("pointerdown", down);
    for (const t of ["pointerup", "pointercancel", "lostpointercapture"]) {
      pttButton.addEventListener(t, up);
    }
    // Nothing but the hold does anything on a public screen.
    for (const t of ["contextmenu", "selectstart", "dragstart", "gesturestart"]) {
      document.addEventListener(t, (e) => { if (!root.classList.contains("ops-open")) e.preventDefault(); });
    }
    document.addEventListener("wheel", (e) => { if (e.ctrlKey) e.preventDefault(); }, { passive: false });

    // Operator corner: five taps in the top-right corner within three seconds.
    const corner = document.createElement("div");
    corner.id = "opsCorner";
    document.body.appendChild(corner);
    const opsStatus = document.createElement("pre");
    opsStatus.id = "opsStatus";
    document.querySelector(".controls").prepend(opsStatus);
    let taps = [], opsTimer = null, opsPoll = null;
    // The console strip: what the operator reads between turns, in words, not meters.
    const strip = {
      link: document.getElementById("cLink"), net: document.getElementById("cNet"),
      mic: document.getElementById("cMic"), ear: document.getElementById("cListen"),
    };
    const LINK_WORD = { ok: "pez conectado", silent: "pez callado", off: "sin pez" };
    function paintStrip(st) {
      if (!CONSOLE) return;
      if (!st) {
        strip.link.textContent = "sin respuesta del cerebro";
        strip.link.className = "bad";
        strip.net.textContent = ""; strip.mic.textContent = ""; strip.ear.textContent = "";
        return;
      }
      const health = (st.link || {}).health || "";
      strip.link.textContent = LINK_WORD[health] || ("enlace " + (health || "?"));
      strip.link.className = health === "ok" ? "good" : "bad";
      strip.net.textContent = st.online === undefined ? "internet ?" : st.online ? "internet" : "sin internet";
      strip.net.className = st.online ? "good" : "bad";
      const b = st.backends || {};
      const cap = st.mic_capture === "browser" ? "mic del teléfono" : "mic del tablero";
      strip.mic.textContent = cap + (b.ptt ? " · " + b.ptt : "") + (st.wait ? " · espera activada" : "");
      strip.mic.className = "";
      strip.ear.textContent = st.listening ? "escuchando" : "";
      strip.ear.className = st.listening ? "ear" : "";
    }
    async function refreshStatus() {
      try {
        const st = await (await fetch("/status", { cache: "no-store" })).json();
        const link = st.link || {};
        const b = st.backends || {};
        opsStatus.textContent =
          `${st.host}  ${st.ip}  up ${st.up_s}s${st.tls ? "  https" : ""}\n` +
          `link: ${link.desc || "?"}  [${link.health || "?"}]\n` +
          `internet: ${st.online === undefined ? "?" : st.online ? "ok" : "OFFLINE"}` +
          `   ready: ${st.ready ? "yes" : "no"}${st.wait ? "   WAIT-TO-SPEAK ON" : ""}` +
          `${st.listening ? "   listening" : ""}\n` +
          `stt ${b.stt || "?"}  llm ${b.llm || "?"}  tts ${b.tts || "?"}\nptt ${b.ptt || "?"}` +
          `${st.mic_capture ? "  mic " + st.mic_capture : ""}` +
          `${st.max_record_s ? "  max " + st.max_record_s + "s" : ""}`;
        paintStrip(st);
      } catch (_) {
        opsStatus.textContent = "sin respuesta del pez (fish-brain)";
        paintStrip(null);
      }
    }
    function ops(open) {
      root.classList.toggle("ops-open", open);
      clearTimeout(opsTimer); clearInterval(opsPoll);
      if (open) {
        refreshStatus(); if (!CONSOLE) loadMics();
        if (!CONSOLE) opsPoll = setInterval(refreshStatus, 2000);   // the console polls anyway
        opsTimer = setTimeout(() => ops(false), 45000);
      }
    }
    if (CONSOLE) {
      // Muted and without bubbles: the phone shows, the fish speaks.
      toggleAudio.checked = false;
      toggleBubbles.checked = false;
      refreshStatus();
      setInterval(refreshStatus, 3000);
      document.getElementById("consoleGear").addEventListener("click", (e) => {
        e.preventDefault();
        ops(!root.classList.contains("ops-open"));
      });
    }
    corner.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      const now = performance.now();
      taps = taps.filter((t) => now - t < 3000);
      taps.push(now);
      if (taps.length >= 5) { taps = []; ops(!root.classList.contains("ops-open")); }
    });

    show("offline");
    return {
      conn(live) { online = live; if (!pttDown) settle(); },
      event(ev) {
        if (ev.type === "level") {
          lastLevel = performance.now();
          if (CONSOLE) strip.ear.textContent = "escuchando";
          if (pttDown) {
            show("listening");
            pttButton.style.setProperty("--lvl", Math.min(1, ev.rms * 12).toFixed(3));
          }
        } else if (ev.type === "ptt" && !ev.held) {
          fingers.clear();
          if (state === "listening" || state === "waiting") show("thinking");
        } else if (ev.type === "stt") {
          if (ev.role === "user") {
            heard.textContent = ev.text || "";
            if ((ev.text || "").startsWith("…")) { clearTimeout(thinkTimer); nudge(); settle(); }
          } else {
            reply.textContent = ev.text || "";
          }
        } else if (ev.type === "speak") {
          clearTimeout(thinkTimer);
          const left = (ev.duration_ms || 0) - Math.max(0, Number(ev.age_ms) || 0);
          if (left < 0) { settle(); return; }    // a replay of a reply that already ended
          speakUntil = performance.now() + left + 300;
          show("speaking");
          setTimeout(() => { if (!pttDown) settle(); }, left + 350);
        }
      },
    };
  })();

  // ---- transport ---------------------------------------------------------
  function setConn(state, text) {
    dot.className = state;            // "" | "live" | "off"
    statusEl.textContent = text;
    if (KIOSK) kiosk.conn(state === "live");
  }
  // The host sends {"type":"hb"} every 10 s of silence. A phone that slept, changed network
  // or lost the hotspot can keep a dead EventSource open for minutes: if nothing (not even
  // a heartbeat) arrived for STALE_MS, drop it and open a new one; the same on coming back.
  const STALE_MS = 25000;
  let es = null, lastMsgAt = 0;
  function connect() {
    if (es) { try { es.close(); } catch (_) {} }
    es = new EventSource("/events" + tokenQuery());
    lastMsgAt = performance.now();
    es.onopen = () => { lastMsgAt = performance.now(); setConn("live", "Conectado"); };
    es.onerror = () => setConn("off", "Desconectado — reintentando…");
    es.onmessage = (e) => {
      lastMsgAt = performance.now();
      let ev;
      try { ev = JSON.parse(e.data); } catch (_) { return; }
      if (ev.type === "hb") return;
      if (ev.type === "speak") handleSpeak(ev);
      else if (ev.type === "level") { pushMicLevel(ev.rms); wakeDraw(); }
      else if (ev.type === "stt") setTranscript(ev.role, ev.text);
      else if (ev.type === "ptt" && !ev.held) hostReleasedPtt();
      else if (ev.type === "draft") { speakText.value = ev.text || ""; speakText.focus(); }
      if (KIOSK) kiosk.event(ev);
    };
  }
  function stale() {
    return !es || es.readyState === EventSource.CLOSED || performance.now() - lastMsgAt > STALE_MS;
  }
  function reconnectIfStale() {
    if (!stale()) return;
    setConn("off", "Desconectado — reintentando…");
    connect();
  }
  connect();
  setInterval(reconnectIfStale, 5000);
  window.addEventListener("pageshow", reconnectIfStale);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") reconnectIfStale();
  });
  loadMics();

  // offline test: load a WAV by hand
  fileInput.addEventListener("change", async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    try { await playBuffer(await f.arrayBuffer()); }
    catch (err) { console.error(err); }
  });
  // resume a suspended AudioContext on first interaction (autoplay policy)
  document.addEventListener("click", () => {
    if (audioCtx && audioCtx.state === "suspended") audioCtx.resume();
  });
})();
