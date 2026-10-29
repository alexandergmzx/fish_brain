"""What fish.js expects of index.html, read from the two files. No browser, no server."""
import re

import pytest

from fish_brain.viz import WEB_DIR


def test_every_id_fish_js_looks_up_exists_in_index_html():
    js = (WEB_DIR / "fish.js").read_text(encoding="utf-8")
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    wanted = set(re.findall(r'(?:getElementById|\bel)\(\s*"([\w-]+)"', js))
    have = set(re.findall(r'\bid="([\w-]+)"', html))
    assert len(wanted) > 20                  # the pattern still finds the lookups
    assert sorted(wanted - have) == []


def test_the_page_animates_only_transform_and_opacity():
    """The lightness rule of docs/viz.md: nothing else is animated or transitioned."""
    css = (WEB_DIR / "fish.css").read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@font-face\s*\{.*?\}", "", css, flags=re.S)
    allowed = {"transform", "opacity"}
    frames = re.findall(r"@keyframes\s+([\w-]+)\s*\{((?:[^{}]*\{[^{}]*\})*)\s*\}", css)
    assert len(frames) > 10                  # the pattern still finds them
    for name, body in frames:
        props = set(re.findall(r"([\w-]+)\s*:", re.sub(r"[^{}]*\{", "{", body)))
        assert props <= allowed, (name, props - allowed)
    for value in re.findall(r"transition\s*:\s*([^;}]+)", css):
        for part in value.split(","):
            assert part.split()[0] in allowed | {"none"}, value
    assert not re.findall(r"transition-property\s*:", css)


# --- the debug page keeps the same promises ---

def test_every_id_debug_js_looks_up_exists_in_debug_html():
    js = (WEB_DIR / "debug.js").read_text(encoding="utf-8")
    html = (WEB_DIR / "debug.html").read_text(encoding="utf-8")
    wanted = set(re.findall(r'\$\("([\w-]+)"\)', js))
    have = set(re.findall(r'\bid="([\w-]+)"', html))
    assert len(wanted) > 40
    assert sorted(wanted - have) == []
    # every panel belongs to exactly one tab, and every tab's panels exist
    in_tabs = [p for group in re.findall(r'data-panels="([\w ]+)"', html) for p in group.split()]
    assert sorted(in_tabs) == sorted(m[2:] for m in re.findall(r'id="(p-\w+)"', html))


