"""Management API: case management, CSV export, audit log and analytics."""

import csv
import io
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.permissions import Permission, permissions_for
from app.db import get_db
from app.dependencies import Principal, audit, require_permission
from app.models import (
    Account,
    AccountStatus,
    AuditLog,
    OfficeMembership,
    Officer,
    Priority,
    Report,
    ReportHistory,
    ReportStatus,
    User,
)
from app.schemas_admin import (
    AdminReportOut,
    Analytics,
    AssignRequest,
    AuditOut,
    CountItem,
    DailyCount,
    OfficerStat,
    OfficeStat,
    Page,
    PriorityChange,
    StatusOverride,
)
from app.services.realtime import realtime_hub
from app.services.reports import REPORT_LOAD, get_report, report_outputs_with_transcripts

router = APIRouter(prefix="/admin", tags=["Administration"])

CLOSED = (ReportStatus.RESOLVED, ReportStatus.CANCELLED)
STATUS_LABELS = {
    "NEW": "New",
    "ACKNOWLEDGED": "Acknowledged",
    "ASSIGNED": "Assigned",
    "RESPONDING": "Responding",
    "ARRIVED": "Arrived",
    "RESOLVED": "Resolved",
    "CANCELLED": "Cancelled",
}


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def minutes_between(start: datetime | None, end: datetime | None) -> float | None:
    start, end = as_utc(start), as_utc(end)
    if not start or not end:
        return None
    return max((end - start).total_seconds() / 60, 0)


def average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


# --- report queries ---------------------------------------------------------


def report_query(
    principal: Principal,
    status: ReportStatus | None,
    priority: Priority | None,
    office_id: int | None,
    officer_id: int | None,
    unassigned: bool,
    open_only: bool,
    search: str | None,
    date_from: date | None,
    date_to: date | None,
) -> Select:
    query = select(Report)
    if not principal.global_scope:
        query = query.where(Report.office_id.in_(principal.office_ids))
    if office_id is not None:
        query = query.where(Report.office_id == office_id)
    if status:
        query = query.where(Report.status == status)
    if open_only:
        query = query.where(Report.status.not_in(CLOSED))
    if priority:
        query = query.where(Report.priority == priority)
    if officer_id is not None:
        query = query.where(Report.assigned_officer_id == officer_id)
    if unassigned:
        query = query.where(Report.assigned_officer_id.is_(None))
    if date_from:
        query = query.where(Report.created_at >= datetime.combine(date_from, time.min, UTC))
    if date_to:
        query = query.where(
            Report.created_at < datetime.combine(date_to + timedelta(days=1), time.min, UTC)
        )
    if search:
        term = f"%{search.strip()}%"
        query = query.where(
            or_(
                Report.category.ilike(term),
                Report.description.ilike(term),
                Report.reference_code.ilike(term),
                Report.public_id.ilike(term),
                Report.reporter_name.ilike(term),
                Report.location_label.ilike(term),
            )
        )
    return query


SORTS = {
    "newest": Report.created_at.desc(),
    "oldest": Report.created_at.asc(),
    "priority": Report.priority.asc(),  # CRITICAL < HIGH < NORMAL alphabetically
    "updated": Report.updated_at.desc(),
}


class ReportFilters:
    def __init__(
        self,
        status: ReportStatus | None = None,
        priority: Priority | None = None,
        office_id: int | None = None,
        officer_id: int | None = None,
        unassigned: bool = False,
        open_only: bool = False,
        search: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        sort: Literal["newest", "oldest", "priority", "updated"] = "newest",
    ) -> None:
        self.status = status
        self.priority = priority
        self.office_id = office_id
        self.officer_id = officer_id
        self.unassigned = unassigned
        self.open_only = open_only
        self.search = search
        self.date_from = date_from
        self.date_to = date_to
        self.sort = sort

    def query(self, principal: Principal) -> Select:
        if self.office_id is not None and not principal.can_access_office(self.office_id):
            raise HTTPException(status_code=403, detail="You do not have access to this office")
        return report_query(
            principal,
            self.status,
            self.priority,
            self.office_id,
            self.officer_id,
            self.unassigned,
            self.open_only,
            self.search,
            self.date_from,
            self.date_to,
        ).order_by(SORTS[self.sort], Report.id.desc())


