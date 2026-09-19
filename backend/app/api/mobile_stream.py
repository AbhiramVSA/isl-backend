"""Live ISL streaming for the Equal mobile app.

Mounted under ``/app`` next to the clip endpoint: the phone opens one of the
two sockets below instead of recording a finished file for
``POST /app/api/v1/predict``. This process never decodes video — it validates,
throttles, and relays frames to the recognition service's own live socket
(``WS /ws/stream``), streams the pipeline snapshots back, and saves the
accumulated transcript as a draft the phone prefills its report with.

Both sockets are deliberately unauthenticated (like ``/predict``: record
before anyone signs in), so per-kind and per-IP concurrency caps plus
per-stream time/byte budgets are the abuse control — see ``app/core/config.py``
``stream_*`` settings.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime, timedelta

import anyio
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import delete, select

from app.core.config import settings
from app.db import SessionLocal
from app.models import StreamDraft
from app.schemas_mobile import StreamDraftResponse
from app.services.isl_stream import (
    ISL_DOWN_MESSAGE,
    DraftAccumulator,
    InboundThrottle,
    connect_isl,
    hash_token,
    limiter,
    new_draft_token,
    new_stream_id,
    tokens_match,
    validate_client_message,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["Equal mobile app streaming"])

BUSY_CODE = 4409
ISL_DOWN_CODE = 4403


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def _purge_expired_drafts() -> None:
    try:
        async with SessionLocal() as db:
            await db.execute(delete(StreamDraft).where(StreamDraft.expires_at <= _now()))
            await db.commit()
    except Exception:
        log.exception("stream draft purge failed")


@router.get(
    "/api/v1/stream/{stream_id}/draft",
    response_model=StreamDraftResponse,
    summary="Transcript saved when a stream closed",
)
async def get_stream_draft(
    stream_id: str, token: str = Query(min_length=1, max_length=256)
) -> StreamDraftResponse:
    """How the phone turns a finished stream into a report.

    ``stream_id`` and ``token`` come from the socket ``hello``. Unknown ids,
    wrong tokens, and expired drafts all answer 404 so ids cannot be probed.
    """
    await _purge_expired_drafts()
    async with SessionLocal() as db:
        draft = await db.scalar(select(StreamDraft).where(StreamDraft.stream_id == stream_id))
        if draft is None or _as_utc(draft.expires_at) <= _now():
            if draft is not None:
                await db.delete(draft)
                await db.commit()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found.")
        if not tokens_match(token, draft.secret_hash):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found.")
        return StreamDraftResponse(
            stream_id=draft.stream_id,
            kind=draft.kind,
            transcript=draft.transcript or "",
            sentences=list(draft.sentences or []),
            safety_events=list(draft.safety_events or []),
            frames_seen=draft.frames_seen or 0,
            duration_ms=draft.duration_ms or 0,
            completed=bool(draft.completed),
            expires_at=_as_utc(draft.expires_at),
        )


@router.websocket("/api/v1/stream/landmarks")
async def stream_landmarks(websocket: WebSocket) -> None:
    """On-device MediaPipe landmarks in, live glosses out (preferred path)."""
    await _serve_stream(websocket, kind="landmarks")


@router.websocket("/api/v1/stream/video")
async def stream_video(websocket: WebSocket) -> None:
    """Camera JPEG frames in, live glosses out (server decodes; CPU-hot)."""
    await _serve_stream(websocket, kind="video")


async def _serve_stream(websocket: WebSocket, *, kind: str) -> None:
    ip = websocket.client.host if websocket.client else "unknown"
    if kind == "video":
        kind_max = settings.stream_max_video_streams
        max_fps = settings.stream_max_in_fps_video
        max_msg_bytes = settings.stream_max_message_bytes_video
    else:
        kind = "landmarks"
        kind_max = settings.stream_max_landmark_streams
        max_fps = settings.stream_max_in_fps_landmarks
        max_msg_bytes = settings.stream_max_message_bytes_landmarks
    max_seconds = settings.stream_max_minutes * 60.0
    max_bytes = settings.stream_max_bytes_mb * 1024 * 1024
    idle_seconds = settings.stream_idle_seconds

    if not await limiter.acquire(
        kind, ip, kind_max=kind_max, ip_max=settings.stream_max_streams_per_ip
    ):
        await websocket.close(code=BUSY_CODE, reason="busy, try again in a moment")
        return

    stream_id = new_stream_id()
    draft_token = new_draft_token()
    started = _now()
    expires = started + timedelta(hours=settings.stream_draft_ttl_hours)
    accumulator = DraftAccumulator()
    throttle = InboundThrottle(max_fps)
    isl = None
    bytes_in = 0
    try:
        await websocket.accept()
        # Draft row first: the hello already promises it, and the phone may
        # fetch it even if the recogniser never answers.
        try:
            async with SessionLocal() as db:
                db.add(
                    StreamDraft(
                        stream_id=stream_id,
                        secret_hash=hash_token(draft_token),
                        kind=kind,
                        transcript="",
                        sentences=[],
                        safety_events=[],
                        frames_seen=0,
                        duration_ms=0,
                        completed=False,
                        expires_at=expires,
                    )
                )
                await db.commit()
        except Exception:
            log.exception("stream %s: draft insert failed", stream_id)
        await websocket.send_json(
            {"type": "hello", "stream_id": stream_id, "draft_token": draft_token, "kind": kind}
        )

        try:
            isl = await connect_isl(
                settings.isl_ws_url, timeout=settings.isl_stream_connect_timeout_seconds
            )
        except Exception:
            log.warning("stream %s: ISL dial failed", stream_id)
            await _finish_draft(stream_id, kind, accumulator, completed=True)
            try:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": ISL_DOWN_MESSAGE,
                        "fallback": "/app/api/v1/predict",
                    }
                )
                await websocket.close(code=ISL_DOWN_CODE, reason="recogniser unavailable")
            except (RuntimeError, WebSocketDisconnect):
                pass
            return

        # The recogniser greets every session with {"type":"hello"}; the relay
        # loop below drops it (only "update"/"error" are forwarded) since the
        # phone already received our hello above. The relay runs on an anyio
        # task group (not asyncio tasks + gather): cancelling a gather of
        # tasks mid-cleanup does not compose with the server's cancel scopes.
        deadline = time.monotonic() + max_seconds
        last_activity = time.monotonic()

        def expired() -> bool:
            return time.monotonic() >= deadline

        def idle() -> bool:
            return time.monotonic() - last_activity >= idle_seconds

        async def receive_client_text() -> str | None:
            """One client frame, or None on timeout (caller checks idle)."""
            with anyio.move_on_after(2.0):
                try:
                    return await websocket.receive_text()
                except (WebSocketDisconnect, RuntimeError):
                    raise _ClientGone from None
            return None

        async def client_to_isl() -> None:
            nonlocal bytes_in, last_activity
            while True:
                if expired():
                    return
                try:
                    raw = await receive_client_text()
                except _ClientGone:
                    return
                if raw is None:
                    if idle():
                        return
                    continue
                last_activity = time.monotonic()
                if bytes_in > max_bytes or len(raw.encode("utf-8", "ignore")) > max_msg_bytes * 4:
                    try:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": "Stream budget exceeded; reopen to continue.",
                            }
                        )
                    except (RuntimeError, WebSocketDisconnect):
                        pass
                    return
                bytes_in += len(raw.encode("utf-8", "ignore"))
                try:
                    msg = json.loads(raw)
                except ValueError:
                    await _send_error(websocket, "invalid JSON")
                    continue
                try:
                    clean = validate_client_message(msg, kind=kind, max_frame_bytes=max_msg_bytes)
                except ValueError as exc:
                    await _send_error(websocket, f"bad message: {exc}")
                    continue
                if clean.get("type") == "control":
                    if clean.get("action") == "reset":
                        for key in list(accumulator.sentences):
                            del accumulator.sentences[key]
                        accumulator.order.clear()
                        accumulator.latest_glosses = []
                    try:
                        await isl.send(json.dumps(clean))
                    except Exception:
                        return
                    continue
                if not throttle.allow():
                    continue
                try:
                    await isl.send(json.dumps(clean))
                except Exception:
                    return

        async def isl_to_client() -> None:
            nonlocal last_activity
            while True:
                if expired():
                    return
                with anyio.move_on_after(2.0):
                    try:
                        raw = await isl.recv()
                    except Exception:
                        return
                    last_activity = time.monotonic()
                    if isinstance(raw, (bytes, bytearray)):
                        continue
                    msg = raw if isinstance(raw, dict) else _parse_json(raw)
                    if not isinstance(msg, dict):
                        continue
                    if msg.get("type") == "update":
                        accumulator.add_snapshot(msg)
                    elif msg.get("type") != "error":
                        continue
                    try:
                        await websocket.send_json(msg)
                    except (RuntimeError, WebSocketDisconnect):
                        return
                    continue
                if idle():
                    return

        # An outer cancellation (server shutdown, or the test harness closing
        # the socket) raises here with the draft still unsaved. Swallow only
        # cancellation and fall through: the shielded wrap-up below must run
        # either way. A shield alone would not do — it blocks *new*
        # cancellation but never runs its body for an in-flight one.
        try:
            async with anyio.create_task_group() as relay:

                async def _uplink() -> None:
                    try:
                        await client_to_isl()
                    finally:
                        relay.cancel_scope.cancel()

                async def _downlink() -> None:
                    try:
                        await isl_to_client()
                    finally:
                        relay.cancel_scope.cancel()

                relay.start_soon(_uplink)
                relay.start_soon(_downlink)
        except anyio.get_cancelled_exc_class():
            # Outer scope cancelled (server shutdown, or the socket closing
            # under us) — fall through to the shielded wrap-up below.
            pass

        # Shield the wrap-up so a server shutdown racing the disconnect still
        # leaves a fetchable draft behind.
        with anyio.CancelScope(shield=True):
            await _finish_draft(stream_id, kind, accumulator, completed=True)
            try:
                await websocket.send_json(
                    {
                        "type": "done",
                        "stream_id": stream_id,
                        "transcript": accumulator.transcript,
                        "sentences": accumulator.ordered_sentences,
                        "frames_seen": accumulator.frames_seen,
                        "duration_ms": accumulator.duration_ms,
                    }
                )
            except (RuntimeError, WebSocketDisconnect):
                pass
            try:
                await websocket.close(code=1000)
            except (RuntimeError, WebSocketDisconnect):
                pass
    finally:
        if isl is not None:
            try:
                await isl.close()
            except Exception:  # noqa: S110
                pass
        await limiter.release(kind, ip)


class _ClientGone(Exception):
    """The phone hung up; unwinds the relay without an error frame."""


def _parse_json(raw: object) -> object:
    try:
        return json.loads(raw)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None


async def _send_error(websocket: WebSocket, message: str) -> None:
    try:
        await websocket.send_json({"type": "error", "message": message})
    except (RuntimeError, WebSocketDisconnect):
        pass


async def _finish_draft(
    stream_id: str, kind: str, accumulator: DraftAccumulator, *, completed: bool
) -> None:
    try:
        async with SessionLocal() as db:
            draft = await db.scalar(select(StreamDraft).where(StreamDraft.stream_id == stream_id))
            if draft is None:
                return
            draft.kind = kind
            draft.transcript = accumulator.transcript
            draft.sentences = accumulator.ordered_sentences
            draft.safety_events = accumulator.safety_events
            draft.frames_seen = accumulator.frames_seen
            draft.duration_ms = accumulator.duration_ms
            draft.completed = completed
            await db.commit()
    except Exception:
        log.exception("stream %s: draft finish failed", stream_id)
