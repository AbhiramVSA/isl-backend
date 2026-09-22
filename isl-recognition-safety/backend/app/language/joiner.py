"""Deterministic ISL-gloss -> English joiner. Always available; never invents content.

ISL grammar notes applied (Zeshan 2003; Aboh, Pfau & Zeshan 2005; ISL generation
literature): basic order is SOV, no articles/copula, time expressions first, negation
after the verb, a single sentence-final question sign. The joiner produces plain,
possibly clunky English whose every content word is a recognised gloss.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

PRONOUNS = {"i": "I", "me": "I", "you": "you", "youplural": "you all", "he": "he", "she": "she", "it": "it",
            "we": "we", "they": "they", "my": "my", "your": "your", "his": "his", "her": "her", "our": "our",
            "their": "their", "myself": "myself", "yourself": "yourself", "toyou": "to you"}
WH = {"what": "what", "where": "where", "who": "who", "whom": "whom", "whose": "whose", "when": "when",
      "why": "why", "how": "how", "howmany": "how many", "howmuch": "how much", "howbig": "how big",
      "whattime": "what time", "which": "which"}
NEG = {"not", "no", "dont", "never", "nothing"}
TIME = {"today", "tomorrow", "yesterday", "now", "morning", "afternoon", "evening", "night", "tonight",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "week", "month", "year",
        "later", "before", "after", "always", "sometimes"}
GREETINGS = {"hello", "goodmorning", "goodafternoon", "goodevening", "goodnight", "thankyou", "sorry",
             "please", "welcome", "bye", "goodbye", "namaste", "howareyou", "allthebest", "congratulations"}
# glosses that read naturally as verbs (used for SOV -> SVO reordering)
VERBS = {"want", "need", "go", "come", "eat", "drink", "help", "call", "give", "take", "like", "love", "know",
         "understand", "see", "hear", "feel", "have", "buy", "sell", "learn", "teach", "work", "play", "sleep",
         "wake", "read", "write", "sit", "stand", "walk", "run", "stop", "wait", "open", "close", "find", "save",
         "meet", "live", "die", "hurt", "attack", "kill", "fall", "cry", "laugh", "think", "forget", "remember",
         "ask", "tell", "say", "speak", "sign", "cook", "wash", "bath", "drive", "ride", "fly", "swim", "pay",
         "study", "listen", "look", "watch", "search", "bring", "send", "show", "make", "do", "try", "use",
         "start", "finish", "win", "lose", "fight", "escape", "hide", "climbup", "climbdown", "push", "pull",
         "throw", "catch", "cut", "break", "fix", "build", "choose", "decide", "agree", "complain", "insult",
         "ignore", "invent", "submit", "express", "beat"}
ADJ_HINTS = {"good", "bad", "happy", "sad", "sick", "hot", "cold", "tired", "hungry", "thirsty", "angry", "afraid",
             "fear", "alone", "safe", "dangerous", "urgent", "fine", "alright", "beautiful", "ugly", "big",
             "small", "biglarge", "smalllittle", "new", "old", "young", "fast", "slow", "strong", "weak",
             "healthy", "dead", "alive", "rich", "poor", "clean", "dirty", "wet", "dry", "loud", "quiet",
             "deaf", "blind", "pleased", "disappointed", "careful", "careless", "lazy", "busy", "free", "late",
             "early", "ready", "correct", "wrong", "important", "special", "normal", "strange"}


@dataclass
class JoinResult:
    text: str
    tokens: list[str]         # content tokens actually used (canonical keys), for verification
    unknown_count: int


def _key(label: str) -> str:
    return re.sub(r"[^a-z0-9]", "", label.lower())


def _surface(gloss) -> str:
    """Surface form for a gloss object (has .label/.display/.status)."""
    if gloss.status == "unknown" or gloss.label == "UNKNOWN":
        return "[unknown sign]"
    k = _key(gloss.label)
    if k in PRONOUNS:
        s = PRONOUNS[k]
    else:
        s = gloss.display.split("/")[0].strip()
        s = re.sub(r"\s*\([^)]*\)", "", s).strip().lower() or gloss.display.lower()
        if k == "biglarge":
            s = "big"
        elif k == "smalllittle":
            s = "small"
    if gloss.status == "uncertain":
        s = f"{s}(?)"
    return s


def join(glosses) -> JoinResult:
    """glosses: sequence of objects with .label, .display, .status."""
    if not glosses:
        return JoinResult("", [], 0)
    keys = [_key(g.label) if g.status != "unknown" else "UNKNOWN" for g in glosses]
    surf = [_surface(g) for g in glosses]
    unknown = sum(1 for k in keys if k == "UNKNOWN")

    # 1. greeting-only or single-token utterances
    if len(glosses) == 1:
        s = surf[0]
        if keys[0] in GREETINGS:
            base = {"howareyou": "How are you", "thankyou": "Thank you", "goodmorning": "Good morning",
                    "goodafternoon": "Good afternoon", "goodevening": "Good evening", "goodnight": "Good night",
                    "hello": "Hello", "sorry": "Sorry", "please": "Please", "allthebest": "All the best"}.get(keys[0], s.capitalize())
            if glosses[0].status == "uncertain":
                base += "(?)"
            return JoinResult(base + ("?" if keys[0] == "howareyou" else "."), [keys[0]], unknown)
        return JoinResult(_cap(s) + ("." if not s.endswith("]") else ""), [k for k in keys if k != "UNKNOWN"], unknown)

    # 2. pull out sentence-final question word, leading greetings, time words
    q_word = None
    items = list(zip(keys, surf))
    if items[-1][0] in WH:
        q_word = WH[items[-1][0]]
        items = items[:-1]
    elif items[0][0] in WH:
        q_word = WH[items[0][0]]
        items = items[1:]
    lead: list[str] = []
    while items and items[0][0] in GREETINGS:
        lead.append(items[0][1])
        items = items[1:]
    times = [s for k, s in items if k in TIME]
    items = [(k, s) for k, s in items if k not in TIME]
    negs = [k for k, _ in items if k in NEG]
    items = [(k, s) for k, s in items if k not in NEG]

    # 3. SOV -> SVO: if a verb appears last and a pronoun subject first, move verb after subject
    words = [s for _, s in items]
    ks = [k for k, _ in items]
    if len(ks) >= 3 and ks[-1] in VERBS and ks[0] in PRONOUNS and ks[1] not in VERBS:
        ks = [ks[0], ks[-1]] + ks[1:-1]
        words = [words[0], words[-1]] + words[1:-1]
    # 4. pronoun + adjective/noun with no verb -> insert copula
    if len(ks) == 2 and ks[0] in PRONOUNS and ks[1] not in VERBS and ks[1] != "UNKNOWN":
        cop = {"I": "am", "you": "are", "we": "are", "they": "are", "you all": "are"}.get(words[0], "is")
        words = [words[0], cop, words[1]]
    # 5. negation after the verb
    if negs:
        vi = next((i for i, k in enumerate(ks) if k in VERBS), None)
        if vi is not None and vi + 1 <= len(words):
            words.insert(vi + 1 if len(words) > vi else vi, "not")
            words.insert(vi, "do")
        else:
            words.append("not")
    body = " ".join(words)
    if times:
        body = (" ".join(times) + " " + body).strip()
    if q_word:
        body = f"{q_word} {body}".strip() + "?"
    elif body:
        body += "."
    text = " ".join(lead + [body]).strip()
    text = _cap(text)
    return JoinResult(text, [k for k in keys if k != "UNKNOWN"], unknown)


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s
