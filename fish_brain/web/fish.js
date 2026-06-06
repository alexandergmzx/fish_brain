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
  let pttDown = false;
  function setPtt(down) {
    if (down === pttDown) return;              // edges only (keydown auto-repeats)
    pttDown = down;
    pttButton.classList.toggle("recording", down);
    fetch("/ptt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ down }),
    }).catch(() => {});
  }
  pttButton.addEventListener("mousedown", (e) => { e.preventDefault(); setPtt(true); });
  pttButton.addEventListener("touchstart", (e) => { e.preventDefault(); setPtt(true); }, { passive: false });
  pttButton.addEventListener("touchend", (e) => { e.preventDefault(); setPtt(false); });
  pttButton.addEventListener("touchcancel", () => setPtt(false));
  window.addEventListener("mouseup", () => setPtt(false));   // release anywhere, not just on the button
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
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device: micSelect.value || null }),
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
  async function playBuffer(arrayBuffer) {
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
    src.start(0);
    currentSource = src;
    playing = true;
    src.onended = () => { if (currentSource === src) { playing = false; mouthTarget = 0; } };
  }
  // Mouth envelope sent with the reply: [[t_ms, level0to1], ...] on the browser's own clock.
  let mouthTrackData = null, mouthClock = 0, mouthTrackEnd = 0;
  function startMouthTrack(track) {
    if (track && track.length) {
      mouthTrackData = track;
      mouthClock = performance.now();
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
    scheduleGestures(ev.gestures || []);
    startMouthTrack(ev.mouth || null);        // drives the mouth even with sound off
    if (!toggleAudio.checked) return;         // sound off: envelope is enough; skip audio
    try {
      const resp = await fetch(ev.audio);
      await playBuffer(await resp.arrayBuffer());
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
  // Body "v1 ms1 v2 ms2 ..."; we only need WHEN the channel is firing to pick a pose frame.
  let activeGestures = [];
  function scheduleGestures(list) {
    const now = performance.now();
    for (const [tMs, channel, body] of list) {
      const nums = String(body).trim().split(/\s+/).map(Number);
      let total = 0;
      for (let i = 1; i < nums.length; i += 2) total += nums[i] || 0;
      activeGestures.push({
        channel: channel.toUpperCase(),
        start: now + tMs,
        end: now + tMs + total,
      });
    }
  }
  function gestureActive(channel, now) {
    for (const g of activeGestures) {
      if (g.channel === channel && now >= g.start && now < g.end) return true;
    }
    return false;
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
    const neck = gestureActive("NECK", now) ? 1 : 0;
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
  function frame(now) {
    let dt = (now - last) / 1000;
    last = now;
    if (dt > 0.05) dt = 0.05;

    mouthTarget = sampleMouth(now);
    step(mouth, mouthTarget, dt);
    if (activeGestures.length) activeGestures = activeGestures.filter((g) => now < g.end + 50);
    updateBubbles(dt);

    try { draw(now); drawMicMeter(); } catch (e) { console.error("draw frame error:", e); }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  // ---- transport ---------------------------------------------------------
  function setConn(state, text) {
    dot.className = state;            // "" | "live" | "off"
    statusEl.textContent = text;
  }
  function connect() {
    const es = new EventSource("/events");
    es.onopen = () => setConn("live", "Conectado");
    es.onerror = () => setConn("off", "Desconectado — reintentando…");
    es.onmessage = (e) => {
      let ev;
      try { ev = JSON.parse(e.data); } catch (_) { return; }
      if (ev.type === "speak") handleSpeak(ev);
      else if (ev.type === "level") pushMicLevel(ev.rms);
      else if (ev.type === "stt") setTranscript(ev.role, ev.text);
    };
  }
  connect();
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
