"""Job Hunt cycle: DISCOVER → NORMALIZE → DEDUPE → HARD FILTERS → SCORE → PRIORITIZE → QUEUE → PACKAGE → REMINDERS.

Never silently reports "0 jobs": every run ends with an explicit outcome:
  no_sources_enabled | all_sources_failed | no_results | only_duplicates | no_matching_jobs | ok
"""
from __future__ import annotations

import logging
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Application, Job, JobSearch, JobSearchRun, JobSource, Video, utcnow
from app.services.application_engine import build_package
from app.services.followups import refresh_reminders
from app.services.jobs_service import _rates, category_success_rates, ingest_job, rescore_job
from app.services.profile_service import get_profile
from app.services.settings_service import get_all_settings
from app.sources.base import JobSourceAdapter, SearchQuery, SourceNotSupported, SourceRateLimited
from app.sources.registry import all_adapters, sync_sources

log = logging.getLogger(__name__)

OUTCOME_MESSAGES = {
    "no_sources_enabled": "No job sources are enabled. Enable at least one source in Settings → Job sources.",
    "all_sources_failed": "Every enabled source failed — see the source errors below.",
    "no_results": "Sources responded but returned no listings for your searches.",
    "rate_limited": "All enabled sources were checked recently; their terms limit how often they can be searched. Try again later.",
    "only_duplicates": "Sources returned listings, but all of them were already known (duplicates).",
    "no_matching_jobs": "New jobs were found, but none passed your filters and minimum match score.",
    "ok": "Job hunt completed.",
}


def _searches(db: Session, profile) -> list[JobSearch]:
    searches = list(db.scalars(select(JobSearch).where(JobSearch.enabled.is_(True))))
    if searches:
        return searches
    roles = profile.preferred_roles or [""]
    return [JobSearch(name=f"Auto: {r or 'all'}", query=r, sources=[], filters={}) for r in roles[:5]]


def _reason_key(reason: str) -> str:
    r = reason.lower()
    for key, words in [("salary", ("salary",)), ("location", ("location", "restricted", "arrangement")),
                       ("employment_type", ("employment type",)), ("seniority", ("seniority",)),
                       ("excluded_company", ("company",)), ("excluded_type", ("job type", "industry")),
                       ("required_keywords", ("keyword",))]:
        if any(w in r for w in words):
            return key
    return "other"


def update_source_health(src: JobSource | None, *, ok: bool, found: int = 0, error: str | None = None) -> None:
    if src is None:
        return
    src.last_run_at = utcnow()
    if ok:
        src.last_status = "ok" if found else "empty"
        src.last_success_at = utcnow()
        src.last_found_count = found
        src.last_error = None
    else:
        src.last_status = "error"
        src.last_error = (error or "unknown error")[:500]


def run_job_hunt_cycle(db: Session, trigger: str = "manual", adapters: dict[str, JobSourceAdapter] | None = None,
                       source_keys: list[str] | None = None, run_id: int | None = None) -> JobSearchRun:
    run = db.get(JobSearchRun, run_id) if run_id else None
    if run is None:
        run = JobSearchRun(trigger=trigger, status="running", stats={}, log=[])
        db.add(run)
        db.commit()
    stats = {"sources": {}, "sources_checked": 0, "sources_failed": 0, "found": 0, "new": 0, "duplicates": 0,
             "rejected_by_filters": 0, "review_by_filters": 0, "filter_reasons": {}, "qualified": 0, "queued": 0,
             "packaged": 0, "video_required": 0, "errors": 0}
    logs: list[str] = []
    try:
        _run(db, run, stats, logs, adapters, source_keys)
    except Exception as e:  # a bug must never leave a run "running" forever
        log.exception("Job hunt failed")
        db.rollback()
        run.status, run.outcome, run.message = "failed", "error", f"Job hunt crashed: {type(e).__name__}: {e}"
    run.stats = stats
    run.log = logs[-300:]
    run.finished_at = utcnow()
    db.commit()
    return run


