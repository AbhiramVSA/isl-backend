from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Report, User
from app.schemas.report import (
    ReportListResponse,
    ReportResponse,
    ReportStatusUpdate,
    ReportSubmission,
)
from app.services.security import new_id, new_reference_code

router = APIRouter()


@router.post("/reports", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
def submit_report(
    payload: ReportSubmission,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReportResponse:
    """Stores a report the app already wrote, making it a dispatchable incident.

    This is not a generation endpoint — the prose arrives finished from the
    device. What happens here is validation, persistence, and assigning the
    things the client is not allowed to decide: the id, the reference code, and
    the status.

    Resubmitting the same `client_id` returns the existing record with 200
    instead of filing a duplicate. A caller retrying over a bad connection must
    not end up with two incidents.
    """
    existing = db.scalar(
        select(Report).where(
            Report.user_id == user.id, Report.client_id == payload.client_id
        )
    )
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return ReportResponse.model_validate(existing)

    report_id = new_id("rpt")
    created_at = payload.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    report = Report(
        id=report_id,
        reference_code=new_reference_code(report_id),
        client_id=payload.client_id,
        user_id=user.id,
        created_at=created_at,
        title=payload.title,
        category=payload.category,
        severity=payload.severity,
        status="Submitted",
        summary=payload.summary,
        situation_analysis=payload.situation_analysis,
        recommended_actions=payload.recommended_actions,
        transcript=payload.transcript,
        labels=payload.labels,
        duration_ms=payload.duration_ms,
        latitude=payload.latitude,
        longitude=payload.longitude,
        location_label=payload.location_label,
        reporter_name=payload.reporter_name or user.display_name,
        source=payload.source,
        generated_by=payload.generated_by,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    # TODO: this is where the incident should be pushed to whoever dispatches.
    # Until that exists, a filed report sits in the database and no one is paged.
    return ReportResponse.model_validate(report)


@router.get("/reports", response_model=ReportListResponse)
def list_reports(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReportListResponse:
    """This caller's reports, newest first."""
    reports = db.scalars(
        select(Report)
        .where(Report.user_id == user.id)
        .order_by(Report.created_at.desc())
        .limit(limit)
    ).all()
    return ReportListResponse(
        reports=[ReportResponse.model_validate(report) for report in reports]
    )


@router.get("/reports/{report_id}", response_model=ReportResponse)
def get_report(
    report_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReportResponse:
    """One report. This is how the caller watches its status change."""
    report = db.get(Report, report_id)
    # Same 404 whether it does not exist or belongs to someone else — otherwise
    # this endpoint tells you which report ids are real.
    if report is None or report.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Report not found."
        )
    return ReportResponse.model_validate(report)


@router.patch("/reports/{report_id}/status", response_model=ReportResponse)
def update_report_status(
    report_id: str,
    payload: ReportStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReportResponse:
    """Moves a report along: Submitted → Acknowledged → UnitDispatched → Resolved.

    Not in the original handoff doc, but `GET /reports/{id}` exists so the caller
    can watch the status change, and nothing could change it. This is the missing
    half.

    ⚠️ Currently the report's own owner can call this, because there are no roles
    yet. Before a control room uses it, gate it behind a dispatcher role — a
    caller should not be able to mark their own incident resolved.
    """
    report = db.get(Report, report_id)
    if report is None or report.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Report not found."
        )

    report.status = payload.status
    db.commit()
    db.refresh(report)
    return ReportResponse.model_validate(report)
