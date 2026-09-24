from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    """A citizen who files reports.

    `identifier` is whatever they signed in with — a phone number, an email, or
    an ID issued by a disability-services office.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    identifier: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    passcode_hash: Mapped[str] = mapped_column(String(200))
    preferred_language: Mapped[str] = mapped_column(
        String(60), default="Indian Sign Language"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    reports: Mapped[list["Report"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )
