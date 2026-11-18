"""Attach a live-stream recording to the report it belongs to.

The phone files its report after the stream closes and names the stream it
came from (``stream_id`` plus the ``draft_token`` from the socket hello, so a
caller cannot claim someone else's video). The MP4 may still be encoding at
that moment, so the link is stored first and the size filled in when the file
lands — the console only lists videos whose file exists.
"""

from __future__ import annotations

import logging
import shutil

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import SessionLocal
from app.models import Report, ReportHistory, ReportMedia, StreamDraft
from app.services.isl_stream import tokens_match
from app.services.live_relay import live_hub, motion_key, recording_key, streams_dir
from app.services.realtime import realtime_hub

log = logging.getLogger(__name__)

UPLOADED_BY = "live-stream"


async def link_stream(
    db: AsyncSession, report: Report, stream_id: str | None, stream_token: str | None
) -> bool:
    """Record that ``report`` was signed on ``stream_id``. Caller commits."""
    if not stream_id or not stream_token:
        return False
    draft = await db.scalar(select(StreamDraft).where(StreamDraft.stream_id == stream_id))
    if draft is None or draft.kind != "video" or not tokens_match(stream_token, draft.secret_hash):
        return False
    key = recording_key(stream_id)
    if await db.scalar(select(ReportMedia.id).where(ReportMedia.storage_key == key)):
        return False  # already attached to a report
    path = settings.upload_dir / key
    db.add_all(
        [
            ReportMedia(
                report_id=report.id,
                uploaded_by=UPLOADED_BY,
                media_type="video",
                storage_key=key,
                mime_type="video/mp4",
                size=path.stat().st_size if path.is_file() else 0,
            ),
            ReportHistory(
                report_id=report.id,
                actor_type="SYSTEM",
                actor_id=None,
                event="SIGN_VIDEO_ATTACHED",
                new_status=report.status.value,
                event_metadata={"stream_id": stream_id, "duration_ms": draft.duration_ms},
            ),
        ]
    )
    live_hub.link_report(stream_id, report.public_id)
    return True


async def attach_recording_if_linked(stream_id: str) -> None:
    """Called when the MP4 finishes encoding; fills in the size and tells the console."""
    key = recording_key(stream_id)
    path = settings.upload_dir / key
    if not path.is_file():
        return
    try:
        async with SessionLocal() as db:
            media = await db.scalar(select(ReportMedia).where(ReportMedia.storage_key == key))
            if media is None:
                return
            media.size = path.stat().st_size
            report = await db.get(Report, media.report_id)
            await db.commit()
            if report:
                await realtime_hub.office_event(
                    report.office_id,
                    {"type": "report.updated", "report_id": report.public_id, "video": True},
                )
    except Exception:
        log.exception("live %s: attaching recording failed", stream_id)


async def discard_stream_media(db: AsyncSession, stream_id: str, *, keep_if_linked: bool) -> bool:
    """Delete a stream's frames and MP4 and drop it from the live list.

    Returns False (and deletes nothing) when the stream is attached to a report
    and ``keep_if_linked`` is set.
    """
    key = recording_key(stream_id)
    linked = await db.scalar(select(ReportMedia.id).where(ReportMedia.storage_key == key))
    if linked and keep_if_linked:
        # The report keeps the MP4; the raw frames are only needed for live rewinding.
        if live_hub.get(stream_id) is None:
            shutil.rmtree(streams_dir() / stream_id, ignore_errors=True)
        return False
    await live_hub.discard(stream_id)
    shutil.rmtree(streams_dir() / stream_id, ignore_errors=True)
    (settings.upload_dir / key).unlink(missing_ok=True)
    (settings.upload_dir / motion_key(stream_id)).unlink(missing_ok=True)
    return True
