"""Shapes the Equal mobile app expects.

Kept apart from `app/schemas.py` because these are a different dialect of the
same incident: the app names the urgency `severity` where the console names it
`priority`, its status vocabulary is five values against the console's seven,
and its report is a written document rather than a category and a description.
The translation between the two lives in `app/services/mobile_reports.py`.

Field names here follow the app's DTOs (`core/network/dto/Dtos.kt`), not this
service's own conventions. That is the point of the module.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# The exact strings the app parses. Anything else degrades to a safe default on
# the device, so they are rejected here rather than allowed to drift silently.
CATEGORIES = {
    "MedicalEmergency",
    "Fire",
    "Violence",
    "Theft",
    "Accident",
    "Harassment",
    "Unknown",
}
SEVERITIES = {"Critical", "High", "Moderate", "Low"}


class HealthResponse(BaseModel):
    """The app's pre-flight check.

    `model_loaded` is the only signal a caller gets before they start signing,
    so it reports whether the transcription model can actually run — not merely
    whether the web service is up.
    """

    status: str = "ok"
    model_loaded: bool
    model_error: str | None = None


class PredictionResponse(BaseModel):
    label: str
    confidence: float | None = None


class LoginRequest(BaseModel):
    """Phone number, email, or an ID issued by a disability-services office."""

    identifier: str = Field(min_length=1, max_length=160)
    passcode: str = Field(default="", max_length=200)


class MobileUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    identifier: str
    preferred_language: str = "Indian Sign Language"


class LoginResponse(BaseModel):
    user: MobileUser
    access_token: str
    expires_at: datetime


class ReportSubmission(BaseModel):
    """A finished report arriving from a device.

    Every word of it was written on the phone — by the language model, or by the
    app's own composer when that was unreachable — so it is treated as untrusted
    input: lengths capped, enums checked. `id`, `reference_code` and `status` are
    absent by design; this service assigns them.
    """

    client_id: str = Field(min_length=1, max_length=64)
    created_at: datetime
    title: str = Field(min_length=1, max_length=300)
    category: str
    severity: str
    summary: str = Field(min_length=1, max_length=2_000)
    situation_analysis: str = Field(min_length=1, max_length=20_000)
    recommended_actions: list[str] = Field(default_factory=list, max_length=20)
    transcript: str = Field(default="", max_length=5_000)
    labels: list[str] = Field(default_factory=list, max_length=50)
    duration_ms: int = Field(default=0, ge=0, le=60 * 60 * 1000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    location_label: str | None = Field(default=None, max_length=300)
    reporter_name: str = Field(default="", max_length=120)
    source: str = Field(default="sign_video")
    generated_by: str = Field(default="", max_length=60)

    @field_validator("category")
    @classmethod
    def _known_category(cls, value: str) -> str:
        if value not in CATEGORIES:
            raise ValueError(f"category must be one of {sorted(CATEGORIES)}")
        return value

    @field_validator("severity")
    @classmethod
    def _known_severity(cls, value: str) -> str:
        if value not in SEVERITIES:
            raise ValueError(f"severity must be one of {sorted(SEVERITIES)}")
        return value

    @field_validator("source")
    @classmethod
    def _known_source(cls, value: str) -> str:
        if value not in {"sign_video", "chat"}:
            raise ValueError("source must be 'sign_video' or 'chat'")
        return value

    @field_validator("recommended_actions")
    @classmethod
    def _trim_actions(cls, value: list[str]) -> list[str]:
        return [item.strip()[:400] for item in value if item.strip()]


class ReportResponse(BaseModel):
    """The canonical stored record. The app replaces its local copy with this."""

    id: str
    reference_code: str
    created_at: datetime
    title: str
    category: str
    severity: str
    status: str
    summary: str
    situation_analysis: str
    recommended_actions: list[str]
    transcript: str
    labels: list[str]
    duration_ms: int
    latitude: float | None
    longitude: float | None
    location_label: str | None
    reporter_name: str
    source: str
    generated_by: str


class ReportListResponse(BaseModel):
    reports: list[ReportResponse]


class StationResponse(BaseModel):
    id: str
    name: str
    address: str
    latitude: float
    longitude: float
    distance_m: int
    phone: str
    open_now: bool = True
    sign_language_officer: bool = False


class StationListResponse(BaseModel):
    stations: list[StationResponse]
