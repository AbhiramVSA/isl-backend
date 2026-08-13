import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import get_db
from app.dependencies import Principal, current_principal, require_officer, require_user
from app.models import AuditLog, ReportHistory, StreamSession
from app.schemas import StreamState
from app.services.realtime import realtime_hub
from app.services.reports import get_report

router = APIRouter(tags=["Live video"])


async def session_for(db: AsyncSession, report_id: int, room_name: str) -> StreamSession:
    session = await db.scalar(select(StreamSession).where(StreamSession.report_id == report_id))
    if not session:
        session = StreamSession(report_id=report_id, room_name=room_name)
        db.add(session)
        await db.flush()
    return session


def authorize(report, principal: Principal, user_owner: bool = True) -> None:
    if principal.user and user_owner and report.user_id == principal.user.id:
        return
    if principal.officer and report.office_id in principal.office_ids:
        return
    if principal.account.role.value == "ADMIN":
        return
    raise HTTPException(
        status_code=403, detail="You do not have access to live video for this report"
    )


def livekit_token(room: str, identity: str, can_publish: bool) -> str:
    try:
        from livekit import api

        grant = api.VideoGrants(
            room_join=True, room=room, can_publish=can_publish, can_subscribe=True
        )
        return (
            api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
            .with_identity(identity)
            .with_grants(grant)
            .to_jwt()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Live video is currently unavailable") from exc


async def start_recording(session: StreamSession, public_id: str) -> bool:
    """Start server-side MP4 recording when the development egress worker is available."""
    if settings.environment == "test":
        return False
    try:
        from livekit import api

        filename = f"{public_id}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.mp4"
        client = api.LiveKitAPI(
            settings.livekit_url.replace("ws://", "http://").replace("wss://", "https://"),
            settings.livekit_api_key,
            settings.livekit_api_secret,
        )
        try:
            # The room must exist before recording is requested; the phone joins it immediately after.
            await client.room.create_room(api.CreateRoomRequest(name=session.room_name))
            result = await asyncio.wait_for(
                client.egress.start_room_composite_egress(
                    api.RoomCompositeEgressRequest(
                        room_name=session.room_name,
                        layout="speaker-dark",
                        file_outputs=[
                            api.EncodedFileOutput(
                                file_type=api.EncodedFileType.MP4,
                                filepath=f"/out/{filename}",
                            )
                        ],
                    )
                ),
                timeout=8,
            )
        finally:
            await client.aclose()
        session.egress_id = result.egress_id
        session.recording_key = filename
        return True
    except Exception:
        # The emergency and live feed must still start if the optional recorder is unavailable.
        return False


async def stop_recording(session: StreamSession) -> None:
    if not session.egress_id:
        return
    try:
        from livekit import api

        client = api.LiveKitAPI(
            settings.livekit_url.replace("ws://", "http://").replace("wss://", "https://"),
            settings.livekit_api_key,
            settings.livekit_api_secret,
        )
        try:
            await client.egress.stop_egress(api.StopEgressRequest(egress_id=session.egress_id))
        finally:
            await client.aclose()
    except Exception:
        # Ending the user's live session must not fail if the recorder already stopped.
        return


@router.post(
    "/officer/reports/{public_id}/stream/request",
    response_model=StreamState,
    summary="Ask the reporter to share live video",
)
async def request_video(
    public_id: str,
    principal: Principal = Depends(require_officer),
    db: AsyncSession = Depends(get_db),
) -> StreamState:
    report = await get_report(db, public_id)
    authorize(report, principal, False)
    session = await session_for(db, report.id, f"report-{report.public_id}")
    session.requested_at = datetime.now(UTC)
    db.add(
        AuditLog(
            actor_type="OFFICER",
            actor_id=principal.officer.id if principal.officer else None,
            action="VIDEO_REQUESTED",
            target_type="REPORT",
            target_id=public_id,
        )
    )
    await db.commit()
    await realtime_hub.user_event(
        report.user_id,
        {
            "type": "video.requested",
            "report_id": public_id,
            "message": "An officer is asking to see your signing by live video. Your camera will only start if you accept.",
        },
    )
    return StreamState(available=True, active=False, requested=True)


@router.post(
    "/reports/{public_id}/stream/start",
    response_model=StreamState,
    summary="Start live video after user consent",
)
async def start_video(
    public_id: str, principal: Principal = Depends(require_user), db: AsyncSession = Depends(get_db)
) -> StreamState:
    report = await get_report(db, public_id)
    authorize(report, principal)
    session = await session_for(db, report.id, f"report-{report.public_id}")
    session.active = True
    session.started_at = datetime.now(UTC)
    db.add(
        ReportHistory(
            report_id=report.id,
            actor_type="USER",
            actor_id=principal.user.id,
            event="VIDEO_STARTED",
            new_status=report.status.value,
            event_metadata={},
        )
    )  # type: ignore[union-attr]
    await db.commit()
    await realtime_hub.office_event(
        report.office_id, {"type": "stream.started", "report_id": public_id}
    )
    token = livekit_token(session.room_name, f"user-{principal.user.id}", True)  # type: ignore[union-attr]
    return StreamState(
        available=True,
        active=True,
        requested=bool(session.requested_at),
        recording=False,
        viewer_url=settings.livekit_url,
        access_token=token,
    )


@router.post(
    "/reports/{public_id}/stream/record",
    response_model=StreamState,
    summary="Record an active emergency video",
)
async def record_video(
    public_id: str, principal: Principal = Depends(require_user), db: AsyncSession = Depends(get_db)
) -> StreamState:
    report = await get_report(db, public_id)
    authorize(report, principal)
    session = await session_for(db, report.id, f"report-{report.public_id}")
    if not session.active:
        raise HTTPException(status_code=409, detail="Start the live video before recording")
    recording = bool(session.egress_id) or await start_recording(session, public_id)
    await db.commit()
    return StreamState(
        available=True,
        active=True,
        requested=bool(session.requested_at),
        recording=recording,
    )


@router.post(
    "/reports/{public_id}/stream/stop", response_model=StreamState, summary="Stop live video"
)
async def stop_video(
    public_id: str, principal: Principal = Depends(require_user), db: AsyncSession = Depends(get_db)
) -> StreamState:
    report = await get_report(db, public_id)
    authorize(report, principal)
    session = await session_for(db, report.id, f"report-{report.public_id}")
    session.active = False
    session.stopped_at = datetime.now(UTC)
    await stop_recording(session)
    db.add(
        ReportHistory(
            report_id=report.id,
            actor_type="USER",
            actor_id=principal.user.id,
            event="VIDEO_STOPPED",
            new_status=report.status.value,
            event_metadata={},
        )
    )  # type: ignore[union-attr]
    await db.commit()
    await realtime_hub.office_event(
        report.office_id, {"type": "stream.stopped", "report_id": public_id}
    )
    recording_available = bool(
        session.recording_key and (settings.recording_dir / session.recording_key).is_file()
    )
    return StreamState(
        available=True,
        active=False,
        requested=bool(session.requested_at),
        recording_available=recording_available,
    )


@router.get(
    "/reports/{public_id}/stream", response_model=StreamState, summary="Get live video availability"
)
async def get_stream(
    public_id: str,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> StreamState:
    report = await get_report(db, public_id)
    authorize(report, principal)
    session = await db.scalar(select(StreamSession).where(StreamSession.report_id == report.id))
    if not session:
        return StreamState(available=True, active=False, requested=False)
    token = None
    if session.active and principal.officer:
        token = livekit_token(session.room_name, f"officer-{principal.officer.id}", False)
        db.add(
            AuditLog(
                actor_type="OFFICER",
                actor_id=principal.officer.id,
                action="LIVE_VIDEO_VIEWED",
                target_type="REPORT",
                target_id=public_id,
            )
        )
        await db.commit()
    return StreamState(
        available=True,
        active=session.active,
        requested=bool(session.requested_at),
        recording=bool(session.active and session.egress_id),
        recording_available=bool(
            session.recording_key and (settings.recording_dir / session.recording_key).is_file()
        ),
        viewer_url=settings.livekit_url if session.active else None,
        access_token=token,
    )


@router.get(
    "/officer/reports/{public_id}/recording",
    summary="Play the saved emergency video",
)
async def get_recording(
    public_id: str,
    principal: Principal = Depends(require_officer),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    report = await get_report(db, public_id)
    authorize(report, principal, False)
    session = await db.scalar(select(StreamSession).where(StreamSession.report_id == report.id))
    if not session or not session.recording_key:
        raise HTTPException(status_code=404, detail="A saved video is not available yet")
    recording = settings.recording_dir / session.recording_key
    if not recording.is_file():
        raise HTTPException(status_code=404, detail="The video is still being prepared")
    return FileResponse(recording, media_type="video/mp4", filename=recording.name)
