import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def now() -> datetime:
    return datetime.now(UTC)


class Role(str, enum.Enum):
    USER = "USER"
    OFFICER = "OFFICER"
    ADMIN = "ADMIN"


class AccountStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class Priority(str, enum.Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    NORMAL = "NORMAL"


class ReportStatus(str, enum.Enum):
    NEW = "NEW"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ASSIGNED = "ASSIGNED"
    RESPONDING = "RESPONDING"
    ARRIVED = "ARRIVED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False), index=True)
    status: Mapped[AccountStatus] = mapped_column(
        Enum(AccountStatus, native_enum=False), default=AccountStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    account: Mapped[Account] = relationship()


class Officer(Base):
    __tablename__ = "officers"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    badge_number: Mapped[str] = mapped_column(String(64), unique=True)
    rank: Mapped[str | None] = mapped_column(String(80))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    account: Mapped[Account] = relationship()


class Office(Base):
    __tablename__ = "offices"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    address: Mapped[str] = mapped_column(String(500))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    service_radius: Mapped[float] = mapped_column(Float, default=10.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OfficeMembership(Base):
    __tablename__ = "office_memberships"
    __table_args__ = (UniqueConstraint("office_id", "officer_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    office_id: Mapped[int] = mapped_column(ForeignKey("offices.id"), index=True)
    officer_id: Mapped[int] = mapped_column(ForeignKey("officers.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    office: Mapped[Office] = relationship()
    officer: Mapped[Officer] = relationship()


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        Index("ix_reports_office_status_created", "office_id", "status", "created_at"),
        Index("ix_reports_location", "initial_latitude", "initial_longitude"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(
        String(36), unique=True, index=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    office_id: Mapped[int] = mapped_column(ForeignKey("offices.id"), index=True)
    assigned_officer_id: Mapped[int | None] = mapped_column(ForeignKey("officers.id"), index=True)
    category: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[Priority] = mapped_column(Enum(Priority, native_enum=False), index=True)
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, native_enum=False), default=ReportStatus.NEW, index=True
    )
    initial_latitude: Mapped[float] = mapped_column(Float)
    initial_longitude: Mapped[float] = mapped_column(Float)
    location_accuracy: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responding_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    # --- filed from the Equal app -------------------------------------------
    # Null on anything filed through the existing mobile endpoint. The app
    # writes a whole document on the device before it ever reaches the network,
    # and `description` alone would throw away the part that matters: the signed
    # transcript and the analysis written from it.
    reference_code: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    # Generated on the device and stable across retries, so a report submitted
    # twice over a flaky connection is stored once.
    client_id: Mapped[str | None] = mapped_column(String(64), index=True)
    title: Mapped[str | None] = mapped_column(String(300))
    severity: Mapped[str | None] = mapped_column(String(20))
    situation_analysis: Mapped[str | None] = mapped_column(Text)
    recommended_actions: Mapped[list | None] = mapped_column(JSON)
    transcript: Mapped[str | None] = mapped_column(Text)
    labels: Mapped[list | None] = mapped_column(JSON)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    location_label: Mapped[str | None] = mapped_column(String(300))
    reporter_name: Mapped[str | None] = mapped_column(String(120))
    source: Mapped[str | None] = mapped_column(String(20))
    generated_by: Mapped[str | None] = mapped_column(String(60))

    office: Mapped[Office] = relationship()
    assigned_officer: Mapped[Officer | None] = relationship()


class ReportHistory(Base):
    __tablename__ = "report_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    actor_type: Mapped[str] = mapped_column(String(30))
    actor_id: Mapped[int | None] = mapped_column(Integer)
    event: Mapped[str] = mapped_column(String(80), index=True)
    old_status: Mapped[str | None] = mapped_column(String(30))
    new_status: Mapped[str | None] = mapped_column(String(30))
    event_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class ReportLocation(Base):
    __tablename__ = "report_locations"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    accuracy: Mapped[float | None] = mapped_column(Float)
    speed: Mapped[float | None] = mapped_column(Float)
    heading: Mapped[float | None] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class ReportMedia(Base):
    __tablename__ = "report_media"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    uploaded_by: Mapped[str] = mapped_column(String(80))
    media_type: Mapped[str] = mapped_column(String(30))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    mime_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class StreamSession(Base):
    __tablename__ = "stream_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), unique=True
    )
    room_name: Mapped[str] = mapped_column(String(120), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    egress_id: Mapped[str | None] = mapped_column(String(120))
    recording_key: Mapped[str | None] = mapped_column(String(500))


class StreamDraft(Base):
    """Transcript accumulated while an unauthenticated /app stream was live.

    The streaming endpoints take no login (like ``POST /app/api/v1/predict``:
    record before sign-in), so there is no user to key on. The phone holds an
    opaque ``draft_token`` returned in the WS ``hello``; only its SHA-256 is
    stored. ``GET /app/api/v1/stream/{stream_id}/draft?token=`` returns the
    transcript the phone prefills ``POST /app/api/v1/reports`` with.
    """

    __tablename__ = "stream_drafts"
    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    secret_hash: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16), default="landmarks")
    transcript: Mapped[str] = mapped_column(Text, default="")
    sentences: Mapped[list] = mapped_column(JSON, default=list)
    safety_events: Mapped[list] = mapped_column(JSON, default=list)
    frames_seen: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_type: Mapped[str] = mapped_column(String(30), index=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    target_type: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(String(80))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    audit_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
