"""The kiosk supervisor's decisions, with no display and no browser."""
from fish_brain import kiosk
from fish_brain.kiosk import Output

LIT = """Screen 0: minimum 320 x 200, current 1920 x 1080, maximum 5120 x 4096
DP-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 530mm x 290mm
   1920x1080     60.00*+
   1280x720      60.00
"""
DARK = """Screen 0: minimum 320 x 200, current 1024 x 768, maximum 5120 x 4096
DP-1 connected (normal left inverted right x axis y axis)
   1920x1080     60.00 +
"""
NONE = """Screen 0: minimum 320 x 200, current 1024 x 768, maximum 5120 x 4096
DP-1 disconnected (normal left inverted right x axis y axis)
"""


def test_parse_outputs():
    assert kiosk.parse_outputs(LIT) == [Output("DP-1", True, 1920, 1080)]
    assert kiosk.parse_outputs(DARK) == [Output("DP-1", True, 0, 0)]
    assert kiosk.parse_outputs(NONE) == [Output("DP-1", False, 0, 0)]
    assert kiosk.parse_outputs("") == []


def test_pick_output():
    outs = kiosk.parse_outputs(LIT)
    assert kiosk.pick_output(outs).name == "DP-1"
    assert kiosk.pick_output(outs, "HDMI-1") is None
    assert kiosk.pick_output(kiosk.parse_outputs(NONE)) is None


def test_decide():
    lit = Output("DP-1", True, 1920, 1080)
    assert kiosk.decide(None, False, True) == "none"        # no display: no browser at all
    assert kiosk.decide(lit, True, True) == "none"          # paused
    assert kiosk.decide(lit, False, False) == "wait"
    assert kiosk.decide(lit, False, True) == "fish"


def test_browser_argv_has_a_private_profile_and_no_secret():
    argv = kiosk.browser_argv("chromium", "http://127.0.0.1:8723/?kiosk=1", 1280, 720)
    assert argv[0] == "chromium" and "--kiosk" in argv
    assert f"--user-data-dir={kiosk.PROFILE}" in argv and "--window-size=1280,720" in argv
    assert not any("token" in a.lower() for a in argv)


def test_settings_read_only_their_own_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-secret\nFISH_VIZ_TOKEN=tok\nFISH_KIOSK_MODE=1280x720\n"
                   "FISH_VIZ_PORT=9000\n# FISH_KIOSK_OUTPUT=x\n")
    got = kiosk.read_settings(env, environ={"FISH_KIOSK_OUTPUT": "DP-1", "HOME": "/x"})
    assert got == {"FISH_KIOSK_MODE": "1280x720", "FISH_VIZ_PORT": "9000",
                   "FISH_KIOSK_OUTPUT": "DP-1"}
    assert kiosk.read_settings(tmp_path / "missing", environ={}) == {}


def test_wait_page_ships_with_the_package():
    assert kiosk.WAIT_PAGE.is_file()
    assert (kiosk.WAIT_PAGE.parent / "img" / "neckRest_mouth0_tailRest.png").is_file()
