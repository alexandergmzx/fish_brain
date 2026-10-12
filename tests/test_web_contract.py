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
