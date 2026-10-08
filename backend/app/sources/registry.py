"""Registry of all job sources and their automation status."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import JobSource
from app.sources.base import JobSourceAdapter, ManualOnlyAdapter
from app.sources.public_boards import (
    AshbyAdapter, GreenhouseAdapter, HimalayasAdapter, LeverAdapter, RemoteOKAdapter, RemotiveAdapter, WeWorkRemotelyAdapter,
)

MANUAL_SOURCES = [
    ("linkedin", "LinkedIn Jobs", "https://www.linkedin.com/jobs", "No public job-search API; automated access is prohibited by LinkedIn's User Agreement. Paste job links/descriptions manually."),
    ("indeed", "Indeed", "https://www.indeed.com", "Indeed's publisher job-search API is closed to new users and scraping is prohibited. Import manually."),
    ("wellfound", "Wellfound", "https://wellfound.com", "No public job-search API. Import manually."),
    ("remoteco", "Remote.co", "https://remote.co", "No documented public API. Import manually."),
    ("workingnomads", "Working Nomads", "https://www.workingnomads.com", "No documented public API confirmed. Import manually (status: unknown)."),
    ("justremote", "JustRemote", "https://justremote.co", "No public API. Import manually."),
    ("dynamitejobs", "Dynamite Jobs", "https://dynamitejobs.com", "No public API. Import manually."),
    ("builtin", "Built In", "https://builtin.com", "No public API. Import manually."),
    ("flexjobs", "FlexJobs", "https://www.flexjobs.com", "Paid membership site; no public API. Import manually."),
    ("upwork", "Upwork", "https://www.upwork.com", "Official GraphQL API exists but requires an approved OAuth app. Not connected — import manually or apply in Upwork."),
]
REVIEW = {"workingnomads": "unknown", "upwork": "review_required"}


def all_adapters() -> dict[str, JobSourceAdapter]:
    adapters: dict[str, JobSourceAdapter] = {}
    for cls in (RemotiveAdapter, RemoteOKAdapter, HimalayasAdapter, WeWorkRemotelyAdapter, GreenhouseAdapter, LeverAdapter, AshbyAdapter):
        a = cls()
        adapters[a.key] = a
    for key, name, url, note in MANUAL_SOURCES:
        adapters[key] = ManualOnlyAdapter(key, name, url, note, REVIEW.get(key, "manual_only"))
    return adapters


def get_adapter(key: str) -> JobSourceAdapter | None:
    return all_adapters().get(key)


def sync_sources(db: Session) -> list[JobSource]:
    """Ensure a JobSource row exists for every adapter (user-editable enable flag/config persist)."""
    existing = {s.key: s for s in db.scalars(select(JobSource))}
    for key, a in all_adapters().items():
        info = a.info()
        row = existing.get(key)
        if row is None:
            row = JobSource(key=key, name=a.name, base_url=a.base_url, enabled=False, config={})
            db.add(row)
        row.name = a.name
        row.base_url = a.base_url
        row.automation_status = info["automation_status"]
        row.apply_automation_status = info["apply_automation_status"]
        row.has_official_api = info["has_official_api"]
        row.notes = info["terms_note"]
    db.commit()
    return list(db.scalars(select(JobSource).order_by(JobSource.name)))
