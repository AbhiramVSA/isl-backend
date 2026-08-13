import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import get_db
from app.dependencies import Principal, require_user
from app.models import AuditLog, Report, ReportHistory, ReportLocation, ReportMedia
from app.schemas import LocationCreate, LocationOut, ReportCreate, ReportOut
from app.services.realtime import realtime_hub
from app.services.reports import REPORT_LOAD, create_report, get_report

router = APIRouter(tags=["Mobile reports"])


async def owned_report(db: AsyncSession, public_id: str, principal: Principal) -> Report:
    report = await get_report(db, public_id)
    if not principal.user or report.user_id != principal.user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this report")
    return report


@router.post(
    "/reports", response_model=ReportOut, status_code=201, summary="Create an incident report"
)
async def create(
    data: ReportCreate,
    principal: Principal = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> Report:
    report = await create_report(db, principal.user.id, data)  # type: ignore[union-attr]
    await realtime_hub.office_event(
        report.office_id, {"type": "report.created", "report_id": report.public_id}
    )
    return report


@router.get(
    "/reports/{public_id}", response_model=ReportOut, summary="Get one of the user's reports"
)
async def detail(
    public_id: str, principal: Principal = Depends(require_user), db: AsyncSession = Depends(get_db)
) -> Report:
    return await owned_report(db, public_id, principal)


@router.get("/users/me/reports", response_model=list[ReportOut], summary="List the user's reports")
async def mine(
    principal: Principal = Depends(require_user), db: AsyncSession = Depends(get_db)
) -> list[Report]:
    result = await db.scalars(
        select(Report)
        .options(*REPORT_LOAD)
        .where(Report.user_id == principal.user.id)
        .order_by(Report.created_at.desc())
    )  # type: ignore[union-attr]
    return list(result.all())


@router.post(
    "/reports/{public_id}/location",
    response_model=LocationOut,
    status_code=201,
    summary="Add a location update",
)
async def add_location(
    public_id: str,
    data: LocationCreate,
    principal: Principal = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> ReportLocation:
    report = await owned_report(db, public_id, principal)
    if report.status.value in {"RESOLVED", "CANCELLED"}:
        raise HTTPException(status_code=409, detail="This report is no longer active")
    location = ReportLocation(report_id=report.id, **data.model_dump(exclude_none=True))
    db.add(location)
    await db.flush()
    db.add(
        ReportHistory(
            report_id=report.id,
            actor_type="USER",
            actor_id=principal.user.id,
            event="LOCATION_UPDATED",
            event_metadata={},
            new_status=report.status.value,
        )
    )  # type: ignore[union-attr]
    await db.commit()
    await db.refresh(location)
    await realtime_hub.office_event(
        report.office_id,
        {
            "type": "location.updated",
            "report_id": public_id,
            "location": LocationOut.model_validate(location).model_dump(mode="json"),
        },
    )
    return location


@router.post("/reports/{public_id}/media", status_code=201, summary="Upload report evidence")
async def upload_media(
    public_id: str,
    file: UploadFile = File(...),
    principal: Principal = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    report = await owned_report(db, public_id, principal)
    if file.content_type not in settings.allowed_media_types:
        raise HTTPException(status_code=415, detail="This file type is not supported")
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="The file is too large")
    suffix = Path(file.filename or "upload").suffix.lower()
    key = f"{report.public_id}/{hashlib.sha256(content).hexdigest()}{suffix}"
    destination = settings.upload_dir / key
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    media = ReportMedia(
        report_id=report.id,
        uploaded_by=f"USER:{principal.user.id}",
        media_type="video" if file.content_type.startswith("video/") else "image",
        storage_key=key,
        mime_type=file.content_type,
        size=len(content),
    )  # type: ignore[union-attr]
    db.add_all(
        [
            media,
            AuditLog(
                actor_type="USER",
                actor_id=principal.user.id,
                action="MEDIA_UPLOADED",
                target_type="REPORT",
                target_id=public_id,
            ),
        ]
    )  # type: ignore[union-attr]
    await db.commit()
    await db.refresh(media)
    return {
        "id": media.id,
        "media_type": media.media_type,
        "mime_type": media.mime_type,
        "size": media.size,
        "created_at": media.created_at,
    }
