"""Sentence builder + LLM polish tests with mocked providers (no network)."""
from types import SimpleNamespace

from app.language.builder import SentenceBuilder
from app.language.llm import LLMPolisher, LLMResult, _extract_json


def G(label, display, status="confident", p=0.9, t=0.0):
    return SimpleNamespace(label=label, display=display, status=status, p=p, t_start_ms=t, t_end_ms=t + 500,
                           heads={}, safety_lexicon=None, to_json=lambda: {"label": label})


class FakePolisher(LLMPolisher):
    def __init__(self, sentence, ok=True, error=None):
        self.provider, self.model, self.error, self._client = "anthropic", "fake", None, None
        self._sentence, self._ok, self._err = sentence, ok, error

    @property
    def available(self):
        return True

    def polish(self, glosses):
        return LLMResult(self._ok, self._sentence, self._err, self.provider, self.model)


def test_llm_polish_accepted_when_grounded():
    b = SentenceBuilder(FakePolisher("I want some water."))
    s = b.build([G("i", "I"), G("water", "Water"), G("want", "Want")])
    assert s.pending and s.joiner_text == "I want water."
    b.polish(s)
    assert s.source == "llm" and s.final_text == "I want some water." and s.verification["passed"]


def test_llm_polish_rejected_when_it_invents_content():
    b = SentenceBuilder(FakePolisher("I want a glass of cold water."))
    s = b.build([G("i", "I"), G("water", "Water"), G("want", "Want")])
    b.polish(s)
    assert s.source == "joiner" and s.final_text == "I want water."
    assert not s.verification["passed"] and "glass" in s.verification["reason"]


def test_llm_polish_must_preserve_unknown():
    b = SentenceBuilder(FakePolisher("I want water."))
    s = b.build([G("i", "I"), G("UNKNOWN", "UNKNOWN", status="unknown", p=0.1), G("water", "Water")])
    b.polish(s)
    assert s.source == "joiner" and "[unknown sign]" in s.final_text


def test_llm_error_falls_back_to_joiner():
    b = SentenceBuilder(FakePolisher(None, ok=False, error="timeout"))
    s = b.build([G("thankyou", "Thank You")])
    b.polish(s)
    assert s.source == "joiner" and s.final_text == "Thank you." and s.llm_error == "timeout"


def test_no_provider_means_joiner_only():
    p = LLMPolisher(provider="none")
    assert not p.available
    b = SentenceBuilder(p)
    s = b.build([G("hello", "Hello")])
    assert not s.pending and s.final_text == "Hello."


def test_extract_json_tolerates_prose():
    assert _extract_json('Sure! {"ok": true, "sentence": "Hi.", "used_glosses": []}').startswith("{")
