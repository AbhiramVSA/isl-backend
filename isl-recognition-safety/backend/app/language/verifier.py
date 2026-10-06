"""Grounding verifier for LLM-polished sentences.

Accepts an LLM sentence only if every content word is grounded in an input gloss (or is
an allow-listed function word), every non-unknown input gloss is represented, and the
number of "[unknown sign]" markers equals the number of UNKNOWN glosses.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

FUNCTION_WORDS = {
    "a", "an", "the", "is", "are", "am", "was", "were", "be", "been", "being", "do", "does", "did", "not", "no",
    "to", "of", "in", "on", "at", "for", "with", "and", "or", "but", "so", "that", "this", "these", "those",
    "i", "me", "my", "mine", "you", "your", "yours", "he", "him", "his", "she", "her", "hers", "it", "its", "we",
    "us", "our", "they", "them", "their", "will", "would", "can", "could", "should", "may", "might", "must",
    "have", "has", "had", "some", "any", "there", "here", "please", "very", "also", "too", "now", "then", "up",
    "down", "out", "into", "from", "by", "about", "what", "where", "who", "whom", "whose", "when", "why", "how",
    "which", "all", "many", "much", "one", "get", "got", "go", "going", "want", "need", "let", "s", "m", "re",
    "ve", "ll", "d", "t", "unknown", "sign",
}
_SUFFIXES = ("ing", "ed", "es", "s", "ly", "er", "est")


def lemmas(word: str) -> set[str]:
    w = re.sub(r"[^a-z0-9]", "", word.lower())
    out = {w}
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= (2 if suf in ("s", "es") else 3):
            base = w[: -len(suf)]
            out.add(base)
            if suf in ("ed", "ing", "es") and len(base) >= 3:
                out.add(base + "e")
            if suf == "ing" and len(base) >= 3 and base[-1] == base[-2]:
                out.add(base[:-1])
    if w.endswith("ies") and len(w) > 4:
        out.add(w[:-3] + "y")
    return {x for x in out if x}


def _gloss_keys(gloss) -> set[str]:
    """All acceptable lemma keys for one gloss (display alternatives, parenthetical parts, individual words)."""
    keys: set[str] = set()
    raw = gloss.display if hasattr(gloss, "display") else str(gloss)
    label = getattr(gloss, "label", raw)
    for src in (raw, label):
        s = re.sub(r"\[[^\]]*\]", " ", src)
        for part in re.split(r"[/(),]", s):
            part = part.strip().lower()
            if not part:
                continue
            keys.add(re.sub(r"[^a-z0-9]", "", part))
            for w in part.split():
                keys |= lemmas(w)
    keys.discard("")
    return keys


@dataclass
class Verification:
    passed: bool
    reason: str | None

    def to_json(self) -> dict:
        return {"passed": self.passed, "reason": self.reason}


def verify(sentence: str, glosses) -> Verification:
    if not sentence or not sentence.strip():
        return Verification(False, "empty sentence")
    unknown_expected = sum(1 for g in glosses if g.status == "unknown" or g.label == "UNKNOWN")
    unknown_found = sentence.count("[unknown sign]")
    if unknown_found != unknown_expected:
        return Verification(False, f"expected {unknown_expected} '[unknown sign]' marker(s), found {unknown_found}")
    body = sentence.replace("[unknown sign]", " ").replace("(?)", " ")
    words = re.findall(r"[A-Za-z0-9']+", body)
    known = [g for g in glosses if not (g.status == "unknown" or g.label == "UNKNOWN")]
    gloss_key_sets = [_gloss_keys(g) for g in known]
    all_gloss_keys: set[str] = set().union(*gloss_key_sets) if gloss_key_sets else set()
    # phrase-level keys (e.g. "goodmorning") are matched against concatenated bigrams as well
    lw = [w.lower().replace("'", "") for w in words]
    bigrams = {lw[i] + lw[i + 1] for i in range(len(lw) - 1)}
    trigrams = {lw[i] + lw[i + 1] + lw[i + 2] for i in range(len(lw) - 2)}
    for w in lw:
        if w in FUNCTION_WORDS:
            continue
        if lemmas(w) & all_gloss_keys:
            continue
        # part of a multi-word gloss ("good morning", "thank you", "police station")
        if any(k in all_gloss_keys for k in (bigrams | trigrams) if w in k):
            continue
        return Verification(False, f"content word '{w}' is not grounded in any recognised gloss")
    # every known gloss must appear
    text_keys = set(lw) | bigrams | trigrams
    text_lemmas: set[str] = set()
    for w in lw:
        text_lemmas |= lemmas(w)
    for g, keys in zip(known, gloss_key_sets):
        if not (keys & (text_keys | text_lemmas)):
            return Verification(False, f"recognised gloss '{g.display}' is missing from the sentence")
    return Verification(True, None)
