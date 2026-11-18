"""SentenceBuilder: joiner first (always), optional LLM polish accepted only if verified."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .joiner import join
from .llm import LLMPolisher
from .verifier import verify

log = logging.getLogger(__name__)


@dataclass
class Sentence:
    id: int
    glosses: list
    joiner_text: str
    llm_text: str | None
    final_text: str
    source: str                       # "llm" | "joiner"
    verification: dict[str, Any]
    llm_error: str | None
    t_start_ms: float
    t_end_ms: float
    llm_provider: str = "none"
    pending: bool = False             # LLM polish still running

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "glosses": [g.to_json() for g in self.glosses], "joiner_text": self.joiner_text,
                "llm_text": self.llm_text, "final_text": self.final_text, "source": self.source,
                "verification": self.verification, "llm_error": self.llm_error, "t_start_ms": self.t_start_ms,
                "t_end_ms": self.t_end_ms, "llm_provider": self.llm_provider, "pending": self.pending}


class SentenceBuilder:
    def __init__(self, polisher: LLMPolisher | None):
        self.polisher = polisher
        self.llm_enabled = polisher is not None and polisher.available
        self._next = 1

    def build(self, glosses: list) -> Sentence:
        jr = join(glosses)
        s = Sentence(self._next, list(glosses), jr.text, None, jr.text, "joiner",
                     {"passed": True, "reason": "deterministic joiner (no LLM)"}, None,
                     glosses[0].t_start_ms if glosses else 0.0, glosses[-1].t_end_ms if glosses else 0.0,
                     self.polisher.provider if self.polisher else "none",
                     pending=bool(self.llm_enabled and self.polisher and self.polisher.available))
        self._next += 1
        return s

    def polish(self, s: Sentence) -> Sentence:
        """Blocking LLM call + verification; safe to run in a worker thread."""
        try:
            if not (self.llm_enabled and self.polisher and self.polisher.available):
                s.llm_error = None if not self.polisher or self.polisher.provider == "none" else self.polisher.error
                return s
            res = self.polisher.polish(s.glosses)
            s.llm_text = res.sentence
            if not res.ok or not res.sentence:
                s.llm_error = res.error
                s.verification = {"passed": False, "reason": res.error or "LLM returned nothing"}
                return s
            v = verify(res.sentence, s.glosses)
            s.verification = v.to_json()
            if v.passed:
                s.final_text, s.source = res.sentence, "llm"
            else:
                log.info("LLM sentence rejected: %s | %r", v.reason, res.sentence)
            return s
        finally:
            s.pending = False
