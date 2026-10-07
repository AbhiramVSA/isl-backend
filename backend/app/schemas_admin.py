"""Request and response models for the management (``/admin``) API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models import AccountStatus, Priority, ReportStatus, Role
from app.schemas import ORMModel, ReportOut


class Page[T](BaseModel):
    items: list[T]
    page: int
    page_size: int
    total: int


class OfficeRef(ORMModel):
    id: int
    name: str


class RoleInfo(BaseModel):
    role: Role
    label: str
    description: str
    permissions: list[str]
    global_scope: bool
    grantable: bool


# --- Staff ------------------------------------------------------------------


def _staff_role(value: Role | None) -> Role | None:
    if value == Role.USER:
        raise ValueError("Reporters are managed from the Reporters page")
    return value


class StaffOut(BaseModel):
    id: int
    account_id: int
    name: str
    email: EmailStr
    phone: str | None
    badge_number: str
    rank: str | None
    role: Role
    role_label: str
    status: AccountStatus
    offices: list[OfficeRef]
    open_reports: int = 0
    created_at: datetime
    last_login_at: datetime | None


class StaffCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    name: str = Field(min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=32)
    badge_number: str | None = Field(default=None, max_length=64)
    rank: str | None = Field(default=None, max_length=80)
    role: Role = Role.OFFICER
    office_ids: list[int] = Field(default_factory=list)

    _role = field_validator("role")(_staff_role)


class StaffUpdate(BaseModel):
    email: EmailStr | None = None
    name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=32)
    badge_number: str | None = Field(default=None, min_length=2, max_length=64)
    rank: str | None = Field(default=None, max_length=80)
    role: Role | None = None
    office_ids: list[int] | None = None

    _role = field_validator("role")(_staff_role)


class AccountStatusUpdate(BaseModel):
    status: AccountStatus
    reason: str | None = Field(default=None, max_length=500)


class PasswordReset(BaseModel):
    password: str = Field(min_length=10, max_length=128)


# --- Offices ----------------------------------------------------------------


class OfficeAdminOut(ORMModel):
    id: int
    name: str
    address: str
    latitude: float
    longitude: float
    service_radius: float
    active: bool
    created_at: datetime
    staff_count: int = 0
    open_reports: int = 0
    total_reports: int = 0


class OfficeCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    address: str = Field(min_length=2, max_length=500)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    service_radius: float = Field(default=10, gt=0, le=1000)


class OfficeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    address: str | None = Field(default=None, min_length=2, max_length=500)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    service_radius: float | None = Field(default=None, gt=0, le=1000)
    active: bool | None = None


# --- Reporters (Equal app users) ---------------------------------------------


class ReporterOut(BaseModel):
    id: int
    account_id: int
    name: str
    email: EmailStr
    phone: str | None
    status: AccountStatus
    created_at: datetime
    last_login_at: datetime | None
    total_reports: int
    open_reports: int


# --- Reports ----------------------------------------------------------------


class AssignRequest(BaseModel):
    officer_id: int | None = None  # None returns the report to the open queue
    reason: str | None = Field(default=None, max_length=500)


class StatusOverride(BaseModel):
    status: ReportStatus
    reason: str = Field(min_length=3, max_length=500)


class PriorityChange(BaseModel):
    priority: Priority
    reason: str = Field(min_length=3, max_length=500)


class AdminReportOut(ReportOut):
    """Kept as its own name for the management API; every field now lives on ReportOut."""


# --- Oversight --------------------------------------------------------------


class AuditOut(BaseModel):
    id: int
    created_at: datetime
    action: str
    actor_type: str
    actor_id: int | None
    actor_name: str | None
    actor_email: str | None
    target_type: str
    target_id: str | None
    ip_address: str | None
    metadata: dict[str, Any]


class CountItem(BaseModel):
    key: str
    label: str
    count: int


class DailyCount(BaseModel):
    date: str
    created: int
    resolved: int


class OfficeStat(BaseModel):
    office_id: int
    name: str
    total: int
    open: int
    resolved: int
    avg_acknowledge_minutes: float | None


class OfficerStat(BaseModel):
    officer_id: int
    name: str
    active: int
    resolved: int


class Analytics(BaseModel):
    days: int
    total: int
    open: int
    resolved: int
    critical_open: int
    unassigned_open: int
    avg_acknowledge_minutes: float | None
    avg_arrival_minutes: float | None
    avg_resolution_minutes: float | None
    by_status: list[CountItem]
    by_priority: list[CountItem]
    by_category: list[CountItem]
    daily: list[DailyCount]
    offices: list[OfficeStat]
    officers: list[OfficerStat]
