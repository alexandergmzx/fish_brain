/* The operator's page (docs/debug.md, ADR 0011): the debug view on a desktop or on his phone,
 * with the drawn hat showing what the fish is doing.
 *
 * One store, one stream, one render pass per animation frame for the parts that changed.
 *   GET /debug/state        the slow state, every 5 s while the page is shown and after an action
 *   GET /debug/events       every record the fish keeps (log lines, keys, turns, lines sent,
 *                           the page's own events); a first load gets only the last ones
 *   POST /debug/...         the tests, the arm, STOP;  /visit /cues /show /fortune /reading /ptt
 *                           /speak /wait /micstate /utterance: the operator's tools
 * Text from the fish only ever enters the page through textContent. Records replayed on
 * connect only set state (the visit, the last lines); what moves the hat, buzzes the phone or
 * starts a recording runs only for records that arrive live (S.caughtUp).
 */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const CAP = { log: 3000, key: 300, turn: 200, tx: 400, act: 120 };
  const SLOW = { stt: 3, llm: 5, tts: 2 };              // seconds: a stage slower than this is flagged (estimates)

  // ---- token: as the phone page does (out of the address bar, kept for this tab) ----------
  const PARAMS = new URLSearchParams(location.search);
  if (PARAMS.get("lite") === "1") document.documentElement.classList.add("lite");   // the loops stop (a hot phone)
  let TOKEN = PARAMS.get("token") || "";
  if (TOKEN) {
    try { sessionStorage.setItem("fishToken", TOKEN); } catch (_) {}
    try { history.replaceState(null, "", location.pathname); } catch (_) {}
  } else {
    try { TOKEN = sessionStorage.getItem("fishToken") || ""; } catch (_) {}
  }
  const headers = (json) => {
    const h = json ? { "Content-Type": "application/json" } : {};
    if (TOKEN) h["X-Fish-Token"] = TOKEN;
    return h;
  };
  const api = (path, body) => fetch(path, body === undefined
    ? { headers: headers(false), cache: "no-store" }
    : { method: "POST", headers: headers(true), body: JSON.stringify(body) });
  async function post(path, body) {
    try {
      const r = await api(path, body || {});
      let out = {};
      try { out = await r.json(); } catch (_) {}
      out.status = r.status;
      return out;
    } catch (_) { return { ok: false, error: "no connection", status: 0 }; }
  }

  // ---- store -------------------------------------------------------------------------------
  const S = { state: null, boot: "", log: [], keys: [], presses: {}, turns: [], tx: [], acts: [],
              llm: [], stt: [], tts: [], modelOnly: null, helloSeq: 0, caughtUp: false, openCalls: new Set(), seenCall: 0,
              visit: null, fortune: null,
              levels: [], sel: null, live: "", logOff: new Set(), logPaused: false,
              logWindow: null, armedUntil: 0, lastSeq: 0, missed: 0, connected: false };
  const dirty = new Set(["all"]);
  const mark = (...names) => { for (const n of names) dirty.add(n); schedule(); };
  let scheduled = false;
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => { scheduled = false; render(); });
  }
  const push = (arr, item, cap) => { arr.push(item); if (arr.length > cap) arr.splice(0, arr.length - cap); };

  // ---- small helpers -------------------------------------------------------------------------
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  }
  function fill(node, children) { node.textContent = ""; for (const c of children) node.appendChild(c); }
  const clock = (t) => new Date(t * 1000).toLocaleTimeString("en-GB", { hour12: false });
  const clockMs = (t) => clock(t) + "." + String(Math.floor((t % 1) * 1000)).padStart(3, "0");
  const secs = (v) => (v === undefined || v === null ? "" : Number(v).toFixed(1));
  const ago = (s) => (s < 90 ? Math.round(s) + " s" : s < 5400 ? Math.round(s / 60) + " min"
                      : (s / 3600).toFixed(1) + " h");
  function kv(node, pairs) {
    fill(node, pairs.filter((p) => p).flatMap(([k, v, cls]) =>
      [el("span", "k", k), el("span", "v" + (cls ? " " + cls : ""), v === undefined || v === null || v === "" ? "—" : v)]));
  }
  // The device table (ADR 0021) as a map by id, built once per state: every row, chip, the hat
  // and the hold read whether a part is there, failed or in use from it, never from their own test.
  let devFor = null, devMap = {};
  function dev() {
    const st = S.state;
    if (st !== devFor) {
      devFor = st; devMap = {};
      for (const d of (st && Array.isArray(st.devices) ? st.devices : [])) devMap[d.id] = d;
    }
    return devMap;
  }
  const MARK = { ok: "● ", warn: "▲ ", bad: "■ ", off: "○ " };
  // One place for what an action answered (the old per-panel spots are gone).
  let toastTimer = null;
  function msg(_node, text, ms) {
    const t = $("toast");
    if (!text) return;
    t.textContent = text;
    t.className = /refused|NOT DELIVERED|no connection|failed/.test(text) ? "warn" : "";
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, ms || 6000);
  }
  // A block that fails to start (a missing element, a browser without a feature) leaves a
  // stub: the page, STOP above all, keeps working.
  function guard(name, make, stub) {
    try { return make(); } catch (e) { console.error("[page] " + name + " is off:", e); return stub; }
  }
  const PHONE = matchMedia("(max-width: 700px)");

  // ---- ARM and STOP: wired first, so nothing below can take them down ------------------------
  let armTick = null;
  function setArmed(seconds) {
    const was = performance.now() < S.armedUntil;
    S.armedUntil = seconds > 0 ? performance.now() + seconds * 1000 : 0;
    const on = seconds > 0;
    if (on !== was || !on) {
      document.body.classList.toggle("armed", on);
      $("armBar").style.animationDuration = on ? seconds + "s" : "";
    }
    clearInterval(armTick);
    const paint = () => {
      const left = Math.max(0, Math.round((S.armedUntil - performance.now()) / 1000));
      $("armBtn").textContent = left ? "ARMED 0:" + String(left).padStart(2, "0") : "ARM locked";
      $("armBtn2").textContent = left ? "ARMED 0:" + String(left).padStart(2, "0") : "ARM";
      document.title = (left ? "ARMED · " : "") + "Sombrero";
      if (!left) { clearInterval(armTick); document.body.classList.remove("armed"); mark("panels"); }
    };
    paint();
    if (on) armTick = setInterval(paint, 500);
    mark("panels");
  }
  async function toggleArm() {
    const out = await post("/debug/arm", { on: !(performance.now() < S.armedUntil) });
    if (out.ok) setArmed(out.armed_s || 0);
  }
  $("armBtn").addEventListener("click", toggleArm);
  $("armBtn2").addEventListener("click", toggleArm);
  async function stop() {
    const b = $("stopBtn");
    b.textContent = "STOP…";
    const out = await post("/debug/stop", {});
    setArmed(0);
    b.textContent = out.status === 200 && out.ok ? "STOP sent " + new Date().toLocaleTimeString("en-GB")
                                                  : "NOT DELIVERED" + (out.error ? " (" + out.error + ")" : "");
    if (out.speaking) msg($("motorMsg"), "STOP sent; the fish is speaking: its next pulse moves the mouth again until the phrase ends", 10000);
    setTimeout(() => { b.textContent = "STOP"; }, 4000);
    refresh();
  }
  $("stopBtn").addEventListener("click", stop);
  window.addEventListener("keydown", (e) => { if (e.key === "Escape") { $("restartAsk").hidden = true; stop(); } });



  // Which tab explains a part of the fish (hints and chips name the old panel).
  const TAB_OF = { checks: "checks", inputs: "live", motors: "live", model: "model", cloud: "model",
                   voice: "voice", switches: "switches", board: "system", config: "system", clients: "system" };

  // ---- the stream ------------------------------------------------------------------------------
  // One id per load: a reconnect replaces this page's own stream on the board instead of
  // waiting for its dead socket to free one of the four places.
  const PAGE = Math.random().toString(36).slice(2, 10);
  let es = null, lastMsgAt = 0;
  function connect() {
    if (es) { try { es.close(); } catch (_) {} }
    if (document.hidden) { es = null; return; }   // resume() opens it again
    const q = new URLSearchParams();
    if (TOKEN) q.set("token", TOKEN);
    q.set("page", PAGE);
    if (S.boot && S.lastSeq) q.set("since", S.boot + "-" + S.lastSeq);
    else q.set("tail", "1500");                   // a first load: the last records, not every ring
    es = new EventSource("/debug/events" + (q.toString() ? "?" + q : ""));
    es.onopen = () => { S.connected = true; lastMsgAt = performance.now(); mark("bar"); };
    es.onerror = () => { S.connected = false; mark("bar"); checkToken(); };
    es.onmessage = (e) => {
      lastMsgAt = performance.now();
      let r;
      try { r = JSON.parse(e.data); } catch (_) { return; }
      take(r);
    };
  }
  setInterval(() => {                           // a stream that went quiet (sleep, network): reopen
    if (document.hidden) return;
    if (!es || es.readyState === EventSource.CLOSED || performance.now() - lastMsgAt > 25000) connect();
  }, 5000);
  // The server's clock against this one, from records that arrive live: each sample is at most
  // the true offset (a record is never received before it is made), so the largest is close.
  const offs = [];
  function sampleClock(r) {
    if (!r.t) return;
    offs.push(r.t - Date.now() / 1000);
    if (offs.length > 64) offs.shift();
    S.off = Math.max(...offs);
  }
  // How long ago the fish made a record, in ms (0..400): a reply's mouth starts in step.
  function ageOf(r) {
    if (!r.t || S.off === undefined) return 0;
    return Math.max(0, Math.min(400, (Date.now() / 1000 + S.off - r.t) * 1000));
  }

  function take(r) {
    if (r.kind === "hb") return;
    // Records replayed from the rings on connect are history: the fish and its lamps only
    // follow what arrives once the page has caught up.
    if (r.seq && r.seq > S.helloSeq) S.caughtUp = true;     // (no clocks compared: by sequence)
    if (r.kind === "hello") {
      if (S.boot && S.boot !== r.boot) {         // the fish restarted: history starts again
        push(S.log, { kind: "log", t: Date.now() / 1000, mark: true,
                      text: "──── the fish restarted (pid " + r.pid + ") ────" }, CAP.log);
        S.turns = []; S.keys = []; S.tx = []; S.lastSeq = 0; S.sel = null;
        S.llm = []; S.stt = []; S.tts = []; S.modelOnly = null; S.openCalls.clear();
        mark("all");
      }
      S.boot = r.boot;
      S.helloSeq = r.seq || 0;                     // what existed when this stream opened
      S.caughtUp = false;
      return;
    }
    if (r.seq) {
      if (r.seq <= S.lastSeq) return;            // already have it (a replay after a reconnect)
      if (S.caughtUp && S.lastSeq && r.seq > S.lastSeq + 1 && r.seq - S.lastSeq < 100000) S.missed += r.seq - S.lastSeq - 1;
      S.lastSeq = Math.max(S.lastSeq, r.seq);
    }
    const live = S.caughtUp;
    if (live) sampleClock(r);
    switch (r.kind) {
      case "log": push(S.log, r, CAP.log); mark("log"); break;
      case "key": push(S.keys, r, CAP.key); mark("keys"); break;
      case "press": S.presses[r.dev + "|" + r.key] = r; mark("keys"); break;
      case "turn": push(S.turns, r, CAP.turn); mark("turns", "pipe"); soon(); if (live) fish.turnEnded(r); break;
      case "perf": S.perf = r; mark("motors"); break;
      case "tx": push(S.tx, r, CAP.tx); if (live) fish.line(r); mark("tx"); break;
      case "level": S.levels.push(r.rms); if (S.levels.length > 200) S.levels.shift();
                    if (live) fish.listening(); mark("pipe"); wakeLevel(); break;
      case "action": case "http": push(S.acts, r, CAP.act); mark("clients"); break;
      case "llm": case "stt": case "tts": push(S[r.kind], r, 50); mark("model"); break;
      case "visitor":                              // a new visitor: the earlier one's records go
        S.llm = []; S.stt = []; S.tts = []; S.modelOnly = null; S.openCalls.clear();
        mark("model"); break;
      case "page": {
        const ev = r.ev || {};
        switch (ev.type) {
          case "listen": hostListening = ev.ready !== false; if (live) fish.listen(!!ev.ready); break;
          case "stt":
            if (ev.role === "user") { $("heardLine").textContent = ev.text ? "heard: " + ev.text : ""; if (live) fish.heard(ev.text || ""); }
            else $("saidLine").textContent = ev.text ? "said: " + ev.text : "";
            break;
          case "speak": if (live) fish.speak(ev, ageOf(r), r.t); break;
          case "visit":                           // the visit's view, with the show's and the fortune's
            S.visit = ev; fish.visit(ev, live); visitRow.view(ev);
            fortuneRow.view(ev.fortune, ev); fish.fortune(ev.fortune, live);
            mark("bar", "panels"); break;
          case "draft": if (live) voiceDraft(ev.text || ""); break;
          case "reading": if (live) fish.thinking("model"); break;
          case "ptt": if (live) ptt.event(ev); break;
          case "play": if (live) phoneSpeaker.play(ev); break;
          case "play_stop": phoneSpeaker.stop(); break;
        }
        mark("pipe");
        break;
      }
    }
  }

  // ---- the hat: what the fish is doing, at a glance -------------------------------------------
  // The drawing is the old face's (svg#hat): the mouth follows the reply's loudness track through
  // a critically damped spring and lifts the brows; a NECK stroke in one direction holds or
  // returns the tip, a chain is a passing window; TAIL wags the brim; the burble (a sound with an
  // empty track) perks the tip. Around it: a pose and a colour for what the fish is doing, the
  // visit's stage, a shake when a turn dies, and lamps for every line the link really sent.
  let hostListening = true;
  const HOUSE = { Gryffindor: "gryffindor", Hufflepuff: "hufflepuff", Ravenclaw: "ravenclaw", Slytherin: "slytherin" };
  const DIED_IN = ["the trigger", "the microphone", "speech-to-text", "the model", "the voice", "the speaker", "the motors"];
  const fish = guard("hat", () => {
    const box = $("hatBox"), mouthEl = $("mouth"), lipLower = $("lip-lower"), brows = $("brows"),
          tipBend = $("tip-bend"), brimParts = [$("brim"), $("brim-front"), $("brim-fold")];
    const mouth = { value: 0, vel: 0 };
    const tip = { value: 0, vel: 0, k: 40, d: 7 }, brim = { value: 0, vel: 0, k: 90, d: 19 };
    const shown = { m: -1, tip: -1, brim: -1 };
    let track = null, clock0 = 0, trackEnd = 0, windows = [], neck = [], perkUntil = 0;
    let running = false, last = 0, lastDraw = 0;
    // His sprites: one whole hat per mouth opening (0 closed … 3 widest). Once all four are
    // here the canvas replaces the drawing; the tip (NECK) and the brim (TAIL), which have no
    // sprites of their own, tilt the whole picture instead.
    const sprite = $("hatSprite"), sctx = sprite.getContext("2d"), frames = [];
    let sprites = false, shownFrame = -1, shownTilt = "", stillMouth = null;
    for (let m = 0; m < 4; m++) {
      const im = new Image();
      im.onload = () => {
        frames[m] = im;
        if (!sprites && [0, 1, 2, 3].every((i) => frames[i])) {
          sprites = true;
          $("hat").setAttribute("hidden", "");
          sprite.hidden = false;
          shownFrame = -1;
          draw(stillMouth !== null ? stillMouth : mouth.value, performance.now());
        }
      };
      im.src = "/img/neckRest_mouth" + m + "_tailRest.png";
    }
    // What the fish is doing: waiting | listening | thinking | speaking (offline is an overlay).
    const ST = { state: "waiting", since: performance.now(), sub: "", speakUntil: 0 };
    let tick = null, errTimer = null, houseTimer = null, stillMode = false;

    function stepFree(sp, target, dt) {
      sp.vel += (-sp.k * (sp.value - target) - sp.d * sp.vel) * dt;
      sp.value += sp.vel * dt;
    }
    function draw(m, now) {
      if (sprites) {
        const f = Math.min(3, Math.round(m * 3));
        if (f !== shownFrame) {
          shownFrame = f;
          sctx.clearRect(0, 0, 600, 500);
          sctx.drawImage(frames[f], 0, 0, 600, 500);
        }
        const brimA = 3.5 * brim.value * Math.sin(now * 0.018), tipA = -6 * tip.value;
        const tilt = `rotate(${(brimA + tipA).toFixed(2)}deg) translateY(${(-6 * tip.value).toFixed(1)}px)`;
        if (tilt !== shownTilt) { shownTilt = tilt; sprite.style.transform = tilt; }
        return;
      }
      const mr = Math.round(m * 200) / 200;
      if (mr !== shown.m) {
        shown.m = mr;
        mouthEl.setAttribute("d", `M214,338 Q302,${(328 - 4 * mr).toFixed(1)} 396,336 Q302,${(346 + 64 * mr).toFixed(1)} 214,338 Z`);
        lipLower.setAttribute("d", `M224,346 Q302,${(354 + 66 * mr).toFixed(1)} 386,344`);
        brows.setAttribute("transform", `translate(0 ${(-7 * mr).toFixed(2)})`);
      }
      const tr = Math.round(tip.value * 400) / 400;
      if (tr !== shown.tip) { shown.tip = tr; tipBend.setAttribute("transform", `rotate(${(24 * tr).toFixed(2)} 316 150)`); }
      const a = Math.round(3.5 * brim.value * Math.sin(now * 0.018) * 50) / 50;
      if (a !== shown.brim) { shown.brim = a; for (const part of brimParts) part.setAttribute("transform", `rotate(${a} 300 415)`); }
    }
    function level(now) {
      if (!track) return 0;
      const t = now - clock0;
      if (t > trackEnd + 150) { track = null; return 0; }
      let v = 0;
      for (const [at, lv] of track) { if (at <= t) v = lv; else break; }
      return Math.min(1, v * 2.5);
    }
    const active = (ch, now) => windows.some((w) => w.ch === ch && now >= w.start && now < w.end);
    function neckOut(now) { let out = false; for (const e of neck) { if (e.start <= now) out = e.out; else break; } return out || active("NECK", now); }
    const moving = (now) => now < perkUntil || Math.abs(tip.value) > 0.005 || Math.abs(tip.vel) > 0.01 ||
                            Math.abs(brim.value) > 0.005 || Math.abs(brim.vel) > 0.01;
    function frame(now) {
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      const f = -104 * (mouth.value - level(now)) - 20 * mouth.vel;
      mouth.vel += f * dt; mouth.value = Math.max(0, Math.min(1, mouth.value + mouth.vel * dt));
      stepFree(tip, neckOut(now) ? 1 : now < perkUntil ? 0.6 : 0, dt);
      stepFree(brim, active("TAIL", now) ? 1 : 0, dt);
      windows = windows.filter((w) => now < w.end + 50);
      if (now - lastDraw >= 30) { lastDraw = now; draw(mouth.value, now); }   // ~30 fps is plenty, even at 120 Hz
      const busy = track || mouth.value > 0.01 || windows.length || neck.some((e) => e.start > now) || moving(now);
      if (busy) requestAnimationFrame(frame); else { draw(0, now); running = false; }   // asleep when nothing moves
    }
    function wake() { if (!running) { running = true; last = performance.now(); requestAnimationFrame(frame); } }

    // ---- what it is doing -----------------------------------------------------------------------
    function buzz(pattern) {
      try { if ($("buzzTick").checked && navigator.vibrate && (!navigator.userActivation || navigator.userActivation.hasBeenActive)) navigator.vibrate(pattern); } catch (_) {}
    }
    function budgetS() {
      const rows = Array.isArray((S.state || {}).config) ? S.state.config : [];
      const on = rows.find((r) => r.section === "filler" && r.field === "enabled");
      const t = rows.find((r) => r.section === "filler" && r.field === "turn_timeout_s");
      return on && on.value === false ? 0 : (t ? Number(t.value) : 12);
    }
    function set(state, sub) {
      const was = ST.state;
      if (state === was && (sub === undefined || sub === ST.sub)) return;
      if (state !== was) ST.since = performance.now();
      ST.state = state;
      if (sub !== undefined) ST.sub = sub;
      S.live = state === "listening" ? "recording" : state === "waiting" ? "waiting" : state;
      for (const c of ["waiting", "listening", "thinking", "speaking"]) box.classList.toggle("st-" + c, c === state);
      if (state !== was) {
        const bar = $("budgetBar"), b = budgetS();
        bar.classList.remove("run");
        if (state === "thinking" && b) { void bar.offsetWidth; bar.style.animationDuration = b + "s"; bar.classList.add("run"); }
        if (state === "listening") buzz(25);
        if (state === "speaking") buzz([25, 60, 25]);
        if (state === "speaking") { box.classList.remove("kick"); void box.offsetWidth; box.classList.add("kick"); }
      }
      clearInterval(tick);
      if (state === "thinking") tick = setInterval(() => paint(), 200);
      paint();
      mark("pipe");
    }
    function listening() { set("listening", ""); }
    function listen(ready) {
      if (ready) { if (ST.state !== "speaking") set("waiting", ""); }
      else if (ST.state !== "speaking") set("thinking", "hearing");
    }
    function heard(text) {
      if (text.startsWith("…")) set("waiting", "");      // nothing usable was heard
      else set("thinking", "model");
    }
    function thinking(sub) { set("thinking", sub); }
    function speak(ev, age, t) {
      const now = performance.now(), dur = ev.duration_ms || 0;
      const quiet = Array.isArray(ev.mouth) && ev.mouth.length === 0;     // the burble: a sound, no speech
      if (quiet) perkUntil = now - age + dur;
      else if (Array.isArray(ev.mouth) && ev.mouth.length && age <= ev.mouth[ev.mouth.length - 1][0]) {
        track = ev.mouth; clock0 = now - age; trackEnd = track[track.length - 1][0];
      }
      for (const [tMs, ch, body] of ev.gestures || []) {
        const nums = String(body).trim().split(/\s+/).map(Number);
        let total = 0, pos = false, neg = false;
        for (let i = 0; i + 1 < nums.length; i += 2) { total += nums[i + 1] || 0; if (nums[i] > 0) pos = true; else if (nums[i] < 0) neg = true; }
        const start = now - age + tMs;
        if (String(ch).toUpperCase() === "NECK" && pos !== neg) neck.push({ start, out: pos });
        else windows.push({ ch: String(ch).toUpperCase(), start, end: start + total });
      }
      neck.sort((a, b) => a.start - b.start);
      wake();
      if (!ev.filler && !quiet) {                       // the reply itself (fillers: still thinking)
        set("speaking", "");
        ST.speakUntil = now - age + dur;
        setTimeout(() => { if (ST.state === "speaking" && performance.now() >= ST.speakUntil) set(hostListening ? "waiting" : "thinking", ""); }, Math.max(0, dur - age) + 300);
      }
      if (!quiet && Array.isArray(ev.mouth) && ev.mouth.length) checkMotor(t, dur);
    }
    // After a phrase with a mouth track: did the link send MOUTH lines in its window?
    function checkMotor(t, dur) {
      if (!t) return;
      setTimeout(() => {
        const from = t - 0.2, to = t + dur / 1000 + 0.5;
        const lines = S.tx.filter((r) => r.t >= from && r.t <= to && /^MOUTH\b/i.test(String(r.line)));
        const note = $("motorNote");
        if (!lines.length) { note.textContent = "motor: no lines"; note.className = "note bad-text"; }
        else if (lines.every((r) => r.flag)) { note.textContent = "motor: " + lines[0].flag; note.className = "note warn-text"; }
        else { note.textContent = "motor: " + lines.length + " lines"; note.className = "note"; }
      }, dur + 800);
    }
    function reconcile(mode) {                          // the slow state agrees, or puts it right
      if (!mode) return;
      const held = performance.now() - ST.since;
      if (mode.recording && ST.state !== "listening") set("listening", "");
      else if (mode.listening && !mode.recording && !mode.speaking && ST.state === "thinking" && held > 2000) set("waiting", "");
      else if (mode.listening && !mode.recording && !mode.speaking && ST.state === "speaking" && performance.now() > ST.speakUntil + 1000) set("waiting", "");
      else if (mode.listening && !mode.recording && !mode.speaking && ST.state === "listening" && held > 2000) set("waiting", "");
    }
    // The visit: the stage shows on the band and in the face; a house that appears live is
    // revealed (the house's colour and name for 10 s).
    let lastVisit = null;
    function visit(v, live) {
      for (let n = 1; n <= 4; n++) box.classList.toggle("s" + n, v.stage === n);
      box.classList.toggle("sdone", v.stage > v.of);
      const prev = lastVisit; lastVisit = v;
      if (live && v.house && prev && prev.n === v.n && !prev.house) reveal(v.house);
    }
    function reveal(house) {
      const key = HOUSE[house] || "";
      for (const k of Object.values(HOUSE)) box.classList.toggle("h-" + k, k === key);
      box.classList.remove("h-fortune", "reading");
      box.classList.remove("reveal"); void box.offsetWidth; box.classList.add("reveal");
      $("hatHouse").textContent = "¡" + house + "!";
      $("hatHouse").hidden = false;
      buzz([40, 40, 40, 40, 40, 40, 120]);
      clearTimeout(houseTimer);
      houseTimer = setTimeout(() => { $("hatHouse").hidden = true; box.classList.remove("reveal"); for (const k of Object.values(HOUSE)) box.classList.remove("h-" + k); }, 10000);
    }
    // The fortune: a live edge into its reading turns the room violet, swells the candle's
    // halo and shows the sign for 12 s (the ending is the act's reveal).
    let lastFortune = null;
    function fortune(f, live) {
      if (!f) return;
      const prev = lastFortune; lastFortune = f;
      if (live && f.open && f.stage === "reading" && prev && prev.n === f.n && prev.open && prev.stage !== "reading") foresee((f.data || {}).signo || "");
    }
    function foresee(sign) {
      for (const k of Object.values(HOUSE)) box.classList.remove("h-" + k);
      box.classList.add("h-fortune", "reading");
      box.classList.remove("reveal"); void box.offsetWidth; box.classList.add("reveal");
      $("hatHouse").textContent = sign ? "✦ " + sign + " ✦" : "✦";
      $("hatHouse").hidden = false;
      buzz([40, 40, 40, 40, 120]);
      clearTimeout(houseTimer);
      houseTimer = setTimeout(() => { $("hatHouse").hidden = true; box.classList.remove("reveal", "h-fortune", "reading"); }, 12000);
    }
    // A turn that died: a shake and where it died; a turn that heard nothing: amber, no shake.
    function turnEnded(t) {
      const o = t.outcome || "";
      const hard = /^timeout:/.test(o) || ["offline", "misconfigured", "error", "mic error", "read: no signal"].includes(o) || /playback failed/.test(o);
      const soft = ["not understood", "silence", "too short", "empty reply", "dropped: speaking"].includes(o);
      if (!hard && !soft) return;
      let where = o;
      if (hard) {
        const dead = stagesOf(t).findIndex((x) => x.cls === "dead");
        where = dead >= 0 ? "died in " + DIED_IN[dead] + " (" + o + ")" : o;
        box.classList.remove("err"); void box.offsetWidth; box.classList.add("err");
        buzz(300);
      }
      const e = $("hatErr");
      e.textContent = hard ? where : "not understood: " + o;
      e.className = hard ? "bad-text" : "warn-text";
      e.hidden = false;
      clearTimeout(errTimer);
      errTimer = setTimeout(() => { e.hidden = true; box.classList.remove("err"); }, 8000);
    }
    function paint() {
      const st = S.state || {};
      const quiet = performance.now() - lastMsgAt > 15000;
      const off = STILL === "offline" || (!STILL && (!S.connected || (quiet && !document.hidden && lastMsgAt > 0)));
      box.classList.toggle("st-offline", off);
      const noNet = (dev().internet || {}).present === false;
      box.classList.toggle("no-net", noNet);
      const w = $("fishState");
      let word;
      if (off) word = "NO STREAM";
      else if (ST.state === "thinking") {
        const s = (performance.now() - ST.since) / 1000, b = budgetS();
        word = "THINKING " + s.toFixed(1) + " s" + (ST.sub ? " · " + ST.sub : "") + (b && s > b ? " · over budget" : "");
      } else word = { waiting: (st.mode || {}).listening === false ? "BUSY" : "WAITING for a press", listening: "LISTENING", speaking: "SPEAKING" }[ST.state];
      if (noNet) word += " · NO INTERNET";
      w.textContent = word;
      w.className = off ? "offline" : ST.state;
    }
    // The lamps: lit for as long as the line it was sent drives the motor.
    const lamps = { MOUTH: $("lampMouth"), NECK: $("lampNeck"), TAIL: $("lampTail") }, timers = {};
    function line(r) {
      const parts = String(r.line).trim().split(/\s+/), ch = (parts[0] || "").toUpperCase();
      $("lastLine").textContent = clockMs(r.t) + "  " + r.line + (r.flag ? "  (" + r.flag + ")" : "");
      if (ch === "STOP" || ch === "S") { for (const k in lamps) lamps[k].classList.remove("lit", "hollow"); return; }
      const lamp = lamps[ch];
      if (!lamp) return;
      let ms = 0;
      for (let i = 2; i < parts.length; i += 2) ms += Number(parts[i]) || 0;
      lamp.classList.add("lit");
      lamp.classList.toggle("hollow", !!r.flag);            // muted or dropped: told, not sent
      clearTimeout(timers[ch]);
      timers[ch] = setTimeout(() => lamp.classList.remove("lit", "hollow"), Math.max(160, ms));
    }
    function state() {                                     // called on every render of the bar
      const st = S.state || {}, link = st.link || {};
      paint();
      $("lampMouth").parentElement.classList.toggle("muted", !!link.muted);
      if (link.muted) $("lastLine").textContent = "MOTORS MUTED: lines are dropped";
      else if (link.health && link.health !== "ok" && !$("lastLine").textContent.includes("link")) {
        $("lastLine").textContent = "link " + link.health + (link.mock ? " (mock)" : "") + " · " + $("lastLine").textContent;
      }
    }
    // ?hat=<waiting|listening|thinking|speaking|offline>&mouth=0..1&house=<House>&stage=1..5: a
    // still, for screenshots; the live state machine then stays out of the way.
    const STILL = PARAMS.get("hat");
    if (STILL) {
      stillMode = true;
      set(STILL === "offline" ? "waiting" : STILL, STILL === "thinking" ? "model" : "");
      if (STILL === "offline") box.classList.add("st-offline");
      const st = Number(PARAMS.get("stage")) || 0;
      if (st) visit({ n: 1, stage: st, of: 4, house: null }, false);
      if (PARAMS.get("house")) reveal(PARAMS.get("house"));
      stillMouth = Math.max(0, Math.min(1, Number(PARAMS.get("mouth")) || 0));
      draw(stillMouth, performance.now());
    }
    const api = { speak, line, state, listening, listen, heard, thinking, reconcile, visit, turnEnded, fortune, foresee,
                  perk(ms) { perkUntil = performance.now() + ms; wake(); } };
    if (stillMode) for (const k of ["listening", "listen", "heard", "thinking", "reconcile"]) api[k] = () => {};
    return api;
  }, { speak() {}, line() {}, state() {}, listening() {}, listen() {}, heard() {}, thinking() {},
       reconcile() {}, visit() {}, turnEnded() {}, fortune() {}, foresee() {}, perk() {} });

  // ---- the slow state --------------------------------------------------------------------------
  let stateTimer = null;
  async function refresh() {
    try {
      const r = await api("/debug/state");
      if (r.status === 403) { $("tokenGate").hidden = false; return; }
      if (!r.ok) throw new Error(r.status);
      S.state = await r.json();
      S.stateAt = performance.now();
      if (S.off === undefined && S.state.now) S.off = S.state.now - Date.now() / 1000;   // until live records refine it
      $("tokenGate").hidden = true;
      const armed = (S.state.mode || {}).armed_s || 0;
      setArmed(armed);
      const page = S.state.page && !S.state.page.error ? S.state.page : {};
      const tab = S.state.show_tab && !S.state.show_tab.error ? S.state.show_tab : {};
      visitRow.status(page);
      fortuneRow.status(page, tab);
      phoneMic.status(page, dev());
      phoneSpeaker.status(dev());
      if (page.visit && !S.visit) { S.visit = page.visit; fish.visit(page.visit, false); visitRow.view(page.visit); }
      if (page.visit && page.visit.fortune && !S.fortune) { fortuneRow.view(page.visit.fortune, page.visit); fish.fortune(page.visit.fortune, false); }
      fish.reconcile(S.state.mode);
    } catch (_) { S.state = S.state || null; S.stateAt = 0; }
    mark("bar", "hints", "panels");
  }
  function soon() { clearTimeout(stateTimer); stateTimer = setTimeout(refresh, 400); }
  let hiddenTicks = 0;
  setInterval(() => { if (!document.hidden || ++hiddenTicks % 4 === 0) refresh(); }, 5000);   // 20 s when hidden
  async function checkToken() {
    try { if ((await api("/debug/state")).status === 403) $("tokenGate").hidden = false; } catch (_) {}
  }
  $("tokenBtn").addEventListener("click", () => {
    TOKEN = $("tokenInput").value.trim();
    try { sessionStorage.setItem("fishToken", TOKEN); } catch (_) {}
    refresh(); connect();
  });

  // ---- the Status tab: is the hat ready; Settings and the Visit tab's place and fortune extras ---
  // Rows from /debug/state's device table (ADR 0021), then show_tab and the service. Green,
  // amber or red, each with what to do in a few words. The controls post to routed actions only.
  const PLACE_EN = { casa: "home", fiesta: "party", universidad: "university", otro: "other" };
  function goRow(name, cls, text, fix) {
    const r = el("div", "go " + cls);
    r.appendChild(el("b", "", name));
    r.appendChild(el("span", "", text));
    if (fix) r.appendChild(el("span", "fix", fix));
    return r;
  }
  function setSummary(cls, text) {
    const s = $("showSummary");
    s.className = "summary " + cls;
    s.textContent = text;
  }
  function renderStatus() {
    const rows = $("goRows");
    // Never a "ready" without data: until the hat answers, and when its answer gets old, say so.
    const age = S.stateAt ? (performance.now() - S.stateAt) / 1000 : Infinity;
    const st = S.state;
    if (!st || (!Array.isArray(st.devices) && (!st.show_tab || st.show_tab.error))) {
      setSummary("wait", S.stateAt ? "No answer from the hat" : "Waiting for the hat…");
      rows.replaceChildren();
      return;
    }
    if (age > 15) {
      setSummary("bad", "No answer from the hat for " + Math.round(age) + " s: check the Wi-Fi");
      return;
    }
    const t = st.show_tab && !st.show_tab.error ? st.show_tab : {};
    const out = [], local = [];                  // local: the rows only the page decides
    // The device rows first, in the table's order (ADR 0021): the USB rows lead on the board;
    // a part that does not apply here is hidden.
    for (const d of Array.isArray(st.devices) ? st.devices : [])
      if (d.level && d.level !== "off")
        out.push(goRow(d.label, d.level, d.state + (d.reason ? " · " + d.reason : ""), d.fix || ""));
    const row = (name, cls, text, fix) => { const r = goRow(name, cls, text, fix); out.push(r); if (cls !== "ok") local.push([cls, name + " · " + text]); };
    const v = t.voice || {};
    row("Voice", v.state === "tainted" ? "bad" : "ok",
      v.state === "tainted" ? "licence warning" : v.state === "clean" ? "clean" : "not probed",
      v.state === "tainted" ? "restart the hat" : "");
    const sh = t.show || {}, echo = !!((st.backends || {}).echo);
    row("Mode", "ok", echo ? "echo: repeats what it hears"
      : sh.setting === "off" ? "model" : sh.setting === "script" ? "script" : "auto: " + (sh.now === "script" ? "script" : "model") + " (" + sh.why + ")", "");
    if (sh.lines) row("Lines", sh.ready < sh.lines ? "warn" : "ok", sh.ready + " of " + sh.lines + " ready",
      sh.ready < sh.lines ? "rendering after a restart" : "");
    // The fortune act: its toggles and the place, and whether its clips are rendered.
    const ft = t.fortune;
    if (ft) {
      const short = typeof ft.ready === "number" && ft.lines ? ft.ready < ft.lines : ft.ready === false;
      row("Fortune", short ? "warn" : "ok",
        (ft.deck === "off" ? "no deck" : ft.deck || "no deck") + " · cup " + (ft.cup ? "on" : "off") + " · " + (PLACE_EN[ft.place] || ft.place || "other")
          + (typeof ft.ready === "number" && ft.lines ? " · " + ft.ready + " of " + ft.lines + " lines" : ""),
        short ? "rendering after a restart" : "");
    }
    row("Act", "ok", actNow(), "");
    const svc = st.service || {};
    row("Start at boot", svc.enabled === false ? "bad" : "ok", svc.enabled === false ? "off" : "on",
      svc.enabled === false ? "systemctl --user enable fish-brain" : "");
    rows.replaceChildren(...out);
    // The summary: the server's verdict on the devices, then the page's own rows.
    const sum = st.summary || {}, d = dev();
    const say = (id) => { const x = d[id] || {}; return (x.label || id) + " · " + (x.state || x.reason || ""); };
    const bad = (sum.bad || []).map(say).concat(local.filter(([c]) => c === "bad").map(([, s]) => s));
    const warn = (sum.warn || []).map(say).concat(local.filter(([c]) => c === "warn").map(([, s]) => s));
    if (bad.length) setSummary("bad", "Check: " + bad.join("; "));
    else if (warn.length) setSummary("warn", "Ready, with a warning: " + warn.join("; "));
    else setSummary("ok", "Ready for visitors");
  }
  // What is on now: a fortune, a visit, or nothing (the band says the same).
  function actNow() {
    const v = S.visit, f = S.fortune;
    if (f && f.open) return (f.stage === "reading" ? "fortune: reading the future" : "fortune: question " + f.q + " of " + f.of) + (f.first ? " · " + f.first : "");
    if (v && v.stage) return (v.stage > v.of ? "verdict: " + (v.house || "—") : "visit: stage " + v.stage + " of " + v.of) + (v.first ? " · " + v.first : "");
    return "none";
  }
  // The pressed states of the Settings tab (mode and network from show_tab, the hardware marks
  // from the device table) and of the Visit tab's place and fortune toggles (from the switches by
  // name, show_tab's fortune as the fallback). `key` "start" is the switch's value at start-up.
  function switchValue(name, key) {
    const w = (Array.isArray((S.state || {}).switches) ? S.state.switches : []).find((x) => x.name === name);
    return w ? w[key || "value"] : undefined;
  }
  function pressed(selector, test) {
    for (const b of document.querySelectorAll(selector)) b.setAttribute("aria-pressed", test(b) ? "true" : "false");
  }
  function renderSetup() {
    const st = S.state, t = st && st.show_tab;
    if (!st || !t || t.error) return;
    const a = t.audio || {}, n = t.net || {}, sh = t.show || {}, ft = t.fortune || {}, d = dev();
    const echo = !!((st.backends || {}).echo);
    const mode = echo ? "echo" : sh.setting === "off" ? "model" : sh.setting;
    if (typeof a.volume === "number" && !volDragging) { $("volSlider").value = Math.round(a.volume * 100); $("volNow").textContent = Math.round(a.volume * 100) + " %"; }
    pressed("[data-mode]", (b) => b.dataset.mode === mode);
    pressed("[data-hw]", (b) => !!(d[b.dataset.hw] || {}).marked);
    // What the table finds failing that is not marked: the marks are his, the detection is not.
    const seen = Array.from(document.querySelectorAll("[data-hw]"), (b) => d[b.dataset.hw])
      .filter((x) => x && !x.marked && (x.level === "warn" || x.level === "bad") && (x.dead || x.present === false));
    const note = $("hwNote");
    note.textContent = seen.length ? "detected, not marked: " + seen.map((x) => x.label + " (" + (x.reason || x.state) + ")").join("; ") : "";
    note.hidden = !seen.length;
    pressed("[data-net]", (b) => b.dataset.net === (n.pin || "auto"));
    const place = switchValue("place") || ft.place || "otro";
    pressed("[data-place]", (b) => b.dataset.place === place);
    $("placeOther").hidden = place !== "otro";
    const text = switchValue("place_text"), field = $("placeText");
    if (text !== undefined && document.activeElement !== field) field.value = text || "";
    const deck = switchValue("fortune_deck") || ft.deck || "tarot";
    pressed('[data-fortune="deck"]', (b) => b.dataset.val === deck);
    const cup = switchValue("fortune_cup");
    $("cupBtn").setAttribute("aria-pressed", (cup !== undefined ? cup : ft.cup) ? "true" : "false");
  }
  setInterval(() => mark("panels"), 5000);      // the stale check runs even when nothing arrives
  let volDragging = false, volTimer = 0;
  $("volSlider").addEventListener("input", () => {
    volDragging = true;
    $("volNow").textContent = $("volSlider").value + " %";
    clearTimeout(volTimer);
    volTimer = setTimeout(async () => {
      const out = await post("/debug/volume", { value: Number($("volSlider").value) });
      $("setupMsg").textContent = out.ok ? "" : "the volume could not be changed";
      volDragging = false; soon();
    }, 250);
  });
  // Mode: one control over two switches (the scripted visit and echo).
  const MODES = { auto: ["auto", "llm"], model: ["off", "llm"], script: ["script", "llm"], echo: ["off", "echo"] };
  for (const b of document.querySelectorAll("[data-mode]")) {
    b.addEventListener("click", async () => {
      const [show, mode] = MODES[b.dataset.mode];
      const a1 = await post("/debug/set", { name: "show", value: show });
      const a2 = await post("/debug/set", { name: "mode", value: mode });
      const bad = [a1, a2].find((o) => !o.ok);
      $("setupMsg").textContent = bad ? "refused: " + (bad.error || bad.status) : "";
      soon();
    });
  }
  // One switch set from a button on the Visit tab (place, deck, cup): the tap shows at once, the
  // state confirms it; a refusal is written under them in #actMsg.
  async function setFromTap(name, value) {
    const out = await post("/debug/set", { name, value });
    $("actMsg").textContent = out.ok ? "" : "refused: " + (out.error === "busy" ? "the hat is mid-turn, try again when it waits" : out.error || out.status);
    soon();
  }
  // The place: a setting for the evening (the intro and the closing of the fortune follow it);
  // "Other" opens a text the web model alone is told.
  for (const b of document.querySelectorAll("[data-place]")) {
    b.addEventListener("click", () => {
      pressed("[data-place]", (o) => o === b);
      $("placeOther").hidden = b.dataset.place !== "otro";
      setFromTap("place", b.dataset.place);
    });
  }
  $("placeText").addEventListener("change", () => setFromTap("place_text", $("placeText").value.trim().slice(0, 60)));
  $("placeText").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); $("placeText").blur(); } });
  // The fortune's extras: the deck the visitor draws from (or none) and the cup.
  for (const b of document.querySelectorAll('[data-fortune="deck"]')) {
    b.addEventListener("click", () => {
      pressed('[data-fortune="deck"]', (o) => o === b);
      setFromTap("fortune_deck", b.dataset.val);
    });
  }
  $("cupBtn").addEventListener("click", () => {
    const on = $("cupBtn").getAttribute("aria-pressed") !== "true";
    $("cupBtn").setAttribute("aria-pressed", on ? "true" : "false");
    setFromTap("fortune_cup", on);
  });
  // Hardware he marks failed. Marking the speaker or the microphone failed also arms this phone
  // for it in the same tap (a browser lets sound and the microphone start only from a tap).
  for (const b of document.querySelectorAll("[data-hw]")) {
    b.addEventListener("click", async () => {
      const part = b.dataset.hw, failed = b.getAttribute("aria-pressed") !== "true";
      if (failed && part === "speaker") phoneSpeaker.enable();
      if (failed && part === "mic") phoneMic.arm();
      b.setAttribute("aria-pressed", failed ? "true" : "false");
      const out = await post("/debug/hw", { part, failed });
      $("setupMsg").textContent = out.ok ? "" : "refused: " + (out.error || out.status);
      soon();
    });
  }
  for (const b of document.querySelectorAll("[data-net]")) {
    b.addEventListener("click", async () => {
      const out = await post("/debug/net", { pin: b.dataset.net });
      $("setupMsg").textContent = out.ok ? (b.dataset.net === "ap" ? "the hat raises its own Wi-Fi" : "the hat looks for its known networks") : "refused";
      soon();
    });
  }

  // ---- the phone as the last speaker (ADR 0016) ----------------------------------------------------
  // Off until a tap unlocks the sound. Then the page tells the board every 10 s that it can play
  // (/speakerstate); the board sends a `play` event only when its own speakers are gone, the page
  // fetches the phrase, plays it and says when it started (/speaker/started) so the motors follow.
  const phoneSpeaker = guard("phone speaker", () => {
    const btn = $("spkBtn"), state = $("spkState");
    let actx = null, on = false, beat = 0, src = null;
    function say(t) { state.textContent = t; }
    function announce(ready) {
      api("/speakerstate", { page: PAGE, ready }).catch(() => {});
    }
    async function enable() {
      actx = actx || new (window.AudioContext || window.webkitAudioContext)();
      await actx.resume();
      const buf = actx.createBuffer(1, 1, 22050), s = actx.createBufferSource();   // unlock
      s.buffer = buf; s.connect(actx.destination); s.start(0);
      on = true; announce(true); beat = setInterval(() => { if (!document.hidden) announce(true); }, 10000);
      btn.setAttribute("aria-pressed", "true"); say("ready: plays here when the other speakers fail");
    }
    function disable() {
      on = false; clearInterval(beat); announce(false);
      btn.setAttribute("aria-pressed", "false"); say("off");
    }
    btn.addEventListener("click", () => { on ? disable() : enable().catch(() => say("the browser refused")); });
    document.addEventListener("visibilitychange", () => { if (on) announce(!document.hidden); });
    return {
      async play(ev) {
        if (!on || !actx) return;
        try {
          const r = await fetch(ev.audio, { headers: TOKEN ? { "X-Fish-Token": TOKEN } : {} });
          const audio = await actx.decodeAudioData(await r.arrayBuffer());
          if (src) { try { src.stop(); } catch (_) {} }
          src = actx.createBufferSource(); src.buffer = audio; src.connect(actx.destination);
          src.start(0);
          api("/speaker/started", { id: ev.id, in_ms: 0 }).catch(() => {});   // it starts now
          say("playing here");
        } catch (e) { say("could not play"); }
      },
      stop() { if (src) { try { src.stop(); } catch (_) {} src = null; } },
      enable() { if (!on) enable().catch(() => say("the browser refused")); },
      // The table's phone_speaker row: how many pages are armed and whether a phone plays now.
      status(d) {
        const x = (d && d.phone_speaker) || {};
        if (x.level === undefined) return;
        const n = x.pages || 0;
        if (on) say(x.in_use ? "on: the hat speaks through a phone now" : "ready: plays here when the other speakers fail");
        else if (x.level === "off") say("off");
        else if (n) say("off here · " + n + " phone" + (n > 1 ? "s" : "") + " armed");
        else say(x.level === "warn" ? "off · " + x.reason : "off");
      },
    };
  }, { play() {}, stop() {}, enable() {}, status() {} });

  // ---- render ----------------------------------------------------------------------------------
  function render() {
    const now = new Set(dirty);                  // what changed, taken before the set is emptied
    dirty.clear();
    const all = now.has("all");
    const d = (n) => all || now.has(n);
    const run = (fn) => { try { fn(); } catch (e) { console.error(fn.name, e); } };   // one panel never stops the others
    // On a phone only what is on screen is drawn; showTab() asks for everything again.
    const col = (c) => !PHONE.matches || document.body.dataset.col === c;
    const shown = (id) => !PHONE.matches || (col("colPanels") && !$("p-" + id).hidden);
    if (d("bar")) { run(renderBar); run(renderBand); }
    if (d("bar") || d("pipe") || d("panels")) run(fish.state);
    if (d("hints")) run(renderHints);
    if ((d("pipe") || d("turns")) && col("colTurns")) run(renderPipe);
    if (d("turns") && col("colTurns")) run(renderTurns);
    if (d("log") && col("colLog")) run(renderLog);
    if ((d("panels") || d("keys")) && shown("inputs")) run(renderInputs);
    if ((d("panels") || d("motors") || d("tx")) && shown("motors")) run(renderMotors);
    if (d("panels")) { run(renderStatus); run(renderSetup); run(renderVoice); run(renderCloud); run(renderBoard); run(renderConfig); run(renderChecks); run(renderSwitches); }
    if ((d("panels") || d("model")) && shown("model")) run(renderModel);
    if (d("panels") || d("clients")) run(renderClients);
  }

  function chip(word, cls, title, tab) {
    const c = el("span", "chip " + cls, word);
    if (title) c.title = title;
    if (tab) c.addEventListener("click", () => showTab(tab));
    return c;
  }
  const lastTurn = () => S.turns[S.turns.length - 1];

  function renderBar() {
    const st = S.state;
    const stream = $("hStream");
    stream.className = "chip " + (S.connected ? "ok" : "bad");
    stream.textContent = (S.connected ? "● stream live" : "■ stream down") + (S.missed ? " · missed " + S.missed : "");
    if (!st) { $("hHost").textContent = "no answer from the fish"; return; }
    $("hHost").textContent = st.host || "fish";
    $("hAddr").textContent = location.host;
    $("hUp").textContent = "up " + ago(st.now - st.started);
    $("hCommit").textContent = ((st.version || {}).commit || "") + " pid " + ((st.service || {}).pid || "");
    const flags = st.flags || {}, be = st.backends || {}, mode = st.mode || {};
    const badges = [];
    if (be.echo !== undefined ? be.echo : flags.echo) badges.push("ECHO");
    const flipped = (Array.isArray(st.switches) ? st.switches : []).filter((w) => w.changed).length;
    if (flipped) badges.push(flipped + " switch" + (flipped > 1 ? "es" : "") + " changed");
    if ((st.link || {}).muted) badges.push("MOTORS MUTED");
    if (flags.dry_run) badges.push("DRY-RUN");
    if (flags.text) badges.push("TEXT");
    if (flags.no_audio) badges.push("NO-AUDIO");
    if (mode.wait) badges.push("WAIT");
    const mic = dev().mic || {};
    if (mic.capture && mic.capture !== "host") badges.push("MIC=" + mic.capture);
    if (!st.token) badges.push("no token");
    if ((st.version || {}).changed_since_start) badges.push("code changed: restart");
    fill($("hBadges"), badges.map((b) => el("span", "badge", b)));

    const remote = st.remote || {}, sys = st.system || {}, d = dev();
    const t = lastTurn() || {}, times = t.times || {};
    const chips = [];
    // LINK, NET, TRIG, MIC and SPK from the device table (ADR 0021): the level is the row's.
    const devChip = (x, word, short, tab) => x
      ? chip((MARK[x.level] || "○ ") + word + (x.level === "ok" ? "" : " " + short), x.level === "off" ? "unknown" : x.level,
             [x.state, x.reason].filter(Boolean).join(" · "), tab)
      : chip("○ " + word, "unknown", "", tab);
    const m = d.motors, net = d.internet, rem = d.remote, mc = d.mic, sp = d.speaker;
    chips.push(devChip(m, "LINK", m && (m.marked ? "marked" : m.state), "live"));
    chips.push(devChip(net, "NET", net && (net.marked ? "marked" : "offline"), "model"));
    const other = Object.keys(remote.other_keys || {}).length;
    if (rem && rem.level !== "off")
      chips.push(other && rem.level === "ok" ? chip("▲ TRIG other key", "warn", remote.keys, "live")
        : devChip(rem, "TRIG", rem.marked ? "marked" : rem.present === false ? "none" : rem.state, "live"));
    else chips.push(chip("○ TRIG " + (be.ptt || "page"), "unknown", "", "live"));
    chips.push(devChip(mc, "MIC", mc && (mc.marked ? "marked" : mc.dead ? "zeros" : mc.state), "live"));
    for (const k of ["stt", "llm", "tts"]) {
      const v = times[k], name = k === "llm" ? (be.echo ? "echo" : be.llm_profile) : be[k];
      chips.push(chip((v > SLOW[k] ? "▲ " : "● ") + k.toUpperCase() + " " + (name || "") + (v !== undefined ? " " + secs(v) + "s" : ""),
                      v > SLOW[k] ? "warn" : v !== undefined ? "ok" : "unknown", "last turn", k === "tts" ? "voice" : "model"));
    }
    chips.push(devChip(sp, "SPK", sp && (sp.marked ? "marked" : sp.state), "voice"));
    const hot = Math.max(0, ...(sys.thermal || []).map((z) => z.c));
    chips.push(chip((hot > 70 ? "▲ " : "● ") + (hot ? hot.toFixed(0) + " C" : "BOARD"),
                    hot > 70 ? "warn" : "ok", "the machine", "system"));
    const cs = st.checks_summary;
    if (cs) chips.unshift(chip((cs.failed ? "■ " : cs.warned ? "▲ " : "● ") + "CHECKS " + cs.passed + "/" + cs.of,
                               cs.failed ? "bad" : cs.warned ? "warn" : "ok", cs.failed + " failed, " + cs.warned + " warnings", "checks"));
    fill($("hChips"), chips);
  }

  function renderHints() {
    const raw = (S.state || {}).hints;
    const hints = Array.isArray(raw) ? raw : [];   // a section that failed arrives as {error}
    const flagged = new Set(hints.filter((h) => h.level !== "info").map((h) => TAB_OF[h.panel] || h.panel));
    for (const b of $("tabs").children) b.classList.toggle("flag", flagged.has(b.dataset.tab));
    const order = { bad: 0, warn: 1, info: 2 };
    hints.sort((x, y) => order[x.level] - order[y.level]);
    $("hintBar").hidden = !hints.length;
    if (!hints.length) { $("hints").hidden = true; return; }
    const worst = hints[0];
    $("hintBar").className = worst.level;
    $("hintLine").textContent = (worst.level === "bad" ? "■ " : worst.level === "warn" ? "▲ " : "○ ") +
      (hints.length > 1 ? hints.length + " hints · " : "") + worst.text + (worst.fix ? "  → " + worst.fix : "");
    $("hintToggle").hidden = hints.length < 2;
    $("hintToggle").textContent = $("hints").hidden ? "all " + hints.length : "fold";
    fill($("hints"), hints.map((h) => {
      const li = el("li", h.level);
      li.appendChild(el("span", "", (h.level === "bad" ? "■ " : h.level === "warn" ? "▲ " : "○ ") + h.text));
      if (h.fix) li.appendChild(el("span", "fix", h.fix));
      const b = el("button", "", "show");
      b.addEventListener("click", () => showTab(TAB_OF[h.panel] || h.panel));
      li.appendChild(b);
      return li;
    }));
  }
  $("hintToggle").addEventListener("click", () => { $("hints").hidden = !$("hints").hidden; mark("hints"); });
  $("hintLine").addEventListener("click", () => { const h = ((S.state || {}).hints || [])[0]; if (h) showTab(TAB_OF[h.panel] || h.panel); });

  // The stage a turn ended in, by its outcome.
  const DIED = { "too short": 1, "silence": 1, "mic error": 1, "not understood": 2, "offline": 3,
                 "misconfigured": 3, "empty reply": 3, "dropped: speaking": 4, "error": -1,
                 "read: no signal": 3, "timeout: stt": 2, "timeout: llm": 3, "timeout: tts": 4 };
  function stagesOf(t) {
    const times = t.times || {}, rec = t.rec || {}, perf = t.perf || {};
    const names = ["Trigger", "Microphone", "Speech-to-text", "LLM", "Voice", "Speaker", "Motors"];
    const lines = [
      [t.trigger || "?", t.ended ? "ended: " + t.ended : ""],
      [times.rec !== undefined ? secs(times.rec) + " s" : "", rec.rms !== undefined ? "rms " + rec.rms + " · zeros " + Math.round((rec.zero_frac || 0) * 100) + " %" : ""],
      [times.stt !== undefined ? secs(times.stt) + " s" : "", t.user ? t.user.length + " chars" : ""],
      [times.llm !== undefined ? secs(times.llm) + " s" : (t.reply !== undefined ? "echo" : ""), t.reply ? t.reply.length + " chars" : ""],
      [times.tts !== undefined ? secs(times.tts) + " s" : "", ""],
      [times.play_start !== undefined ? "+" + secs(times.play_start) + " s" : "", perf.result ? perf.player + " · " + perf.result : ""],
      [perf.pulses !== undefined ? perf.pulses + " pulses" : "", perf.late_max_ms !== undefined ? "late max " + perf.late_max_ms + " ms · link " + (t.link || "?") : ""],
    ];
    let dead = DIED[t.outcome];
    if (perf.result && perf.result !== "ok") dead = 5;
    if (dead === -1) dead = lines.findIndex((l, i) => i > 0 && !l[0]);
    return names.map((name, i) => ({
      name, word: lines[i][0], line: lines[i][1],
      cls: dead !== undefined && dead >= 0 ? (i < dead ? "ok" : i === dead ? "dead" : "none") : (lines[i][0] ? "ok" : "none"),
      reason: i === dead ? (t.error ? t.error.type + ": " + t.error.text : t.outcome) : "",
    }));
  }
  function renderPipe() {
    const t = S.sel || lastTurn();
    const liveIdx = { waiting: 0, recording: 1, thinking: 2, speaking: 5 }[S.live];
    let stages = t ? stagesOf(t) : ["Trigger", "Microphone", "Speech-to-text", "LLM", "Voice", "Speaker", "Motors"]
      .map((name) => ({ name, word: "", line: "", cls: "none" }));
    fill($("stages"), stages.map((s, i) => {
      const live = !S.sel && liveIdx === i;
      const box = el("div", "stage " + (live ? "active" : s.cls));
      box.appendChild(el("b", "", s.name));
      box.appendChild(el("div", "word", live ? S.live + "…" : s.cls === "dead" ? "DIED HERE" : s.cls === "none" && !s.word ? (t ? "not reached" : "—") : s.word || "ok"));
      box.appendChild(el("div", "line", s.cls === "dead" ? s.reason : s.line));
      if (s.cls === "dead") box.title = s.reason;
      return box;
    }));
    $("pipeLabel").textContent = !t ? "no turn yet" + (S.live ? " · " + S.live : "")
      : (S.sel ? "viewing turn #" + t.id : "turn #" + t.id + " · " + ago(Date.now() / 1000 - t.t) + " ago" + (S.live ? " · now " + S.live : ""));
    $("pipeLive").hidden = !S.sel;
  }
  $("pipeLive").addEventListener("click", () => { S.sel = null; S.logWindow = null; mark("turns", "pipe", "log"); });

  function renderTurns() {
    $("turnCount").textContent = S.turns.length ? S.turns.length + " kept" : "";
    const rows = [];
    for (let i = S.turns.length - 1; i >= 0; i--) {
      const t = S.turns[i], x = t.times || {}, rec = t.rec || {};
      const tr = el("tr", S.sel === t ? "sel" : (i === S.turns.length - 1 ? "new" : ""));
      const bad = !/^(spoken|read: ask|read: tell|draft)/.test(t.outcome || "");
      const cells = [t.id, clock(t.t), secs(x.rec), secs(x.stt), secs(x.llm), secs(x.tts), t.outcome || ""];
      tr.title = (t.trigger || "") + (rec.rms !== undefined ? " · rms " + rec.rms : "") + (t.user ? " · heard: " + t.user : "");
      cells.forEach((c, j) => {
        const td = el("td", j === 1 || j === 6 ? "" : "n", c);
        if (j === 6) td.className = bad ? "bad" : "ok";
        if ((j === 3 && x.stt > SLOW.stt) || (j === 4 && x.llm > SLOW.llm) || (j === 5 && x.tts > SLOW.tts)) td.className = "n warn";
        tr.appendChild(td);
      });
      tr.addEventListener("click", () => selectTurn(t));
      rows.push(tr);
    }
    if (!rows.length) { const tr = el("tr", "empty"); const td = el("td", "", "no turn yet: each press of the remote becomes a row"); td.colSpan = 7; tr.appendChild(td); rows.push(tr); }
    fill($("turnRows"), rows);
    if (S.sel) renderDetail(S.sel);
  }
  function turnText(t) {
    const x = t.times || {}, rec = t.rec || {}, perf = t.perf || {};
    const lines = ["turn #" + t.id + "  " + clockMs(t.t) + "  outcome: " + t.outcome,
                   "trigger: " + (t.trigger || "?") + (t.ended ? "  ended by: " + t.ended : "") + (t.device ? "  device: " + t.device : ""),
                   "times:   " + Object.keys(x).map((k) => k + "=" + secs(x[k]) + "s").join(" ") + (t.link ? "  link=" + t.link : "")];
    if (rec.samples !== undefined) lines.push("recording: " + rec.dur_s + " s at " + rec.rate + " Hz  rms " + rec.rms + "  peak " + rec.peak +
      "  zeros " + Math.round((rec.zero_frac || 0) * 100) + " %  clipped " + ((rec.clip_frac || 0) * 100).toFixed(1) + " %  (" + rec.origin + ")");
    if (perf.result) lines.push("performance: " + perf.pulses + " mouth pulses, " + perf.gestures + " gestures, " + perf.player +
      ", late max " + perf.late_max_ms + " ms, " + perf.result + (perf.error ? " (" + perf.error.type + ": " + perf.error.text + ")" : ""));
    if (t.error) lines.push("error: " + t.error.type + ": " + t.error.text);
    if (t.user !== undefined) lines.push("heard: " + (t.user || "(nothing)"));
    if (t.reply !== undefined) lines.push("reply: " + (t.reply || "(empty)"));
    return lines.join("\n");
  }
  function renderDetail(t) {
    const box = $("turnDetail");
    fill(box, [el("div", "", turnText(t))]);
    const row = el("div", "row");
    const a = el("button", "", "Log of this turn"), b = el("button", "", "Copy");
    a.addEventListener("click", () => { S.logWindow = [t.t - ((t.times || {}).rec || 0) - 20, t.t + 2]; mark("log"); });
    b.addEventListener("click", () => copy(turnText(t)));
    row.appendChild(a); row.appendChild(b);
    if ((t.model || []).length) {
      const m = el("button", "", "What the models saw");
      m.addEventListener("click", () => { S.modelOnly = new Set(t.model); showTab("model"); mark("model"); });
      row.appendChild(m);
    }
    box.appendChild(row);
  }
  function selectTurn(t) { S.sel = S.sel === t ? null : t; if (!S.sel) { S.logWindow = null; fill($("turnDetail"), [el("span", "", "Click a turn.")]); } mark("turns", "pipe", "log"); }

  // ---- log -------------------------------------------------------------------------------------
  function renderLog() {
    const tags = new Map();
    for (const r of S.log) tags.set(r.tag || "other", (tags.get(r.tag || "other") || 0) + 1);
    fill($("logTags"), [...tags.keys()].sort().map((t) => {
      const c = el("span", "tag" + (S.logOff.has(t) ? " off" : ""), t + " " + tags.get(t));
      c.addEventListener("click", () => { S.logOff.has(t) ? S.logOff.delete(t) : S.logOff.add(t); mark("log"); });
      return c;
    }));
    const w = $("logWindow");
    w.hidden = !S.logWindow;
    if (S.logWindow) w.textContent = clock(S.logWindow[0]) + " – " + clock(S.logWindow[1]) + "  ✕";
    if (S.logPaused) { $("logCount").textContent = S.log.length + " lines · paused"; return; }
    const q = $("logSearch").value.toLowerCase();
    const rows = S.log.filter((r) => r.mark || (!S.logOff.has(r.tag || "other")
      && (!q || r.text.toLowerCase().includes(q))
      && (!S.logWindow || (r.t >= S.logWindow[0] && r.t <= S.logWindow[1])))).slice(-400);
    $("logCount").textContent = rows.length + " of " + S.log.length;
    const box = $("logBox");
    const stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
    fill($("logRows"), rows.map((r) => {
      const tr = el("tr", r.mark ? "mark" : (r.stream === "err" ? "err " : "") + (r.tag || ""));
      tr.appendChild(el("td", "t", r.mark ? "" : clockMs(r.t)));
      tr.appendChild(el("td", "x", r.text));
      return tr;
    }));
    if (stick) box.scrollTop = box.scrollHeight;
    S.shownLog = rows;
  }
  $("logSearch").addEventListener("input", () => mark("log"));
  $("logWindow").addEventListener("click", () => { S.logWindow = null; mark("log"); });
  $("logPause").addEventListener("click", () => { S.logPaused = !S.logPaused; $("logPause").textContent = S.logPaused ? "Resume" : "Pause"; mark("log"); });
  $("logCopy").addEventListener("click", () => copy((S.shownLog || []).map((r) => clockMs(r.t) + " " + r.text).join("\n")));
  function copy(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).catch(() => {});
  }

  // ---- inputs ----------------------------------------------------------------------------------
  function renderInputs() {
    const st = S.state || {}, remote = st.remote || {}, be = st.backends || {}, mode = st.mode || {};
    const rem = dev().remote || {}, mic = dev().mic || {}, lvl = (x) => (x.level === "bad" ? "bad-text" : x.level === "warn" ? "warn-text" : "");
    kv($("trigFacts"), [
      ["trigger", be.ptt],
      ["remote", rem.state ? rem.state + (rem.reason ? " · " + rem.reason : "") : "", lvl(rem)],
      ["configured keys", remote.keys, ""],
      ["devices read", remote.present ? (remote.devices || []).map((d) => d.path.replace("/dev/input/", "") + " '" + d.name + "'").join("\n") || "NONE" : "no remote configured (FISH_PTT_DEVICE)", remote.present && rem.present === false ? lvl(rem) : ""],
      remote.present ? ["button", (remote.armed ? "armed" : "not armed") + (remote.held ? " · HELD" : "") + (remote.need_release ? " · waiting for a release" : "") + " · mode " + remote.mode] : null,
      ["other keys seen", Object.entries(remote.other_keys || {}).map(([k, n]) => k + " ×" + n).join("  ") || "none", Object.keys(remote.other_keys || {}).length ? "bad-text" : ""],
      remote.text_keys ? ["text keys (not named)", remote.text_keys] : null,
      ["the fish is", mode.speaking ? "speaking" : mode.recording ? "recording" : mode.listening ? "waiting for a press" : "busy"],
    ]);
    const rows = [];
    for (let i = S.keys.length - 1; i >= 0 && rows.length < 80; i--) {
      const k = S.keys[i];
      const p = k.value === 0 ? S.presses[k.dev + "|" + k.key] : null;
      const held = p && Math.abs(p.t - k.t) < 0.2 ? p.held_s + " s" : "";
      const tr = el("tr", i === S.keys.length - 1 ? "new" : "");
      const verdict = !k.configured ? "NOT THE CONFIGURED KEY" : k.value === 1 ? (k.armed ? "counts" : "ignored: fish not waiting") : "";
      [clockMs(k.t), k.dev.replace("/dev/input/", ""), k.key + (k.code ? " (" + k.code + ")" : ""), k.value === 1 ? "down" : "up", held, verdict, k.name]
        .forEach((c, j) => tr.appendChild(el("td", j === 5 ? (!k.configured ? "bad" : c === "counts" ? "ok" : "dim") : j === 6 ? "dim" : "", c)));
      rows.push(tr);
    }
    fill($("keyRows"), rows.length ? rows : [el("tr", "", "")]);
    kv($("micFacts"), [
      ["capture", (mic.capture || "host") + " · the next hold records on " + (mic.recorder === "browser" ? "a phone" : "this machine")],
      ["microphone", mic.state ? mic.state + (mic.reason ? " · " + mic.reason : "") : "", lvl(mic)],
      ["source", be.mic_source || be.mic_device || "the sound server's default"],
      ["speech-to-text", be.stt],
    ]);
    const rec = st.rec;
    kv($("recFacts"), rec && rec.bytes ? [
      ["last recording", (rec.origin || "") + (rec.turn ? " · turn #" + rec.turn : "") + " · " + clock(rec.t)],
      ["length", rec.dur_s !== undefined ? rec.dur_s + " s at " + rec.rate + " Hz" : "?"],
      ["level", "rms " + rec.rms + " · peak " + rec.peak, rec.rms < 0.005 ? "bad-text" : ""],
      ["zero samples", Math.round((rec.zero_frac || 0) * 100) + " %" + (rec.lead_zero_s ? " · " + rec.lead_zero_s + " s of zeros first" : ""), rec.zero_frac > 0.95 ? "bad-text" : ""],
      ["clipped", ((rec.clip_frac || 0) * 100).toFixed(1) + " %"],
      ["verdict", rec.zero_frac > 0.95 ? "digital zeros: the microphone sent nothing" : rec.rms < 0.005 ? "near silence" : rec.clip_frac > 0.02 ? "clipped" : "has signal"],
    ] : [["last recording", "none yet (kept in memory only, replaced by the next)"]]);
    $("recPlay").disabled = !(rec && rec.kept);
  }
  // The level trace: the value goes through a spring before it is drawn; the exact numbers
  // are the text beside it.
  const lv = { ctx: $("level").getContext("2d"), value: 0, vel: 0, trace: new Array(260).fill(0), running: false, idle: 0 };
  function wakeLevel() { if (!lv.running) { lv.running = true; lv.last = performance.now(); requestAnimationFrame(levelFrame); } }
  function levelFrame(now) {
    const dt = Math.min(0.05, (now - lv.last) / 1000); lv.last = now;
    const target = Math.min(1, (S.levels.length ? S.levels[S.levels.length - 1] : 0) * 12);
    if (S.live !== "recording") S.levels.length = 0;
    const f = -90 * (lv.value - target) - 14 * lv.vel;
    lv.vel += f * dt; lv.value = Math.max(0, Math.min(1, lv.value + lv.vel * dt));
    lv.trace.push(lv.value); lv.trace.shift();
    const c = lv.ctx, W = 520, H = 56;
    c.clearRect(0, 0, W, H);
    c.strokeStyle = "#3a4552"; c.beginPath(); c.moveTo(0, H - 0.005 * 12 * H); c.lineTo(W, H - 0.005 * 12 * H); c.stroke();
    c.strokeStyle = "#7ee2a8"; c.lineWidth = 2; c.beginPath();
    lv.trace.forEach((v, i) => { const x = i * (W / lv.trace.length), y = H - 2 - v * (H - 6); i ? c.lineTo(x, y) : c.moveTo(x, y); });
    c.stroke();
    lv.idle = lv.value < 0.003 && target === 0 ? lv.idle + dt : 0;
    if (lv.idle < 6) requestAnimationFrame(levelFrame); else lv.running = false;   // asleep when nothing moves
  }
  $("recPlay").addEventListener("click", async () => {
    try {
      const r = await api("/debug/rec.wav");
      if (!r.ok) { msg($("micMsg"), "no recording kept", 4000); return; }
      const a = $("recAudio");
      if (a.src) URL.revokeObjectURL(a.src);
      a.src = URL.createObjectURL(await r.blob());
      a.hidden = false;
      a.play().catch(() => {});
    } catch (_) { msg($("micMsg"), "no connection", 4000); }
  });
  $("micCheck").addEventListener("click", async () => {
    msg($("micMsg"), "recording 2 s…");
    const out = await post("/debug/mic", { seconds: 2 });
    msg($("micMsg"), out.ok ? "done: rms " + ((out.rec || {}).rms ?? "?") : "refused: " + (out.error || out.status), 8000);
    refresh();
  });

  // ---- voice -----------------------------------------------------------------------------------
  function renderVoice() {
    const st = S.state || {}, be = st.backends || {}, t = lastTurn() || {}, x = t.times || {}, perf = S.perf || {};
    kv($("voiceFacts"), [
      ["text-to-speech", be.tts],
      ["last tts / play start", x.tts !== undefined ? secs(x.tts) + " s / +" + secs(x.play_start) + " s" : ""],
      ["player", be.player],
      ["speaker device", be.speaker || "the sound server's default"],
      ["last playback", perf.result ? perf.result + (perf.error ? " (" + perf.error.type + ": " + perf.error.text + ")" : "") : "", perf.result && perf.result !== "ok" ? "bad-text" : ""],
    ]);
    if (document.activeElement !== $("waitTick")) $("waitTick").checked = !!(st.mode || {}).wait;
    const pron = Array.isArray(st.pron) ? st.pron : [];
    if ($("pronRows").childElementCount !== pron.length) {
      fill($("pronRows"), pron.map((label, i) => {
        const b = el("button", "", "▶ " + label);
        b.title = "renders it with loq and plays it through the hat's speaker";
        b.addEventListener("click", async () => {
          msg(null, "saying: " + label + "…");
          const out = await post("/debug/pron", { i });
          msg(null, out.ok ? "said: " + label : "refused: " + (out.error || out.status), 6000);
        });
        return b;
      }));
    }
    fill($("cannedRows"), (Array.isArray(st.canned) ? st.canned : []).map((c) => {
      const b = el("button", "", (c.rendered ? "▶ " : "○ ") + c.name);
      b.disabled = !c.rendered;
      b.title = c.rendered ? "play the rendered phrase, audio only" : "not rendered yet";
      b.addEventListener("click", async () => {
        msg($("voiceMsg"), "playing " + c.name + "…");
        const out = await post("/debug/say", { name: c.name });
        msg($("voiceMsg"), out.ok ? "played through " + out.player : "refused: " + (out.error || out.status), 8000);
      });
      return b;
    }));
  }
  $("sayBtn").addEventListener("click", async () => {
    const text = $("sayText").value.trim();
    if (!text) return;
    const out = await post("/speak", { text });
    msg($("voiceMsg"), out.ok ? "sent" : "refused: " + (out.error || out.status), 5000);
    if (out.ok) $("sayText").value = "";
  });
  $("waitTick").addEventListener("change", async () => { await post("/wait", { on: $("waitTick").checked }); refresh(); });

  // ---- motors ----------------------------------------------------------------------------------
  function renderMotors() {
    const st = S.state || {}, link = st.link || {}, perf = S.perf || {}, mode = st.mode || {};
    kv($("linkFacts"), [
      ["link", (link.desc || "") + (link.mock ? "  — MOCK LINK: nothing moves" : ""), link.mock ? "bad-text" : ""],
      ["health", link.health, link.health && link.health !== "ok" ? "bad-text" : ""],
      ["attached", link.attached ? "yes" : "NO"],
      link.unanswered !== undefined ? ["lines unanswered", link.unanswered] : null,
      ["lines sent / dropped", (link.tx_total ?? 0) + " / " + (link.tx_dropped ?? 0)],
      ["bytes back", link.rx_bytes ?? 0],
    ]);
    const lines = st.motor_lines || {};
    const armed = performance.now() < S.armedUntil;
    const busy = mode.speaking ? "the fish is speaking" : mode.recording ? "the fish is recording" : !mode.listening ? "the fish is busy" : "";
    fill($("motorRows"), ["mouth", "neck", "tail"].map((part) => {
      const row = el("div", "motor");
      const b = el("button", "", part[0].toUpperCase() + part.slice(1));
      const planned = Array.isArray(lines[part]) ? lines[part].join("   then   ") : (lines[part] || {}).error || "";
      b.disabled = !armed || !!busy || !Array.isArray(lines[part]);
      b.title = !armed ? "arm first" : busy || "send: " + planned;
      b.addEventListener("click", async () => {
        msg($("motorMsg"), "sending " + part + "…");
        const out = await post("/debug/motor", { part });
        msg($("motorMsg"), out.ok ? part + ": " + out.result + " · " + (out.lines || []).join(" | ") + (out.note ? " · " + out.note : "")
                                  : part + " refused: " + (out.error || out.status), 10000);
        refresh();
      });
      row.appendChild(b);
      row.appendChild(el("span", Array.isArray(lines[part]) ? "" : "bad-text", planned));
      return row;
    }).concat([el("div", "note", !armed ? "locked: press ARM (60 s)" : busy ? "armed, but " + busy : "ARMED")]));
    kv($("perfFacts"), perf.result ? [
      ["mouth pulses / gestures", perf.pulses + " / " + perf.gestures],
      ["worst lateness", perf.late_max_ms + " ms", perf.late_max_ms > 50 ? "bad-text" : ""],
      ["played for", (perf.play_s ?? "?") + " s through " + perf.player],
      ["result", perf.result, perf.result !== "ok" ? "bad-text" : ""],
    ] : [["last performance", "none yet"]]);
    $("rxTail").textContent = link.rx_tail || "(nothing yet: bytes arrive when a line is sent)";
    $("txCount").textContent = S.tx.length ? "last " + Math.min(S.tx.length, 120) : "";
    const rows = [];
    for (let i = S.tx.length - 1; i >= 0 && rows.length < 120; i--) {
      const r = S.tx[i], tr = el("tr");
      tr.appendChild(el("td", "dim", clockMs(r.t)));
      tr.appendChild(el("td", /^MOUTH -?\d+$/.test(r.line) ? "bad" : "", r.line));
      tr.appendChild(el("td", r.flag ? "bad" : "dim", r.flag));
      rows.push(tr);
    }
    fill($("txRows"), rows);
  }
  $("pingBtn").addEventListener("click", async () => {
    const out = await post("/debug/ping", {});
    msg($("pingMsg"), out.ok ? "MCU: " + out.result + " in " + out.ms + " ms · health " + out.health : "refused: " + (out.error || out.status), 8000);
    refresh();
  });

  // ---- cloud, board, config, clients -----------------------------------------------------------
  function renderCloud() {
    const be = (S.state || {}).backends || {}, llm = be.llm || {}, net = dev().internet || {};
    kv($("cloudFacts"), [
      ["internet", net.state ? net.state + (net.reason ? " · " + net.reason : "") : "", net.level === "bad" ? "bad-text" : net.level === "warn" ? "warn-text" : ""],
      ["keys", Object.entries(be.keys || {}).map(([k, ok]) => k + (ok ? " present" : " MISSING")).join("\n")],
      ["speech-to-text", be.stt + ((be.stt_online || []).length || (be.stt_long || []).length
        ? " · online first: " + ((be.stt_online || []).join(" > ") || "none") + " · long: " + ((be.stt_long || []).join(" > ") || "local") : "")],
      ["last transcription", be.stt_last ? be.stt_last.service + " (" + be.stt_last.route + ") " + secs(be.stt_last.seconds) + " s" : ""],
      ["LLM", be.echo ? "echo (no model called)" : be.llm_profile + " : " + be.llm_model],
      ["last LLM call", llm.last_s !== undefined && llm.last_s !== null ? secs(llm.last_s) + " s" : ""],
      ["last LLM error", llm.last_error || "none", llm.last_error ? "bad-text" : ""],
      ["history", llm.history !== undefined ? llm.history + " messages" : ""],
      ["text-to-speech", be.tts],
    ]);
  }
  function renderBoard() {
    const st = S.state || {}, sys = st.system || {}, svc = st.service || {}, mem = sys.mem_mb || {};
    const port = dev().usb_port || {}, usb = dev().usb_devices || {};
    kv($("boardFacts"), [
      ["temperature", (sys.thermal || []).map((z) => z.name + " " + z.c + " C").join("\n") || "n/a on this machine"],
      ["load (1, 5, 15 min)", (sys.load || []).join("  ") + "  on " + (sys.cores || "?") + " cores"],
      ["memory", mem.total ? mem.available + " MB free of " + mem.total : ""],
      ["disk", sys.disk_free_mb !== undefined ? sys.disk_free_mb + " MB free" : ""],
      ["machine up", sys.uptime_s ? ago(sys.uptime_s) : ""],
      ["Wi-Fi link", (sys.wifi || []).map((w) => w.dev + " " + w.link + "/70").join("  ") || "n/a"],
      ["USB port", port.level === "off" || !port.state ? "n/a on this machine" : port.state + (port.reason ? " · " + port.reason : ""), port.level === "bad" ? "bad-text" : ""],
      ["USB devices", usb.level === "off" || !usb.state ? "n/a on this machine" : usb.state, usb.level === "warn" ? "warn-text" : ""],
    ]);
    kv($("usbFacts"), (sys.usb || []).map((u) => [u.id, u.product]));
    kv($("svcFacts"), [
      ["process", "pid " + svc.pid + " · python " + svc.python + " · up " + (st.now ? ago(st.now - st.started) : "")],
      ["systemd service", svc.supervised ? svc.unit : "no (started by hand: nothing would restart it)"],
      ["code", ((st.version || {}).branch || "") + " " + ((st.version || {}).commit || "") + ((st.version || {}).changed_since_start ? "  — CHANGED ON DISK SINCE START" : ""), (st.version || {}).changed_since_start ? "bad-text" : ""],
      ["faults swallowed by the debug hooks", st.hub_errors ?? 0, st.hub_errors ? "bad-text" : ""],
    ]);
    const armed = performance.now() < S.armedUntil;
    $("restartBtn").disabled = !armed || !svc.supervised;
    $("restartBtn").title = !svc.supervised ? "not a systemd service here" : !armed ? "arm first" : "";
  }
  $("restartBtn").addEventListener("click", () => { $("restartAsk").hidden = false; $("restartNo").focus(); });
  $("restartNo").addEventListener("click", () => { $("restartAsk").hidden = true; });
  $("restartYes").addEventListener("click", async () => {
    $("restartAsk").hidden = true;
    const out = await post("/debug/restart", { confirm: "restart" });
    msg($("restartMsg"), out.ok ? "signalled: waiting for the fish to come back…" : "refused: " + (out.error || out.status), 20000);
  });
  function renderConfig() {
    const rows = (S.state || {}).config;
    if (!Array.isArray(rows)) return;
    const q = $("cfgFilter").value.toLowerCase();
    const shown = rows.filter((r) => !q || (r.section + "." + r.field + " " + r.env + " " + JSON.stringify(r.value)).toLowerCase().includes(q))
      .sort((a, b) => (b.set ? 1 : 0) - (a.set ? 1 : 0));
    fill($("cfgRows"), shown.map((r) => {
      const tr = el("tr");
      tr.appendChild(el("td", r.set ? "warn" : "dim", r.section + "." + r.field));
      tr.appendChild(el("td", "dim", r.env));
      tr.appendChild(el("td", "wrap", typeof r.value === "string" ? r.value : JSON.stringify(r.value)));
      return tr;
    }));
  }
  $("cfgFilter").addEventListener("input", () => { renderConfig(); });
  function renderClients() {
    kv($("phoneFacts"), phoneFacts());
    const c = (S.state || {}).clients || {};
    kv($("clientFacts"), [
      ["phone pages connected", (c.pages ?? "?") + " of " + (c.max ?? 8)],
      ["pages with their microphone ready", (dev().phone_mic || {}).pages ?? 0],
      ["pages armed as the speaker", (dev().phone_speaker || {}).pages ?? 0],
      ["debug pages", c.debug_pages ?? 0],
      ["events a slow page missed", c.dropped ?? 0, c.dropped ? "bad-text" : ""],
      ["pages pushed out by a newer one", c.evicted ?? 0],
      ["records this page missed", S.missed, S.missed ? "bad-text" : ""],
    ]);
    const rows = [];
    for (let i = S.acts.length - 1; i >= 0 && rows.length < 60; i--) {
      const r = S.acts[i], tr = el("tr");
      tr.appendChild(el("td", "dim", clockMs(r.t)));
      tr.appendChild(el("td", "", r.kind === "http" ? r.method + " " + r.path : r.what));
      tr.appendChild(el("td", r.kind === "http" ? "bad" : "", r.kind === "http" ? r.status + " " + (r.error || "") : (r.result || "") + (r.lines && r.lines.length ? " · " + r.lines.join(" | ") : "")));
      rows.push(tr);
    }
    fill($("actRows"), rows);
  }

  // ---- checks -----------------------------------------------------------------------------------
  const WORD = { pass: "● PASS", fail: "■ FAIL", warn: "▲ WARN", skip: "○ skip" };
  function renderChecks() {
    const st = S.state || {}, rows = Array.isArray(st.checks) ? st.checks : [], cs = st.checks_summary || {};
    $("checkCount").textContent = rows.length ? cs.passed + " of " + cs.of + " pass · " + cs.failed + " failed · " + cs.warned + " warnings" : "not available";
    const out = [];
    let group = "";
    for (const r of rows) {
      if (r.group !== group) {
        group = r.group;
        const g = el("tr"); const td = el("td", "g", group); td.colSpan = 3; g.appendChild(td); out.push(g);
      }
      const tr = el("tr");
      tr.appendChild(el("td", "s " + r.status, WORD[r.status] || r.status));
      tr.appendChild(el("td", "", r.name));
      const d = el("td", "wrap", r.detail);
      if (r.fix) d.appendChild(el("span", "fix", r.fix));
      tr.appendChild(d);
      out.push(tr);
    }
    fill($("checkRows"), out);
  }
  function testButton(id, path, label, say) {
    $(id).addEventListener("click", async () => {
      msg($("checkMsg"), label + "…");
      const out = await post(path, {});
      msg($("checkMsg"), out.ok ? label + ": " + say(out) : label + " refused: " + (out.error || out.status), 15000);
      refresh();
    });
  }
  testButton("loopBtn", "/debug/loop", "loop", (o) => o.verdict + " (room " + o.room + ", playing " + o.level + ")");
  testButton("voiceBtn", "/debug/voice", "voice render", (o) => o.seconds + " s with " + o.backend);
  testButton("cloudBtn", "/debug/cloud", "cloud", (o) => Object.entries(o.parts || {}).map(([k, v]) =>
    k + " " + (v.skipped ? "skipped" : v.ok ? v.seconds + " s" : v.error + (v.status ? " " + v.status : ""))).join(" · "));

  // ---- switches ---------------------------------------------------------------------------------
  async function setSwitch(w, value) {
    msg($("switchMsg"), w.label + "…");
    const out = await post("/debug/set", { name: w.name, value });
    msg($("switchMsg"), out.ok ? w.label + ": " + (out.unchanged ? "already " : "now ") + out.value
      : w.label + " refused: " + (out.error === "busy" ? "busy (the fish is mid-turn: try again when it waits)" : out.error || out.status), 12000);
    await refresh();
  }
  function renderSwitches() {
    const box = $("switchRows");
    if (box.contains(document.activeElement)) return;      // not under the reader's hands
    const list = Array.isArray((S.state || {}).switches) ? S.state.switches : [];
    const armed = performance.now() < S.armedUntil;
    fill(box, list.map((w) => {
      const tr = el("tr", w.changed ? "changed" : "");
      tr.appendChild(el("td", "", w.label));
      const cell = el("td");
      const locked = w.armed && !armed;
      if (w.kind === "bool") {
        const c = document.createElement("input");
        c.type = "checkbox"; c.checked = !!w.value; c.disabled = locked;
        c.addEventListener("change", () => { c.blur(); setSwitch(w, c.checked); });
        cell.appendChild(c); cell.appendChild(document.createTextNode(w.value ? " on" : " off"));
      } else if (w.kind === "number") {
        const n = document.createElement("input");
        n.type = "number"; n.value = w.value; n.min = w.choices[0]; n.max = w.choices[1]; n.step = 1;
        n.addEventListener("change", () => { n.blur(); setSwitch(w, Number(n.value)); });
        cell.appendChild(n);
      } else {
        const sel = document.createElement("select");
        sel.disabled = locked;
        for (const c of w.choices) { const o = el("option", "", c); o.value = c; o.selected = c === w.value; sel.appendChild(o); }
        sel.addEventListener("change", () => { sel.blur(); setSwitch(w, sel.value); });
        cell.appendChild(sel);
      }
      tr.appendChild(cell);
      tr.appendChild(el("td", "dim", w.kind === "bool" ? (w.start ? "on" : "off") : w.start));
      const back = el("td");
      if (w.changed) {
        const b = el("button", "", "back to start");
        b.disabled = locked;
        b.addEventListener("click", () => setSwitch(w, w.start));
        back.appendChild(b);
      }
      tr.appendChild(back);
      tr.appendChild(el("td", "dim wrap", (locked ? "arm first · " : "") + (w.note || "")));
      return tr;
    }));
  }

  // ---- what the models see ------------------------------------------------------------------------
  function bubble(role, text, cls) {
    const m = el("div", "m " + (cls || role));
    m.appendChild(el("b", "", role));
    m.appendChild(document.createTextNode(text === undefined || text === null ? "" : String(text)));
    return m;
  }
  function renderModel() {
    const st = S.state || {}, mo = st.model || {};
    $("modelNow").textContent = mo.profile ? (mo.echo ? "echo mode: no model is called · " : "") + mo.profile + " : " + mo.model +
      " · history " + (mo.history || []).length + " of " + mo.history_max : "";
    const now = [bubble("system", mo.prompt)];
    if (mo.rules_active) now.push(bubble("system (the reading's rules)", mo.reading_rules, "system"));
    for (const m of mo.history || []) now.push(bubble(m.role, m.content));
    fill($("modelPrompt"), now);
    const only = S.modelOnly, pick = (arr) => arr.filter((r) => !only || only.has(r.seq)).slice().reverse();
    $("modelClear").hidden = !only;
    const llm = pick(S.llm);
    $("llmCount").textContent = llm.length ? llm.length + (only ? " of this turn" : " kept") : "none yet";
    fill($("llmRows"), llm.map((r, i) => {
      const d = el("details", r.error || r.sent === false ? "bad" : "");
      // Open what the reader opened; a call that is new since the last paint opens once.
      if (i === 0 && r.seq > S.seenCall) { S.seenCall = r.seq; S.openCalls.add(r.seq); }
      d.open = S.openCalls.has(r.seq);
      d.addEventListener("toggle", () => { d.open ? S.openCalls.add(r.seq) : S.openCalls.delete(r.seq); });
      const tok = r.tokens ? " · " + (r.tokens.prompt ?? "?") + "+" + (r.tokens.completion ?? "?") + " tok" : "";
      d.appendChild(el("summary", "", clockMs(r.t) + "  " + r.model + "  " + (r.sent === false ? r.note
        : r.error ? r.error.type + (r.error.status ? " " + r.error.status : "") : secs(r.seconds) + " s" + tok) +
        "  · " + (r.messages || []).length + " messages" + (r.probe ? "  · cloud check" : "")));
      const box = el("div", "msgs");
      if (r.params) box.appendChild(bubble("parameters", JSON.stringify(r.params), "params"));
      for (const m of r.messages || []) box.appendChild(bubble(m.role, m.content));
      if (r.reply !== undefined) box.appendChild(bubble("reply" + (r.finish ? " (" + r.finish + ")" : ""), r.reply || "(empty)", "assistant"));
      if (r.error) box.appendChild(bubble("error", r.error.type + ": " + r.error.text, "err"));
      d.appendChild(box);
      return d;
    }));
    kv($("sttFacts"), [["prompt", mo.stt_prompt], ["keywords", (mo.stt_keywords || []).join(", ") || "none"]]);
    fill($("sttRows"), pick(S.stt).map((r) => {
      const tr = el("tr");
      tr.appendChild(el("td", "dim", clockMs(r.t)));
      tr.appendChild(el("td", r.seconds > SLOW.stt ? "warn" : "", secs(r.seconds)));
      const route = el("td", "dim wrap", (r.backend || "") + (r.route ? " · " + r.route : ""));
      if (r.skipped && r.skipped.length) route.title = "passed over: " + r.skipped.join("; ");
      tr.appendChild(route);
      tr.appendChild(el("td", "wrap", r.sent === false ? r.note : r.error ? r.error.type + ": " + r.error.text : (r.raw || "(empty)")));
      tr.appendChild(el("td", r.dropped || r.error || r.sent === false ? "bad" : "ok",
        r.dropped ? "DROPPED: " + r.dropped : r.error || r.sent === false ? "failed" : r.final ? "kept" : "empty"));
      return tr;
    }));
    fill($("ttsRows"), pick(S.tts).map((r) => {
      const tr = el("tr");
      tr.appendChild(el("td", "dim", clockMs(r.t)));
      tr.appendChild(el("td", r.seconds > SLOW.tts ? "warn" : "", secs(r.seconds)));
      tr.appendChild(el("td", "", r.backend + (r.voice ? " " + r.voice : "")));
      tr.appendChild(el("td", r.error ? "bad wrap" : "wrap", r.error ? r.error.type + ": " + r.error.text : r.text));
      return tr;
    }));
  }
  $("modelClear").addEventListener("click", () => { S.modelOnly = null; mark("model"); });

  // ---- the band: what he needs without scrolling -----------------------------------------------
  function renderBand() {
    const ago = lastMsgAt ? Math.round((performance.now() - lastMsgAt) / 1000) : null;
    const a = $("hAgo");
    a.textContent = ago === null ? "" : ago < 2 ? "now" : ago + " s ago";
    a.className = "chip " + (ago === null ? "unknown" : ago > 15 ? "bad" : ago > 8 ? "warn" : "ok");
    const v = S.visit, f = S.fortune, b = $("bandVisit");
    const fortune = !!(f && f.open);
    b.hidden = !fortune && !(v && v.stage);
    if (fortune) {                                // the act on now; a tap opens the Visit tab
      b.textContent = (f.stage === "reading" ? "Fortune: reading" : "Fortune " + f.q + "/" + f.of) + (f.first ? " · " + f.first : "");
      b.className = "chip warn";
    } else if (v && v.stage) {
      b.textContent = v.stage > v.of ? "Verdict: " + (v.house || "—") + (v.first ? " · " + v.first : "")
                                     : "Stage " + v.stage + "/" + v.of + (v.first ? " · " + v.first : "");
      b.className = "chip " + (v.stage > v.of ? "ok" : "warn");
    }
    const page = (S.state || {}).page || {};
    const sec = $("chipSecure");
    sec.hidden = !PHONE.matches && window.isSecureContext;
    sec.textContent = window.isSecureContext ? "secure" : "http: no screen lock";
    sec.className = "chip " + (window.isSecureContext ? "ok" : "warn");
    if (!window.isSecureContext && page.tls_port) {
      const u = new URL(location.href);
      u.protocol = "https:"; u.port = String(page.tls_port); u.pathname = "/"; u.search = "";
      sec.href = u.href;
    }
    else sec.removeAttribute("href");
    wake.paint();
  }
  setInterval(() => { if (!document.hidden) renderBand(); }, 1000);
  $("bandVisit").addEventListener("click", () => showTab("visit"));

  // ---- wait-to-speak: a draft lands in the Voice tab's box --------------------------------------
  function voiceDraft(text) {
    const box = $("sayText");
    if (document.activeElement === box) return;          // never under the operator's fingers
    box.value = text;
    msg(null, "draft ready: Voice tab → Speak", 6000);
    for (const b of $("tabs").children) if (b.dataset.tab === "voice") b.classList.add("flag");
  }

  // ---- the screen stays on (Screen Wake Lock: https only) ----------------------------------------
  const wake = guard("wake", () => {
    let lock = null, wanted = false;
    async function ask() {
      wanted = true;
      if (!("wakeLock" in navigator) || document.hidden || lock) { paint(); return; }
      try {
        lock = await navigator.wakeLock.request("screen");
        lock.addEventListener("release", () => { lock = null; paint(); });
      } catch (_) { lock = null; }
      paint();
    }
    function paint() {
      const c = $("chipScreen");
      c.hidden = !PHONE.matches && !lock;
      if (!("wakeLock" in navigator)) { c.textContent = "screen may sleep (http)"; c.className = "chip warn"; return; }
      c.textContent = lock ? "screen on" : wanted ? "screen may sleep" : "tap: keep screen on";
      c.className = "chip " + (lock ? "ok" : "warn");
    }
    window.addEventListener("pointerdown", () => { if (!lock) ask(); }, { passive: true });
    return { ask, paint, held: () => !!lock };
  }, { ask() {}, paint() {}, held: () => false });

  // ---- hold to talk: the backup for the remote's button (POST /ptt; the board records) ----------
  const ptt = guard("ptt", () => {
    const btn = $("pttButton");
    let down = false, needRelease = false, remoteHold = false, pointer = null, armedInstead = false;
    // The board cannot hear (its microphone dead, or marked failed): a press turns this phone's
    // microphone on instead of recording silence on the board; the next press records. The
    // switch resets on every reload and every screen sleep, so this is what a cold page does.
    function boardDeaf() { return !!(dev().mic || {}).out; }   // marked, its source gone or zeros
    function send(on) {
      if (phoneMic.ready() && (on || phoneMic.holding())) { on ? phoneMic.begin() : phoneMic.end(); return; }
      if (on && phoneMic.can() && boardDeaf()) {
        armedInstead = true;
        phoneMic.arm();
        msg(null, "the board has no microphone: turning this phone's on, then hold again", 6000);
        return;
      }
      if (!on && armedInstead) { armedInstead = false; return; }
      api("/ptt", { down: on }).catch(() => {});
    }
    function setPtt(on) {
      if (!on) needRelease = false;
      else if (needRelease) return;
      if (on === down) return;
      down = on;
      btn.classList.toggle("held", on);
      send(on);
    }
    // Leaving the page while holding must still release: a beacon is not cancelled as the
    // page hides, a fetch can be.
    function releaseNow() {
      needRelease = false;
      if (!down) return;
      down = false;
      btn.classList.remove("held");
      if (phoneMic.holding()) { phoneMic.abort(); return; }
      const url = "/ptt" + (TOKEN ? "?token=" + encodeURIComponent(TOKEN) : "");
      const body = new Blob([JSON.stringify({ down: false })], { type: "application/json" });
      if (!(navigator.sendBeacon && navigator.sendBeacon(url, body))) api("/ptt", { down: false }).catch(() => {});
    }
    // One finger, captured: a drift, a scroll or a long press cannot cancel the hold silently.
    btn.addEventListener("pointerdown", (e) => {
      if (pointer !== null) return;
      e.preventDefault();
      pointer = e.pointerId;
      try { btn.setPointerCapture(e.pointerId); } catch (_) {}
      setPtt(true);
    });
    for (const t of ["pointerup", "pointercancel", "lostpointercapture"]) {
      btn.addEventListener(t, (e) => { if (e.pointerId !== pointer) return; pointer = null; setPtt(false); });
    }
    btn.addEventListener("touchstart", (e) => e.preventDefault(), { passive: false });
    btn.addEventListener("contextmenu", (e) => e.preventDefault());
    // The host's own word: it ended the press (the recording limit), or a remote's press is
    // relayed to this page because the phone is the microphone.
    function event(ev) {
      if (ev.source) {
        if (!phoneMic.ready()) { remoteHold = false; return; }
        if (ev.held && !down) { remoteHold = true; setPtt(false); setPtt(true); }
        else if (!ev.held && remoteHold) { remoteHold = false; setPtt(false); }
      } else if (!ev.held) {
        if (down) needRelease = true;
        down = false;
        btn.classList.remove("held");
      }
    }
    return { event, releaseNow };
  }, { event() {}, releaseNow() {} });

  // ---- the typed name (ADR 0007, the photo gone): "¿Tú eres X?"; the fortune reads it too ------
  const reader = guard("reader", () => {
    const name = $("readName"), note = $("readMsg"), readBtn = $("readBtn");
    let busy = false;
    function say(text, cls) { note.textContent = text || ""; note.className = "note " + (cls || ""); }
    function setBusy(on) { busy = on; readBtn.disabled = on; }
    async function sendName() {
      const n = name.value.trim();
      if (!n || busy) { name.focus(); return; }
      setBusy(true);
      say("Sending the name…", "busy");
      const out = await post("/reading", { name: n });
      if (out.status === 409) say("The hat is busy", "bad-text");
      else if (out.status === 400) say("Type a name", "bad-text");
      else if (!out.ok) say(out.status === 0 ? "No connection" : "Could not send the name", "bad-text");
      else { say("Sent: the hat greets " + n, ""); name.value = ""; name.blur(); }
      setBusy(false);
    }
    readBtn.addEventListener("click", sendName);
    name.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); sendName(); } });
    return { busy: () => busy, name: () => name.value.trim() };
  }, { busy: () => false, name: () => "" });

  // ---- the hat's visit: "New visitor" and the cues (visit.py) --------------------------------
  // The server owns the cues: a lit chip is one the hat has not used yet, and the row draws the
  // server's view (the POST /cues answer, the `visit` record) unless an edit of its own is on its way.
  const visitRow = guard("visit", () => {
    const row = $("cVisit"), btn = $("visitNew"), note = $("visitMsg"), used = $("visitSent");
    const texts = [$("cueLleva"), $("cueNota")];
    const chips = Array.from(row.querySelectorAll(".cue"));
    const label = {};                              // the host's Spanish value → the chip's English
    for (const c of chips) label[c.dataset.cue + ":" + c.dataset.val] = c.textContent;
    let on = false, rev = 0, postedRev = 0, inflight = false, timer = 0;
    let latest = null, lastN = -1, wantN = null, btnTimer = 0;
    function say(text, cls) { note.textContent = text || ""; note.className = "note " + (cls || ""); }
    function current() {
      const out = {};
      for (const c of chips) if (c.getAttribute("aria-pressed") === "true") out[c.dataset.cue] = c.dataset.val;
      for (const t of texts) { const v = t.value.trim(); if (v) out[t.dataset.cue] = v; }
      return out;
    }
    // The scripted visit: answer buttons for the open question, a house now, skip.
    const showRow = $("showRow"), showAnswers = $("showAnswers"), showQ = $("showQ");
    const showHeard = $("showHeard"), showLast = $("showLast");
    let showKey = "";
    async function showTap(action, value) {
      const out = await post("/show", { action, value: value || "" });
      if (!out.ok) say(out.status === 409 ? "The hat is busy: try again in a moment"
                     : out.status === 0 ? "No connection" : "Refused", "bad-text");
    }
    for (const b of showRow.querySelectorAll(".pick[data-house]")) {
      b.addEventListener("click", () => showTap("force", b.dataset.house));
    }
    $("showSkip").addEventListener("click", () => showTap("skip"));
    function showView(sh) {
      const open = !!(sh && sh.open);
      showRow.hidden = !open;
      const last = sh && sh.last && sh.last.house ? "last verdict: " + sh.last.house + " (" + sh.last.how + ")" : "";
      showLast.textContent = sh && sh.mode && sh.mode !== "off" ? "script " + sh.mode + (last ? " · " + last : "") : "";
      if (!open) return;
      if (!sh.qid) { showQ.textContent = "Verdict…"; showAnswers.replaceChildren(); showKey = ""; return; }
      showQ.textContent = "Question " + sh.q + " of " + sh.of + " (" + sh.qid + ", " + sh.why + ")";
      const key = sh.n + ":" + sh.qid;
      if (key !== showKey) {
        showKey = key;
        showAnswers.replaceChildren();
        for (const o of sh.options || []) {
          const b = document.createElement("button");
          b.type = "button"; b.className = "pick"; b.textContent = o.label;
          b.addEventListener("click", () => showTap("answer", o.id));
          showAnswers.appendChild(b);
        }
      }
      showHeard.textContent = sh.heard && sh.heard.length ? "heard: " + sh.heard.slice(1).join(" · ") : "";
    }
    function view(v) {
      if (!v) return;
      showView(v.show);
      if (v.n !== lastN) {
        lastN = v.n;
        if (wantN !== null && v.n >= wantN) { wantN = null; clearTimeout(btnTimer); btn.disabled = false; }
      }
      const who = v.first ? " · " + v.first : "";
      $("visitState").textContent = !v.stage ? "no visitor"
        : v.stage > v.of ? "verdict: " + (v.house || "—") + who : "stage " + v.stage + " of " + v.of + who;
      const s = Object.entries(v.sent || {}).map(([k, val]) => label[k + ":" + val] || val);
      used.textContent = s.length ? "used: " + s.join(" · ") : "";
      if (rev !== postedRev || inflight || timer) { latest = v; return; }
      latest = null;
      const cues = v.cues || {};
      for (const c of chips) c.setAttribute("aria-pressed", cues[c.dataset.cue] === c.dataset.val ? "true" : "false");
      for (const t of texts) if (document.activeElement !== t) t.value = cues[t.dataset.cue] || "";
    }
    function edit(ms) { rev++; clearTimeout(timer); timer = setTimeout(() => { timer = 0; flush(); }, ms); }
    async function flush() {
      clearTimeout(timer); timer = 0;
      if (inflight || rev === postedRev) return;
      const at = rev;
      inflight = true;
      const out = await post("/cues", { cues: current() });
      if (out.status === 0) {                       // no connection: try again shortly
        say("No connection: the cue did not arrive", "bad-text");
        timer = setTimeout(() => { timer = 0; flush(); }, 3000);
      } else {
        postedRev = at;                             // a refusal is not retried
        if (out.ok) { say(""); latest = out.visit || latest; }
        else if (out.status === 400) say("Cue refused", "bad-text");
        else if (out.status === 403) say("No permission (token)", "bad-text");
        else say("The visit is off", "bad-text");
      }
      inflight = false;
      if (rev !== postedRev && !timer) flush();
      else if (latest && !timer) view(latest);
    }
    for (const c of chips) {
      c.addEventListener("click", () => {
        const was = c.getAttribute("aria-pressed") === "true";
        for (const o of chips) if (o.dataset.cue === c.dataset.cue) o.setAttribute("aria-pressed", "false");
        c.setAttribute("aria-pressed", was ? "false" : "true");
        edit(250);
      });
    }
    for (const t of texts) {
      t.addEventListener("input", () => { rev++; });          // sent when the field is left
      t.addEventListener("change", () => { if (rev === postedRev) rev++; flush(); });
      t.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); t.blur(); } });
    }
    btn.addEventListener("click", async () => {
      if (btn.disabled || reader.busy()) return;
      flush();
      btn.disabled = true;
      msg(null, "calling the hat…", 3000);
      const out = await post("/visit", {});
      if (out.ok) {
        $("heardLine").textContent = ""; $("saidLine").textContent = "";
        wantN = lastN + 1;                          // enabled again by the new visit's view
        btnTimer = setTimeout(() => { wantN = null; btn.disabled = false; }, 3000);
        showTab("visit");
        return;
      }
      msg(null, out.status === 409 ? "refused: the hat is busy · wait until it finishes"
              : out.status === 503 ? "refused: the visit is off" : out.status === 0 ? "no connection" : "refused: " + (out.error || out.status), 6000);
      btn.disabled = false;
    });
    return {
      status(page) { on = !!page.visit_enabled; row.hidden = !on; btn.hidden = !on; },
      view, flush, on: () => on,
    };
  }, { status() {}, view() {}, flush() {}, on: () => false });

  // ---- the fortune act: "🔮 Fortune", the open question, skip and end (fortune_run.py) --------
  // The server owns the act: the row draws its view (the `visit` record's `fortune`, the page's
  // on a load) and the buttons post to /fortune. An event without the key keeps the last view.
  // The big button is hidden unless the hat has the act, greyed and disabled until its clips are
  // rendered (show_tab's fortune alone says so) and off while an act is open.
  const QUESTION_EN = { fecha: "birth date", sueno: "dreams", carta: "the card", taza: "the cup", animal: "the animal" };
  const DATA_EN = { signo: "sign", elemento: "element", numero: "lucky number", sueno: "dream", carta: "card",
                    taza: "cup", animal: "animal", luna: "moon", palabra: "magic word" };
  const fortuneRow = guard("fortune", () => {
    const row = $("fortuneRow"), btn = $("fortuneBtn"), q = $("fortuneQ"), heard = $("fortuneHeard");
    const data = $("fortuneData"), last = $("fortuneLast");
    let open = false, ready = false, wantOpen = false, btnTimer = 0, still = false, label = "🔮 Fortune";
    function refuse(out) {
      msg(null, out.status === 409 && out.why === "visit open" ? "refused: finish the visit first (or Force a house)"
        : out.status === 503 ? "refused: the fortune is off" : out.status === 0 ? "no connection"
        : out.busy || out.status === 409 ? "refused: the hat is busy" : "refused: " + (out.error || out.status), 6000);
    }
    async function tap(action, value) {
      const out = await post("/fortune", { action, value: value || "" });
      if (!out.ok) refuse(out);
      return !!out.ok;
    }
    function paint() {
      btn.disabled = open || wantOpen || !ready;
      btn.classList.toggle("dim", !ready);
      btn.textContent = label + (ready ? "" : " · rendering…");
      btn.title = !ready ? "its lines are still rendering: wait" : open ? "a fortune is open" : "";
    }
    function draw(f, v) {
      open = !!f.open;
      if (open && wantOpen) { wantOpen = false; clearTimeout(btnTimer); }
      row.hidden = !open;
      const who = f.first ? " · " + f.first : "";
      if (open) {
        q.textContent = f.stage === "reading" ? "Reading the future…" + who
          : "Question " + f.q + " of " + f.of + " · " + (QUESTION_EN[f.qid] || f.qid || "") + (f.tries ? " (asked again)" : "") + who;
        heard.textContent = f.heard ? "heard: " + f.heard : "";
        const d = f.data || {};
        fill(data, Object.keys(DATA_EN).filter((k) => d[k] !== undefined && d[k] !== null && d[k] !== "").map((k) => {
          const c = el("span", "datum", d[k]); c.title = DATA_EN[k]; return c;
        }));
        $("visitState").textContent = (f.stage === "reading" ? "fortune: reading" : "fortune: question " + f.q + " of " + f.of) + who;
      }
      label = "🔮 Fortune" + (v && v.stage > v.of && v.first ? " for " + v.first : "");
      const l = f.last || {};
      const got = Object.values(l.data || {}).filter((x) => x !== null && x !== "");
      last.textContent = l.n ? "last fortune: " + (got.length ? got.join(" · ") : "nothing heard") + (l.mode ? " (" + (l.mode === "llm" ? "model" : l.mode) + ")" : "") : "";
      paint();
    }
    function view(f, v) {
      if (still) return;
      if (f === undefined) f = S.fortune;          // an event without the key: the last view stays
      if (!f) return;
      S.fortune = f;
      draw(f, v);
    }
    btn.addEventListener("click", async () => {
      if (btn.disabled || reader.busy()) return;
      visitRow.flush();
      wantOpen = true; paint();
      msg(null, "calling the hat…", 3000);
      const out = await post("/fortune", { action: "start", value: reader.name().slice(0, 20) });
      if (out.ok) {
        $("heardLine").textContent = ""; $("saidLine").textContent = "";
        btnTimer = setTimeout(() => { wantOpen = false; paint(); }, 3000);   // or the open view, sooner
        showTab("visit");
        return;
      }
      wantOpen = false; paint();
      refuse(out);
    });
    $("fortuneSkip").addEventListener("click", () => tap("skip"));
    $("fortuneEnd").addEventListener("click", () => tap("end"));
    // ?fortune=<1..6>: a still at that question (6 = the reading), for screenshots.
    const STILL_Q = Number(PARAMS.get("fortune")) || 0;
    if (STILL_Q) {
      still = true;
      btn.hidden = false;
      const qids = Object.keys(QUESTION_EN), of = qids.length, at = Math.min(STILL_Q, of);
      const all = { signo: "Escorpio", elemento: "agua", numero: "6", sueno: "dientes", carta: "La Muerte",
                    taza: "una estrella", animal: "el gato negro", luna: "llena", palabra: "Zumbalí" };
      const have = [0, 3, 4, 5, 6, 9][Math.min(STILL_Q, 6) - 1];
      const f = { on: true, ready: true, open: true, deck: "tarot", cup: true, place: "fiesta", last: null, n: 1,
                  stage: STILL_Q > of ? "reading" : "ask", q: at, of, qid: qids[at - 1], tries: STILL_Q === 2 ? 1 : 0,
                  question: "", heard: STILL_Q > 1 ? "veintitrés de octubre" : "", first: "Ana", house: "Ravenclaw",
                  data: Object.fromEntries(Object.entries(all).slice(0, have)) };
      S.fortune = f; ready = true;
      draw(f, { n: 1, stage: 5, of: 4, first: "Ana", house: "Ravenclaw" });
      if (f.stage === "reading") fish.foresee(f.data.signo);
    }
    return {
      status(page, tab) {
        if (still) return;
        btn.hidden = !page.fortune_enabled;
        const ft = tab && tab.fortune;
        ready = !!ft && (typeof ft.ready === "boolean" ? ft.ready : typeof ft.ready === "number" && !(ft.lines && ft.ready < ft.lines));
        paint();
      },
      view,
    };
  }, { status() {}, view() {} });

  // ---- the phone's microphone: off unless he turns it on (the Voice tab) --------------------------
  // On: the permission prompt (inside the tap), then the board is told to take recordings from
  // phones (switch mic=browser) and this page announces itself (/micstate) while its stream is
  // live, so a remote's press is relayed here only when this page can hear it. A hold then
  // records here: a 600 ms ring keeps the first syllable, the AudioWorklet (/rec.js) hands the
  // chunks over, and the clip goes up as a 16 kHz WAV (POST /utterance). Off, or the screen
  // sleeping, gives the board its microphone back.
  const phoneMic = guard("phone mic", () => {
    const tick = $("phoneMic"), note = $("phoneMicMsg");
    const CAN = window.isSecureContext && !!navigator.mediaDevices && !!navigator.mediaDevices.getUserMedia;
    const TARGET_RATE = 16000, RING_MS = 600, TAIL_MS = 250, MIN_HOLD_MS = 350, QUIET_RMS = 0.003, KEEPALIVE_MS = 20000;
    // The silence end (page.silence_end_s, 0 = off): a hold with nothing at or above
    // page.quiet_rms for that long, from the start or from the last sound, ends as the limit
    // does (the holdTimer path); the upload says how it ended (X-Fish-End).
    let maxRecordS = 15, silenceEndS = 0, quietRms = 0.04, quietSince = 0, ending = false, endedBy = "release";
    let stream = null, actx = null, node = null, source = null, sink = null;
    let ring = [], ringLen = 0, clip = null, clipLen = 0, holdAt = 0, holdTimer = null, tailTimer = null;
    let holding = false, peak = 0, lastEmit = 0, announced = false, keepTimer = null, busy = false;
    function say(text, cls) { note.textContent = text || ""; note.className = "note " + (cls || ""); }
    function micState(ready, beacon) {
      announced = ready;
      const body = JSON.stringify({ ready, page: PAGE });
      if (beacon && navigator.sendBeacon) {
        const url = "/micstate" + (TOKEN ? "?token=" + encodeURIComponent(TOKEN) : "");
        if (navigator.sendBeacon(url, new Blob([body], { type: "application/json" }))) return Promise.resolve();
      }
      return fetch("/micstate", { method: "POST", headers: headers(true), body, keepalive: true }).catch(() => {});
    }
    const streamLive = () => S.connected && performance.now() - lastMsgAt < 25000;
    function keepAlive() {
      clearInterval(keepTimer);
      keepTimer = setInterval(() => {
        if (actx && trackAlive() && streamLive()) micState(true);
        else if (announced) micState(false);     // a deaf page must not be relayed presses
      }, KEEPALIVE_MS);
    }
    function trackAlive() {
      const t = stream && stream.getAudioTracks()[0];
      return !!t && t.readyState === "live" && !t.muted;
    }
    function onChunk(data) {
      if (!data || !data.length) return;
      if (holding) {
        clip.push(data); clipLen += data.length;
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
        const rms = Math.sqrt(sum / data.length);
        if (rms > peak) peak = rms;
        const now = performance.now();
        if (now - lastEmit >= 40) { lastEmit = now; S.levels.push(rms); if (S.levels.length > 200) S.levels.shift(); wakeLevel(); }
        if (rms >= quietRms) quietSince = now;
        else if (silenceEndS > 0 && !ending && now - quietSince >= silenceEndS * 1000) endHold("silence");
      } else {
        ring.push(data); ringLen += data.length;
        const keep = (actx ? actx.sampleRate : 48000) * RING_MS / 1000;
        while (ring.length > 1 && ringLen - ring[0].length > keep) ringLen -= ring.shift().length;
      }
    }
    async function arm() {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      actx = new (window.AudioContext || window.webkitAudioContext)();
      if (actx.state === "suspended") { try { await actx.resume(); } catch (_) {} }
      source = actx.createMediaStreamSource(stream);
      sink = actx.createGain(); sink.gain.value = 0; sink.connect(actx.destination);
      try {
        await actx.audioWorklet.addModule("/rec.js");
        node = new AudioWorkletNode(actx, "fish-rec", { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1] });
        node.port.onmessage = (e) => onChunk(e.data);
      } catch (_) {
        node = actx.createScriptProcessor(4096, 1, 1);
        node.onaudioprocess = (e) => onChunk(new Float32Array(e.inputBuffer.getChannelData(0)));
      }
      source.connect(node).connect(sink);
      stream.getAudioTracks()[0].addEventListener("ended", () => off("the microphone was lost: turn it on again"));
      ring = []; ringLen = 0;
    }
    function release(beacon) {
      clearInterval(keepTimer); keepTimer = null;
      const done = announced ? micState(false, beacon) : Promise.resolve();
      if (stream) for (const t of stream.getTracks()) { try { t.stop(); } catch (_) {} }
      if (actx) { try { actx.close(); } catch (_) {} }
      stream = actx = node = source = sink = null;
      ring = []; ringLen = 0; holding = false;
      return done;
    }
    async function on() {
      if (!CAN) { tick.checked = false; say("needs the https address (see the band's 'secure' chip)", "bad-text"); return; }
      busy = true; say("asking for the microphone…");
      try { await arm(); }
      catch (e) { await release(); tick.checked = false; busy = false;
                  say(e && e.name === "NotAllowedError" ? "permission denied: Chrome's site settings → Microphone" : "no microphone: " + (e && e.name), "bad-text"); return; }
      const out = await post("/debug/set", { name: "mic", value: "browser" });
      if (!out.ok) { await release(); tick.checked = false; busy = false; say("refused: " + (out.error || out.status), "bad-text"); return; }
      await micState(true); keepAlive(); busy = false;
      say("on: the hold button and the remote record with this phone");
      refresh();
    }
    async function off(why) {
      busy = true;
      await release();
      await post("/debug/set", { name: "mic", value: switchValue("mic", "start") || "host" });   // back to how it started
      tick.checked = false; busy = false;
      say(why || "off: the board records", why ? "warn-text" : "");
      refresh();
    }
    tick.addEventListener("change", () => { if (busy) return; tick.checked ? on() : off(); });
    // The page itself ends the hold (the limit, the silence end): the button drops, then finish.
    function endHold(why) {
      if (!holding || ending) return;
      endedBy = why;
      ptt.event({ held: false });
      finish();
      if (why === "silence") msg(null, "phone mic: nothing heard for " + silenceEndS + " s, the clip is answered", 4000);
    }
    function finish() {
      if (!holding || ending) return;         // once per hold: a release after the page ended it
      ending = true;
      clearTimeout(holdTimer);
      const heldMs = Math.round(performance.now() - holdAt), ended = endedBy;
      tailTimer = setTimeout(() => {           // the last word is still in the pipeline
        holding = false; ending = false;
        const chunks = clip || [], total = clipLen;
        clip = null; clipLen = 0;
        if (heldMs < MIN_HOLD_MS) { msg(null, "phone mic: too short", 3000); return; }
        if (peak < QUIET_RMS) { msg(null, "phone mic: silence (is it the right microphone?)", 5000); return; }
        upload(toWav(chunks, total, actx ? actx.sampleRate : 48000), heldMs, ended);
        fish.thinking("hearing");
      }, TAIL_MS);
    }
    // Float32 chunks at the context's rate → one Int16 WAV at 16 kHz (linear interpolation).
    function toWav(chunks, total, rate) {
      const all = new Float32Array(total);
      let o = 0;
      for (const c of chunks) { all.set(c, o); o += c.length; }
      const ratio = rate / TARGET_RATE, n = Math.max(1, Math.floor(total / ratio)), pcm = new Int16Array(n);
      for (let i = 0; i < n; i++) {
        const pos = i * ratio, j = Math.floor(pos), frac = pos - j;
        const a = all[j] || 0, b = all[j + 1 < total ? j + 1 : j] || 0;
        let v = a + (b - a) * frac;
        v = Math.max(-1, Math.min(1, v));
        pcm[i] = v < 0 ? v * 32768 : v * 32767;
      }
      const bytes = pcm.length * 2, buf = new ArrayBuffer(44 + bytes), dv = new DataView(buf);
      const str = (at, t) => { for (let i = 0; i < t.length; i++) dv.setUint8(at + i, t.charCodeAt(i)); };
      str(0, "RIFF"); dv.setUint32(4, 36 + bytes, true); str(8, "WAVE");
      str(12, "fmt "); dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
      dv.setUint32(24, TARGET_RATE, true); dv.setUint32(28, TARGET_RATE * 2, true);
      dv.setUint16(32, 2, true); dv.setUint16(34, 16, true);
      str(36, "data"); dv.setUint32(40, bytes, true);
      new Int16Array(buf, 44).set(pcm);
      return new Blob([buf], { type: "audio/wav" });
    }
    async function upload(blob, heldMs, ended) {
      const h = headers(false);
      h["Content-Type"] = "audio/wav"; h["X-Fish-Hold-Ms"] = String(heldMs); h["X-Fish-End"] = ended || "release";
      try {
        const r = await fetch("/utterance", { method: "POST", headers: h, body: blob });
        if (!r.ok) msg(null, r.status === 409 ? "phone mic: the hat is busy" : "phone mic: refused " + r.status, 5000);
      } catch (_) { msg(null, "phone mic: no connection", 5000); }
    }
    return {
      status(page, d) {
        const mic = (d && d.mic) || {};
        if (page.max_record_s) maxRecordS = Number(page.max_record_s) || maxRecordS;
        if (page.silence_end_s !== undefined) silenceEndS = Math.max(0, Number(page.silence_end_s) || 0);
        if (page.quiet_rms) quietRms = Number(page.quiet_rms) || quietRms;
        if (!busy && !actx && mic.capture === "browser" && !note.textContent) say("the board takes phone recordings, but this phone's microphone is off");
      },
      ready: () => !!actx && trackAlive(),
      can: () => CAN,
      holding: () => holding,
      begin() {
        if (!actx) return;
        if (actx.state === "suspended") actx.resume().catch(() => {});
        clearTimeout(tailTimer);
        clip = ring.slice(); clipLen = ringLen; ring = []; ringLen = 0;   // the ring first: the first syllable
        peak = 0; holding = true; holdAt = performance.now(); lastEmit = 0;
        quietSince = holdAt; ending = false; endedBy = "release";
        fish.listening();
        holdTimer = setTimeout(() => endHold("limit"), maxRecordS * 1000);
      },
      end: finish,
      abort() { clearTimeout(holdTimer); clearTimeout(tailTimer); holding = false; ending = false; clip = null; clipLen = 0; },
      hidden() { if (actx) { release(true); tick.checked = false; say("released when the screen slept: turn it on again", "warn-text"); } },
      arm() { if (!tick.checked && !busy) { tick.checked = true; on(); } },   // the Hardware tap
    };
  }, { status() {}, ready: () => false, can: () => false, holding: () => false, begin() {}, end() {}, abort() {}, hidden() {}, arm() {} });

  // ---- coming back: the phone slept, the tab was hidden, the network returned ---------------------
  function onHidden() {
    ptt.releaseNow();
    visitRow.flush();
    phoneMic.hidden();
    if (es) { try { es.close(); } catch (_) {} es = null; }   // frees the board's place at once
    S.connected = false;
  }
  function resume() {
    if (document.hidden) return;
    refresh();
    wake.ask();
    if (!es || es.readyState === EventSource.CLOSED || performance.now() - lastMsgAt > 12000) connect();
  }
  document.addEventListener("visibilitychange", () => (document.hidden ? onHidden() : resume()));
  window.addEventListener("pageshow", resume);
  window.addEventListener("online", resume);
  window.addEventListener("pagehide", () => ptt.releaseNow());

  // ---- this phone's own facts, and two of its preferences ---------------------------------------
  function phoneFacts() {
    const st = getComputedStyle(document.documentElement);
    return [
      ["screen", innerWidth + " × " + innerHeight + " CSS px · DPR " + (devicePixelRatio || 1).toFixed(2)],
      ["secure context", window.isSecureContext ? "yes" : "NO: use https for the screen lock and the microphone", window.isSecureContext ? "" : "bad-text"],
      ["screen lock", wake.held() ? "held" : "not held"],
      ["stream", (S.connected ? "live" : "down") + (lastMsgAt ? " · last record " + Math.round((performance.now() - lastMsgAt) / 1000) + " s ago" : "")],
      ["page id", PAGE],
    ];
  }
  for (const [id, key, cls] of [["buzzTick", "fishBuzz", null], ["stillTick", "fishStill", "still"]]) {
    try { const v = localStorage.getItem(key); if (v !== null) $(id).checked = v === "1"; } catch (_) {}
    const apply = () => { if (cls) document.body.classList.toggle(cls, $(id).checked); try { localStorage.setItem(key, $(id).checked ? "1" : "0"); } catch (_) {} };
    $(id).addEventListener("change", apply);
    apply();
  }

  // ---- tabs, arm, STOP ---------------------------------------------------------------------------
  // A tab names panels (data-panels) or, on a phone only, a whole column (data-col: turns, log).
  // A name a phone still holds from before (the Show tab) maps to today's; an unknown one falls
  // to the default without a second look-up.
  const TAB_ALIAS = { show: "status" };
  const defaultTab = () => (PHONE.matches ? "status" : "checks");
  function tabButton(name) {
    for (const b of $("tabs").children) if (b.dataset.tab === name && (PHONE.matches || !b.dataset.col)) return b;
    return null;
  }
  function showTab(name) {
    name = TAB_ALIAS[name] || name;
    const target = tabButton(name) || tabButton(defaultTab());
    if (!target) return;
    name = target.dataset.tab;
    for (const b of $("tabs").children) b.classList.toggle("on", b === target);
    document.body.dataset.col = target.dataset.col || "colPanels";
    if (target.dataset.panels) {
      const panels = target.dataset.panels.split(" ");
      for (const p of $("panels").children) p.hidden = !panels.includes(p.id.slice(2));
      $("panels").scrollTop = 0;
    }
    try { localStorage.setItem("fishDebugTab", name); } catch (_) {}
    mark("all");
  }
  $("tabs").addEventListener("click", (e) => { const b = e.target.closest("[data-tab]"); if (b) showTab(b.dataset.tab); });
  // On a phone the hat and the tabs sit above the columns (only one column shows at a time) and
  // the pipeline goes to the top of the turns; on a desktop everything is where it was.
  function place() {
    if (PHONE.matches) {
      $("phoneTop").append($("fishBox"), $("tabs"));
      $("colTurns").prepend($("pipe"));
    } else {
      $("colTurns").prepend($("fishBox"));
      $("colPanels").prepend($("tabs"));
      document.querySelector("main").before($("pipe"));
    }
  }
  place();
  const storedTab = () => { try { return localStorage.getItem("fishDebugTab") || ""; } catch (_) { return ""; } };
  PHONE.addEventListener("change", () => { place(); showTab(storedTab() || defaultTab()); });
  showTab(PARAMS.get("tab") || storedTab() || defaultTab());        // ?tab=<name> for a look or a still

  refresh().then(() => connect());
})();
