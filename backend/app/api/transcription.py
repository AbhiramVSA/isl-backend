from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import get_db
from app.dependencies import Principal, require_officer, require_user
from app.models import ReportHistory, StreamSession
from app.services.realtime import realtime_hub
from app.services.reports import get_report
from app.services.transcription import HOLISTIC_MODEL, transcribe_video


class Alternative(BaseModel):
    word: str
    confidence: float = Field(ge=0, le=1)


class TranscribedWord(BaseModel):
    word: str
    confidence: float = Field(ge=0, le=1)
    start_seconds: float
    end_seconds: float
    alternatives: list[Alternative]
    landmarks: dict[str, float | int]


class SignTranscription(BaseModel):
    transcript: str
    words: list[TranscribedWord]
    model: str


router = APIRouter(tags=["Sign transcription"])
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/webm", "video/quicktime"}
VIDEO_SUFFIXES = {"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov"}


@router.get("/officer/transcription/model", response_class=FileResponse, include_in_schema=False)
async def get_holistic_model(
    _principal: Principal = Depends(require_officer),
) -> FileResponse:
    if not HOLISTIC_MODEL.is_file():
        raise HTTPException(status_code=503, detail="The landmark model is not installed.")
    return FileResponse(
        HOLISTIC_MODEL,
        media_type="application/octet-stream",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.post(
    "/reports/{public_id}/transcription",
    response_model=SignTranscription,
    summary="Transcribe the user's saved emergency video",
)
async def transcribe_saved_video(
    public_id: str,
    principal: Principal = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> SignTranscription:
    report = await get_report(db, public_id)
    if not principal.user or report.user_id != principal.user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this recording.")
    session = await db.scalar(select(StreamSession).where(StreamSession.report_id == report.id))
    if not session or not session.recording_key:
        raise HTTPException(
            status_code=409, detail="No saved video is available for transcription."
        )
    if session.active:
        raise HTTPException(status_code=409, detail="End the video before starting transcription.")
    recording = settings.recording_dir / session.recording_key
    if not recording.is_file():
        raise HTTPException(
            status_code=409,
            detail="The saved video is still being prepared. Try again in a moment.",
        )

    result = SignTranscription.model_validate(await transcribe_video(recording))
    db.add(
        ReportHistory(
            report_id=report.id,
            actor_type="USER",
            actor_id=principal.user.id,
            event="SIGN_TRANSCRIBED",
            new_status=report.status.value,
            event_metadata=result.model_dump(mode="json"),
        )
    )
    await db.commit()
    await realtime_hub.office_event(
        report.office_id,
        {"type": "transcription.ready", "report_id": public_id},
    )
    return result


@router.post(
    "/officer/transcription",
    response_model=SignTranscription,
    summary="Try to transcribe a signing clip",
)
async def create_transcription(
    video: UploadFile = File(...),
    _principal: Principal = Depends(require_officer),
) -> SignTranscription:
    if video.content_type not in ALLOWED_VIDEO_TYPES:
        raise HTTPException(status_code=415, detail="Upload an MP4, WebM, or QuickTime video.")

    suffix = VIDEO_SUFFIXES[video.content_type]
    temp_path: Path | None = None
    total = 0
    try:
        with NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            temp_path = Path(temporary.name)
            while chunk := await video.read(1024 * 1024):
                total += len(chunk)
                if total > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail="The signing clip is too large.")
                temporary.write(chunk)
        if total == 0:
            raise HTTPException(status_code=422, detail="The signing clip is empty.")
        return SignTranscription.model_validate(await transcribe_video(temp_path))
    finally:
        await video.close()
        if temp_path:
            temp_path.unlink(missing_ok=True)
