/* The desktop debug view (docs/debug.md).
 *
 * One store, one stream, one render pass per animation frame for the parts that changed.
 *   GET /debug/state        the slow state, every 5 s and after an action
 *   GET /debug/events       every record the fish keeps (log lines, keys, turns, lines sent,
 *                           the page's own events), replayed from the start on connect
 *   POST /debug/...         the tests, the arm, STOP
 * Text from the fish only ever enters the page through textContent.
 */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const CAP = { log: 3000, key: 300, turn: 200, tx: 400, act: 120 };
  const SLOW = { stt: 3, llm: 5, tts: 2 };              // seconds: a stage slower than this is flagged (estimates)

  // ---- token: as the phone page does (out of the address bar, kept for this tab) ----------
  const PARAMS = new URLSearchParams(location.search);
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
              llm: [], stt: [], tts: [], vision: [], modelOnly: null, helloSeq: 0, caughtUp: false, openCalls: new Set(), seenCall: 0,
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
  // Which tab explains a part of the fish (hints and chips name the old panel).
  const TAB_OF = { checks: "checks", inputs: "live", motors: "live", model: "model", cloud: "model",
                   voice: "voice", switches: "switches", board: "system", config: "system", clients: "system" };

  // ---- the stream ------------------------------------------------------------------------------
  let es = null, lastMsgAt = 0;
  function connect() {
    if (es) { try { es.close(); } catch (_) {} }
    const q = new URLSearchParams();
    if (TOKEN) q.set("token", TOKEN);
    if (S.boot && S.lastSeq) q.set("since", S.boot + "-" + S.lastSeq);
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
    if (!es || es.readyState === EventSource.CLOSED || performance.now() - lastMsgAt > 25000) connect();
  }, 5000);

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
        S.llm = []; S.stt = []; S.tts = []; S.vision = []; S.modelOnly = null; S.openCalls.clear();
        mark("all");
      }
      S.boot = r.boot;
      S.helloSeq = r.seq || 0;                     // what existed when this stream opened
      S.caughtUp = false;
      return;
    }
    if (r.seq) {
      if (r.seq <= S.lastSeq) return;            // already have it (a replay after a reconnect)
      if (S.lastSeq && r.seq > S.lastSeq + 1 && r.seq - S.lastSeq < 100000) S.missed += r.seq - S.lastSeq - 1;
      S.lastSeq = Math.max(S.lastSeq, r.seq);
    }
    switch (r.kind) {
      case "log": push(S.log, r, CAP.log); mark("log"); break;
      case "key": push(S.keys, r, CAP.key); mark("keys"); break;
      case "press": S.presses[r.dev + "|" + r.key] = r; mark("keys"); break;
      case "turn": push(S.turns, r, CAP.turn); S.live = ""; mark("turns", "pipe"); soon(); break;
      case "perf": S.perf = r; mark("motors"); break;
      case "tx": push(S.tx, r, CAP.tx); if (S.caughtUp) fish.line(r); mark("tx"); break;
      case "level": S.levels.push(r.rms); if (S.levels.length > 200) S.levels.shift();
                    S.live = "recording"; mark("pipe"); wakeLevel(); break;
      case "action": case "http": push(S.acts, r, CAP.act); mark("clients"); break;
      case "llm": case "stt": case "tts": case "vision": push(S[r.kind], r, 50); mark("model"); break;
      case "visitor":                              // a reading started: the earlier visitor's records go
        S.llm = []; S.stt = []; S.tts = []; S.vision = []; S.modelOnly = null; S.openCalls.clear();
        mark("model"); break;
      case "page": {
        const ev = r.ev || {};
        if (ev.type === "listen") S.live = ev.ready ? "waiting" : (S.live === "recording" ? "thinking" : S.live);
        else if (ev.type === "stt" && ev.role === "user") S.live = "thinking";
        else if (ev.type === "speak") { if (S.caughtUp) fish.speak(ev); S.live = "speaking"; setTimeout(() => { if (S.live === "speaking") { S.live = "waiting"; mark("pipe"); } }, (ev.duration_ms || 0) + 300); }
        mark("pipe");
        break;
      }
    }
  }

  // ---- the fish: the sprite follows the reply, the lamps the lines really sent ----------------
  // The same rules as the phone page (fish.js): one whole-fish PNG per (neck, mouth, tail);
  // the mouth is the reply's loudness track through a critically damped spring; a NECK line
  // with one direction holds or returns the head, a chain is a passing window; TAIL flaps.
  const fish = (() => {
    const cv = $("fish"), ctx = cv.getContext("2d");
    const imgs = new Map();
    const name = (n, m, t) => "neck" + (n ? "Out" : "Rest") + "_mouth" + m + "_tail" + (t ? "Flap" : "Rest") + ".png";
    for (let n = 0; n < 2; n++) for (let m = 0; m < 4; m++) for (let t = 0; t < 2; t++) {
      const im = new Image();
      im.onload = () => { imgs.set(name(n, m, t), im); wake(); };
      im.src = "/img/" + name(n, m, t);
    }
    const mouth = { value: 0, vel: 0 };
    let track = null, clock0 = 0, trackEnd = 0, windows = [], neck = [], running = false, last = 0;
    function speak(ev) {
      const age = Math.max(0, Number(ev.age_ms) || 0), now = performance.now();
      if (Array.isArray(ev.mouth) && ev.mouth.length && age <= ev.mouth[ev.mouth.length - 1][0]) {
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
    function frame(now) {
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      const f = -104 * (mouth.value - level(now)) - 20 * mouth.vel;
      mouth.vel += f * dt; mouth.value = Math.max(0, Math.min(1, mouth.value + mouth.vel * dt));
      windows = windows.filter((w) => now < w.end + 50);
      const m = Math.round(mouth.value * 3), n = neckOut(now) ? 1 : 0, t = active("TAIL", now) ? 1 : 0;
      const im = imgs.get(name(n, m, t)) || imgs.get(name(0, m, 0)) || imgs.get(name(0, 0, 0));
      ctx.clearRect(0, 0, cv.width, cv.height);
      if (im) ctx.drawImage(im, 0, 0, cv.width, cv.height);
      const busy = track || mouth.value > 0.01 || windows.length || neck.some((e) => e.start > now);
      if (busy) requestAnimationFrame(frame); else running = false;   // asleep when nothing moves
    }
    function wake() { if (!running) { running = true; last = performance.now(); requestAnimationFrame(frame); } }

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
    function state() {
      const st = S.state || {}, mode = st.mode || {};
      const word = !S.connected ? "offline" : track ? "speaking" : S.live || (mode.speaking ? "speaking" : mode.recording ? "recording" : mode.listening ? "waiting" : "busy");
      const box = $("fishState");
      box.textContent = word + (word === "waiting" ? " for a press" : "…");
      box.className = word;
      $("lampMouth").parentElement.classList.toggle("muted", !!(st.link || {}).muted);
      if ((st.link || {}).muted) $("lastLine").textContent = "MOTORS MUTED: lines are dropped";
    }
    return { speak, line, state };
  })();

  // ---- the slow state --------------------------------------------------------------------------
  let stateTimer = null;
  async function refresh() {
    try {
      const r = await api("/debug/state");
      if (r.status === 403) { $("tokenGate").hidden = false; return; }
      if (!r.ok) throw new Error(r.status);
      S.state = await r.json();
      S.stateAt = performance.now();
      $("tokenGate").hidden = true;
      const armed = (S.state.mode || {}).armed_s || 0;
      setArmed(armed);
    } catch (_) { S.state = S.state || null; S.stateAt = 0; }
    mark("bar", "hints", "panels");
  }
  function soon() { clearTimeout(stateTimer); stateTimer = setTimeout(refresh, 400); }
  setInterval(refresh, 5000);
  async function checkToken() {
    try { if ((await api("/debug/state")).status === 403) $("tokenGate").hidden = false; } catch (_) {}
  }
  $("tokenBtn").addEventListener("click", () => {
    TOKEN = $("tokenInput").value.trim();
    try { sessionStorage.setItem("fishToken", TOKEN); } catch (_) {}
    refresh(); connect();
  });

  // ---- render ----------------------------------------------------------------------------------
  function render() {
    const now = new Set(dirty);                  // what changed, taken before the set is emptied
    dirty.clear();
    const all = now.has("all");
    const d = (n) => all || now.has(n);
    const run = (fn) => { try { fn(); } catch (e) { console.error(fn.name, e); } };   // one panel never stops the others
    if (d("bar")) run(renderBar);
    if (d("bar") || d("pipe") || d("panels")) run(fish.state);
    if (d("hints")) run(renderHints);
    if (d("pipe") || d("turns")) run(renderPipe);
    if (d("turns")) run(renderTurns);
    if (d("log")) run(renderLog);
    if (d("panels") || d("keys")) run(renderInputs);
    if (d("panels") || d("motors") || d("tx")) run(renderMotors);
    if (d("panels")) { run(renderVoice); run(renderCloud); run(renderBoard); run(renderConfig); run(renderChecks); run(renderSwitches); }
    if (d("panels") || d("model")) run(renderModel);
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
    if (be.capture === "browser") badges.push("MIC=browser");
    if (!st.token) badges.push("no token");
    if ((st.version || {}).changed_since_start) badges.push("code changed: restart");
    fill($("hBadges"), badges.map((b) => el("span", "badge", b)));

    const link = st.link || {}, remote = st.remote || {}, rec = st.rec || {}, sys = st.system || {};
    const t = lastTurn() || {}, times = t.times || {};
    const chips = [];
    const health = link.health || "?";
    chips.push(chip((health === "ok" ? "● " : "■ ") + "LINK " + (link.mock ? "mock" : health),
                    health === "ok" ? "ok" : "bad", link.desc, "live"));
    chips.push(chip((be.online === false ? "■ NET offline" : "● NET"), be.online === false ? "bad" : "ok", "internet", "model"));
    const other = Object.keys(remote.other_keys || {}).length;
    if (remote.present) {
      const n = (remote.devices || []).length;
      chips.push(chip((n ? (other ? "▲ " : "● ") : "■ ") + "TRIG" + (n ? "" : " none") + (other ? " other key" : ""),
                      !n ? "bad" : other ? "warn" : "ok", remote.keys, "live"));
    } else chips.push(chip("○ TRIG " + (be.ptt || "page"), "unknown", "", "live"));
    const zeros = rec && rec.zero_frac > 0.95, quiet = rec && rec.rms !== undefined && rec.rms < 0.005;
    chips.push(chip(rec && rec.samples ? (zeros ? "■ MIC zeros" : quiet ? "▲ MIC silent" : "● MIC")
                    : "○ MIC", !rec || !rec.samples ? "unknown" : zeros ? "bad" : quiet ? "warn" : "ok", "the last recording", "live"));
    for (const k of ["stt", "llm", "tts"]) {
      const v = times[k], name = k === "llm" ? (be.echo ? "echo" : be.llm_profile) : be[k];
      chips.push(chip((v > SLOW[k] ? "▲ " : "● ") + k.toUpperCase() + " " + (name || "") + (v !== undefined ? " " + secs(v) + "s" : ""),
                      v > SLOW[k] ? "warn" : v !== undefined ? "ok" : "unknown", "last turn", k === "tts" ? "voice" : "model"));
    }
    const perf = S.perf || {};
    chips.push(chip(perf.result && perf.result !== "ok" ? "■ SPK " + perf.result : (be.player === "SilentPlayer" ? "○ SPK silent" : "● SPK"),
                    perf.result && perf.result !== "ok" ? "bad" : "ok", "playback", "voice"));
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
                 "read: no signal": 3 };
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
    kv($("trigFacts"), [
      ["trigger", be.ptt],
      ["configured keys", remote.keys, ""],
      ["devices read", remote.present ? (remote.devices || []).map((d) => d.path.replace("/dev/input/", "") + " '" + d.name + "'").join("\n") || "NONE" : "no remote configured (FISH_PTT_DEVICE)", remote.present && !(remote.devices || []).length ? "bad-text" : ""],
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
      ["capture", be.capture === "browser" ? "the phone's microphone (browser)" : "this machine's microphone (host)"],
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
    const be = (S.state || {}).backends || {}, llm = be.llm || {};
    kv($("cloudFacts"), [
      ["internet", be.online === false ? "OFFLINE" : "online", be.online === false ? "bad-text" : ""],
      ["keys", Object.entries(be.keys || {}).map(([k, ok]) => k + (ok ? " present" : " MISSING")).join("\n")],
      ["speech-to-text", be.stt],
      ["LLM", be.echo ? "echo (no model called)" : be.llm_profile + " : " + be.llm_model],
      ["last LLM call", llm.last_s !== undefined && llm.last_s !== null ? secs(llm.last_s) + " s" : ""],
      ["last LLM error", llm.last_error || "none", llm.last_error ? "bad-text" : ""],
      ["history", llm.history !== undefined ? llm.history + " messages" : ""],
      ["text-to-speech", be.tts],
    ]);
  }
  function renderBoard() {
    const st = S.state || {}, sys = st.system || {}, svc = st.service || {}, mem = sys.mem_mb || {};
    kv($("boardFacts"), [
      ["temperature", (sys.thermal || []).map((z) => z.name + " " + z.c + " C").join("\n") || "n/a on this machine"],
      ["load (1, 5, 15 min)", (sys.load || []).join("  ") + "  on " + (sys.cores || "?") + " cores"],
      ["memory", mem.total ? mem.available + " MB free of " + mem.total : ""],
      ["disk", sys.disk_free_mb !== undefined ? sys.disk_free_mb + " MB free" : ""],
      ["machine up", sys.uptime_s ? ago(sys.uptime_s) : ""],
      ["Wi-Fi link", (sys.wifi || []).map((w) => w.dev + " " + w.link + "/70").join("  ") || "n/a"],
      ["USB role", sys.usb_role || "n/a on this machine", sys.usb_role && !sys.usb_role.includes("[host]") ? "bad-text" : ""],
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
    const c = (S.state || {}).clients || {};
    kv($("clientFacts"), [
      ["phone pages connected", (c.pages ?? "?") + " of " + (c.max ?? 8)],
      ["pages with their microphone ready", c.mic_pages ?? 0],
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
    fill($("visionRows"), pick(S.vision).map((r) => {
      const tr = el("tr");
      tr.appendChild(el("td", "dim", clockMs(r.t)));
      tr.appendChild(el("td", "", secs(r.seconds)));
      tr.appendChild(el("td", "", r.tokens ?? ""));
      tr.appendChild(el("td", r.error || !r.found ? "bad wrap" : "wrap", r.error ? r.error.type + ": " + r.error.text
        : r.found ? r.name + " (says: " + r.name_for_speech + ", " + r.confidence + ")" + (r.look ? " · look: " + r.look : "") : "not found"));
      tr.appendChild(el("td", "dim wrap", r.ask));
      return tr;
    }));
    $("badgePrompt").textContent = mo.badge_prompt || "";
  }
  $("modelClear").addEventListener("click", () => { S.modelOnly = null; mark("model"); });

  // ---- tabs, arm, STOP ---------------------------------------------------------------------------
  function showTab(name) {
    let panels = null;
    for (const b of $("tabs").children) {
      const on = b.dataset.tab === name;
      b.classList.toggle("on", on);
      if (on) panels = b.dataset.panels.split(" ");
    }
    if (!panels) return showTab("checks");
    for (const p of $("panels").children) p.hidden = !panels.includes(p.id.slice(2));
    $("panels").scrollTop = 0;
    try { localStorage.setItem("fishDebugTab", name); } catch (_) {}
  }
  $("tabs").addEventListener("click", (e) => { if (e.target.dataset && e.target.dataset.tab) showTab(e.target.dataset.tab); });
  try { showTab(localStorage.getItem("fishDebugTab") || "checks"); } catch (_) { showTab("checks"); }

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
      document.title = (left ? "ARMED · " : "") + "fish · debug";
      if (!left) { clearInterval(armTick); document.body.classList.remove("armed"); mark("panels"); }
    };
    paint();
    if (on) armTick = setInterval(paint, 500);
    mark("panels");
  }
  $("armBtn").addEventListener("click", async () => {
    const out = await post("/debug/arm", { on: !(performance.now() < S.armedUntil) });
    if (out.ok) setArmed(out.armed_s || 0);
  });
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

  refresh();
  connect();
})();
