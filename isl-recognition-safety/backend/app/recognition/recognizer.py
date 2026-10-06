"""SignRecognizer: turns the landmark stream + gate events into gloss emissions.

Windows are classified (a) periodically while a segment is active, for live feedback,
and (b) definitively when the gate reports a pause or a segment end. Only (b) emits
glosses. Fusion: HWGAT (2,002 words) is primary; the INCLUDE head (263 words) adds or
removes confidence when its prediction maps to the same word. Uncertain and unknown
outcomes are emitted explicitly instead of being dropped or guessed.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..config import settings
from ..landmarks.frame import LandmarkFrame
from ..models.registry import ModelRegistry, TopK
from .gate import GateEvent, SigningGate
from .vocab import AliasIndex, display_name, norm_key

log = logging.getLogger(__name__)

# Prior weights per head; renormalised over the heads that produced output and scaled by
# each head's own top-1 confidence at fusion time.
HEAD_WEIGHTS = {"hwgat": 0.6, "slgcn": 0.25, "include": 0.15}


@dataclass
class Gloss:
    id: int
    label: str                 # canonical key e.g. "water", or "UNKNOWN"
    display: str               # e.g. "Water"
    p: float
    status: str                # confident | uncertain | unknown
    t_start_ms: float
    t_end_ms: float
    heads: dict[str, float] = field(default_factory=dict)
    safety_lexicon: str | None = None
    raw_label: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "display": self.display, "p": round(self.p, 3),
                "status": self.status, "t_start_ms": self.t_start_ms, "t_end_ms": self.t_end_ms,
                "heads": {k: round(v, 3) for k, v in self.heads.items()}, "safety_lexicon": self.safety_lexicon}


@dataclass
class WindowResult:
    t_start_ms: float
    t_end_ms: float
    frames: int
    heads: dict[str, dict[str, Any]]
    fused: dict[str, Any] | None
    final: bool

    def to_json(self) -> dict[str, Any]:
        return {"t_start_ms": self.t_start_ms, "t_end_ms": self.t_end_ms, "frames": self.frames,
                "heads": {k: {"top": [{"label": t["label"], "p": round(t["p"], 3)} for t in v["top"]],
                              "latency_ms": v["latency_ms"]} for k, v in self.heads.items()},
                "fused": self.fused, "final": self.final}


class SignRecognizer:
    def __init__(self, registry: ModelRegistry, safety_lexicon: dict[str, set[str]] | None = None):
        self.reg = registry
        self.gate = SigningGate()
        self.buffer: deque[LandmarkFrame] = deque()
        self.buffer_ms = 12000.0
        self.stride_ms = settings.window_stride_ms if registry.device.type == "cuda" else settings.window_stride_cpu_ms
        self.aliases: dict[str, AliasIndex] = {}
        if registry.hwgat:
            for key in ("include", "slgcn"):
                head = getattr(registry, key, None)
                if head:
                    self.aliases[key] = AliasIndex(registry.hwgat.labels, head.labels)
                    log.info("%s->HWGAT alias map: %d/%d labels mapped", key, self.aliases[key].n_mapped, len(head.labels))
        self.safety_lexicon = safety_lexicon or {}
        self._lex_by_key = {norm_key(lbl): cat for cat, labels in self.safety_lexicon.items() for lbl in labels}
        self.min_confidence = settings.conf_high
        self.reset()

    def reset(self) -> None:
        self.gate.reset()
        self.buffer.clear()
        self.glosses: list[Gloss] = []
        self.last_window: WindowResult | None = None
        self._next_id = 1
        self._last_infer_ms = -1e9
        self._sub_start_ms: float | None = None
        self._seg_start_ms: float | None = None
        self._seg_glosses: list[Gloss] = []
        self._last_emit: Gloss | None = None

    # ------------------------------------------------------------------
    def frames_between(self, t0: float, t1: float) -> list[LandmarkFrame]:
        return [f for f in self.buffer if t0 <= f.t_ms <= t1]

    def process(self, f: LandmarkFrame) -> list[Gloss]:
        self.buffer.append(f)
        while self.buffer and f.t_ms - self.buffer[0].t_ms > self.buffer_ms:
            self.buffer.popleft()
        events = self.gate.update(f)
        emitted: list[Gloss] = []
        for ev in events:
            emitted += self._on_event(ev, f)
        st = self.gate.st
        if (st.state == "ACTIVE" and self._sub_start_ms is not None
                and f.t_ms - self._last_infer_ms >= self.stride_ms
                and f.t_ms - self._sub_start_ms >= settings.min_segment_ms):
            self._classify(self._sub_start_ms, f.t_ms, final=False)
        if st.state == "ACTIVE" and self._sub_start_ms is not None and f.t_ms - self._sub_start_ms > settings.max_segment_ms:
            # very long segment without any pause: force a boundary so glosses keep flowing
            emitted += self._finalize(self._sub_start_ms, f.t_ms)
            self._sub_start_ms = f.t_ms
        return emitted

    def _on_event(self, ev: GateEvent, f: LandmarkFrame) -> list[Gloss]:
        if ev.kind == "segment_start":
            self._sub_start_ms = ev.t_ms
            self._seg_start_ms = ev.t_ms
            self._seg_glosses = []
            return []
        if self._sub_start_ms is None:
            return []
        start = self._sub_start_ms
        out = self._finalize(start, ev.t_ms)
        self._seg_glosses += out
        if ev.kind == "pause":
            self._sub_start_ms = ev.t_ms
            return out
        self._sub_start_ms = None
        # Segment ended: if it was split into fragments that were not all confident, try the
        # whole segment as one sign (a hold in the middle of a sign looks like a pause).
        merged = self._merge_segment(self._seg_start_ms, ev.t_ms)
        self._seg_glosses = []
        return merged if merged is not None else out

    def _merge_segment(self, t0: float | None, t1: float) -> list[Gloss] | None:
        frags = self._seg_glosses
        if t0 is None or len(frags) < 2 or all(g.status == "confident" for g in frags):
            return None
        if t1 - t0 > settings.max_segment_ms:
            return None
        win = self._classify(t0, t1, final=True)
        if win is None or win.fused is None:
            return None
        fz = win.fused
        best_frag = max(g.p for g in frags)
        if fz["p"] >= self.min_confidence and fz["margin"] >= settings.margin_min and fz["p"] > best_frag:
            for g in frags:
                if g in self.glosses:
                    self.glosses.remove(g)
            g = Gloss(self._next_id, fz["key"], fz["label"], fz["p"], "confident", t0, t1, fz["heads"],
                      self._lex_by_key.get(fz["key"]), fz["label"])
            self._next_id += 1
            self.glosses.append(g)
            self._last_emit = g
            log.debug("merged %d fragments into %s (p=%.2f)", len(frags), g.display, g.p)
            return [g]
        return None

    # ------------------------------------------------------------------
    def _run_heads(self, frames: list[LandmarkFrame]) -> dict[str, TopK]:
        heads: dict[str, TopK] = {}
        for key in ("hwgat", "slgcn", "include"):
            head = getattr(self.reg, key, None)
            if head is None:
                continue
            try:
                r = head.predict(frames)
            except Exception as e:  # noqa: BLE001 - one broken head must not stop the others
                log.warning("head %s failed: %s", key, e)
                continue
            if r is not None:
                heads[key] = r
        return heads

    def _fuse(self, heads: dict[str, TopK]) -> dict[str, Any] | None:
        if not heads:
            return None
        scores: dict[str, float] = {}
        display: dict[str, str] = {}
        per_head: dict[str, dict[str, float]] = {}
        # Confidence-weighted mixture: each head's prior weight is scaled by its own top-1
        # probability and renormalised, so an unsure head cannot drown out a sure one and
        # disagreement between sure heads lowers the fused confidence.
        raw_w = {k: HEAD_WEIGHTS.get(k, 0.2) * max(v["top"][0]["p"], 0.02) for k, v in heads.items()}
        tot = sum(raw_w.values())
        weights = {k: w / tot for k, w in raw_w.items()}
        for key, res in heads.items():
            alias = self.aliases.get(key)
            for t in res["top"]:
                if t["p"] < 0.005:
                    continue
                mapped = alias.map(t["label"]) if alias else None
                k = norm_key(mapped) if mapped else norm_key(t["label"])
                scores[k] = scores.get(k, 0.0) + weights[key] * t["p"]
                if key == "hwgat" or k not in display:
                    display[k] = display_name(mapped) if mapped else display_name(t["label"])
                per_head.setdefault(k, {})[key] = t["p"]
        if not scores:
            return None
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        top_k, top_p = ranked[0]
        second_p = ranked[1][1] if len(ranked) > 1 else 0.0
        ph = per_head.get(top_k, {})
        supporting = [k for k, p in ph.items() if p >= 0.1]
        agreement = len(heads) > 1 and len(supporting) >= 2
        return {"label": display[top_k], "key": top_k, "p": round(float(top_p), 3),
                "margin": round(float(top_p - second_p), 3), "agreement": agreement,
                "heads": {k: round(v, 3) for k, v in ph.items()},
                "weights": {k: round(w, 2) for k, w in weights.items()}}

    def _classify(self, t0: float, t1: float, final: bool) -> WindowResult | None:
        frames = self.frames_between(t0 - 120, t1 + 120)
        if len(frames) < 6:
            return None
        self._last_infer_ms = t1
        heads = self._run_heads(frames)
        if not heads:
            return None
        fused = self._fuse(heads)
        self.last_window = WindowResult(t0, t1, len(frames), heads, fused, final)
        return self.last_window

    def _finalize(self, t0: float, t1: float) -> list[Gloss]:
        if t1 - t0 < settings.min_segment_ms:
            return []
        win = self._classify(t0, t1, final=True)
        if win is None or win.fused is None:
            return []
        fz = win.fused
        p, margin = fz["p"], fz["margin"]
        if p >= self.min_confidence and margin >= settings.margin_min:
            status = "confident"
        elif p >= settings.conf_low:
            status = "uncertain"
        else:
            status = "unknown"
        if status == "unknown":
            g = Gloss(self._next_id, "UNKNOWN", "UNKNOWN", p, "unknown", t0, t1, fz["heads"], None, fz["label"])
        else:
            g = Gloss(self._next_id, fz["key"], fz["label"], p, status, t0, t1, fz["heads"],
                      self._lex_by_key.get(fz["key"]), fz["label"])
        # de-duplicate a sign that was split by a brief hold (same label, tiny gap)
        le = self._last_emit
        if le and le.label == g.label and g.label != "UNKNOWN" and t0 - le.t_end_ms < 350:
            le.t_end_ms, le.p = t1, max(le.p, g.p)
            return []
        self._next_id += 1
        self.glosses.append(g)
        self._last_emit = g
        return [g]

    def take_sentence_glosses(self) -> list[Gloss]:
        out, self.glosses = self.glosses, []
        return out
