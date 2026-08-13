from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import Priority, ReportStatus, Role


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserRegister(BaseModel):
    email: EmailStr
    phone: str | None = Field(default=None, min_length=7, max_length=32)
    password: str = Field(min_length=10, max_length=128)
    name: str = Field(min_length=2, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class Identity(BaseModel):
    id: int
    role: Role
    name: str
    email: EmailStr
    offices: list[str] = Field(default_factory=list)
    phone: str | None = None
    created_at: datetime | None = None


class ReportCreate(BaseModel):
    category: str = Field(min_length=2, max_length=100)
    description: str = Field(min_length=3, max_length=5000)
    latitude: float
    longitude: float
    location_accuracy: float | None = Field(default=None, ge=0, le=10000)
    answers: dict[str, Any] = Field(default_factory=dict)

    @field_validator("latitude")
    @classmethod
    def latitude_valid(cls, value: float) -> float:
        if not -90 <= value <= 90:
            raise ValueError("latitude must be between -90 and 90")
        return value

    @field_validator("longitude")
    @classmethod
    def longitude_valid(cls, value: float) -> float:
        if not -180 <= value <= 180:
            raise ValueError("longitude must be between -180 and 180")
        return value


class OfficeOut(ORMModel):
    id: int
    name: str
    address: str
    latitude: float
    longitude: float
    service_radius: float


class OfficerSummary(ORMModel):
    id: int
    name: str
    badge_number: str
    rank: str | None


class ReportOut(ORMModel):
    public_id: str
    category: str
    description: str
    priority: Priority
    status: ReportStatus
    initial_latitude: float
    initial_longitude: float
    location_accuracy: float | None
    created_at: datetime
    updated_at: datetime
    acknowledged_at: datetime | None
    responding_at: datetime | None
    arrived_at: datetime | None
    resolved_at: datetime | None
    office: OfficeOut
    assigned_officer: OfficerSummary | None


class PaginatedReports(BaseModel):
    items: list[ReportOut]
    page: int
    page_size: int
    total: int


class LocationCreate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0, le=10000)
    speed: float | None = Field(default=None, ge=0)
    heading: float | None = Field(default=None, ge=0, le=360)
    recorded_at: datetime | None = None


class LocationOut(ORMModel):
    latitude: float
    longitude: float
    accuracy: float | None
    speed: float | None
    heading: float | None
    recorded_at: datetime


class HistoryOut(ORMModel):
    event: str
    old_status: str | None
    new_status: str | None
    event_metadata: dict[str, Any]
    created_at: datetime


class RelatedReport(ReportOut):
    relation: str
    distance_km: float | None = None


class RelatedReports(BaseModel):
    nearby: list[RelatedReport]
    same_user: list[RelatedReport]
    same_office: list[RelatedReport]


class StreamState(BaseModel):
    available: bool
    active: bool
    requested: bool
    recording: bool = False
    recording_available: bool = False
    viewer_url: str | None = None
    access_token: str | None = None


class ReportVideoOut(BaseModel):
    id: str
    label: str
    mime_type: str
    size: int | None = None
    created_at: datetime


class ReporterDetails(BaseModel):
    name: str
    email: EmailStr
    phone: str | None
    joined_at: datetime
    last_login_at: datetime | None
    total_reports: int
    active_reports: int
    resolved_reports: int
    reports: list[ReportOut]


class AdminOfficeCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    address: str = Field(min_length=2, max_length=500)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    service_radius: float = Field(default=10, gt=0, le=1000)


class AdminOfficerCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    name: str = Field(min_length=2, max_length=120)
    badge_number: str = Field(min_length=2, max_length=64)
    rank: str | None = Field(default=None, max_length=80)
    office_id: int


class PriorityUpdate(BaseModel):
    priority: Priority
    reason: str = Field(min_length=3, max_length=500)
