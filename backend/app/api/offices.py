from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import Principal, require_officer
from app.models import Office, Report
from app.schemas import OfficeOut, ReportOut
from app.services.reports import REPORT_LOAD

router = APIRouter(prefix="/officer/office", tags=["Officer office"])


@router.get("", response_model=list[OfficeOut], summary="Get the officer's office")
async def offices(
    principal: Principal = Depends(require_officer), db: AsyncSession = Depends(get_db)
) -> list[Office]:
    rows = await db.scalars(
        select(Office).where(Office.id.in_(principal.office_ids), Office.active.is_(True))
    )
    return list(rows.all())


@router.get("/reports", response_model=list[ReportOut], summary="Get current office reports")
async def office_reports(
    principal: Principal = Depends(require_officer), db: AsyncSession = Depends(get_db)
) -> list[Report]:
    rows = await db.scalars(
        select(Report)
        .options(*REPORT_LOAD)
        .where(Report.office_id.in_(principal.office_ids))
        .order_by(Report.created_at.desc())
        .limit(100)
    )
    return list(rows.all())
