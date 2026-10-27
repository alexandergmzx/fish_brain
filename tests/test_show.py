"""show.py and show_bank.py: the scripted visit's decisions are balanced, deterministic and
never stuck."""
import itertools
import json

import pytest

from fish_brain import show, show_bank
from fish_brain.show import Heard, ShowState, decide, houses_in, match_option

OPPOSITE = {"G": "R", "R": "G", "H": "S", "S": "H"}       # across the cross


def opts(qid):
    return [o["id"] for o in show_bank.question(qid)["options"]]


@pytest.mark.parametrize("set_id", sorted(show_bank.SETS))
def test_the_cross_gives_four_paths_per_house_and_no_tie(set_id):
    q1, q2, q3 = (q["id"] for q in show_bank.SETS[set_id])
    wins = {h: 0 for h in show_bank.HOUSES}
    for a, b, c in itertools.product(opts(q1), opts(q2), opts(q3)):
        house, how = decide({q1: a, q2: b, q3: c}, {})
        assert how == "answers"
        wins[house] += 1
        grid, _ = decide({q1: a, q2: b}, {})
        assert house != OPPOSITE[grid]            # Q3 moves at most to a neighbour
    assert wins == {"G": 4, "H": 4, "R": 4, "S": 4}
    grid = {decide({q1: a, q2: b}, {})[0] for a, b in itertools.product(opts(q1), opts(q2))}
    assert grid == set(show_bank.HOUSES)          # two answers alone: one house per corner


@pytest.mark.parametrize("set_id", sorted(show_bank.SETS))
def test_a_chip_never_changes_a_clear_winner(set_id):
    q1, q2, q3 = (q["id"] for q in show_bank.SETS[set_id])
    for a, b, c in itertools.product(opts(q1) + [None], opts(q2) + [None], opts(q3) + [None]):
        answers = {q1: a, q2: b, q3: c}
        s = show.scores_for(answers, {})
        top = max(s.values())
        if list(s.values()).count(top) != 1:
            continue
        plain, _ = decide(answers, {})
        for colour in ("rojo", "amarillo", "azul", "verde"):
            assert decide(answers, {"color": colour})[0] == plain


def test_every_path_with_misses_ends_in_a_house(tmp_path):
    st = ShowState(tmp_path / "s.json", seed="t")
    for set_id, qs in show_bank.SETS.items():
        ids = [q["id"] for q in qs]
        for combo in itertools.product(*[opts(i) + [None] for i in ids]):
            for colour in (None, "azul"):
                cues = {"color": colour} if colour else {}
                house, _ = decide(dict(zip(ids, combo)), cues, bag=st.house_bag)
                assert house in show_bank.HOUSES


def test_four_silent_visitors_get_four_houses(tmp_path):
    st = ShowState(tmp_path / "s.json", seed="fair")
    got = [decide({}, {}, bag=st.house_bag) for _ in range(8)]
    assert [how for _, how in got] == ["bag"] * 8
    assert sorted(h for h, _ in got[:4]) == sorted(show_bank.HOUSES)
    assert sorted(h for h, _ in got[4:]) == sorted(show_bank.HOUSES)


def test_the_ladder_force_preference_veto():
    q1, q2, q3 = (q["id"] for q in show_bank.SETS["A"])
    answers = {q1: "fiesta", q2: "volcan", q3: "mapa"}            # Gryffindor
    assert decide(answers, {}, force="S") == ("S", "operator")
    assert decide(answers, {}, preference="R") == ("R", "preference")
    assert decide(answers, {}, preference="R", vetoes={"R"})[0] == "G"
    assert decide(answers, {}, vetoes={"G"})[0] != "G"
    assert decide(answers, {}, vetoes=set(show_bank.HOUSES))[0] == "G"   # all vetoed: ignored


def test_a_tie_goes_to_the_trait_answer_then_the_bag(tmp_path):
    q1, q2, q3 = (q["id"] for q in show_bank.SETS["A"])
    assert decide({q1: "fiesta", q2: None, q3: "amigo"}, {}) == ("H", "answers")
    # Only Q1 heard: G and H tied, nothing else -> the bag.
    st = ShowState(tmp_path / "s.json", seed="x")
    house, how = decide({q1: "fiesta", q2: None, q3: None}, {}, bag=st.house_bag)
    assert house in ("G", "H") and how == "tie: bag"
    assert decide({q1: "fiesta"}, {"color": "amarillo"}) == ("H", "answers")


@pytest.mark.parametrize("text,expect", [
    ("La fiesta.", "fiesta"), ("¡fiesta!", "fiesta"), ("Fiestas", "fiesta"),
    ("Acertijo.", "acertijo"), ("una adivinanza", "acertijo"),
    ("yo digo el primero", "fiesta"), ("la segunda", "acertijo"), ("el último", "acertijo"),
])
def test_matching_options(text, expect):
    h = match_option(show_bank.question("A1"), text)
    assert h.kind == "option" and h.option == expect, h


