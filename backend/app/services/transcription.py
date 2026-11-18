from __future__ import annotations

from pathlib import Path

from .isl_recognition import transcribe_video as transcribe_with_safety_model


def model_ready() -> bool:
    # The recognition weights live in the separate isl service. The API
    # container cannot inspect them directly; the service call is the
    # authoritative runtime check when a clip is submitted.
    return True


async def transcribe_video(video_path: Path) -> dict:
    return await transcribe_with_safety_model(video_path)