@router.get("/reports", response_model=Page[AdminReportOut], summary="Search every report in scope")
async def list_reports(
    filters: ReportFilters = Depends(),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require_permission(Permission.REPORTS_VIEW)),
    db: AsyncSession = Depends(get_db),
) -> Page[AdminReportOut]:
    query = filters.query(principal)
    total = await db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    rows = list(
        (
            await db.scalars(
                query.options(*REPORT_LOAD).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
    )
    outputs = await report_outputs_with_transcripts(db, rows)
    items = [
        AdminReportOut(**output.model_dump()) for output in outputs
    ]
    return Page(items=items, page=page, page_size=page_size, total=total)


@router.get("/reports/export.csv", summary="Export reports in scope as CSV")
async def export_reports(
    request: Request,
    filters: ReportFilters = Depends(),
    principal: Principal = Depends(require_permission(Permission.REPORTS_EXPORT)),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    rows = list(
        (await db.scalars(filters.query(principal).options(*REPORT_LOAD).limit(10_000))).all()
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "report_id",
            "reference_code",
            "created_at",
            "category",
            "priority",
            "status",
            "office",
            "assigned_officer",
            "reporter_name",
            "latitude",
            "longitude",
            "acknowledged_at",
            "arrived_at",
            "resolved_at",
            "minutes_to_acknowledge",
            "minutes_to_resolve",
            "description",
        ]
    )
    for row in rows:
        ack = minutes_between(row.created_at, row.acknowledged_at)
        res = minutes_between(row.created_at, row.resolved_at)
        writer.writerow(
            [
                row.public_id,
                row.reference_code or "",
                as_utc(row.created_at).isoformat(),
                row.category,
                row.priority.value,
                row.status.value,
                row.office.name,
                row.assigned_officer.name if row.assigned_officer else "",
                row.reporter_name or "",
                row.initial_latitude,
                row.initial_longitude,
                as_utc(row.acknowledged_at).isoformat() if row.acknowledged_at else "",
                as_utc(row.arrived_at).isoformat() if row.arrived_at else "",
                as_utc(row.resolved_at).isoformat() if row.resolved_at else "",
                f"{ack:.1f}" if ack is not None else "",
                f"{res:.1f}" if res is not None else "",
                row.description,
            ]
        )
    db.add(audit(principal, "REPORTS_EXPORTED", "REPORT", None, {"count": len(rows)}, request))
    await db.commit()
    filename = f"equal-reports-{datetime.now(UTC):%Y%m%d-%H%M}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def load_in_scope(db: AsyncSession, principal: Principal, public_id: str) -> Report:
    report = await get_report(db, public_id)
    if not principal.can_access_office(report.office_id):
        raise HTTPException(status_code=404, detail="Report not found")
    if not principal.can_manage_office(report.office_id):
        raise HTTPException(status_code=403, detail="This report belongs to another office")
    return report


async def broadcast(report: Report) -> None:
    event = {"type": "report.updated", "report_id": report.public_id, "status": report.status.value}
    await realtime_hub.office_event(report.office_id, event)
    await realtime_hub.user_event(report.user_id, event)


@router.post(
    "/reports/{public_id}/assign",
    response_model=AdminReportOut,
    summary="Assign, reassign or unassign a report",
)
async def assign_report(
    public_id: str,
    data: AssignRequest,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.REPORTS_ASSIGN)),
    db: AsyncSession = Depends(get_db),
) -> AdminReportOut:
    report = await load_in_scope(db, principal, public_id)
    if report.status in CLOSED:
        raise HTTPException(status_code=409, detail="Closed reports cannot be reassigned")
    old_status = report.status
    old_officer = report.assigned_officer.name if report.assigned_officer else None
    now = datetime.now(UTC)
    if data.officer_id is None:
        if report.status in {ReportStatus.RESPONDING, ReportStatus.ARRIVED}:
            raise HTTPException(
                status_code=409,
                detail="An officer is already on the way; reassign instead of unassigning",
            )
        report.assigned_officer_id = None
        report.status = ReportStatus.NEW
        new_officer = None
    else:
        officer = await db.scalar(
            select(Officer)
            .options(selectinload(Officer.account))
            .where(Officer.id == data.officer_id)
        )
        if (
            not officer
            or officer.account.status != AccountStatus.ACTIVE
            or Permission.REPORTS_RESPOND not in permissions_for(officer.account.role)
        ):
            raise HTTPException(status_code=422, detail="Choose an active officer")
        member = await db.scalar(
            select(OfficeMembership.id).where(
                OfficeMembership.officer_id == officer.id,
                OfficeMembership.office_id == report.office_id,
                OfficeMembership.active.is_(True),
            )
        )
        if not member:
            raise HTTPException(
                status_code=422, detail=f"{officer.name} is not a member of {report.office.name}"
            )
        report.assigned_officer_id = officer.id
        if report.status == ReportStatus.NEW:
            report.status = ReportStatus.ASSIGNED
            report.acknowledged_at = report.acknowledged_at or now
        new_officer = officer.name
    report.updated_at = now
    metadata = {"from": old_officer, "to": new_officer, "reason": data.reason}
    db.add_all(
        [
            ReportHistory(
                report_id=report.id,
                actor_type=principal.role.value,
                actor_id=principal.account.id,
                event="OFFICER_UNASSIGNED" if new_officer is None else "OFFICER_ASSIGNED",
                old_status=old_status.value,
                new_status=report.status.value,
                event_metadata=metadata,
            ),
            audit(principal, "REPORT_ASSIGNED", "REPORT", public_id, metadata, request),
        ]
    )
    await db.commit()
    db.expire_all()
    fresh = await get_report(db, public_id)
    await broadcast(fresh)
    return await admin_output(db, fresh)