@pytest.mark.parametrize("text,expect", [
    ("Bolcán", "volcan"), ("jardin", "jardin"), ("Un litro.", "libro"), ("el mapa", "mapa"),
    ("Mi mejor amiga", "amigo"), ("trofeo", "trofeo"), ("tro feo", "trofeo"),
])
def test_spelling_slips_still_match(text, expect):
    qid = "A2" if expect in ("volcan", "jardin") else "A3"
    h = match_option(show_bank.question(qid), text)
    assert h.option == expect, h


@pytest.mark.parametrize("text,kind", [
    ("", "none"), ("Sí.", "none"), ("No.", "none"), ("simón", "none"),
    ("No sé.", "not_sure"), ("los dos", "not_sure"), ("me da igual", "not_sure"),
    ("hola cómo estás me gusta mucho la pizza con queso y jamón", "none"),
    ("perro", "none"),
])
def test_what_is_not_an_answer(text, kind):
    assert match_option(show_bank.question("A1"), text).kind == kind


def test_a_tie_between_two_options_is_no_answer():
    assert match_option(show_bank.question("A1"), "fiesta o acertijo").kind == "none"


@pytest.mark.parametrize("text,pref,vetoes", [
    ("Quiero ser de Ravenclaw", "R", set()),
    ("Yo quiero Slider in", "S", set()),
    ("grifindor porfa", "G", set()),
    ("no Slytherin por favor", None, {"S"}),
    ("ni Hufflepuff ni Slytherin", None, {"H", "S"}),
    ("no sé, Ravenclaw", "R", set()),
    ("una fiesta", None, set()),
])
def test_preferences_and_vetoes(text, pref, vetoes):
    assert houses_in(text) == (pref, vetoes)


def test_bags_deal_every_line_before_repeating_and_persist(tmp_path):
    path = tmp_path / "s.json"
    names = show_bank.pool_names("greet")
    st = ShowState(path, seed="s1")
    first = [st.pick("greet", names) for _ in range(len(names))]
    assert sorted(first) == sorted(names)
    nxt = st.pick("greet", names)
    assert nxt != first[-1]                      # a new cycle never starts with the last one
    again = ShowState(path)                      # a reboot: the same position
    assert again.seed == "s1"
    assert again.data["bags"]["greet"]["dealt"] == [nxt]


def test_the_same_seed_gives_the_same_lines(tmp_path):
    a = ShowState(tmp_path / "a.json", seed="same")
    b = ShowState(tmp_path / "b.json", seed="same")
    names = show_bank.pool_names("season")
    assert [a.pick("season", names) for _ in range(20)] == [b.pick("season", names) for _ in range(20)]


def test_a_corrupt_state_file_starts_fresh(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not json")
    st = ShowState(path)
    assert st.recovered and st.visit == 0
    st.next_visit()
    assert json.loads(path.read_text())["visit"] == 1


def test_question_sets_rotate_by_visit():
    assert [show.question_set(n) for n in range(1, 7)] == ["A", "B", "C", "A", "B", "C"]


def test_the_bank_is_well_formed():
    for set_id, qs in show_bank.SETS.items():
        assert len(qs) == 3
        assert all(len(o["scores"]) == 2 for q in qs[:2] for o in q["options"])
        assert all(len(o["scores"]) == 1 for o in qs[2]["options"])
        for q in qs:
            heads = [show.phon_key(o["words"][0]) for o in q["options"]]
            assert len(set(heads)) == len(heads)
            assert q["prompt"].rstrip().endswith("?")
    for name, text in show_bank.SHOW_PHRASES.items():
        assert name.startswith("show_") and text.strip()
        assert not text.lstrip().startswith("-")          # loq would read it as an option
        assert "difícil" not in text.lower()              # not the book's line
    assert len(show_bank.SHOW_PHRASES) >= 130


ENGLISH = {"halloween", "gryffindor", "hufflepuff", "ravenclaw", "slytherin"}


def test_the_lines_are_for_the_season_and_their_english_is_spelled_right():
    import re
    from fish_brain.visit import _fold
    spanish_only = re.compile(r"[a-zñ]+")
    texts = list(show_bank.SHOW_PHRASES.values())
    joined = " ".join(_fold(t) for t in texts)
    assert "feria" not in joined and "cenart" not in joined
    for house in ("Gryffindor", "Hufflepuff", "Ravenclaw", "Slytherin"):
        assert any(house in t for t in texts)               # spelled exactly so somewhere
    for bad in ("grifindor", "slitherin", "hufflepuf ", "ravenclow", "halowen", "haloween"):
        assert bad not in joined
    english = {w for t in texts for w in spanish_only.findall(_fold(t))
               if w in ENGLISH}
    assert english <= ENGLISH and "halloween" in english
    assert show_bank.pool_names("season") and "fair" not in show_bank.POOLS


def test_an_article_run_into_the_word_still_matches():
    assert match_option(show_bank.question("A2"), "Unbolkan.").option == "volcan"
    assert match_option(show_bank.question("A2"), "elvolcan").option == "volcan"


def test_the_trick_or_treat_answer_counts_for_the_neighbourhood_option():
    assert match_option(show_bank.question("C1"), "trick or treat").option == "puertas"
    assert match_option(show_bank.question("C1"), "¡dulce o truco!").option == "puertas"


def test_canarys_spelling_of_slytherin_is_a_veto():
    assert houses_in("No quiero esliterín.") == (None, {"S"})
