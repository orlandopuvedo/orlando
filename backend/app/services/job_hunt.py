"""Daily Job Hunt cycle: search → normalize → dedupe → score → filter → package → queue → video → dashboard."""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Application, Job, JobSearch, JobSearchRun, JobSource, Video, utcnow
from app.services.application_engine import build_package
from app.services.followups import refresh_reminders
from app.services.jobs_service import category_success_rates, ingest_job, rescore_job, _rates
from app.services.profile_service import get_profile
from app.services.settings_service import get_all_settings
from app.sources.base import JobSourceAdapter, SearchQuery, SourceNotSupported
from app.sources.registry import all_adapters, sync_sources

log = logging.getLogger(__name__)


def _searches(db: Session, profile) -> list[JobSearch]:
    searches = list(db.scalars(select(JobSearch).where(JobSearch.enabled.is_(True))))
    if searches:
        return searches
    # Default: one search per preferred role (or a blank search)
    roles = profile.preferred_roles or [""]
    return [JobSearch(name=f"Auto: {r or 'all'}", query=r, sources=[], filters={}) for r in roles[:5]]


def run_job_hunt_cycle(db: Session, trigger: str = "manual", adapters: dict[str, JobSourceAdapter] | None = None,
                       source_keys: list[str] | None = None) -> JobSearchRun:
    run = JobSearchRun(trigger=trigger, status="running", stats={}, log=[])
    db.add(run)
    db.commit()
    settings = get_all_settings(db)
    profile = get_profile(db)
    adapters = adapters or all_adapters()
    if not source_keys:
        sync_sources(db)
        enabled = {s.key: s for s in db.scalars(select(JobSource).where(JobSource.enabled.is_(True)))}
        source_keys = list(enabled)
    else:
        enabled = {s.key: s for s in db.scalars(select(JobSource).where(JobSource.key.in_(source_keys)))}
    stats = {"sources": {}, "found": 0, "new": 0, "duplicates": 0, "qualified": 0, "queued": 0, "packaged": 0,
             "video_required": 0, "errors": 0}
    logs: list[str] = []
    rates = _rates(settings)
    new_jobs: list[Job] = []
    seen: set[tuple[str, str]] = set()
    failed: set[str] = set()  # listings already processed in this run (several searches can return them)
    per_source_cap = settings.get("max_applications_per_source_per_day", 40)

    # 1-3. Search, normalize, dedupe
    for search in _searches(db, profile):
        for key in search.sources or source_keys:
            adapter = adapters.get(key)
            if adapter is None or key not in source_keys or key in failed:
                continue
            if adapter.automation_status not in ("allowed", "review_required"):
                logs.append(f"{adapter.name}: manual-only source, skipped.")
                continue
            src_stats = stats["sources"].setdefault(key, {"found": 0, "new": 0, "duplicates": 0, "errors": 0})
            src_row = enabled.get(key)
            cfg = dict((src_row.config if src_row else {}) or {})
            if key in ("greenhouse", "lever", "ashby"):
                cfg["boards"] = (settings.get("company_boards") or {}).get(key, []) or cfg.get("boards", [])
            try:
                raws = adapter.search_jobs(SearchQuery(query=search.query, limit=min(100, per_source_cap * 2),
                                                       categories=(search.filters or {}).get("categories", []), config=cfg))
            except SourceNotSupported as e:
                logs.append(str(e))
                continue
            except Exception as e:  # network / parsing errors must not stop the cycle
                stats["errors"] += 1
                src_stats["errors"] += 1
                failed.add(key)
                logs.append(f"{adapter.name}: error {type(e).__name__}: {e}")
                if src_row:
                    src_row.last_error = f"{type(e).__name__}: {e}"[:500]
                continue
            for raw in raws:
                ident = (key, str(raw.get("job_id_external") or raw.get("source_url") or raw.get("title")))
                if ident in seen:
                    continue
                seen.add(ident)
                try:
                    nj = adapter.normalize_job(raw, rates)
                    res = ingest_job(db, nj, score=False, settings=settings)
                except Exception as e:  # skip a malformed listing
                    stats["errors"] += 1
                    logs.append(f"{adapter.name}: skipped listing ({e})")
                    continue
                stats["found"] += 1
                src_stats["found"] += 1
                if res.created:
                    stats["new"] += 1
                    src_stats["new"] += 1
                    new_jobs.append(res.job)
                else:
                    stats["duplicates"] += 1
                    src_stats["duplicates"] += 1
            if src_row:
                src_row.last_run_at = utcnow()
                src_row.last_error = None
            logs.append(f"{adapter.name} '{search.query}': {len(raws)} listings")
        if search.id:
            search.last_run_at = utcnow()
        db.commit()

    # 4-5. Score & filter
    videos = db.scalars(select(Video).where(Video.is_active.is_(True))).all()
    success = category_success_rates(db)
    for job in new_jobs:
        rescore_job(db, job, settings=settings, profile=profile, videos=videos, success=success)
        if job.application_status == "QUALIFIED":
            stats["qualified"] += 1
        if job.in_queue:
            stats["queued"] += 1
        if job.video_required:
            stats["video_required"] += 1
    db.commit()

    # 6-9. Packages for high-value jobs (videos detected + recommended inside the package)
    if (settings.get("scheduler") or {}).get("auto_package", True):
        today_count = db.scalar(select(func.count()).select_from(Application).where(func.date(Application.created_at) == utcnow().date())) or 0
        budget = max(0, settings.get("daily_application_target", 15) - today_count)
        for job in sorted((j for j in new_jobs if j.in_queue and (j.match_score or 0) >= settings.get("package_min_score", 80)),
                          key=lambda j: j.priority_score or 0, reverse=True)[:budget]:
            try:
                build_package(db, job)
                stats["packaged"] += 1
            except Exception as e:
                logs.append(f"Package failed for job {job.id}: {e}")
        db.commit()

    # 10. Reminders/notifications (dashboard is computed live)
    refresh_reminders(db)
    run.stats = stats
    run.log = logs[-200:]
    run.status = "completed" if not stats["errors"] else "completed_with_errors"
    run.finished_at = utcnow()
    db.commit()
    return run