@router.patch(
    "/reports/{public_id}/priority", response_model=AdminReportOut, summary="Change priority"
)
async def change_priority(
    public_id: str,
    data: PriorityChange,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.REPORTS_PRIORITIZE)),
    db: AsyncSession = Depends(get_db),
) -> AdminReportOut:
    report = await load_in_scope(db, principal, public_id)
    old = report.priority
    if old == data.priority:
        return await admin_output(db, report)
    report.priority = data.priority
    report.updated_at = datetime.now(UTC)
    metadata = {"old": old.value, "new": data.priority.value, "reason": data.reason}
    db.add_all(
        [
            ReportHistory(
                report_id=report.id,
                actor_type=principal.role.value,
                actor_id=principal.account.id,
                event="PRIORITY_CHANGED",
                new_status=report.status.value,
                event_metadata=metadata,
            ),
            audit(principal, "PRIORITY_CHANGED", "REPORT", public_id, metadata, request),
        ]
    )
    await db.commit()
    db.expire_all()
    fresh = await get_report(db, public_id)
    await broadcast(fresh)
    return await admin_output(db, fresh)


TIMESTAMP_FOR = {
    ReportStatus.ACKNOWLEDGED: "acknowledged_at",
    ReportStatus.RESPONDING: "responding_at",
    ReportStatus.ARRIVED: "arrived_at",
    ReportStatus.RESOLVED: "resolved_at",
}


@router.post(
    "/reports/{public_id}/status",
    response_model=AdminReportOut,
    summary="Override a report's status (cancel, reopen, close)",
)
async def override_status(
    public_id: str,
    data: StatusOverride,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.REPORTS_OVERRIDE)),
    db: AsyncSession = Depends(get_db),
) -> AdminReportOut:
    report = await load_in_scope(db, principal, public_id)
    old = report.status
    if old == data.status:
        return await admin_output(db, report)
    now = datetime.now(UTC)
    report.status = data.status
    report.updated_at = now
    if data.status == ReportStatus.NEW:
        # Reopen to the queue.
        report.assigned_officer_id = None
        report.resolved_at = None
    elif data.status in {ReportStatus.ASSIGNED, ReportStatus.RESPONDING, ReportStatus.ARRIVED} and (
        report.assigned_officer_id is None
    ):
        raise HTTPException(status_code=422, detail="Assign an officer before setting this status")
    field = TIMESTAMP_FOR.get(data.status)
    if field and getattr(report, field) is None:
        setattr(report, field, now)
    if old == ReportStatus.RESOLVED and data.status != ReportStatus.RESOLVED:
        report.resolved_at = None
    metadata = {"old": old.value, "new": data.status.value, "reason": data.reason}
    db.add_all(
        [
            ReportHistory(
                report_id=report.id,
                actor_type=principal.role.value,
                actor_id=principal.account.id,
                event="STATUS_OVERRIDDEN",
                old_status=old.value,
                new_status=data.status.value,
                event_metadata=metadata,
            ),
            audit(principal, "STATUS_OVERRIDDEN", "REPORT", public_id, metadata, request),
        ]
    )
    await db.commit()
    db.expire_all()
    fresh = await get_report(db, public_id)
    await broadcast(fresh)
    return await admin_output(db, fresh)


async def admin_output(db: AsyncSession, report: Report) -> AdminReportOut:
    output = (await report_outputs_with_transcripts(db, [report]))[0]
    return AdminReportOut(**output.model_dump())