def _run(db: Session, run: JobSearchRun, stats: dict, logs: list[str], adapters, source_keys) -> None:
    settings = get_all_settings(db)
    profile = get_profile(db)
    adapters = adapters or all_adapters()
    if not source_keys:
        sync_sources(db)
        enabled = {s.key: s for s in db.scalars(select(JobSource).where(JobSource.enabled.is_(True)))}
        source_keys = list(enabled)
    else:
        enabled = {s.key: s for s in db.scalars(select(JobSource).where(JobSource.key.in_(source_keys)))}
    searchable = [k for k in source_keys if k in adapters and adapters[k].automation_status == "allowed"]
    if not searchable:
        run.status, run.outcome, run.message = "completed", "no_sources_enabled", OUTCOME_MESSAGES["no_sources_enabled"]
        return

    rates = _rates(settings)
    new_jobs: list[Job] = []
    seen: set[tuple[str, str]] = set()
    failed: set[str] = set()
    per_source_cap = settings.get("max_applications_per_source_per_day", 40)

    for search in _searches(db, profile):
        for key in search.sources or searchable:
            adapter = adapters.get(key)
            if adapter is None or key not in searchable or key in failed:
                continue
            src_stats = stats["sources"].setdefault(key, {"name": adapter.name, "found": 0, "new": 0, "duplicates": 0,
                                                          "errors": 0, "error": None})
            src_row = enabled.get(key)
            cfg = dict((src_row.config if src_row else {}) or {})
            if key in ("greenhouse", "lever", "ashby"):
                cfg["boards"] = (settings.get("company_boards") or {}).get(key, []) or cfg.get("boards", [])
                if not cfg["boards"]:
                    msg = f"{adapter.name}: no company boards configured (Settings → Job sources)."
                    src_stats["error"] = msg
                    logs.append(msg)
                    failed.add(key)
                    update_source_health(src_row, ok=False, error=msg)
                    continue
            try:
                raws = adapter.search_jobs(SearchQuery(query=search.query, limit=min(100, per_source_cap * 2),
                                                       categories=(search.filters or {}).get("categories", []), config=cfg))
            except SourceRateLimited as e:
                logs.append(str(e))
                src_stats["skipped"] = str(e)
                stats["sources_rate_limited"] = stats.get("sources_rate_limited", 0) + 1
                continue
            except SourceNotSupported as e:
                logs.append(str(e))
                src_stats["error"] = str(e)
                continue
            except Exception as e:  # network / schema errors must not stop the hunt
                err = f"{type(e).__name__}: {e}"[:400]
                stats["errors"] += 1
                src_stats["errors"] += 1
                src_stats["error"] = err
                failed.add(key)
                logs.append(f"{adapter.name}: {err}")
                update_source_health(src_row, ok=False, error=err)
                continue
            got = 0
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
                got += 1
                stats["found"] += 1
                src_stats["found"] += 1
                if res.created:
                    stats["new"] += 1
                    src_stats["new"] += 1
                    new_jobs.append(res.job)
                else:
                    stats["duplicates"] += 1
                    src_stats["duplicates"] += 1
            logs.append(f"{adapter.name} '{search.query or 'all'}': {len(raws)} listings, {got} processed")
        if search.id:
            search.last_run_at = utcnow()
        db.commit()

    for key, st in stats["sources"].items():
        if key not in failed and not st.get("error") and not st.get("skipped"):
            update_source_health(enabled.get(key), ok=True, found=st["found"])
    stats["sources_checked"] = len({k for k in searchable if k in stats["sources"]})
    stats["sources_failed"] = len(failed & set(stats["sources"]))

    # HARD FILTERS → SCORE → PRIORITIZE → QUEUE (rescore_job applies filters before qualifying/queueing)
    videos = db.scalars(select(Video).where(Video.is_active.is_(True))).all()
    success = category_success_rates(db)
    reasons: Counter = Counter()
    for job in new_jobs:
        rescore_job(db, job, settings=settings, profile=profile, videos=videos, success=success)
        if job.filter_status == "rejected":
            stats["rejected_by_filters"] += 1
            for r in job.filter_reasons or []:
                if not r.startswith("Note:"):
                    reasons[_reason_key(r)] += 1
        elif job.filter_status == "review":
            stats["review_by_filters"] += 1
        if job.application_status == "QUALIFIED":
            stats["qualified"] += 1
        if job.in_queue:
            stats["queued"] += 1
        if job.video_required:
            stats["video_required"] += 1
    stats["filter_reasons"] = dict(reasons)
    db.commit()

    # PACKAGES for high-value queued jobs (videos detected + recommended inside the package)
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

    refresh_reminders(db)

    if stats["sources_checked"] and stats["sources_failed"] == stats["sources_checked"]:
        outcome = "all_sources_failed"
    elif stats["found"] == 0 and all(st.get("skipped") for st in stats["sources"].values()) and stats["sources"]:
        outcome = "rate_limited"
    elif stats["found"] == 0:
        outcome = "no_results"
    elif stats["new"] == 0:
        outcome = "only_duplicates"
    elif stats["qualified"] == 0:
        outcome = "no_matching_jobs"
    else:
        outcome = "ok"
    run.outcome = outcome
    run.message = OUTCOME_MESSAGES[outcome]
    if outcome == "all_sources_failed":
        run.status = "failed"
    elif stats["errors"] or stats["sources_failed"]:
        run.status = "completed_with_errors"
    else:
        run.status = "completed"
