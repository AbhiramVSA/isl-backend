from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db import get_db
from app.dependencies import Principal, require_admin
from app.models import (
    Account,
    AuditLog,
    Office,
    OfficeMembership,
    Officer,
    Report,
    ReportHistory,
    Role,
)
from app.schemas import (
    AdminOfficeCreate,
    AdminOfficerCreate,
    OfficeOut,
    OfficerSummary,
    PriorityUpdate,
    ReportOut,
)
from app.services.reports import get_report, report_outputs_with_transcripts

router = APIRouter(prefix="/admin", tags=["Administration"])


@router.get("/offices", response_model=list[OfficeOut])
async def offices(
    _principal: Principal = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[Office]:
    return list((await db.scalars(select(Office).order_by(Office.name))).all())


@router.post("/offices", response_model=OfficeOut, status_code=201)
async def add_office(
    data: AdminOfficeCreate,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Office:
    office = Office(**data.model_dump())
    db.add(office)
    await db.flush()
    db.add(
        AuditLog(
            actor_type="ADMIN",
            actor_id=principal.account.id,
            action="OFFICE_CREATED",
            target_type="OFFICE",
            target_id=str(office.id),
        )
    )
    await db.commit()
    await db.refresh(office)
    return office


@router.get("/officers", response_model=list[OfficerSummary])
async def officers(
    _principal: Principal = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[Officer]:
    return list((await db.scalars(select(Officer).order_by(Officer.name))).all())


@router.post("/officers", response_model=OfficerSummary, status_code=201)
async def add_officer(
    data: AdminOfficerCreate,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Officer:
    if await db.scalar(select(Account.id).where(Account.email == data.email.lower())):
        raise HTTPException(status_code=409, detail="An account already exists with this email")
    if not await db.get(Office, data.office_id):
        raise HTTPException(status_code=404, detail="Office not found")
    account = Account(
        email=data.email.lower(), password_hash=hash_password(data.password), role=Role.OFFICER
    )
    db.add(account)
    await db.flush()
    officer = Officer(
        account_id=account.id, name=data.name, badge_number=data.badge_number, rank=data.rank
    )
    db.add(officer)
    await db.flush()
    db.add_all(
        [
            OfficeMembership(office_id=data.office_id, officer_id=officer.id),
            AuditLog(
                actor_type="ADMIN",
                actor_id=principal.account.id,
                action="OFFICER_CREATED",
                target_type="OFFICER",
                target_id=str(officer.id),
            ),
        ]
    )
    await db.commit()
    await db.refresh(officer)
    return officer


@router.get("/reports", response_model=list[ReportOut])
async def reports(
    _principal: Principal = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[ReportOut]:
    from app.services.reports import REPORT_LOAD

    rows = list(
        (
            await db.scalars(
                select(Report).options(*REPORT_LOAD).order_by(Report.created_at.desc()).limit(200)
            )
        ).all()
    )
    return await report_outputs_with_transcripts(db, rows)


@router.patch("/reports/{public_id}/priority", response_model=ReportOut)
async def priority(
    public_id: str,
    data: PriorityUpdate,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Report:
    report = await get_report(db, public_id)
    old = report.priority
    report.priority = data.priority
    db.add_all(
        [
            ReportHistory(
                report_id=report.id,
                actor_type="ADMIN",
                actor_id=principal.account.id,
                event="PRIORITY_CHANGED",
                new_status=report.status.value,
                event_metadata={
                    "old": old.value,
                    "new": data.priority.value,
                    "reason": data.reason,
                },
            ),
            AuditLog(
                actor_type="ADMIN",
                actor_id=principal.account.id,
                action="PRIORITY_CHANGED",
                target_type="REPORT",
                target_id=public_id,
                audit_metadata={"reason": data.reason},
            ),
        ]
    )
    await db.commit()
    return await get_report(db, public_id)