@router.get(
    "/reports/{public_id}/assignable",
    response_model=list[OfficerStat],
    summary="Officers who can take this report, with their current load",
)
async def assignable_officers(
    public_id: str,
    principal: Principal = Depends(require_permission(Permission.REPORTS_ASSIGN)),
    db: AsyncSession = Depends(get_db),
) -> list[OfficerStat]:
    report = await load_in_scope(db, principal, public_id)
    rows = list(
        (
            await db.scalars(
                select(Officer)
                .options(selectinload(Officer.account))
                .join(OfficeMembership, OfficeMembership.officer_id == Officer.id)
                .join(Account, Account.id == Officer.account_id)
                .where(
                    OfficeMembership.office_id == report.office_id,
                    OfficeMembership.active.is_(True),
                    Account.status == AccountStatus.ACTIVE,
                )
                .order_by(Officer.name)
            )
        ).all()
    )
    rows = [row for row in rows if Permission.REPORTS_RESPOND in permissions_for(row.account.role)]
    loads = await officer_loads(db, [row.id for row in rows])
    return [
        OfficerStat(
            officer_id=row.id,
            name=row.name,
            active=loads.get(row.id, (0, 0))[0],
            resolved=loads.get(row.id, (0, 0))[1],
        )
        for row in rows
    ]


async def officer_loads(db: AsyncSession, ids: list[int]) -> dict[int, tuple[int, int]]:
    if not ids:
        return {}
    rows = await db.execute(
        select(Report.assigned_officer_id, Report.status, func.count())
        .where(Report.assigned_officer_id.in_(ids))
        .group_by(Report.assigned_officer_id, Report.status)
    )
    result: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for officer_id, status, count in rows.all():
        if status == ReportStatus.RESOLVED:
            result[officer_id][1] += count
        elif status != ReportStatus.CANCELLED:
            result[officer_id][0] += count
    return {key: (value[0], value[1]) for key, value in result.items()}


# --- audit ------------------------------------------------------------------


