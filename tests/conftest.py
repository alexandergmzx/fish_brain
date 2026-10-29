"""Shared test set-up."""
import pytest


@pytest.fixture(autouse=True)
def _no_fillers(monkeypatch):
    """Fillers are on by default and wait in threads; a test that wants them turns them on
    in the config it builds. Off here, a turn takes the direct path and never renders a
    phrase (rendering reaches the voice program)."""
    monkeypatch.setenv("FISH_FILLER", "false")
    monkeypatch.setenv("FISH_BURBLE", "false")     # the same for the sound at release
    # A shell with the hat exported must not turn the fish's tests into the hat's.
    # The board's licence guard must not probe a voice the tests do not have.
    # A key in the developer's shell must never decide a test's outcome or reach a real API.
    # The evening's place and the fortune's extras from the shell would change every tag.
    # A printer in the shell must never get paper from a test.
    for name in ("FISH_PERSONA", "FISH_VISIT", "FISH_VISIT_IDLE_S", "FISH_LOQ_PROBE_S",
                 "FISH_LOQ_WARNING_S", "FISH_LOQ_MAC_IFACE", "FISH_SHOW", "FISH_SHOW_STATE",
                 "FISH_SHOW_SEED", "FISH_READING_PROFILE", "ANTHROPIC_API_KEY",
                 "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "FISH_PLACE",
                 "FISH_PLACE_TEXT", "FISH_FORTUNE_DECK", "FISH_FORTUNE_CUP",
                 "FISH_TTS_RATE_FACTOR", "FISH_TTS_PITCH_ST", "FISH_TTS_TEMPO",
                 "FISH_PRINTER", "FISH_PRINTER_CHANNEL", "FISH_FORTUNE_TICKET"):
        monkeypatch.delenv(name, raising=False)
