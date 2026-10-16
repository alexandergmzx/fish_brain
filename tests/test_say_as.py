"""What Loquendo is given: the shown text rewritten for the voice only (say_as.py)."""
import pytest

from fish_brain import say_as, tts
from fish_brain.config import TTSConfig
from fish_brain.say_as import rules_hash, voice_text

HAT = {"Hufflepuff": "Jáfelpaf", "Gryffindor": "Grífindor"}


def test_nothing_set_leaves_the_text_alone():
    assert voice_text("Hola, ¿qué tal?") == "Hola, ¿qué tal?"
    assert rules_hash() == ""


def test_whole_words_any_case_with_or_without_accents():
    out = voice_text("¡HUFFLEPUFF! hufflepuff, Hufflepúff. Huffle y Hufflepuffs no.", say_as=HAT)
    assert out == "¡Jáfelpaf! Jáfelpaf, Jáfelpaf. Huffle y Hufflepuffs no."


@pytest.mark.parametrize("text, want", [
    ("Mmm… difícil.", "\\item=Hmh difícil."),
    ("Mmmm. Listo", "\\item=Hmh . Listo"),
    ("Hmm, a ver", "\\item=Hmh , a ver"),
    ("mjm y mhm", "\\item=Hmh y \\item=Hmh"),
    ("Emmm y hum quedan", "Emmm y hum quedan"),       # a vowel: read as a word already
    ("Mamá, mmmh", "Mamá, \\item=Hmh"),
])
def test_hums_with_no_vowel_become_the_recorded_hum(text, want):
    assert voice_text(text, hum="\\item=Hmh") == want


def test_a_plain_hum_keeps_its_dots():
    assert voice_text("Mmm… sí. Hmm, no", hum="Emmm") == "Emmm… sí. Emmm, no"


def test_the_text_can_never_carry_a_tag_but_the_config_can():
    out = voice_text("hola \\pause=9000 \\item=Cough", prefix="\\language=SpanishMx ")
    assert out == "\\language=SpanishMx hola pause=9000 item=Cough"
    assert voice_text("Hufflepuff", say_as={"Hufflepuff": "\\SAMPA=;(xa|fle|paf) "}).startswith("\\SAMPA")


def test_the_cache_key_changes_with_the_rules(monkeypatch):
    for k in ("FISH_LOQ_PREFIX", "FISH_LOQ_HUM", "FISH_PERSONA"):
        monkeypatch.delenv(k, raising=False)
    plain = TTSConfig()
    assert tts.fingerprint(plain) == str(plain.sample_rate)          # the fish: as before
    monkeypatch.setenv("FISH_LOQ_PREFIX", "\\language=SpanishMx ")
    assert tts.fingerprint(TTSConfig()) != tts.fingerprint(plain)


def test_loq_is_given_the_rewritten_text(monkeypatch, tmp_path):
    monkeypatch.setenv("FISH_LOQ_PREFIX", "\\language=SpanishMx ")
    monkeypatch.setenv("FISH_LOQ_HUM", "\\item=Hmh")
    cfg = TTSConfig(); cfg.backend = "loq"
    got = []
    monkeypatch.setattr(tts, "_synthesize_loq", lambda text, c, out: got.append(text))
    monkeypatch.setattr(tts, "_validate_wav", lambda p: None)
    tts.synthesize("Mmm… hola", cfg, tmp_path / "a.wav")
    assert got == ["\\language=SpanishMx \\item=Hmh hola"]


def test_every_candidate_has_a_label_and_text():
    assert len(say_as.CANDIDATES) >= 20
    assert all(label and text for label, text in say_as.CANDIDATES)
