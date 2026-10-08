"""Recruiter CRM: contacts, timeline activities, profile views, interviews, follow-ups."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, utcnow


class Contact(TimestampMixin, Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200))
    job_title: Mapped[str | None] = mapped_column(String(200))
    company: Mapped[str | None] = mapped_column(String(300))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(60))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    other_url: Mapped[str | None] = mapped_column(String(500))
    contact_source: Mapped[str | None] = mapped_column(String(100))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="NEW", index=True)
    first_contact_date: Mapped[date | None] = mapped_column(Date)
    last_contact_date: Mapped[date | None] = mapped_column(Date)
    next_follow_up_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)

    activities: Mapped[list[ContactActivity]] = relationship(
        back_populates="contact", cascade="all, delete-orphan", order_by="ContactActivity.occurred_at"
    )


class ContactActivity(TimestampMixin, Base):
    __tablename__ = "contact_activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    summary: Mapped[str] = mapped_column(String(500))
    details: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(String(60))
    interview_id: Mapped[int | None] = mapped_column(ForeignKey("interviews.id", ondelete="SET NULL"))

    contact: Mapped[Contact] = relationship(back_populates="activities")


class ProfileView(TimestampMixin, Base):
    __tablename__ = "profile_views"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), index=True)
    person_name: Mapped[str | None] = mapped_column(String(200))
    person_title: Mapped[str | None] = mapped_column(String(200))
    company: Mapped[str | None] = mapped_column(String(300))
    platform: Mapped[str] = mapped_column(String(60), default="LinkedIn")
    viewed_on: Mapped[date] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30), default="manual")  # manual | official_import


class Interview(TimestampMixin, Base):
    __tablename__ = "interviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str | None] = mapped_column(String(300))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="SET NULL"), index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), index=True)
    interview_type: Mapped[str] = mapped_column(String(40), default="video")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    meeting_url: Mapped[str | None] = mapped_column(String(1000))
    interview_number: Mapped[int] = mapped_column(Integer, default=1)
    is_final: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="SCHEDULED", index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    questions_asked: Mapped[str | None] = mapped_column(Text)
    answers_lessons: Mapped[str | None] = mapped_column(Text)
    next_steps: Mapped[str | None] = mapped_column(Text)
    follow_up_date: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FollowUp(TimestampMixin, Base):
    __tablename__ = "follow_ups"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), default="custom")
    title: Mapped[str] = mapped_column(String(300))
    due_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)  # PENDING/SENT/DONE/CANCELLED
    message: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(String(40))
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    interview_id: Mapped[int | None] = mapped_column(ForeignKey("interviews.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    postponed_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), unique=True)
