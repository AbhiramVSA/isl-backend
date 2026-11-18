"""Optional LLM polish: gloss sequence -> fluent English, strictly grounded.

Providers: "anthropic" (Claude, official SDK), "ollama" (local, OpenAI-free HTTP),
"none". Only gloss strings and confidences are sent; never video or landmarks.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.request
from dataclasses import dataclass
from typing import Any

from ..config import settings

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You convert a sequence of recognised Indian Sign Language (ISL) glosses into ONE natural English sentence.

Facts about the input: ISL word order is usually subject-object-verb, it has no articles or copula, time words come first, and a question sign comes at the end. Each gloss has a confidence. Glosses marked (?) are low-confidence. The token UNKNOWN means a sign was performed but not recognised.

Rules (mandatory):
1. Every content word (noun, verb, adjective, adverb, number, name) in your sentence must come from an input gloss. You may add only function words: articles, pronouns, copulas (is/are/am), auxiliaries (do/does/did/will/can), prepositions, conjunctions, "some", "please", "not".
2. Do not add, guess, or replace any content word. Do not resolve UNKNOWN: write the literal text [unknown sign] in its position, once per UNKNOWN.
3. Keep every recognised gloss. Keep low-confidence glosses but render them as the word followed by (?) e.g. water(?).
4. Preserve negation and question meaning. Prefer the simplest faithful sentence.
5. If the glosses cannot form a sentence without inventing meaning, set ok=false and put the glosses joined by spaces in sentence.
Return only JSON: {"ok": boolean, "sentence": string, "used_glosses": string[]}"""

JSON_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "sentence": {"type": "string"},
                   "used_glosses": {"type": "array", "items": {"type": "string"}}},
    "required": ["ok", "sentence", "used_glosses"],
    "additionalProperties": False,
}


@dataclass
class LLMResult:
    ok: bool
    sentence: str | None
    error: str | None
    provider: str
    model: str


def _format_glosses(glosses) -> str:
    parts = []
    for g in glosses:
        if g.status == "unknown" or g.label == "UNKNOWN":
            parts.append("UNKNOWN")
        else:
            d = g.display.split("/")[0].strip()
            parts.append(f"{d}(?) [p={g.p:.2f}]" if g.status == "uncertain" else f"{d} [p={g.p:.2f}]")
    return " | ".join(parts)


class LLMPolisher:
    def __init__(self, provider: str | None = None):
        self.provider = (provider or settings.llm_provider).lower()
        self.model = {"anthropic": settings.anthropic_model, "ollama": settings.ollama_model}.get(self.provider, "")
        self.error: str | None = None
        self._client = None
        if self.provider == "anthropic":
            try:
                import anthropic
                self._client = anthropic.Anthropic(timeout=settings.llm_timeout_s, max_retries=1)
                if not (self._client.api_key or getattr(self._client, "auth_token", None)):
                    self.error = "ANTHROPIC_API_KEY not set (or run `ant auth login`)"
            except Exception as e:  # noqa: BLE001
                self.error = f"anthropic SDK unavailable: {e}"
        elif self.provider == "ollama":
            try:
                with urllib.request.urlopen(f"{settings.ollama_url}/api/tags", timeout=3) as r:
                    tags = json.load(r)
                names = [m.get("name", "") for m in tags.get("models", [])]
                if not any(n.startswith(self.model.split(":")[0]) for n in names):
                    self.error = f"model '{self.model}' not pulled in Ollama (have: {names[:5]})"
            except Exception as e:  # noqa: BLE001
                self.error = f"Ollama not reachable at {settings.ollama_url}: {e}"
        elif self.provider != "none":
            self.error = f"unknown provider '{self.provider}'"

    @property
    def available(self) -> bool:
        return self.provider in ("anthropic", "ollama") and self.error is None

    def status(self) -> dict[str, Any]:
        return {"provider": self.provider, "available": self.available, "model": self.model or None, "error": self.error}

    # ------------------------------------------------------------------
    def polish(self, glosses) -> LLMResult:
        if not self.available:
            return LLMResult(False, None, self.error or "LLM disabled", self.provider, self.model)
        user = f"Glosses: {_format_glosses(glosses)}"
        try:
            if self.provider == "anthropic":
                text = self._anthropic(user)
            else:
                text = self._ollama(user)
        except Exception as e:  # noqa: BLE001
            log.warning("LLM call failed: %s", e)
            return LLMResult(False, None, f"{type(e).__name__}: {e}", self.provider, self.model)
        try:
            data = json.loads(_extract_json(text))
            ok = bool(data.get("ok", False))
            sentence = str(data.get("sentence", "")).strip()
        except Exception as e:  # noqa: BLE001
            return LLMResult(False, None, f"LLM returned non-JSON output: {e}", self.provider, self.model)
        if not ok:
            return LLMResult(False, sentence or None, "LLM declined: glosses too ambiguous", self.provider, self.model)
        return LLMResult(True, sentence, None, self.provider, self.model)

    def _anthropic(self, user: str) -> str:
        kwargs: dict[str, Any] = dict(
            model=self.model, max_tokens=400, system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": JSON_SCHEMA}},
        )
        try:
            resp = self._client.messages.create(**kwargs)
        except Exception as e:  # noqa: BLE001 - older models may reject output_config/effort; retry plain
            msg = str(e)
            if "output_config" in msg or "effort" in msg or "format" in msg:
                kwargs.pop("output_config")
                resp = self._client.messages.create(**kwargs)
            else:
                raise
        if getattr(resp, "stop_reason", None) == "refusal":
            raise RuntimeError("model refused the request")
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")

    def _ollama(self, user: str) -> str:
        body = json.dumps({"model": self.model, "stream": False, "format": JSON_SCHEMA,
                           "options": {"temperature": 0},
                           "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]}).encode()
        req = urllib.request.Request(f"{settings.ollama_url}/api/chat", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=settings.llm_timeout_s) as r:
            return json.load(r)["message"]["content"]


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("{"):
        return text
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object found")
    return m.group(0)
