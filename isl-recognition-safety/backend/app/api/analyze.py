"""Uploaded-video analysis: decode -> HolisticLandmarker (server) -> the same SessionPipeline."""
from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import cv2
from fastapi import APIRouter, File, HTTPException, UploadFile

from ..config import settings
from ..landmarks.holistic import HolisticExtractor
from ..pipeline import SessionPipeline
from .state import state

log = logging.getLogger(__name__)
router = APIRouter()

ALLOWED = {".mp4", ".mov", ".avi", ".webm", ".mkv", ".m4v"}


class Job:
    def __init__(self, job_id: str, path: str, filename: str):
        self.job_id, self.path, self.filename = job_id, path, filename
        self.state = "queued"
        self.progress = 0.0
        self.error: str | None = None
        self.result: dict[str, Any] | None = None
        self.created = time.time()

    def to_json(self) -> dict[str, Any]:
        return {"job_id": self.job_id, "state": self.state, "progress": round(self.progress, 3),
                "error": self.error, "result": self.result, "filename": self.filename}


def _run(job: Job) -> None:
    job.state = "running"
    cap = None
    extractor = None
    try:
        if not state.registry.holistic_ok:
            raise RuntimeError(state.registry.holistic_error or "HolisticLandmarker unavailable")
        cap = cv2.VideoCapture(job.path)
        if not cap.isOpened():
            raise RuntimeError("could not open video (unsupported codec or corrupt file)")
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        if not (1.0 <= fps <= 240.0):
            fps = 25.0
        n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        step = max(1, int(round(fps / 30.0)))  # cap processing at ~30 fps
        extractor = HolisticExtractor(settings.models_dir / "mediapipe" / "holistic_landmarker.task")
        pipeline = SessionPipeline(state.registry, state.polisher, async_llm=False)
        timeline: list[dict[str, Any]] = []
        lm_frames: list[dict[str, Any]] = []
        last_sig = None
        i = 0
        processed = 0
        t_first = time.time()
        while True:
            ok, bgr = cap.read()
            if not ok:
                break
            if i % step:
                i += 1
                continue
            t_ms = i * 1000.0 / fps
            h, w = bgr.shape[:2]
            if w > settings.upload_max_width:
                bgr = cv2.resize(bgr, (settings.upload_max_width, int(h * settings.upload_max_width / w)))
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            frame = extractor.process(rgb, t_ms)
            snap = pipeline.process(frame)
            lm_frames.append(frame.to_json())
            sig = (len(snap["glosses"]), len(snap["sentences"]), snap["safety"]["status"], snap["gate"]["state"],
                   snap["window"]["t_end_ms"] if snap["window"] else None, len(snap["safety_events"]))
            if sig != last_sig or processed % 5 == 0:
                timeline.append(snap)
                last_sig = sig
            processed += 1
            i += 1
            if n_total:
                job.progress = min(0.98, i / n_total)
        pipeline.finish()
        final = pipeline.snapshot()
        if final:
            timeline.append(final)
        duration = i / fps
        job.result = {
            "duration_s": round(duration, 2), "fps": round(fps, 2), "frames": processed, "width": width, "height": height,
            "processing_s": round(time.time() - t_first, 1),
            "timeline": timeline,
            "glosses": [g for s in (final["sentences"] if final else []) for g in s["glosses"]] + (final["glosses"] if final else []),
            "sentences": final["sentences"] if final else [],
            "safety": final["safety"] if final else None,
            "safety_events": final["safety_events"] if final else [],
            "landmark_frames": lm_frames,
        }
        job.progress, job.state = 1.0, "done"
    except Exception as e:  # noqa: BLE001
        log.exception("analysis job %s failed", job.job_id)
        job.state, job.error = "error", f"{type(e).__name__}: {e}"
    finally:
        if cap is not None:
            cap.release()
        if extractor is not None:
            extractor.close()
        try:
            os.remove(job.path)
        except OSError:
            pass


@router.post("/api/analyze", status_code=202)
async def analyze(file: UploadFile = File(...)) -> dict[str, Any]:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(400, f"unsupported file type {ext!r}; use one of {sorted(ALLOWED)}")
    if not state.registry.holistic_ok:
        raise HTTPException(503, f"server-side landmark extraction unavailable: {state.registry.holistic_error}")
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    size = 0
    limit = settings.max_upload_mb * 1024 * 1024
    try:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > limit:
                raise HTTPException(413, f"file larger than {settings.max_upload_mb} MB")
            tmp.write(chunk)
    finally:
        tmp.close()
    if size == 0:
        os.remove(tmp.name)
        raise HTTPException(400, "empty upload")
    job = Job(uuid.uuid4().hex[:12], tmp.name, file.filename or "video")
    state.jobs[job.job_id] = job
    # prune old jobs
    for jid in [j for j, jb in state.jobs.items() if time.time() - jb.created > 3600]:
        state.jobs.pop(jid, None)
    threading.Thread(target=_run, args=(job,), daemon=True).start()
    return {"job_id": job.job_id}


@router.get("/api/analyze/{job_id}")
async def analyze_status(job_id: str) -> dict[str, Any]:
    job = state.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job id")
    return job.to_json()
