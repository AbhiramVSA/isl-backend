"""SessionPipeline: the single inference pipeline shared by the live WebSocket path and the
upload path. Feed LandmarkFrames in temporal order; read snapshots."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from .config import settings
from .landmarks.frame import LandmarkFrame
from .language.builder import Sentence, SentenceBuilder
from .language.llm import LLMPolisher
from .models.registry import ModelRegistry
from .recognition.recognizer import Gloss, SignRecognizer
from .safety.monitor import SAFETY_LEXICON, SafetyMonitor

log = logging.getLogger(__name__)


def to_native(obj: Any) -> Any:
    """Recursively convert numpy scalars/arrays and NaN/inf into JSON-safe Python values."""
    import math

    import numpy as np
    if isinstance(obj, dict):
        return {k: to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_native(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return to_native(obj.tolist())
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        obj = float(obj)
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    return obj


class SessionPipeline:
    def __init__(self, registry: ModelRegistry, polisher: LLMPolisher | None,
                 on_sentence_polished: Callable[[Sentence], None] | None = None, async_llm: bool = True):
        self.reg = registry
        self.recognizer = SignRecognizer(registry, SAFETY_LEXICON)
        self.safety = SafetyMonitor(registry)
        self.builder = SentenceBuilder(polisher)
        self.sentences: list[Sentence] = []
        self.on_sentence_polished = on_sentence_polished
        self.async_llm = async_llm
        self._lock = threading.Lock()
        self._fps_t: list[float] = []
        self.last_frame: LandmarkFrame | None = None
        self.frames_seen = 0
        self.started = time.time()

    # ------------------------------------------------------------------
    def reset(self) -> None:
        with self._lock:
            self.recognizer.reset()
            self.safety.reset()
            self.sentences = []
            self.last_frame = None
            self.frames_seen = 0

    def configure(self, llm_enabled: bool | None = None, min_confidence: float | None = None) -> None:
        if llm_enabled is not None:
            self.builder.llm_enabled = bool(llm_enabled) and self.builder.polisher is not None and self.builder.polisher.available
        if min_confidence is not None:
            self.recognizer.min_confidence = float(min(max(min_confidence, 0.2), 0.95))

    # ------------------------------------------------------------------
    def process(self, f: LandmarkFrame) -> dict[str, Any]:
        """Process one frame; returns a snapshot dict (contract: "update" payload minus type)."""
        with self._lock:
            self.frames_seen += 1
            self.last_frame = f
            now = time.time()
            self._fps_t.append(now)
            self._fps_t = [t for t in self._fps_t if now - t < 2.0]
            new_glosses = self.recognizer.process(f)
            for g in new_glosses:
                self.safety.note_gloss(g)
            self.safety.process(f)
            self._maybe_end_sentence(f.t_ms)
            return self._snapshot(f)

    def end_sentence(self, t_ms: float | None = None) -> Sentence | None:
        with self._lock:
            return self._flush_sentence(t_ms if t_ms is not None else (self.last_frame.t_ms if self.last_frame else 0.0))

    def finish(self) -> None:
        """Flush at end of an uploaded video: close any open segment and sentence."""
        if self.last_frame is None:
            return
        with self._lock:
            rec = self.recognizer
            if rec.gate.st.state == "ACTIVE" and rec._sub_start_ms is not None:
                from .recognition.gate import GateEvent
                for g in rec._on_event(GateEvent("segment_end", self.last_frame.t_ms), self.last_frame):
                    self.safety.note_gloss(g)
                rec.gate.st.state = "IDLE"
            self._flush_sentence(self.last_frame.t_ms)

    # ------------------------------------------------------------------
    def _maybe_end_sentence(self, t_ms: float) -> None:
        rec = self.recognizer
        if not rec.glosses:
            return
        st = rec.gate.st
        rest = (t_ms - st.rest_since_ms) if (st.state == "IDLE" and st.rest_since_ms is not None) else 0.0
        if rest >= settings.sentence_rest_ms or len(rec.glosses) >= settings.sentence_max_glosses:
            self._flush_sentence(t_ms)

    def _flush_sentence(self, t_ms: float) -> Sentence | None:
        glosses = self.recognizer.take_sentence_glosses()
        if not glosses:
            return None
        s = self.builder.build(glosses)
        s.t_end_ms = t_ms
        self.sentences.append(s)
        self.sentences = self.sentences[-20:]
        if s.pending:
            if self.async_llm:
                threading.Thread(target=self._polish, args=(s,), daemon=True).start()
            else:
                self._polish(s)
        return s

    def _polish(self, s: Sentence) -> None:
        try:
            self.builder.polish(s)
        except Exception as e:  # noqa: BLE001
            s.llm_error, s.pending = f"{type(e).__name__}: {e}", False
        if self.on_sentence_polished:
            try:
                self.on_sentence_polished(s)
            except Exception:  # noqa: BLE001
                log.exception("on_sentence_polished callback failed")

    # ------------------------------------------------------------------
    def _snapshot(self, f: LandmarkFrame) -> dict[str, Any]:
        rec = self.recognizer
        fps = len(self._fps_t) / 2.0
        return to_native({
            "t_ms": f.t_ms,
            "vision": {"pose": f.pose is not None, "left_hand": f.left_hand is not None,
                       "right_hand": f.right_hand is not None, "face": f.face_present,
                       "fps_in": round(fps, 1), "quality": round(self.safety.posture.st.quality, 2)},
            "gate": rec.gate.st.to_json(f.t_ms),
            "window": rec.last_window.to_json() if rec.last_window else None,
            "glosses": [g.to_json() for g in rec.glosses],
            "sentences": [s.to_json() for s in self.sentences],
            "safety": self.safety.state_json(),
            "safety_events": [e.to_json() for e in self.safety.events[-50:]],
        })

    def snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            return self._snapshot(self.last_frame) if self.last_frame else None
