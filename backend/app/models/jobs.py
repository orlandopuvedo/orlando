"""Companies, job sources, canonical jobs and their source references, searches."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, utcnow


class Company(TimestampMixin, Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    website: Mapped[str | None] = mapped_column(String(500))
    careers_url: Mapped[str | None] = mapped_column(String(500))
    industry: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)


class JobSource(TimestampMixin, Base):
    __tablename__ = "job_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    base_url: Mapped[str | None] = mapped_column(String(500))
    # Automation status of *searching* this source and of *applying* through it.
    automation_status: Mapped[str] = mapped_column(String(30), default="unknown")
    apply_automation_status: Mapped[str] = mapped_column(String(30), default="manual_only")
    has_official_api: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_status: Mapped[str] = mapped_column(String(20), default="never")  # never | ok | empty | error
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_found_count: Mapped[int | None] = mapped_column(Integer)


class Job(TimestampMixin, Base):
    """Canonical job record. The same job seen on several boards = one Job + several JobSourceRef."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str | None] = mapped_column(String(300))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    company_url: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(80), default="manual", index=True)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    canonical_url: Mapped[str | None] = mapped_column(String(1000), index=True)
    apply_url: Mapped[str | None] = mapped_column(String(1000))
    description: Mapped[str | None] = mapped_column(Text)
    requirements: Mapped[str | None] = mapped_column(Text)
    application_questions: Mapped[str | None] = mapped_column(Text)
    salary_min: Mapped[float | None] = mapped_column(Float)
    salary_max: Mapped[float | None] = mapped_column(Float)
    salary_currency: Mapped[str | None] = mapped_column(String(10))
    salary_period: Mapped[str | None] = mapped_column(String(20))  # hour/day/week/month/year
    salary_monthly_usd_min: Mapped[float | None] = mapped_column(Float)
    salary_monthly_usd_max: Mapped[float | None] = mapped_column(Float)
    location: Mapped[str | None] = mapped_column(String(300))
    remote_type: Mapped[str] = mapped_column(String(20), default="unknown")  # remote/hybrid/onsite/unknown
    employment_type: Mapped[str | None] = mapped_column(String(30))
    category: Mapped[str | None] = mapped_column(String(80), index=True)
    seniority: Mapped[str | None] = mapped_column(String(30))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    job_id_external: Mapped[str | None] = mapped_column(String(200))
    applicants_count: Mapped[int | None] = mapped_column(Integer)
    easy_apply: Mapped[bool] = mapped_column(Boolean, default=False)
    # Detection
    video_required: Mapped[bool] = mapped_column(Boolean, default=False)
    video_details: Mapped[dict] = mapped_column(JSON, default=dict)
    detected_requirements: Mapped[dict] = mapped_column(JSON, default=dict)
    # Scoring
    match_score: Mapped[float | None] = mapped_column(Float, index=True)
    classification: Mapped[str | None] = mapped_column(String(20))
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    match_reasons: Mapped[list] = mapped_column(JSON, default=list)
    concerns: Mapped[list] = mapped_column(JSON, default=list)
    priority_score: Mapped[float | None] = mapped_column(Float, index=True)
    priority_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Pipeline
    application_status: Mapped[str] = mapped_column(String(30), default="DISCOVERED", index=True)
    in_queue: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Hard search filters (applied before qualification): passed | review | rejected
    filter_status: Mapped[str | None] = mapped_column(String(20), index=True)
    filter_reasons: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    refs: Mapped[list[JobSourceRef]] = relationship(back_populates="job", cascade="all, delete-orphan")


class JobSourceRef(Base):
    """Where a canonical job was seen (one row per source listing)."""

    __tablename__ = "job_source_refs"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_source_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(80))
    external_id: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(1000))
    canonical_url: Mapped[str | None] = mapped_column(String(1000), index=True)
    apply_url: Mapped[str | None] = mapped_column(String(1000))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    duplicate_reason: Mapped[str | None] = mapped_column(String(200))
    raw: Mapped[dict] = mapped_column(JSON, default=dict)

    job: Mapped[Job] = relationship(back_populates="refs")


class JobSearch(TimestampMixin, Base):
    """A saved search executed by the scheduler across sources."""

    __tablename__ = "job_searches"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    query: Mapped[str] = mapped_column(String(300), default="")
    sources: Mapped[list] = mapped_column(JSON, default=list)  # empty = all enabled sources
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobSearchRun(Base):
    __tablename__ = "job_search_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger: Mapped[str] = mapped_column(String(30), default="manual")
    status: Mapped[str] = mapped_column(String(30), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    log: Mapped[list] = mapped_column(JSON, default=list)
    outcome: Mapped[str | None] = mapped_column(String(40))
    message: Mapped[str | None] = mapped_column(Text)
