"""Master profile (single source of truth), resumes, videos and reusable answers."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin


class UserProfile(TimestampMixin, Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Personal
    full_name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(60))
    location: Mapped[str | None] = mapped_column(String(200))
    country: Mapped[str | None] = mapped_column(String(100))
    time_zone: Mapped[str | None] = mapped_column(String(80))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    portfolio_url: Mapped[str | None] = mapped_column(String(500))
    other_urls: Mapped[list] = mapped_column(JSON, default=list)
    # Professional
    headline: Mapped[str | None] = mapped_column(String(300))
    professional_summary: Mapped[str | None] = mapped_column(Text)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    work_experience: Mapped[list] = mapped_column(JSON, default=list)
    education: Mapped[list] = mapped_column(JSON, default=list)
    certifications: Mapped[list] = mapped_column(JSON, default=list)
    languages: Mapped[list] = mapped_column(JSON, default=list)
    tools: Mapped[list] = mapped_column(JSON, default=list)
    industries: Mapped[list] = mapped_column(JSON, default=list)
    achievements: Mapped[list] = mapped_column(JSON, default=list)
    projects: Mapped[list] = mapped_column(JSON, default=list)
    # Job preferences
    min_salary: Mapped[float | None] = mapped_column(Float)
    target_salary: Mapped[float | None] = mapped_column(Float)
    target_salary_max: Mapped[float | None] = mapped_column(Float)
    max_salary: Mapped[float | None] = mapped_column(Float)  # hard ceiling; None = no limit
    salary_currency: Mapped[str] = mapped_column(String(10), default="USD")
    salary_period: Mapped[str] = mapped_column(String(20), default="month")
    work_arrangements: Mapped[list] = mapped_column(JSON, default=list)  # remote/hybrid/onsite
    employment_types: Mapped[list] = mapped_column(JSON, default=list)  # full_time/part_time/contract/internship
    preferred_roles: Mapped[list] = mapped_column(JSON, default=list)
    preferred_categories: Mapped[list] = mapped_column(JSON, default=list)
    preferred_industries: Mapped[list] = mapped_column(JSON, default=list)
    excluded_industries: Mapped[list] = mapped_column(JSON, default=list)
    preferred_schedules: Mapped[list] = mapped_column(JSON, default=list)
    availability: Mapped[str | None] = mapped_column(String(300))
    # Legal / application
    work_authorization: Mapped[str | None] = mapped_column(Text)
    requires_sponsorship: Mapped[bool | None] = mapped_column(Boolean)
    willing_to_relocate: Mapped[bool | None] = mapped_column(Boolean)
    application_preferences: Mapped[str | None] = mapped_column(Text)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)


class Resume(TimestampMixin, Base):
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    focus: Mapped[str | None] = mapped_column(String(100))  # e.g. sales, operations, ai_automation
    tags: Mapped[list] = mapped_column(JSON, default=list)
    original_filename: Mapped[str | None] = mapped_column(String(300))
    stored_filename: Mapped[str | None] = mapped_column(String(300))
    mime_type: Mapped[str | None] = mapped_column(String(120))
    file_size: Mapped[int | None] = mapped_column(Integer)
    raw_text: Mapped[str | None] = mapped_column(Text)
    parsed_data: Mapped[dict] = mapped_column(JSON, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    versions: Mapped[list[ResumeVersion]] = relationship(back_populates="resume", cascade="all, delete-orphan")


class ResumeVersion(TimestampMixin, Base):
    """A tailored resume generated (or edited) for a specific job / focus."""

    __tablename__ = "resume_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    focus: Mapped[str | None] = mapped_column(String(100))
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    content_text: Mapped[str | None] = mapped_column(Text)
    generated_by: Mapped[str] = mapped_column(String(80), default="template")
    warnings: Mapped[list] = mapped_column(JSON, default=list)

    resume: Mapped[Resume | None] = relationship(back_populates="versions")


class Video(TimestampMixin, Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(1000))
    platform: Mapped[str] = mapped_column(String(50), default="loom")
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    transcript: Mapped[str | None] = mapped_column(Text)
    date_created: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    has_local_file: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    times_used: Mapped[int] = mapped_column(Integer, default=0)


class ApplicationAnswer(TimestampMixin, Base):
    __tablename__ = "application_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    category: Mapped[str | None] = mapped_column(String(80))  # motivation, salary, availability, legal ...
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    times_used: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
