"""What fish.js expects of index.html, read from the two files. No browser, no server."""
import re

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


def test_debug_css_animates_only_transform_and_opacity():
    css = re.sub(r"/\*.*?\*/", "", (WEB_DIR / "debug.css").read_text(encoding="utf-8"), flags=re.S)
    allowed = {"transform", "opacity"}
    frames = re.findall(r"@keyframes\s+([\w-]+)\s*\{((?:[^{}]*\{[^{}]*\})*)\s*\}", css)
    assert len(frames) >= 4
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
