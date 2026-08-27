from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db import get_db
from app.dependencies import Principal, require_officer
from app.models import (
    AuditLog,
    OfficeMembership,
    Priority,
    Report,
    ReportHistory,
    ReportLocation,
    ReportMedia,
    ReportStatus,
    StreamSession,
    User,
)
from app.schemas import (
    HistoryOut,
    LocationOut,
    PaginatedReports,
    RelatedReport,
    RelatedReports,
    ReporterDetails,
    ReportOut,
    ReportVideoOut,
)
from app.services.realtime import realtime_hub
from app.services.reports import (
    REPORT_LOAD,
    get_report,
    report_outputs_with_transcripts,
    transition_report,
)
from app.services.routing_service import haversine_km

router = APIRouter(prefix="/officer", tags=["Officer reports"])


def authorize(report: Report, principal: Principal) -> None:
    if report.office_id not in principal.office_ids and principal.account.role.value != "ADMIN":
        raise HTTPException(status_code=403, detail="You do not have access to this report")


@router.get(
    "/reports", response_model=PaginatedReports, summary="List reports for the officer's office"
)
async def list_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: ReportStatus | None = Query(None, alias="status"),
    priority: Priority | None = None,
    category: str | None = None,
    search: str | None = None,
    scope: Literal["office", "all"] = Query("office"),
    principal: Principal = Depends(require_officer),
    db: AsyncSession = Depends(get_db),
) -> PaginatedReports:
    if scope == "all":
        can_view_all = principal.account.role.value == "ADMIN" or (
            settings.environment == "development" and settings.development_global_officer_queue
        )
        if not can_view_all:
            raise HTTPException(status_code=403, detail="Viewing every office is not enabled")
        query = select(Report)
    else:
        office_ids = principal.office_ids
        # In development, the principal can access the global queue. Keep the
        # default view limited to the officer's real office memberships so the
        # explicit All Database Reports switch has a useful, predictable scope.
        if principal.officer and principal.account.role.value != "ADMIN":
            ids = await db.scalars(
                select(OfficeMembership.office_id).where(
                    OfficeMembership.officer_id == principal.officer.id,
                    OfficeMembership.active.is_(True),
                )
            )
            office_ids = tuple(ids.all())
        query = select(Report).where(Report.office_id.in_(office_ids))
    if status_filter:
        query = query.where(Report.status == status_filter)
    if priority:
        query = query.where(Report.priority == priority)
    if category:
        query = query.where(Report.category == category)
    if search:
        query = query.where(
            or_(Report.category.ilike(f"%{search}%"), Report.description.ilike(f"%{search}%"))
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await db.scalars(
        query.options(*REPORT_LOAD)
        .order_by(Report.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    reports = list(rows.all())
    return PaginatedReports(
        items=await report_outputs_with_transcripts(db, reports),
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/reports/{public_id}", response_model=ReportOut, summary="Open a report")
async def detail(
    public_id: str,
    principal: Principal = Depends(require_officer),
    db: AsyncSession = Depends(get_db),
) -> Report:
    report = await get_report(db, public_id)
    authorize(report, principal)
    db.add(
        AuditLog(
            actor_type="OFFICER",
            actor_id=principal.officer.id if principal.officer else None,
            action="REPORT_VIEWED",
            target_type="REPORT",
            target_id=public_id,
        )
    )
    await db.commit()
    return report


@router.get(
    "/reports/{public_id}/reporter",
    response_model=ReporterDetails,
    summary="View the reporter and their report history",
)
async def reporter_details(
    public_id: str,
    principal: Principal = Depends(require_officer),
    db: AsyncSession = Depends(get_db),
) -> ReporterDetails:
    report = await get_report(db, public_id)
    authorize(report, principal)
    user = await db.scalar(
        select(User).options(selectinload(User.account)).where(User.id == report.user_id)
    )
    if not user:
        raise HTTPException(status_code=404, detail="Reporter not found")
    account = user.account
    rows = list(
        (
            await db.scalars(
                select(Report)
                .options(*REPORT_LOAD)
                .where(Report.user_id == user.id)
                .order_by(Report.created_at.desc())
            )
        ).all()
    )
    active = sum(row.status not in {ReportStatus.RESOLVED, ReportStatus.CANCELLED} for row in rows)
    resolved = sum(row.status == ReportStatus.RESOLVED for row in rows)
    db.add(
        AuditLog(
            actor_type="OFFICER",
            actor_id=principal.officer.id if principal.officer else None,
            action="REPORTER_DETAILS_VIEWED",
            target_type="REPORT",
            target_id=public_id,
        )
    )
    await db.commit()
    return ReporterDetails(
        name=user.name,
        email=account.email,
        phone=user.phone or account.phone,
        joined_at=account.created_at,
        last_login_at=account.last_login_at,
        total_reports=len(rows),
        active_reports=active,
        resolved_reports=resolved,
        reports=[ReportOut.model_validate(row) for row in rows],
    )


@router.get(
    "/reports/{public_id}/location",
    response_model=LocationOut | None,
    summary="Get the latest reported location",
)
async def latest_location(
    public_id: str,
    principal: Principal = Depends(require_officer),
    db: AsyncSession = Depends(get_db),
) -> ReportLocation | None:
    report = await get_report(db, public_id)
    authorize(report, principal)
    return await db.scalar(
        select(ReportLocation)
        .where(ReportLocation.report_id == report.id)
        .order_by(ReportLocation.recorded_at.desc())
        .limit(1)
    )


@router.get(
    "/reports/{public_id}/history",
    response_model=list[HistoryOut],
    summary="Get the report timeline",
)
async def report_history(
    public_id: str,
    principal: Principal = Depends(require_officer),
    db: AsyncSession = Depends(get_db),
) -> list[ReportHistory]:
    report = await get_report(db, public_id)
    authorize(report, principal)
    rows = await db.scalars(
        select(ReportHistory)
        .where(ReportHistory.report_id == report.id)
        .order_by(ReportHistory.created_at)
    )
    return list(rows.all())


@router.get(
    "/reports/{public_id}/videos",
    response_model=list[ReportVideoOut],
    summary="List every saved video for a report",
)
async def report_videos(
    public_id: str,
    principal: Principal = Depends(require_officer),
    db: AsyncSession = Depends(get_db),
) -> list[ReportVideoOut]:
    report = await get_report(db, public_id)
    authorize(report, principal)
    videos: list[ReportVideoOut] = []
    session = await db.scalar(select(StreamSession).where(StreamSession.report_id == report.id))
    if session and session.recording_key:
        recording = settings.recording_dir / session.recording_key
        if recording.is_file():
            videos.append(
                ReportVideoOut(
                    id="live-recording",
                    label="Emergency live-video recording",
                    mime_type="video/mp4",
                    size=recording.stat().st_size,
                    created_at=session.started_at or report.created_at,
                )
            )
    rows = await db.scalars(
        select(ReportMedia)
        .where(ReportMedia.report_id == report.id, ReportMedia.media_type == "video")
        .order_by(ReportMedia.created_at.desc())
    )
    for media in rows.all():
        path = settings.upload_dir / media.storage_key
        if path.is_file():
            videos.append(
                ReportVideoOut(
                    id=f"upload-{media.id}",
                    label="Submitted video",
                    mime_type=media.mime_type,
                    size=media.size,
                    created_at=media.created_at,
                )
            )
    return sorted(videos, key=lambda item: item.created_at, reverse=True)


@router.get(
    "/reports/{public_id}/videos/{video_id}",
    summary="Play a saved report video",
)
async def play_report_video(
    public_id: str,
    video_id: str,
    principal: Principal = Depends(require_officer),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    report = await get_report(db, public_id)
    authorize(report, principal)
    path: Path | None = None
    mime_type = "video/mp4"
    if video_id == "live-recording":
        session = await db.scalar(select(StreamSession).where(StreamSession.report_id == report.id))
        if session and session.recording_key:
            path = settings.recording_dir / session.recording_key
    elif video_id.startswith("upload-"):
        try:
            media_id = int(video_id.removeprefix("upload-"))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Video not found") from exc
        media = await db.scalar(
            select(ReportMedia).where(
                ReportMedia.id == media_id,
                ReportMedia.report_id == report.id,
                ReportMedia.media_type == "video",
            )
        )
        if media:
            path = settings.upload_dir / media.storage_key
            mime_type = media.mime_type
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="Video not found")
    db.add(
        AuditLog(
            actor_type="OFFICER",
            actor_id=principal.officer.id if principal.officer else None,
            action="SAVED_VIDEO_VIEWED",
            target_type="REPORT",
            target_id=public_id,
            audit_metadata={"video_id": video_id},
        )
    )
    await db.commit()
    return FileResponse(path, media_type=mime_type)


@router.get(
    "/reports/{public_id}/related",
    response_model=RelatedReports,
    summary="Get relevant previous reports",
)
async def related(
    public_id: str,
    limit: int = Query(5, ge=1, le=20),
    principal: Principal = Depends(require_officer),
    db: AsyncSession = Depends(get_db),
) -> RelatedReports:
    current = await get_report(db, public_id)
    authorize(current, principal)
    rows = list(
        (
            await db.scalars(
                select(Report)
                .options(*REPORT_LOAD)
                .where(Report.id != current.id, Report.office_id.in_(principal.office_ids))
                .order_by(Report.created_at.desc())
                .limit(100)
            )
        ).all()
    )

    def output(report: Report, relation: str, distance: float | None = None) -> RelatedReport:
        return RelatedReport(
            **ReportOut.model_validate(report).model_dump(),
            relation=relation,
            distance_km=round(distance, 2) if distance is not None else None,
        )

    distances = sorted(
        (
            (
                row,
                haversine_km(
                    current.initial_latitude,
                    current.initial_longitude,
                    row.initial_latitude,
                    row.initial_longitude,
                ),
            )
            for row in rows
        ),
        key=lambda item: item[1],
    )
    nearby = [output(row, "nearby", distance) for row, distance in distances if distance <= 10][
        :limit
    ]
    same_user = [
        output(row, "same_user", distance)
        for row, distance in distances
        if row.user_id == current.user_id
    ][:limit]
    same_office = [
        output(row, "same_office", distance)
        for row, distance in distances
        if row.office_id == current.office_id
    ][:limit]
    return RelatedReports(nearby=nearby, same_user=same_user, same_office=same_office)


async def apply_action(
    public_id: str, action: str, principal: Principal, db: AsyncSession
) -> Report:
    if not principal.officer:
        raise HTTPException(status_code=403, detail="An officer profile is required")
    report = await transition_report(
        db, public_id, principal.officer.id, principal.office_ids, action
    )
    await realtime_hub.office_event(
        report.office_id,
        {"type": "report.updated", "report_id": public_id, "status": report.status.value},
    )
    await realtime_hub.user_event(
        report.user_id,
        {"type": "report.updated", "report_id": public_id, "status": report.status.value},
    )
    return report


@router.post(
    "/reports/{public_id}/acknowledge",
    response_model=ReportOut,
    summary="Acknowledge and take a report",
)
async def acknowledge(
    public_id: str,
    principal: Principal = Depends(require_officer),
    db: AsyncSession = Depends(get_db),
) -> Report:
    return await apply_action(public_id, "acknowledge", principal, db)


@router.post(
    "/reports/{public_id}/respond",
    response_model=ReportOut,
    summary="Mark the officer as responding",
)
async def respond(
    public_id: str,
    principal: Principal = Depends(require_officer),
    db: AsyncSession = Depends(get_db),
) -> Report:
    return await apply_action(public_id, "respond", principal, db)


@router.post(
    "/reports/{public_id}/arrive", response_model=ReportOut, summary="Mark the officer as arrived"
)
async def arrive(
    public_id: str,
    principal: Principal = Depends(require_officer),
    db: AsyncSession = Depends(get_db),
) -> Report:
    return await apply_action(public_id, "arrive", principal, db)


@router.post("/reports/{public_id}/resolve", response_model=ReportOut, summary="Resolve the report")
async def resolve(
    public_id: str,
    principal: Principal = Depends(require_officer),
    db: AsyncSession = Depends(get_db),
) -> Report:
    return await apply_action(public_id, "resolve", principal, db)
