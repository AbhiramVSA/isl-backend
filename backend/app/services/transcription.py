from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fastapi import HTTPException

REPO_ROOT = Path(__file__).resolve().parents[3]
EXP1_DIR = REPO_ROOT / "exp1"
INFERENCE_SCRIPT = EXP1_DIR / "infer_video.py"
CHECKPOINT = EXP1_DIR / "best_classifier.pt"
HOLISTIC_MODEL = EXP1_DIR / ".models" / "holistic_landmarker.task"
EXP1_PYTHON = EXP1_DIR / ".venv" / "bin" / "python"


def model_ready() -> bool:
    return all(path.is_file() for path in (INFERENCE_SCRIPT, CHECKPOINT, HOLISTIC_MODEL, EXP1_PYTHON))


async def transcribe_video(video_path: Path) -> dict:
    if not model_ready():
        raise HTTPException(status_code=503, detail="The sign transcription model is not installed.")

    environment = os.environ.copy()
    environment.setdefault("MPLCONFIGDIR", "/tmp/sign-response-matplotlib")
    process = await asyncio.create_subprocess_exec(
        str(EXP1_PYTHON),
        str(INFERENCE_SCRIPT),
        str(video_path),
        "--checkpoint",
        str(CHECKPOINT),
        "--holistic-model",
        str(HOLISTIC_MODEL),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(EXP1_DIR),
        env=environment,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
    except TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise HTTPException(status_code=504, detail="Sign transcription took too long.") from exc

    if process.returncode != 0:
        last_line = stderr.decode(errors="replace").strip().splitlines()[-1:]
        if last_line and "enough readable frames" in last_line[0]:
            detail = "No clear signing was found. Keep your upper body and hands in view."
        elif last_line and "could not be opened" in last_line[0]:
            detail = "The sign model could not open this video format."
        else:
            detail = "The sign model could not read this clip."
        raise HTTPException(status_code=422, detail=detail)

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="The sign model returned an invalid result.") from exc