@router.get("/audit", response_model=Page[AuditOut], summary="Read the audit log")
async def audit_log(
    action: str | None = None,
    actor_id: int | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(require_permission(Permission.AUDIT_VIEW)),
    db: AsyncSession = Depends(get_db),
) -> Page[AuditOut]:
    query = select(AuditLog)
    if not principal.global_scope:
        offices = principal.member_office_ids
        staff_accounts = (
            select(Officer.account_id)
            .join(OfficeMembership, OfficeMembership.officer_id == Officer.id)
            .where(OfficeMembership.office_id.in_(offices))
        )
        office_reports = select(Report.public_id).where(Report.office_id.in_(offices))
        query = query.where(
            or_(
                AuditLog.actor_id.in_(staff_accounts),
                (AuditLog.target_type == "REPORT") & AuditLog.target_id.in_(office_reports),
            )
        )
    if action:
        query = query.where(AuditLog.action == action)
    if actor_id is not None:
        query = query.where(AuditLog.actor_id == actor_id)
    if target_type:
        query = query.where(AuditLog.target_type == target_type)
    if target_id:
        query = query.where(AuditLog.target_id == target_id)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(
            or_(
                AuditLog.action.ilike(term),
                AuditLog.target_id.ilike(term),
                AuditLog.actor_id.in_(select(Account.id).where(Account.email.ilike(term))),
            )
        )
    if date_from:
        query = query.where(AuditLog.created_at >= datetime.combine(date_from, time.min, UTC))
    if date_to:
        query = query.where(
            AuditLog.created_at < datetime.combine(date_to + timedelta(days=1), time.min, UTC)
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(
        (
            await db.scalars(
                query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    account_ids = {row.actor_id for row in rows if row.actor_id is not None}
    emails: dict[int, str] = {}
    names: dict[int, str] = {}
    if account_ids:
        emails = dict(
            (
                await db.execute(
                    select(Account.id, Account.email).where(Account.id.in_(account_ids))
                )
            ).all()
        )
        names = dict(
            (
                await db.execute(
                    select(Officer.account_id, Officer.name).where(
                        Officer.account_id.in_(account_ids)
                    )
                )
            ).all()
        )
        names |= dict(
            (
                await db.execute(
                    select(User.account_id, User.name).where(User.account_id.in_(account_ids))
                )
            ).all()
        )
    return Page(
        items=[
            AuditOut(
                id=row.id,
                created_at=row.created_at,
                action=row.action,
                actor_type=row.actor_type,
                actor_id=row.actor_id,
                actor_name=names.get(row.actor_id) if row.actor_id is not None else None,
                actor_email=emails.get(row.actor_id) if row.actor_id is not None else None,
                target_type=row.target_type,
                target_id=row.target_id,
                ip_address=row.ip_address,
                metadata=row.audit_metadata or {},
            )
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/audit/actions", response_model=list[str], summary="Distinct audit actions")
async def audit_actions(
    _principal: Principal = Depends(require_permission(Permission.AUDIT_VIEW)),
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    return list(
        (await db.scalars(select(AuditLog.action).distinct().order_by(AuditLog.action))).all()
    )


# --- analytics --------------------------------------------------------------


@router.get("/analytics", response_model=Analytics, summary="Response metrics for a period")
async def analytics(
    days: int = Query(30, ge=1, le=365),
    office_id: int | None = None,
    principal: Principal = Depends(require_permission(Permission.ANALYTICS_VIEW)),
    db: AsyncSession = Depends(get_db),
) -> Analytics:
    since = datetime.combine(datetime.now(UTC).date() - timedelta(days=days - 1), time.min, UTC)
    query = select(Report).where(Report.created_at >= since)
    if not principal.global_scope:
        query = query.where(Report.office_id.in_(principal.office_ids))
    if office_id is not None:
        if not principal.can_access_office(office_id):
            raise HTTPException(status_code=403, detail="You do not have access to this office")
        query = query.where(Report.office_id == office_id)
    reports = list((await db.scalars(query.options(*REPORT_LOAD))).all())

    open_reports = [r for r in reports if r.status not in CLOSED]
    resolved = [r for r in reports if r.status == ReportStatus.RESOLVED]
    ack = [
        m for r in reports if (m := minutes_between(r.created_at, r.acknowledged_at)) is not None
    ]
    arrive = [m for r in reports if (m := minutes_between(r.created_at, r.arrived_at)) is not None]
    resolve = [
        m for r in resolved if (m := minutes_between(r.created_at, r.resolved_at)) is not None
    ]

    status_counts = Counter(r.status.value for r in reports)
    priority_counts = Counter(r.priority.value for r in reports)
    category_counts = Counter(r.category for r in reports)

    created_by_day = Counter(as_utc(r.created_at).date().isoformat() for r in reports)
    resolved_by_day = Counter(
        as_utc(r.resolved_at).date().isoformat() for r in resolved if r.resolved_at
    )
    daily = []
    for offset in range(days):
        day = (since.date() + timedelta(days=offset)).isoformat()
        daily.append(
            DailyCount(
                date=day, created=created_by_day.get(day, 0), resolved=resolved_by_day.get(day, 0)
            )
        )

    by_office: dict[int, list[Report]] = defaultdict(list)
    for r in reports:
        by_office[r.office_id].append(r)
    office_stats = sorted(
        (
            OfficeStat(
                office_id=office_id_,
                name=rows[0].office.name,
                total=len(rows),
                open=sum(r.status not in CLOSED for r in rows),
                resolved=sum(r.status == ReportStatus.RESOLVED for r in rows),
                avg_acknowledge_minutes=average(
                    [
                        m
                        for r in rows
                        if (m := minutes_between(r.created_at, r.acknowledged_at)) is not None
                    ]
                ),
            )
            for office_id_, rows in by_office.items()
        ),
        key=lambda item: item.total,
        reverse=True,
    )

    by_officer: dict[int, list[Report]] = defaultdict(list)
    for r in reports:
        if r.assigned_officer_id:
            by_officer[r.assigned_officer_id].append(r)
    officer_stats = sorted(
        (
            OfficerStat(
                officer_id=officer_id,
                name=rows[0].assigned_officer.name if rows[0].assigned_officer else "Unknown",
                active=sum(r.status not in CLOSED for r in rows),
                resolved=sum(r.status == ReportStatus.RESOLVED for r in rows),
            )
            for officer_id, rows in by_officer.items()
        ),
        key=lambda item: item.active + item.resolved,
        reverse=True,
    )[:10]

    return Analytics(
        days=days,
        total=len(reports),
        open=len(open_reports),
        resolved=len(resolved),
        critical_open=sum(r.priority == Priority.CRITICAL for r in open_reports),
        unassigned_open=sum(r.assigned_officer_id is None for r in open_reports),
        avg_acknowledge_minutes=average(ack),
        avg_arrival_minutes=average(arrive),
        avg_resolution_minutes=average(resolve),
        by_status=[
            CountItem(key=key, label=STATUS_LABELS[key], count=status_counts.get(key, 0))
            for key in STATUS_LABELS
        ],
        by_priority=[
            CountItem(key=p.value, label=p.value.title(), count=priority_counts.get(p.value, 0))
            for p in Priority
        ],
        by_category=[
            CountItem(key=key, label=key, count=count)
            for key, count in category_counts.most_common(8)
        ],
        daily=daily,
        offices=office_stats,
        officers=officer_stats,
    )
