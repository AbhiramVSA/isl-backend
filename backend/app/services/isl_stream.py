"""Bridge helpers for the unauthenticated /app live-stream endpoints.

The phone opens a WebSocket here; this service opens a second one to the
recognition service's own live socket (``WS /ws/stream``) and relays frames
one way and pipeline snapshots back. Video bytes and MediaPipe math never run
in this process — it only validates, throttles, and accumulates the draft
transcript the phone later prefills its report with.

Kept free of FastAPI/SQLAlchemy imports so the validation and accumulation
logic is unit-testable without a running app.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import math
import secrets
import time
import uuid
from dataclasses import dataclass, field

ISL_DOWN_MESSAGE = (
    "Live recognition is unavailable right now. "
    "Record a short clip instead with POST /app/api/v1/predict."
)

CONTROL_ACTIONS = {"reset", "end_sentence", "config"}


def new_stream_id() -> str:
    return uuid.uuid4().hex[:12]


def new_draft_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_match(token: str, secret_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), secret_hash)


def _is_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _check_array(value: object, rows: int, cols: int, name: str, *, allow_none: bool) -> None:
    if value is None:
        if allow_none:
            return
        raise ValueError(f"{name} is required")
    if not isinstance(value, (list, tuple)) or len(value) != rows:
        raise ValueError(f"{name} must have {rows} rows")
    for row in value:
        if not isinstance(row, (list, tuple)) or len(row) != cols:
            raise ValueError(f"{name} rows must have {cols} values")
        for item in row:
            if not _is_finite_number(item):
                raise ValueError(f"{name} must hold finite numbers")


def validate_landmarks_message(msg: dict) -> dict:
    """Check a client ``landmarks`` frame; return it unchanged or raise."""
    if not isinstance(msg, dict) or msg.get("type") != "landmarks":
        raise ValueError("message type must be 'landmarks'")
    if not _is_finite_number(msg.get("t_ms")):
        raise ValueError("t_ms must be a finite number")
    if msg["t_ms"] < 0:
        raise ValueError("t_ms must not be negative")
    _check_array(msg.get("pose"), 33, 4, "pose", allow_none=True)
    _check_array(msg.get("left_hand"), 21, 3, "left_hand", allow_none=True)
    _check_array(msg.get("right_hand"), 21, 3, "right_hand", allow_none=True)
    if msg.get("pose") is None and msg.get("left_hand") is None and msg.get("right_hand") is None:
        raise ValueError("at least one of pose, left_hand, right_hand is required")
    return msg


def validate_frame_message(msg: dict, *, max_bytes: int) -> dict:
    """Check a client ``frame`` (base64 JPEG) message; return it or raise."""
    if not isinstance(msg, dict) or msg.get("type") != "frame":
        raise ValueError("message type must be 'frame'")
    if not _is_finite_number(msg.get("t_ms")):
        raise ValueError("t_ms must be a finite number")
    if msg["t_ms"] < 0:
        raise ValueError("t_ms must not be negative")
    jpeg = msg.get("jpeg")
    if not isinstance(jpeg, str) or not jpeg:
        raise ValueError("jpeg must be a non-empty base64 string")
    if len(jpeg) > max_bytes:
        raise ValueError(f"frame is larger than {max_bytes} bytes")
    try:
        base64.b64decode(jpeg, validate=True)
    except Exception as exc:
        raise ValueError("jpeg is not valid base64") from exc
    return msg


def validate_control_message(msg: dict) -> dict:
    if not isinstance(msg, dict) or msg.get("type") != "control":
        raise ValueError("message type must be 'control'")
    action = msg.get("action")
    if action not in CONTROL_ACTIONS:
        raise ValueError(f"unknown control action {action!r}")
    if action == "config":
        if "llm_enabled" in msg and not isinstance(msg["llm_enabled"], bool):
            raise ValueError("llm_enabled must be a boolean")
        if "min_confidence" in msg:
            confidence = msg["min_confidence"]
            if not _is_finite_number(confidence) or not 0.2 <= float(confidence) <= 0.95:
                raise ValueError("min_confidence must be between 0.2 and 0.95")
    return msg


def validate_client_message(msg: dict, *, kind: str, max_frame_bytes: int) -> dict:
    """Dispatch to the per-type validator based on the stream kind."""
    mtype = msg.get("type") if isinstance(msg, dict) else None
    if mtype == "control":
        return validate_control_message(msg)
    if kind == "landmarks":
        if mtype != "landmarks":
            raise ValueError("this stream only accepts 'landmarks' and 'control' messages")
        return validate_landmarks_message(msg)
    if mtype != "frame":
        raise ValueError("this stream only accepts 'frame' and 'control' messages")
    return validate_frame_message(msg, max_bytes=max_frame_bytes)


def gloss_label(gloss: dict) -> str:
    return str(gloss.get("display") or gloss.get("label") or "UNKNOWN")


def build_transcript(sentences: list[dict], glosses: list[dict]) -> str:
    sentence_text = " ".join(s.get("text", "") for s in sentences if s.get("text")).strip()
    if sentence_text:
        return sentence_text
    return " ".join(gloss_label(g) for g in glosses).strip()


@dataclass
class DraftAccumulator:
    """Merges ISL ``update`` snapshots into a report-ready draft."""

    sentences: dict[str, dict] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    latest_glosses: list[dict] = field(default_factory=list)
    safety_events: list[dict] = field(default_factory=list)
    frames_seen: int = 0
    first_t_ms: float | None = None
    last_t_ms: float | None = None

    def add_snapshot(self, snap: dict) -> None:
        self.frames_seen += 1
        t_ms = snap.get("t_ms")
        if _is_finite_number(t_ms):
            value = float(t_ms)
            if self.first_t_ms is None:
                self.first_t_ms = value
            self.last_t_ms = value
        for item in snap.get("sentences") or []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("id") or item.get("text") or len(self.order))
            if key not in self.sentences:
                self.order.append(key)
            self.sentences[key] = item
        self.order = self.order[-20:]
        for key in list(self.sentences):
            if key not in self.order:
                del self.sentences[key]
        glosses = snap.get("glosses")
        if isinstance(glosses, list):
            self.latest_glosses = [g for g in glosses if isinstance(g, dict)]
        events = snap.get("safety_events")
        if isinstance(events, list):
            self.safety_events = [e for e in events if isinstance(e, dict)][-50:]

    @property
    def ordered_sentences(self) -> list[dict]:
        return [self.sentences[key] for key in self.order]

    @property
    def transcript(self) -> str:
        return build_transcript(self.ordered_sentences, self.latest_glosses)

    @property
    def duration_ms(self) -> int:
        if self.first_t_ms is None or self.last_t_ms is None:
            return 0
        return max(0, int(self.last_t_ms - self.first_t_ms))


class InboundThrottle:
    """Drops over-rate frames so one phone cannot flood the ISL service."""

    def __init__(self, max_fps: float) -> None:
        self.min_interval = 1.0 / max_fps if max_fps > 0 else 0.0
        self.last_forward: float | None = None
        self.dropped = 0

    def allow(self, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else now
        if self.last_forward is None or moment - self.last_forward >= self.min_interval:
            self.last_forward = moment
            return True
        self.dropped += 1
        return False


class StreamLimiter:
    """In-process caps for the unauthenticated streams.

    Mirrors the existing HTTP limiter's style (per-process memory): enough to
    stop one IP or a stress run from pinning the ISL workers, not a
    distributed quota. Counts reset with the process.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.kind_counts: dict[str, int] = {"landmarks": 0, "video": 0}
        self.ip_counts: dict[str, int] = {}

    async def acquire(self, kind: str, ip: str, *, kind_max: int, ip_max: int) -> bool:
        async with self._lock:
            if self.kind_counts.get(kind, 0) >= kind_max:
                return False
            if self.ip_counts.get(ip, 0) >= ip_max:
                return False
            self.kind_counts[kind] = self.kind_counts.get(kind, 0) + 1
            self.ip_counts[ip] = self.ip_counts.get(ip, 0) + 1
            return True

    async def release(self, kind: str, ip: str) -> None:
        async with self._lock:
            self.kind_counts[kind] = max(0, self.kind_counts.get(kind, 0) - 1)
            remaining = self.ip_counts.get(ip, 0) - 1
            if remaining <= 0:
                self.ip_counts.pop(ip, None)
            else:
                self.ip_counts[ip] = remaining

    async def reset(self) -> None:
        async with self._lock:
            self.kind_counts = {"landmarks": 0, "video": 0}
            self.ip_counts = {}


limiter = StreamLimiter()


async def connect_isl(url: str, *, timeout: float, max_size: int = 2 * 1024 * 1024):
    """Open the recognition service's live socket. Separated for tests."""
    from websockets.asyncio.client import connect

    return await connect(url, open_timeout=timeout, max_size=max_size)
