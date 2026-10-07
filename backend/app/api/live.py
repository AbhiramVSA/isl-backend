"""Responder-side access to live Equal app camera streams (see services/live_relay.py)."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.permissions import STAFF_ROLES, Permission, permissions_for
from app.core.security import decode_token
from app.db import SessionLocal, get_db
from app.dependencies import Principal, require_officer
from app.models import Account, AccountStatus, AuditLog, ReportMedia
from app.services.live_relay import live_hub, motion_key
from app.services.reports import get_report
from app.services.stream_media import UPLOADED_BY

router = APIRouter(tags=["Live sign video"])


def _session_or_404(stream_id: str):
    session = live_hub.get(stream_id)
    if session is None:
        raise HTTPException(status_code=404, detail="This stream is no longer available")
    return session


@router.get("/officer/live", summary="Callers signing right now, and streams that just ended")
async def list_live(_principal: Principal = Depends(require_officer)) -> list[dict]:
    return live_hub.listing()


@router.get("/officer/live/{stream_id}", summary="One stream's state")
async def live_detail(stream_id: str, _principal: Principal = Depends(require_officer)) -> dict:
    return _session_or_404(stream_id).summary()


@router.get("/officer/live/{stream_id}/segment", summary="Frames for rewinding a stream")
async def live_segment(
    stream_id: str,
    start_ms: float = Query(0, ge=0),
    duration_ms: float = Query(4000, gt=0, le=20000),
    _principal: Principal = Depends(require_officer),
) -> dict:
    session = _session_or_404(stream_id)
    return {
        "duration_ms": session.duration_ms,
        "live": session.live,
        "frames": live_hub.segment(session, start_ms, duration_ms),
    }


@router.get("/officer/live/{stream_id}/motion", summary="Phone movement recorded so far")
async def live_motion(stream_id: str, _principal: Principal = Depends(require_officer)) -> dict:
    return _session_or_404(stream_id).motion_track()


@router.get(
    "/officer/reports/{public_id}/motion",
    summary="Phone movement recorded while the report was signed, if any",
)
async def report_motion(
    public_id: str,
    principal: Principal = Depends(require_officer),
    db: AsyncSession = Depends(get_db),
) -> dict | None:
    report = await get_report(db, public_id)
    if not principal.can_access_office(report.office_id):
        raise HTTPException(status_code=403, detail="You do not have access to this report")
    key = await db.scalar(
        select(ReportMedia.storage_key).where(
            ReportMedia.report_id == report.id, ReportMedia.uploaded_by == UPLOADED_BY
        )
    )
    if not key:
        return None
    stream_id = key.removeprefix("streams/").removesuffix(".mp4")
    session = live_hub.get(stream_id)
    if session and session.motion:
        return session.motion_track()
    path = settings.upload_dir / motion_key(stream_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text())


@router.get(
    "/officer/reports/{public_id}/live",
    summary="The live stream this report was signed on, while it is still available",
)
async def report_live(
    public_id: str,
    principal: Principal = Depends(require_officer),
    db: AsyncSession = Depends(get_db),
) -> dict | None:
    report = await get_report(db, public_id)
    if not principal.can_access_office(report.office_id):
        raise HTTPException(status_code=403, detail="You do not have access to this report")
    for session in live_hub.sessions.values():
        if session.report_public_id == public_id:
            return session.summary()
    key = await db.scalar(
        select(ReportMedia.storage_key).where(
            ReportMedia.report_id == report.id, ReportMedia.uploaded_by == UPLOADED_BY
        )
    )
    if key:
        stream_id = key.removeprefix("streams/").removesuffix(".mp4")
        session = live_hub.get(stream_id)
        if session:
            return session.summary()
    return None


@router.websocket("/ws/live/{stream_id}")
async def live_socket(websocket: WebSocket, stream_id: str) -> None:
    """Frames and captions as they arrive. Auth by ``access_token`` query param."""
    try:
        payload = decode_token(websocket.query_params.get("access_token") or "")
        async with SessionLocal() as db:
            account = await db.get(Account, int(payload["sub"]))
            if (
                not account
                or account.status != AccountStatus.ACTIVE
                or account.role.value != payload.get("role")
                or account.role not in STAFF_ROLES
                or Permission.REPORTS_VIEW not in permissions_for(account.role)
            ):
                raise ValueError("forbidden")
            db.add(
                AuditLog(
                    actor_type=account.role.value,
                    actor_id=account.id,
                    action="LIVE_STREAM_VIEWED",
                    target_type="STREAM",
                    target_id=stream_id,
                )
            )
            await db.commit()
    except Exception:
        await websocket.close(code=4401)
        return
    session = live_hub.get(stream_id)
    if session is None:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    try:
        await live_hub.add_viewer(session, websocket)
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        live_hub.remove_viewer(session, websocket)
