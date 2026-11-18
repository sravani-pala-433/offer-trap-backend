import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_name: Mapped[str] = mapped_column(Text)
    recruiter_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    recruiter_contact: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    public_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    submitter_name: Mapped[str] = mapped_column(Text)
    submitter_email: Mapped[str] = mapped_column(Text)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    review_status: Mapped[str] = mapped_column(Text, default="submitted", index=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    evidence_files: Mapped[list["EvidenceFile"]] = relationship(
        back_populates="report", cascade="all, delete-orphan", lazy="selectin"
    )
    moderation_logs: Mapped[list["ModerationLog"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
    reward_entries: Mapped[list["RewardLedger"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )


class EvidenceFile(Base):
    __tablename__ = "evidence_files"
    __table_args__ = (
        UniqueConstraint("object_key", name="uq_evidence_files_object_key"),
        Index("ix_evidence_files_report_status", "report_id", "upload_status"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    report_id: Mapped[str | None] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), nullable=True, index=True
    )
    original_name: Mapped[str] = mapped_column(Text)
    # Neon Object Storage key prefix. Nullable only for legacy rows awaiting
    # migration from the previous database-chunk implementation.
    object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    upload_status: Mapped[str] = mapped_column(Text, default="pending", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    report: Mapped[Report | None] = relationship(back_populates="evidence_files")


class ModerationLog(Base):
    __tablename__ = "moderation_logs"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    moderator: Mapped[str] = mapped_column(Text)
    old_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_status: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    report: Mapped[Report] = relationship(back_populates="moderation_logs")


class RewardLedger(Base):
    __tablename__ = "reward_ledger"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    points: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(Text)
    moderator: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    report: Mapped[Report] = relationship(back_populates="reward_entries")
