"""The eval scorer: facts must appear, wrong claims fail, 'cannot be shown' counts."""

from eye.evals.scoring import normalise, score


def test_timestamps_and_paths_compare_in_one_form():
    assert "2026-02-15 07:10" in normalise("at 2026-02-15T07:10:38Z")
    assert "c:\\users\\analyst" in normalise("C:\\\\Users\\\\Analyst")


def test_all_facts_needed_and_any_of_alternatives():
    q = {"must_include": ["CROW-PC$", ["four", "4 failed"]]}
    assert score(q, "4 failed logons by CROW-PC$")["passed"]
    r = score(q, "Failed logons by CROW-PC$")
    assert not r["passed"] and r["facts"] == 0.5 and r["missing"] == [["four", "4 failed"]]


def test_a_wrong_claim_fails_even_with_every_fact():
    q = {"must_include": ["VID_2109"], "must_not": [r"first connected (on|at) 20\d\d"]}
    assert not score(q, "VID_2109 was first connected on 2026-02-05.")["passed"]


def test_honest_unknown_needs_the_answer_to_say_so():
    q = {"must_include": ["VID_2109"], "honest_unknown": True}
    assert score(q, "VID_2109 is present; its connection time cannot be established.")["passed"]
    assert not score(q, "VID_2109 is present.")["passed"]


def test_an_empty_answer_never_passes():
    assert not score({"must_include": []}, "")["passed"]
