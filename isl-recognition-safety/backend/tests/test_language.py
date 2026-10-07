from types import SimpleNamespace

from app.language.joiner import join
from app.language.verifier import verify


def G(label, display=None, status="confident", p=0.9):
    return SimpleNamespace(label=label, display=display or label.capitalize(), status=status, p=p)


def test_joiner_basic_sov_to_svo():
    r = join([G("i", "I"), G("water", "Water"), G("want", "Want")])
    assert r.text == "I want water."
    assert r.unknown_count == 0


def test_joiner_preserves_unknown():
    r = join([G("i", "I"), G("UNKNOWN", "UNKNOWN", status="unknown", p=0.1), G("water", "Water")])
    assert "[unknown sign]" in r.text
    assert r.unknown_count == 1
    assert "water" in r.text.lower()


def test_joiner_uncertain_marker():
    r = join([G("i", "I"), G("water", "Water", status="uncertain", p=0.4), G("want", "Want")])
    assert "water(?)" in r.text


def test_joiner_question_and_copula():
    assert join([G("you", "You"), G("happy", "Happy")]).text == "You are happy."
    assert join([G("you", "You"), G("name", "Name"), G("what", "What")]).text.endswith("?")


def test_joiner_greetings():
    assert join([G("thankyou", "Thank You")]).text == "Thank you."
    assert join([G("goodevening", "Good Evening", status="uncertain", p=0.4)]).text == "Good evening(?)."


def test_verifier_accepts_grounded_sentence():
    gl = [G("i", "I"), G("water", "Water"), G("want", "Want")]
    assert verify("I want some water.", gl).passed
    assert verify("I would like water.", gl).passed is False  # "like" is not grounded


def test_verifier_rejects_invented_content():
    gl = [G("i", "I"), G("water", "Water")]
    v = verify("I want cold water please.", gl)
    assert not v.passed and "cold" in v.reason


def test_verifier_requires_unknown_marker():
    gl = [G("i", "I"), G("UNKNOWN", "UNKNOWN", status="unknown", p=0.1), G("water", "Water")]
    assert not verify("I want water.", gl).passed
    assert verify("I [unknown sign] water.", gl).passed


def test_verifier_requires_all_glosses():
    gl = [G("mother", "Mother"), G("hospital", "Hospital"), G("go", "Go")]
    assert not verify("Mother goes.", gl).passed
    assert verify("Mother goes to the hospital.", gl).passed


def test_verifier_multiword_gloss():
    gl = [G("goodmorning", "Good Morning"), G("police station", "Police Station")]
    assert verify("Good morning, police station.", gl).passed
