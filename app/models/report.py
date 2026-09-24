from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Report(Base):
    """An emergency report filed from the app.

    The prose is written on the device (by the LLM, or by the app's own composer
    when the model is unreachable) — this table stores it and owns everything the
    client is not allowed to decide: the id, the reference code, and the status.
    """

    __tablename__ = "reports"
    __table_args__ = (
        # Retrying a submission over a flaky connection must not file twice.
        UniqueConstraint("user_id", "client_id", name="uq_report_user_client"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    reference_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)

    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    user: Mapped["User"] = relationship(back_populates="reports")  # noqa: F821

    # When the caller filed it, as reported by the device.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # When it reached us. Differs from created_at after an offline retry.
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    title: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True, default="Submitted")

    summary: Mapped[str] = mapped_column(Text)
    situation_analysis: Mapped[str] = mapped_column(Text)
    recommended_actions: Mapped[list] = mapped_column(JSON, default=list)

    transcript: Mapped[str] = mapped_column(Text, default="")
    labels: Mapped[list] = mapped_column(JSON, default=list)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_label: Mapped[str | None] = mapped_column(String(300), nullable=True)

    reporter_name: Mapped[str] = mapped_column(String(120), default="")
    source: Mapped[str] = mapped_column(String(20), default="sign_video")
    generated_by: Mapped[str] = mapped_column(String(60), default="")
