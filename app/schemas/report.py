from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# The exact strings the app parses. Anything else degrades to the safe default
# on the client, so the server rejects it rather than letting it drift.
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
STATUSES = {"Draft", "Submitted", "Acknowledged", "UnitDispatched", "Resolved"}


class ReportSubmission(BaseModel):
    """A finished report arriving from a device.

    Everything here was written on the phone — by the language model or by the
    app's own composer — so it is treated as untrusted input: lengths are capped
    and the enums are checked. `id`, `reference_code` and `status` are absent by
    design; the server assigns them.
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

    model_config = ConfigDict(from_attributes=True)

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


class ReportStatusUpdate(BaseModel):
    """Used by whoever dispatches. Status is never client-settable on submit."""

    status: str

    @field_validator("status")
    @classmethod
    def _known_status(cls, value: str) -> str:
        if value not in STATUSES:
            raise ValueError(f"status must be one of {sorted(STATUSES)}")
        return value