def test_debug_page_takes_text_only_as_text_and_calls_only_routed_paths():
    js = (WEB_DIR / "debug.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js
    assert not re.findall(r"https?://", js)
    viz = (WEB_DIR.parent / "viz.py").read_text(encoding="utf-8")
    actions = (WEB_DIR.parent / "debug_actions.py").read_text(encoding="utf-8")
    for path in set(re.findall(r'"(/debug/[\w./]+)"', js)):
        assert f'"{path}"' in viz or f'"{path}"' in actions, path


@pytest.mark.parametrize("name, least", [("debug.css", 4), ("scene.css", 2)])
def test_debug_css_animates_only_transform_and_opacity(name, least):
    css = re.sub(r"/\*.*?\*/", "", (WEB_DIR / name).read_text(encoding="utf-8"), flags=re.S)
    css = re.sub(r"@font-face\s*\{.*?\}", "", css, flags=re.S)
    allowed = {"transform", "opacity"}
    frames = re.findall(r"@keyframes\s+([\w-]+)\s*\{((?:[^{}]*\{[^{}]*\})*)\s*\}", css)
    assert len(frames) >= least
    for name, body in frames:
        props = set(re.findall(r"([\w-]+)\s*:", re.sub(r"[^{}]*\{", "{", body)))
        assert props <= allowed, (name, props - allowed)
    for value in re.findall(r"transition\s*:\s*([^;}]+)", css):
        for part in value.split(","):
            assert part.split()[0] in allowed | {"none"}, value


def test_the_page_speaks_of_the_hat_not_the_fish():

    for name in ("index.html", "fish.js", "wait.html"):
        text = (WEB_DIR / name).read_text(encoding="utf-8")
        assert not re.search(r"\bpez\b", text, re.I), name
    assert "Coloca PNGs" not in (WEB_DIR / "fish.js").read_text(encoding="utf-8")


# --- the hat's visit row ---

def test_the_visit_chips_are_the_cues_the_host_takes():
    from fish_brain.visit import CUE_CHOICES, CUE_TEXT, CUE_TEXT_MAX
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    pairs = set()
    for tag in re.findall(r"<button[^>]*\bclass=\"chip\"[^>]*>", html):
        cue = re.search(r'data-cue="([^"]+)"', tag).group(1)
        val = re.search(r'data-val="([^"]+)"', tag).group(1)
        pairs.add((cue, val))
    assert pairs == {(k, v) for k, vals in CUE_CHOICES.items() for v in vals}
    inputs = re.findall(r"<input[^>]*\bdata-cue=\"([^\"]+)\"[^>]*>", html)
    assert sorted(inputs) == sorted(CUE_TEXT)
    for tag in re.findall(r"<input[^>]*\bdata-cue=[^>]*>", html):
        assert int(re.search(r'maxlength="(\d+)"', tag).group(1)) <= CUE_TEXT_MAX


def test_the_visit_row_is_hidden_and_in_the_sheet():
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    start, end = html.index('class="controls"'), html.index('id="talkParts"')
    tag = re.search(r'<div[^>]*id="cVisit"[^>]*>', html)
    assert start < tag.start() < end and " hidden" in tag.group(0)


def test_every_path_the_page_posts_to_is_routed():
    js = (WEB_DIR / "fish.js").read_text(encoding="utf-8")
    viz = (WEB_DIR.parent / "viz.py").read_text(encoding="utf-8")
    paths = set(re.findall(r'fetch\(\s*"(/[\w/]+)"', js))
    assert {"/visit", "/cues"} <= paths
    for path in paths:
        assert f'"{path}"' in viz, path


# --- the operator's page (debug.html/debug.js, ADR 0011) ---

def test_every_id_the_operator_page_looks_up_any_way_exists():
    js = (WEB_DIR / "debug.js").read_text(encoding="utf-8")
    html = (WEB_DIR / "debug.html").read_text(encoding="utf-8")
    wanted = set(re.findall(r'(?:\$|getElementById)\(\s*"([\w-]+)"\s*\)', js))
    wanted |= set(re.findall(r'querySelector\(\s*"#([\w-]+)"', js))
    have = set(re.findall(r'\bid="([\w-]+)"', html))
    assert {"hatBox", "pttButton", "visitNew", "cVisit", "fortuneBtn", "fortuneRow", "readName"} <= wanted
    assert sorted(wanted - have) == []
    for tab in re.findall(r'data-col="([\w-]+)"', html):
        assert f'id="{tab}"' in html, tab


def test_every_path_the_operator_page_calls_is_routed():
    js = (WEB_DIR / "debug.js").read_text(encoding="utf-8")
    viz = (WEB_DIR.parent / "viz.py").read_text(encoding="utf-8")
    actions = (WEB_DIR.parent / "debug_actions.py").read_text(encoding="utf-8")
    paths = set(re.findall(r'(?:post|api|fetch|sendBeacon|addModule|EventSource)\(\s*"(/[\w./]+)"', js))
    assert {"/visit", "/cues", "/show", "/fortune", "/ptt", "/reading", "/speak", "/wait", "/debug/state"} <= paths
    for path in paths:
        assert f'"{path}"' in viz or f'"{path}"' in actions, path


# --- the three tabs of the phone (Visit · Status · Settings) and the two acts ---

def _panel(html: str, pid: str) -> str:
    """The HTML of one panel: from its opening tag to the next panel's (or the end of #panels)."""
    start = html.index(f'id="p-{pid}"')
    nxt = re.search(r'<div class="panel"', html[start + 1:])
    return html[start:start + 1 + nxt.start()] if nxt else html[start:html.index('</section>', start)]


def test_the_nav_begins_visit_status_settings_and_each_control_sits_in_its_panel():
    html = (WEB_DIR / "debug.html").read_text(encoding="utf-8")
    tabs = re.findall(r'<button data-tab="(\w+)" data-panels="([\w ]+)"', html)
    assert tabs[:3] == [("visit", "visit"), ("status", "status"), ("setup", "setup")]
    status, setup, visit = _panel(html, "status"), _panel(html, "setup"), _panel(html, "visit")
    for needle in ('id="showSummary"', 'id="goRows"'):
        assert needle in status and needle not in setup and needle not in visit
    for needle in ('data-mode="auto"', 'data-hw="speaker"', 'id="volSlider"', 'data-net="ap"', 'id="spkBtn"',
                   'id="setupMsg"'):
        assert needle in setup and needle not in status and needle not in visit, needle
    for needle in ('id="fortuneRow"', 'id="fortuneBtn"', 'id="showRow"', 'id="cVisit"', 'id="cRead"', 'id="readName"',
                   'data-place="casa"', 'data-place="otro"', 'id="placeText"', 'data-fortune="deck"', 'id="cupBtn"',
                   'id="actMsg"'):
        assert needle in visit and needle not in status and needle not in setup, needle
    # the Visit panel's order: the fortune row, the show row, the fortune button, the cues, the name,
    # then the place and the fortune's extras below the acts
    order = [visit.index(x) for x in ('id="fortuneRow"', 'id="showRow"', 'id="fortuneBtn"', 'id="cVisit"', 'id="cRead"',
                                      'data-place="casa"', 'data-fortune="deck"', 'id="cupBtn"', 'id="actMsg"')]
    assert order == sorted(order)
    # the place's and the deck's choices are the host's values; the lotería button has none
    assert set(re.findall(r'data-place="(\w+)"', visit)) == {"casa", "fiesta", "universidad", "otro"}
    assert set(re.findall(r'data-fortune="deck" data-val="(\w+)"', visit)) == {"tarot", "off"}
    loteria = re.search(r"<button[^>]*>Lotería \(later\)</button>", visit).group(0)
    assert "disabled" in loteria and "data-val" not in loteria
    assert "restart" in setup                 # the note: a restart reverts them
    # the place's and the fortune's refusals are written under them on the Visit tab
    js = (WEB_DIR / "debug.js").read_text(encoding="utf-8")
    tap = js[js.index("async function setFromTap("):]
    tap = tap[:tap.index("\n  }\n")]
    assert '$("actMsg")' in tap and '$("setupMsg")' not in tap


def test_every_tab_alias_and_default_is_a_tab():
    js = (WEB_DIR / "debug.js").read_text(encoding="utf-8")
    html = (WEB_DIR / "debug.html").read_text(encoding="utf-8")
    tabs = set(re.findall(r'data-tab="(\w+)"', html))
    alias = re.search(r"TAB_ALIAS = \{([^}]*)\}", js).group(1)
    names = set(re.findall(r'"(\w+)"', alias))
    default = re.search(r'defaultTab = \(\) => \(PHONE\.matches \? "(\w+)" : "(\w+)"\)', js)
    assert default, "the default tab must be a plain pair, not a second showTab()"
    names |= set(default.groups())
    assert names and names <= tabs, names - tabs
    assert "show" not in tabs and "show" in alias           # his phone still holds the old name
    assert not re.search(r"\n\s*if \(!target\) return showTab\(", js)   # the recursion of before


def test_the_cue_chips_read_english_and_send_the_spanish_values():
    from fish_brain.visit import CUE_CHOICES
    html = (WEB_DIR / "debug.html").read_text(encoding="utf-8")
    panel = html[html.index('id="p-visit"'):html.index('id="cRead"')]
    chips = re.findall(r'<button[^>]*\bclass="cue"[^>]*data-val="([^"]+)"[^>]*>([^<]+)</button>', panel)
    assert {v for v, _ in chips} == {v for vals in CUE_CHOICES.values() for v in vals}
    for val, label in chips:
        assert label != val and re.fullmatch(r"[A-Za-z ]+", label), (val, label)
    for group in re.findall(r'<div class="cue-group" role="group" aria-label="([^"]+)"><span>([^<]+)</span>', panel):
        assert group[0] == group[1] and re.fullmatch(r"[A-Za-z ]+", group[0]), group
    for tag in re.findall(r'<input[^>]*\bdata-cue=[^>]*>', panel):
        assert re.search(r'placeholder="[A-Za-z][^"]*"', tag), tag
    # the fortune row's chips are not cues: the host would take them as such
    assert 'class="cue"' not in _panel(html, "visit")[:html.index('id="cVisit"') - html.index('id="p-visit"')]


def test_the_badge_is_off_the_page():
    html = (WEB_DIR / "debug.html").read_text(encoding="utf-8")
    js = (WEB_DIR / "debug.js").read_text(encoding="utf-8")
    css = (WEB_DIR / "debug.css").read_text(encoding="utf-8")
    assert not re.findall(r'\bid="[^"]*badge', html), "no badge id"
    for gone in ("badgeBtn", "galleryBtn", "lookWrap", "lookTick", "badgeCam", "badgeFile", "visionRows", "badgePrompt"):
        assert gone not in html and gone not in js and gone not in css, gone
    assert '"/badge"' not in js and "toJpeg" not in js and "sendBadge" not in js
    assert "Badge photo" not in html and "Badge or name" not in html and "badge" not in html.lower().split("<main>")[1]


def test_the_fortune_row_posts_only_to_fortune_and_names_the_questions():
    js = (WEB_DIR / "debug.js").read_text(encoding="utf-8")
    block = js[js.index("const fortuneRow = guard("):js.index("const phoneMic = guard(")]
    assert set(re.findall(r'post\(\s*"(/[\w/]+)"', block)) == {"/fortune"}
    assert re.search(r'action: "start", value: reader\.name\(\)\.slice\(0, 20\)', block)
    for action in ("skip", "end"):
        assert f'tap("{action}")' in block
    assert "showTab(\"visit\")" in block
    # its refusals are explain()'s: a 503 names the fortune, a 409 with why "visit open" the visit
    assert 'explain(out, "the fortune")' in block
    assert '"visit open": "finish the visit first (or Force a house)"' in js
    qids = set(re.findall(r'(\w+): "[^"]+"', re.search(r"QUESTION_EN = \{([^}]*)\}", js).group(1)))
    assert qids == {"fecha", "sueno", "deseo", "carta", "taza"}
    data = set(re.findall(r'(\w+): "[^"]+"', re.search(r"DATA_EN = \{([^}]*)\}", js, re.S).group(1)))
    assert data == {"signo", "elemento", "numero", "sueno", "deseo", "carta", "taza", "luna", "palabra"}


def test_the_fortune_flourish_is_off_in_lite_and_still_and_reduced_motion():
    css = (WEB_DIR / "scene.css").read_text(encoding="utf-8")
    assert "@keyframes pulso" in css and re.search(r"\.reading \.vela \.halo \{ animation: pulso", css)
    assert "#hatBox.study.h-fortune { --house:" in css
    for guard in ("html.lite .study .vela .halo", "body.still .study .vela .halo"):
        assert guard in css, guard
    reduced = css[css.index("prefers-reduced-motion"):]
    assert ".vela .halo" in reduced.split("}")[0]


def test_the_visit_cues_on_the_operator_page_are_the_ones_the_host_takes():
    from fish_brain.visit import CUE_CHOICES, CUE_TEXT, CUE_TEXT_MAX
    html = (WEB_DIR / "debug.html").read_text(encoding="utf-8")
    panel = html[html.index('id="p-visit"'):html.index('id="cRead"')]
    pairs = {(re.search(r'data-cue="([^"]+)"', t).group(1), re.search(r'data-val="([^"]+)"', t).group(1))
             for t in re.findall(r'<button[^>]*\bclass="cue"[^>]*>', panel)}
    assert pairs == {(k, v) for k, vals in CUE_CHOICES.items() for v in vals}
    inputs = re.findall(r'<input[^>]*\bdata-cue="([^"]+)"[^>]*>', panel)
    assert sorted(inputs) == sorted(CUE_TEXT)
    for tag in re.findall(r"<input[^>]*\bdata-cue=[^>]*>", panel):
        assert int(re.search(r'maxlength="(\d+)"', tag).group(1)) <= CUE_TEXT_MAX
    assert re.search(r'<div[^>]*id="cVisit"[^>]*\bhidden', panel)


def test_the_operator_page_never_transitions_a_property_list():
    css = re.sub(r"/\*.*?\*/", "", (WEB_DIR / "debug.css").read_text(encoding="utf-8"), flags=re.S)
    assert not re.findall(r"transition-property\s*:", css)


def test_the_operator_page_links_the_scene_and_it_is_served():
    html = (WEB_DIR / "debug.html").read_text(encoding="utf-8")
    assert 'href="/scene.css"' in html and 'class="sign"' in html and 'class="banco"' in html
    assert '"/scene.css"' in (WEB_DIR.parent / "viz.py").read_text(encoding="utf-8")


def test_the_phone_microphone_ends_a_hold_on_silence_once():
    js = (WEB_DIR / "debug.js").read_text(encoding="utf-8")
    # The silence end and the limit share one path; the release after it is ignored.
    assert 'endHold("silence")' in js and 'endHold("limit")' in js
    assert "if (!holding || ending) return;" in js
    assert 'h["X-Fish-End"]' in js and "page.silence_end_s" in js and "page.quiet_rms" in js
    viz = (WEB_DIR.parent / "viz.py").read_text(encoding="utf-8")
    assert '"X-Fish-End"' in viz


# --- the page reads the device table (ADR 0021) ---

def _fn(js: str, start: str) -> str:
    """One top-level function or block of debug.js, from `start` to its closing line."""
    body = js[js.index(start):]
    return body[:body.index("\n  }\n")]


def test_the_page_reads_presence_and_failure_from_the_device_table():
    js = (WEB_DIR / "debug.js").read_text(encoding="utf-8")
    # one map by id, rebuilt only when the state changes
    dev = _fn(js, "function dev() {")
    assert "st !== devFor" in dev and "devMap[d.id] = d" in dev
    # the old per-caller keys are read nowhere
    for gone in ("t.hw ", "t.hw[", "hw = t.hw", "show_tab.hw", "mic_dead", "phone_mics", "t.capture", "page.capture",
                 "be.capture", "be.online", "c.mic_pages"):
        assert gone not in js, gone
    status = _fn(js, "function renderStatus() {")
    assert "st.devices" in status and 'd.level !== "off"' in status
    order = [status.index(x) for x in ('"Voice"', '"Mode"', '"Lines"', '"Fortune"', '"Act"', '"Start at boot"')]
    assert order == sorted(order) and status.index("st.devices") < order[0]
    assert '"Network"' not in status and '"Speaker"' not in status and '"Remote"' not in status
    assert "st.summary" in status
    assert 'setSummary("warn", "Ready, with a warning: "' in status
    assert 'setSummary("bad", "Check: "' in status and 'setSummary("ok", "Ready for visitors")' in status


def test_the_warn_summary_has_its_colour():
    css = (WEB_DIR / "debug.css").read_text(encoding="utf-8")
    assert re.search(r"\.summary\.warn \{[^}]*var\(--hoja-aviso\)", css)


def test_the_chips_come_from_the_table_without_their_own_thresholds():
    js = (WEB_DIR / "debug.js").read_text(encoding="utf-8")
    bar = _fn(js, "function renderBar() {")
    for word, part in (("LINK", "motors"), ("NET", "internet"), ("TRIG", "remote"), ("MIC", "mic"), ("SPK", "speaker")):
        assert f'"{word}"' in bar, word
        assert f"d.{part}" in bar, part
    assert "0.95" not in bar and "0.005" not in bar and "S.perf" not in bar and "link.health" not in bar


def test_the_hat_says_no_internet_from_the_table():
    js = (WEB_DIR / "debug.js").read_text(encoding="utf-8")
    assert '(dev().internet || {}).present === false' in js
    assert 'box.classList.toggle("no-net", noNet)' in js


def test_the_hardware_marks_and_the_detected_note():
    html = (WEB_DIR / "debug.html").read_text(encoding="utf-8")
    setup = _panel(html, "setup")
    assert 'id="hwNote"' in setup and setup.index('data-hw="internet"') < setup.index('id="hwNote"')
    js = (WEB_DIR / "debug.js").read_text(encoding="utf-8")
    body = _fn(js, "function renderSetup() {")
    assert "(d[b.dataset.hw] || {}).marked" in body and '$("hwNote")' in body


def test_the_hold_and_the_phone_rows_read_the_table():
    js = (WEB_DIR / "debug.js").read_text(encoding="utf-8")
    assert "function boardDeaf() { return !!(dev().mic || {}).out; }" in js
    spk = js[js.index("const phoneSpeaker = guard("):js.index("// ---- render ---")]
    assert "d.phone_speaker" in spk and "x.pages" in spk and "x.in_use" in spk
    assert "phoneSpeaker.status(dev())" in js and "phoneMic.status(page, dev())" in js
    mic = js[js.index("const phoneMic = guard("):]
    off = mic[mic.index("async function off("):]
    off = off[:off.index("\n    }\n")]
    assert 'switchValue("mic", "start")' in off and 'value: "host" }' not in off


def test_the_fortune_button_waits_for_its_lines_from_show_tab_only():
    js = (WEB_DIR / "debug.js").read_text(encoding="utf-8")
    block = js[js.index("const fortuneRow = guard("):js.index("const phoneMic = guard(")]
    assert "btn.disabled = open || wantOpen || !ready;" in block
    assert "tabReady" not in block and "f.ready" not in block    # the view's flag no longer decides
    assert "ready = !!ft &&" in block


# --- one connection record and one explain() (ADR 0021, C4) ---

def test_every_refusal_is_worded_once_inside_explain():
    js = (WEB_DIR / "debug.js").read_text(encoding="utf-8")
    body = _fn(js, "function explain(out, what) {")
    for word in ('"no connection"', '"the hat is busy', '"refused: "'):
        assert js.count(word) == 1 and word in body, word
    for word in ('"arm first (60 s)"', '"no permission (token)"', '" is off"', '"the hat did not pick it up"'):
        assert word in body, word
    assert len(re.findall(r"\bexplain\(", js)) >= 16      # the definition and at least 15 callers
    # every POST's answer goes through it: no caller words a refusal itself
    assert not re.search(r"out\.error \|\| out\.status|bad\.error \|\| bad\.status", js)
    # the cue keeps its retry when the board cannot be reached
    flush = js[js.index("async function flush() {"):]
    flush = flush[:flush.index("\n    }\n")]
    assert "out.status === 0" in flush and "setTimeout(() => { timer = 0; flush(); }, 3000)" in flush
    assert "explain(out" in flush


def test_the_toast_colour_is_a_flag_not_a_regex():
    js = (WEB_DIR / "debug.js").read_text(encoding="utf-8")
    body = _fn(js, "function msg(_node, text, ms, warn) {")
    assert 't.className = warn ? "warn" : "";' in body
    assert ".test(text)" not in body


def test_one_connection_record_and_no_stray_thresholds():
    js = (WEB_DIR / "debug.js").read_text(encoding="utf-8")
    assert js.count("CONN = {") == 1
    assert re.search(r"const CONN = \{ QUIET_S: 15, DOWN_S: 25, STALE_S: 15 \};", js)
    conn = _fn(js, "function connState() {")
    # the stream's and the state's ages are read only in connState()
    assert js.count("- lastMsgAt") == 1 and "- lastMsgAt" in conn
    assert js.count("- S.stateAt") == 1 and "- S.stateAt" in conn
    for key in ("stream", "age_s", "state_age_s", "token_ok"):
        assert key in conn, key
    assert not re.search(r"lastMsgAt\)?\s*[<>]=?\s*\d", js)
    # an attempt that has not opened yet is quiet, not down, until DOWN_S after connect()
    assert "Math.max(lastMsgAt, openedAt)" in conn
    assert "openedAt = performance.now();" in _fn(js, "function connect() {")
    assert "connState()" in js and js.count("connState()") >= 7
    # the six sites
    watchdog = js[js.index("// a stream that went quiet"):]
    assert 'connState().stream === "down"' in watchdog[:watchdog.index("}, 5000);")]
    assert 'connState().stream !== "live"' in _fn(js, "function resume() {")
    assert 'const streamLive = () => connState().stream === "live";' in js
    assert "connState()" in _fn(js, "function renderBand() {")
    assert "connState()" in _fn(js, "function renderStatus() {")
    hat = js[js.index("    function paint() {"):]
    assert "connState().stream" in hat[:hat.index("\n    }\n")]
    # a failed refresh keeps the last good state's time: never "Infinity", never stateAt = 0
    assert "Infinity" not in js and "S.stateAt = 0" not in js
    refresh = _fn(js, "async function refresh() {")
    assert refresh.count("S.stateAt =") == 1


def test_a_stale_state_keeps_its_rows_dimmed():
    js = (WEB_DIR / "debug.js").read_text(encoding="utf-8")
    status = _fn(js, "function renderStatus() {")
    assert 'rows.classList.toggle("stale", conn.stale)' in status
    assert status.index("rows.replaceChildren(...out)") < status.index('"No answer from the hat for "')
    css = (WEB_DIR / "debug.css").read_text(encoding="utf-8")
    assert re.search(r"\.go-rows\.stale \{[^}]*opacity", css)


def test_the_hardware_taps_are_pessimistic_and_symmetric():
    js = (WEB_DIR / "debug.js").read_text(encoding="utf-8")
    block = js[js.index('for (const b of document.querySelectorAll("[data-hw]")) {'):]
    block = block[:block.index("\n  }\n")]
    sent = block.index('await post("/debug/hw"')
    assert block.index('b.setAttribute("aria-pressed"') > sent
    assert "if (out.ok) b.setAttribute" in block
    assert block.index("b.disabled = true") < sent < block.index("b.disabled = false")
    assert "explain(out)" in block
    # the phone is armed inside the tap, and disarmed only when this tap armed it
    assert "armedByTap[part] = true" in block and block.index("armedByTap[part] = true") < sent
    assert "if (ph && armedByTap[part] && ((failed && !out.ok) || (!failed && out.ok)))" in block
    assert "(!failed || !out.ok)" not in block      # a refused clear leaves the phone on
    assert "const armedByTap = { speaker: false, mic: false };" in js


def test_the_ticket_sits_after_the_last_fortune_and_its_toggle_beside_the_cup():
    html = (WEB_DIR / "debug.html").read_text(encoding="utf-8")
    visit = _panel(html, "visit")
    order = [visit.index(x) for x in ('id="fortuneBtn"', 'id="fortuneLast"', 'id="ticketRow"', 'id="reprintBtn"',
                                      'id="ticketLine"', 'id="cVisit"', 'id="cupBtn"', 'id="ticketBtn"', 'id="actMsg"')]
    assert order == sorted(order)
    assert re.search(r'<div class="picks" id="ticketRow" hidden>', visit)
    assert re.search(r'id="ticketBtn" data-fortune="ticket" aria-pressed="false" hidden>', visit)
    js = (WEB_DIR / "debug.js").read_text(encoding="utf-8")
    block = js[js.index("const fortuneRow = guard("):js.index("const phoneMic = guard(")]
    assert 'post("/fortune", { action: "reprint" })' in block and 'explain(out, "the printer")' in block
    assert "ticket(r) {" in block and "status(page, tab, printer) {" in block
    assert 'case "ticket": fortuneRow.ticket(r); break;' in js
    assert "fortuneRow.status(page, tab, S.state.printer)" in js
    assert '"printing": "a ticket is printing: wait for it"' in js and '"no ticket yet": "no fortune has ended yet"' in js
    setup = _fn(js, "function renderSetup() {")
    assert '$("ticketBtn").hidden = !prn.present;' in setup and 'switchValue("fortune_ticket")' in setup
    assert 'setFromTap("fortune_ticket", on)' in js
