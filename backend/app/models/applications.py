"""Applications, their status history, generated documents and human approvals."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, utcnow
from app.models.jobs import Job


class Application(TimestampMixin, Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True, unique=True)
    status: Mapped[str] = mapped_column(String(30), default="READY", index=True)
    mode: Mapped[str] = mapped_column(String(20), default="copilot")  # copilot / supervised / auto
    application_type: Mapped[str | None] = mapped_column(String(40))  # easy_apply/company_site/email/referral/...
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    resume_version_id: Mapped[int | None] = mapped_column(ForeignKey("resume_versions.id", ondelete="SET NULL"))
    cover_letter_id: Mapped[int | None] = mapped_column(ForeignKey("generated_documents.id", ondelete="SET NULL", use_alter=True, name="fk_app_cover_letter"))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    video_id: Mapped[int | None] = mapped_column(ForeignKey("videos.id", ondelete="SET NULL"))
    package: Mapped[dict] = mapped_column(JSON, default=dict)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_via: Mapped[str | None] = mapped_column(String(300))
    response_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    offer_amount_monthly_usd: Mapped[float | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(Text)

    job: Mapped[Job] = relationship()
    history: Mapped[list[ApplicationStatusHistory]] = relationship(
        back_populates="application", cascade="all, delete-orphan", order_by="ApplicationStatusHistory.created_at"
    )


class ApplicationStatusHistory(Base):
    __tablename__ = "application_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    application: Mapped[Application] = relationship(back_populates="history")


class GeneratedDocument(TimestampMixin, Base):
    """Cover letters, recruiter messages, follow-up / thank-you messages."""

    __tablename__ = "generated_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str | None] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text, default="")
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="SET NULL"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), index=True)
    generated_by: Mapped[str] = mapped_column(String(80), default="template")
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    edited: Mapped[bool] = mapped_column(default=False)


class ApprovalRequest(TimestampMixin, Base):
    __tablename__ = "approval_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))  # salary/video/legal/demographic/uncertain/final_submit/blocked
    title: Mapped[str] = mapped_column(String(300))
    message: Mapped[str | None] = mapped_column(Text)
    field_key: Mapped[str | None] = mapped_column(String(200))
    proposed_value: Mapped[str | None] = mapped_column(Text)
    final_value: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
