"""The hat's words as files (fish_brain/prompts/, ADR 0029)."""
import pytest

from fish_brain import fortune_bank, texts


def test_every_file_loads_and_the_bank_is_whole():
    for name in ("visit.md", "ask.md", "reading.md"):
        assert texts.rules(name).strip() and not texts.rules(name).endswith("\n")
    assert len(fortune_bank.FORTUNE_PHRASES) == 183


def test_a_broken_lines_file_names_itself(tmp_path):
    bad = tmp_path / "lines.toml"
    bad.write_text('visit_greeting = "sin cerrar\n', encoding="utf-8")
    with pytest.raises(ValueError, match="lines.toml"):
        texts.parse_lines(bad)


@pytest.mark.parametrize("change,word", [
    (lambda d: d["pools"].__setitem__("beat", "Lo vi."), "pools.beat"),
    (lambda d: d.pop("signs"), "signs"),
    (lambda d: d["questions"]["taza"].pop("reprompt"), "questions.taza"),
    (lambda d: d.__setitem__("reversed", ""), "reversed"),
])
def test_a_bad_edit_names_what_is_wrong(change, word):
    import copy
    d = copy.deepcopy(texts.lines())
    change(d)
    with pytest.raises(ValueError, match=word):
        texts.check_lines(d)


def test_the_house_file_loads_and_a_bad_edit_names_the_place():
    import copy
    assert texts.house()["questions"]["C3"]["options"][3]["id"]
    for change, word in [(lambda d: d["questions"].pop("B2"), "questions.B2"),
                         (lambda d: d["questions"]["A1"]["options"].pop(), "questions.A1 needs 2"),
                         (lambda d: d["questions"]["A3"]["options"][1].pop("words"), "A3 option 2 needs words"),
                         (lambda d: d["questions"]["C1"]["options"][0].__setitem__("id", "Con espacio"), "C1 option 1"),
                         (lambda d: d["pools"].__setitem__("greet", []), "pools.greet")]:
        d = copy.deepcopy(texts.house())
        change(d)
        with pytest.raises(ValueError, match=word):
            texts.check_house(d)


def test_prompts_dir_points_every_file_elsewhere(monkeypatch, tmp_path):
    (tmp_path / "ask.md").write_text("otras reglas\n", encoding="utf-8")
    monkeypatch.setenv("FISH_PROMPTS_DIR", str(tmp_path))
    assert texts.rules("ask.md") == "otras reglas"
    monkeypatch.delenv("FISH_PROMPTS_DIR")
    assert texts.rules("ask.md") != "otras reglas"
