from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import AuditLog, Priority, Report, ReportHistory, ReportStatus
from app.schemas import ReportCreate, ReportOut
from app.services.routing_service import routing_service

REPORT_LOAD = (selectinload(Report.office), selectinload(Report.assigned_officer))


async def report_outputs_with_transcripts(
    db: AsyncSession, reports: list[Report]
) -> list[ReportOut]:
    if not reports:
        return []
    transcript_ids = set(
        (
            await db.scalars(
                select(ReportHistory.report_id)
                .where(
                    ReportHistory.report_id.in_([report.id for report in reports]),
                    ReportHistory.event == "SIGN_TRANSCRIBED",
                )
                .distinct()
            )
        ).all()
    )
    return [
        ReportOut.model_validate(report).model_copy(
            update={"transcript_available": report.id in transcript_ids}
        )
        for report in reports
    ]


def determine_priority(category: str, answers: dict) -> Priority:
    category_key = category.casefold()
    immediate_danger = bool(answers.get("immediate_danger"))
    injuries = bool(answers.get("injuries"))
    if immediate_danger or any(
        word in category_key for word in ("fire", "weapon", "medical emergency")
    ):
        return Priority.CRITICAL
    if injuries or any(word in category_key for word in ("accident", "violence", "missing")):
        return Priority.HIGH
    return Priority.NORMAL


def history(
    report: Report,
    event: str,
    actor_type: str,
    actor_id: int | None,
    old: ReportStatus | None = None,
    metadata: dict | None = None,
) -> ReportHistory:
    return ReportHistory(
        report_id=report.id,
        actor_type=actor_type,
        actor_id=actor_id,
        event=event,
        old_status=old.value if old else None,
        new_status=report.status.value,
        event_metadata=metadata or {},
    )


async def create_report(db: AsyncSession, user_id: int, data: ReportCreate) -> Report:
    try:
        route = await routing_service.route(db, data.latitude, data.longitude)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No response office is currently available",
        ) from exc
    report = Report(
        user_id=user_id,
        office_id=route.office.id,
        category=data.category,
        description=data.description,
        priority=determine_priority(data.category, data.answers),
        initial_latitude=data.latitude,
        initial_longitude=data.longitude,
        location_accuracy=data.location_accuracy,
    )
    db.add(report)
    await db.flush()
    db.add_all(
        [
            history(report, "REPORT_CREATED", "USER", user_id, metadata={"answers": data.answers}),
            history(
                report,
                "OFFICE_ASSIGNED",
                "SYSTEM",
                None,
                metadata={
                    "distance_km": round(route.distance_km, 3),
                    "matched_service_area": route.matched_service_area,
                },
            ),
            AuditLog(
                actor_type="USER",
                actor_id=user_id,
                action="REPORT_CREATED",
                target_type="REPORT",
                target_id=report.public_id,
            ),
        ]
    )
    await db.commit()
    return await get_report(db, report.public_id)


async def get_report(db: AsyncSession, public_id: str) -> Report:
    report = await db.scalar(
        select(Report).options(*REPORT_LOAD).where(Report.public_id == public_id)
    )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


TRANSITIONS: dict[str, tuple[set[ReportStatus], ReportStatus, str, str]] = {
    "acknowledge": (
        {ReportStatus.NEW},
        ReportStatus.ACKNOWLEDGED,
        "acknowledged_at",
        "OFFICER_ACKNOWLEDGED",
    ),
    "respond": (
        {ReportStatus.ACKNOWLEDGED, ReportStatus.ASSIGNED},
        ReportStatus.RESPONDING,
        "responding_at",
        "RESPONDING",
    ),
    "arrive": ({ReportStatus.RESPONDING}, ReportStatus.ARRIVED, "arrived_at", "ARRIVED"),
    "resolve": ({ReportStatus.ARRIVED}, ReportStatus.RESOLVED, "resolved_at", "RESOLVED"),
}


async def transition_report(
    db: AsyncSession, public_id: str, officer_id: int, office_ids: tuple[int, ...], action: str
) -> Report:
    if action not in TRANSITIONS:
        raise HTTPException(status_code=400, detail="Unsupported report action")
    allowed, target, timestamp_field, event = TRANSITIONS[action]
    report = await get_report(db, public_id)
    if report.office_id not in office_ids:
        raise HTTPException(status_code=403, detail="You do not have access to this report")
    if action != "acknowledge" and report.assigned_officer_id != officer_id:
        raise HTTPException(status_code=403, detail="This report is assigned to another officer")

    old = report.status
    values = {"status": target, timestamp_field: datetime.now(UTC), "updated_at": datetime.now(UTC)}
    if action == "acknowledge":
        values["assigned_officer_id"] = officer_id
    statement = (
        update(Report)
        .where(Report.id == report.id, Report.status.in_(allowed))
        .where(
            (Report.assigned_officer_id.is_(None))
            if action == "acknowledge"
            else (Report.assigned_officer_id == officer_id)
        )
        .values(**values)
    )
    result = await db.execute(statement)
    if result.rowcount != 1:
        await db.rollback()
        fresh = await get_report(db, public_id)
        if action == "acknowledge" and fresh.assigned_officer_id:
            raise HTTPException(
                status_code=409, detail="Another officer has already taken this report"
            )
        raise HTTPException(status_code=409, detail="This action is no longer available")

    report.status = target
    db.add_all(
        [
            history(report, event, "OFFICER", officer_id, old),
            AuditLog(
                actor_type="OFFICER",
                actor_id=officer_id,
                action=event,
                target_type="REPORT",
                target_id=public_id,
            ),
        ]
    )
    if action == "acknowledge":
        db.add(history(report, "OFFICER_ASSIGNED", "OFFICER", officer_id, old))
    await db.commit()
    return await get_report(db, public_id)
