"""Client for the shared ISL recognition + safety service."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException

from app.core.config import settings


def _transcription(result: dict[str, Any]) -> dict[str, Any]:
    glosses = result.get("glosses") or []
    sentences = result.get("sentences") or []
    words = []
    for gloss in glosses:
        label = gloss.get("display") or gloss.get("label") or "UNKNOWN"
        start = float(gloss.get("t_start_ms", 0)) / 1000
        end = float(gloss.get("t_end_ms", gloss.get("t_start_ms", 0))) / 1000
        confidence = max(0.0, min(1.0, float(gloss.get("p", 0))))
        # The existing sign-lang contract reserves ``landmarks`` for numeric
        # measurements. The safety pipeline's textual status belongs in its
        # richer result, not in this legacy numeric map.
        words.append({"word": label, "confidence": confidence, "start_seconds": start,
                      "end_seconds": end, "alternatives": [], "landmarks": {}})
    sentence_text = [s.get("text", "") for s in sentences if s.get("text")]
    transcript = " ".join(sentence_text).strip() or " ".join(w["word"] for w in words)
    return {"transcript": transcript, "words": words, "model": "isl-recognition-safety",
            "safety": result.get("safety"), "safety_events": result.get("safety_events", []),
            "sentences": sentences}


async def transcribe_video(video_path: Path) -> dict[str, Any]:
    base = settings.isl_recognition_url.rstrip("/")
    timeout = httpx.Timeout(settings.isl_recognition_timeout_seconds, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            with video_path.open("rb") as video:
                response = await client.post(f"{base}/api/analyze",
                                             files={"file": (video_path.name, video, "video/mp4")})
            response.raise_for_status()
            job_id = response.json()["job_id"]
            deadline = asyncio.get_running_loop().time() + settings.isl_recognition_timeout_seconds
            while True:
                if asyncio.get_running_loop().time() >= deadline:
                    raise HTTPException(status_code=504, detail="Sign recognition took too long.")
                status = (await client.get(f"{base}/api/analyze/{job_id}")).json()
                if status.get("state") == "done":
                    return _transcription(status.get("result") or {})
                if status.get("state") == "error":
                    raise HTTPException(status_code=422, detail=status.get("error") or "The sign model could not read this clip.")
                await asyncio.sleep(settings.isl_recognition_poll_seconds)
    except HTTPException:
        raise
    except (httpx.HTTPError, OSError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="The ISL recognition service is unavailable.") from exc
