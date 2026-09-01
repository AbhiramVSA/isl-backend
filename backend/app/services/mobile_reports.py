"""Translating between the Equal app's report and this service's own.

The two describe the same incident differently — four severities against three
priorities, five statuses against seven, a written document against a category
and a description. Every one of those conversions lives here, so there is one
place to look when the app and the console disagree about a report.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.models import Priority, Report, ReportStatus
from app.schemas_mobile import ReportResponse

# --- urgency ----------------------------------------------------------------
# Four values into three. Moderate and Low both land on NORMAL: the console
# draws NORMAL without a colour accent, which is the right treatment for both.
PRIORITY_BY_SEVERITY = {
    "Critical": Priority.CRITICAL,
    "High": Priority.HIGH,
    "Moderate": Priority.NORMAL,
    "Low": Priority.NORMAL,
}
SEVERITY_BY_PRIORITY = {
    Priority.CRITICAL: "Critical",
    Priority.HIGH: "High",
    Priority.NORMAL: "Moderate",
}

# --- progress ---------------------------------------------------------------
# The app knows five values and degrades anything else to "Submitted", which a
# caller reads as their report sliding backwards. So the console's seven are
# folded onto the five rather than sent raw: a unit on the way and a unit that
# has arrived are both "dispatched" as far as the person waiting is concerned.
APP_STATUS_BY_REPORT_STATUS = {
    ReportStatus.NEW: "Submitted",
    ReportStatus.ACKNOWLEDGED: "Acknowledged",
    ReportStatus.ASSIGNED: "Acknowledged",
    ReportStatus.RESPONDING: "UnitDispatched",
    ReportStatus.ARRIVED: "UnitDispatched",
    ReportStatus.RESOLVED: "Resolved",
    ReportStatus.CANCELLED: "Resolved",
}

# --- category ---------------------------------------------------------------
# Stored as the app's enum so a round trip is lossless; the console prints it,
# so it is spaced out on the way there rather than on the way in.
CATEGORY_LABELS = {
    "MedicalEmergency": "Medical Emergency",
    "Fire": "Fire",
    "Violence": "Violence",
    "Theft": "Theft",
    "Accident": "Accident",
    "Harassment": "Harassment",
    "Unknown": "Unknown",
}


def new_reference_code() -> str:
    """`SOS-4F2A91` — short enough to sign, or to read out over a relay call."""
    return f"SOS-{uuid.uuid4().hex[:6].upper()}"


def app_report_id(report: Report) -> str:
    """The app's DTO types `id` as a string; this table's primary key is an int."""
    return f"rpt_{report.id}"


def to_app_report(report: Report) -> ReportResponse:
    created = report.created_at
    return ReportResponse(
        id=app_report_id(report),
        reference_code=report.reference_code or app_report_id(report),
        created_at=created if created.tzinfo else created.replace(tzinfo=UTC),
        title=report.title or report.category,
        category=report.category,
        severity=report.severity or SEVERITY_BY_PRIORITY.get(report.priority, "Moderate"),
        status=APP_STATUS_BY_REPORT_STATUS.get(report.status, "Submitted"),
        summary=report.description,
        situation_analysis=report.situation_analysis or report.description,
        recommended_actions=report.recommended_actions or [],
        transcript=report.transcript or "",
        labels=report.labels or [],
        duration_ms=report.duration_ms or 0,
        latitude=report.initial_latitude,
        longitude=report.initial_longitude,
        location_label=report.location_label,
        reporter_name=report.reporter_name or "",
        source=report.source or "sign_video",
        generated_by=report.generated_by or "",
    )


def utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)
