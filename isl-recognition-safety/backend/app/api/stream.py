"""WebSocket streaming endpoint: landmarks (or JPEG frames) in, pipeline snapshots out."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from typing import Any

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import settings
from ..landmarks.frame import LandmarkFrame
from ..pipeline import SessionPipeline
from .state import state

log = logging.getLogger(__name__)
router = APIRouter()

MAX_UPDATE_HZ = 10.0


@router.websocket("/ws/stream")
async def stream(ws: WebSocket) -> None:
    await ws.accept()
    session_id = uuid.uuid4().hex[:8]
    loop = asyncio.get_running_loop()
    pending_polish: asyncio.Queue = asyncio.Queue()

    def on_polished(s):  # runs in a worker thread
        loop.call_soon_threadsafe(pending_polish.put_nowait, s.id)

    pipeline = SessionPipeline(state.registry, state.polisher, on_sentence_polished=on_polished)
    extractor = None
    last_sent = 0.0
    latest: dict[str, Any] | None = None
    await ws.send_text(json.dumps({"type": "hello", "session_id": session_id, "device": state.registry.device.type,
                                   "models": state.registry.health(),
                                   "llm": state.polisher.status() if state.polisher else {"provider": "none", "available": False, "model": None, "error": None}}))
    log.info("ws session %s opened", session_id)

    async def send_update(snap: dict[str, Any]) -> None:
        await ws.send_text(json.dumps({"type": "update", **snap}, allow_nan=False))

    try:
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=1.0)
            except asyncio.TimeoutError:
                # push polished sentences / keep the client fresh while idle
                if not pending_polish.empty():
                    while not pending_polish.empty():
                        pending_polish.get_nowait()
                    snap = pipeline.snapshot()
                    if snap:
                        await send_update(snap)
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({"type": "error", "message": "invalid JSON"}))
                continue
            mtype = msg.get("type")
            try:
                if mtype == "landmarks":
                    frame = LandmarkFrame.from_message(msg)
                elif mtype == "frame":
                    if extractor is None:
                        from ..landmarks.holistic import HolisticExtractor
                        extractor = HolisticExtractor(settings.models_dir / "mediapipe" / "holistic_landmarker.task")
                    import cv2
                    data = base64.b64decode(msg["jpeg"])
                    bgr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                    if bgr is None:
                        raise ValueError("could not decode JPEG frame")
                    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                    frame = await asyncio.to_thread(extractor.process, rgb, float(msg["t_ms"]))
                elif mtype == "control":
                    action = msg.get("action")
                    if action == "reset":
                        pipeline.reset()
                        await ws.send_text(json.dumps({"type": "update", **_empty_snapshot(pipeline)}))
                    elif action == "end_sentence":
                        pipeline.end_sentence()
                        snap = pipeline.snapshot()
                        if snap:
                            await send_update(snap)
                    elif action == "config":
                        pipeline.configure(msg.get("llm_enabled"), msg.get("min_confidence"))
                    else:
                        await ws.send_text(json.dumps({"type": "error", "message": f"unknown control action {action!r}"}))
                    continue
                else:
                    await ws.send_text(json.dumps({"type": "error", "message": f"unknown message type {mtype!r}"}))
                    continue
            except Exception as e:  # noqa: BLE001
                await ws.send_text(json.dumps({"type": "error", "message": f"bad message: {type(e).__name__}: {e}"}))
                continue

            latest = await asyncio.to_thread(pipeline.process, frame)
            now = time.time()
            if now - last_sent >= 1.0 / MAX_UPDATE_HZ or latest["window"] and latest["window"].get("final"):
                last_sent = now
                await send_update(latest)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("ws session %s crashed", session_id)
        try:
            await ws.send_text(json.dumps({"type": "error", "message": "internal error; see server log"}))
        except Exception:  # noqa: BLE001
            pass
    finally:
        if extractor:
            extractor.close()
        log.info("ws session %s closed after %d frames", session_id, pipeline.frames_seen)


def _empty_snapshot(pipeline: SessionPipeline) -> dict[str, Any]:
    return {"t_ms": 0, "vision": {"pose": False, "left_hand": False, "right_hand": False, "face": False, "fps_in": 0, "quality": 0},
            "gate": {"state": "IDLE", "energy": 0, "segment_ms": 0, "rest_ms": 0}, "window": None, "glosses": [],
            "sentences": [], "safety": pipeline.safety.state_json(), "safety_events": []}
