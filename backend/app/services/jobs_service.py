"""Job ingestion (normalize → dedupe → store → score → queue) and re-scoring."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Application, Company, Contact, Job, JobSourceRef, ResumeVersion, Video, utcnow
from app.services.dedupe import find_duplicate
from app.services.filters import evaluate_hard_filters
from app.services.normalization import NormalizedJob, normalize_job
from app.services.notifications import notify
from app.services.priority import priority_score
from app.services.profile_service import get_profile
from app.services.scoring import score_job
from app.services.settings_service import get_all_settings
from app.services.text_utils import normalize_company
from app.services.video_matching import recommend_video

JOB_FIELDS = [
    "title", "company", "company_url", "source", "source_url", "canonical_url", "apply_url", "description",
    "requirements", "application_questions", "salary_min", "salary_max", "salary_currency", "salary_period",
    "salary_monthly_usd_min", "salary_monthly_usd_max", "location", "remote_type", "employment_type", "category",
    "seniority", "posted_at", "job_id_external", "applicants_count", "easy_apply", "video_required", "video_details",
    "detected_requirements",
]


@dataclass
class IngestResult:
    job: Job
    created: bool
    duplicate_reason: str | None = None


def get_or_create_company(db: Session, name: str | None, url: str | None = None) -> Company | None:
    norm = normalize_company(name)
    if not norm:
        return None
    comp = db.scalar(select(Company).where(Company.normalized_name == norm))
    if comp is None:
        comp = Company(name=name.strip(), normalized_name=norm, website=url)
        db.add(comp)
        db.flush()
    elif url and not comp.website:
        comp.website = url
    return comp


def ingest_job(db: Session, nj: NormalizedJob, *, score: bool = True, settings: dict | None = None) -> IngestResult:
    dup = find_duplicate(db, nj)
    if dup:
        job = dup.job
        exists_ref = any(r.source == nj.source and (r.external_id == nj.job_id_external or (r.canonical_url and r.canonical_url == nj.canonical_url)) for r in job.refs)
        if not exists_ref:
            job.refs.append(JobSourceRef(source=nj.source, external_id=nj.job_id_external, url=nj.source_url,
                                         canonical_url=nj.canonical_url, apply_url=nj.apply_url,
                                         duplicate_reason=dup.reason, raw=_safe_raw(nj.raw)))
        # enrich missing fields from the new listing
        for f in ["salary_min", "salary_max", "salary_currency", "salary_period", "salary_monthly_usd_min",
                  "salary_monthly_usd_max", "company_url", "apply_url", "posted_at", "applicants_count"]:
            if getattr(job, f) in (None, "") and getattr(nj, f) not in (None, ""):
                setattr(job, f, getattr(nj, f))
        if nj.description and (not job.description or len(nj.description) > len(job.description) * 1.3):
            job.description = nj.description
        db.flush()
        return IngestResult(job, False, dup.reason)

    job = Job(**{f: getattr(nj, f) for f in JOB_FIELDS})
    comp = get_or_create_company(db, nj.company, nj.company_url)
    job.company_id = comp.id if comp else None
    job.discovered_at = utcnow()
    job.refs.append(JobSourceRef(source=nj.source, external_id=nj.job_id_external, url=nj.source_url,
                                 canonical_url=nj.canonical_url, apply_url=nj.apply_url, raw=_safe_raw(nj.raw)))
    db.add(job)
    db.flush()
    if score:
        rescore_job(db, job, settings=settings)
    return IngestResult(job, True)


def _safe_raw(raw: dict) -> dict:
    # Keep raw payloads small
    out = {}
    for k, v in (raw or {}).items():
        if isinstance(v, str) and len(v) > 2000:
            continue
        out[k] = v
    return out


def ingest_dict(db: Session, data: dict, source: str = "manual", settings: dict | None = None) -> IngestResult:
    settings = settings or get_all_settings(db)
    nj = normalize_job(data, source=source, usd_rates=_rates(settings))
    return ingest_job(db, nj, settings=settings)


def _rates(settings: dict) -> dict | None:
    from app.services.salary import DEFAULT_USD_RATES

    custom = settings.get("usd_rates") or {}
    return {**DEFAULT_USD_RATES, **custom} if custom else None


def category_success_rates(db: Session) -> dict[str, float]:
    """Interview rate per job category from historical applications (min 5 apps)."""
    rows = db.execute(
        select(Job.category, Application.status, func.count())
        .join(Application, Application.job_id == Job.id)
        .where(Application.applied_at.is_not(None))
        .group_by(Job.category, Application.status)
    ).all()
    totals: dict[str, int] = {}
    wins: dict[str, int] = {}
    for cat, status, n in rows:
        cat = cat or "other"
        totals[cat] = totals.get(cat, 0) + n
        if status in {"INTERVIEW", "OFFER", "HIRED"}:
            wins[cat] = wins.get(cat, 0) + n
    return {c: wins.get(c, 0) / t for c, t in totals.items() if t >= 5}


def rescore_job(db: Session, job: Job, settings: dict | None = None, profile=None, videos=None,
                success: dict | None = None, notify_high: bool = True) -> Job:
    settings = settings or get_all_settings(db)
    profile = profile or get_profile(db)
    videos = videos if videos is not None else db.scalars(select(Video).where(Video.is_active.is_(True))).all()
    previous = job.match_score
    # Hard filters first: a high score can never override a user requirement.
    fr = evaluate_hard_filters(job, profile, settings)
    job.filter_status = fr.status
    job.filter_reasons = fr.as_list()
    result = score_job(job, profile, settings, videos)
    job.match_score = result.score
    job.classification = result.classification
    job.score_breakdown = result.breakdown
    job.match_reasons = result.reasons
    job.concerns = result.concerns
    job.scored_at = utcnow()

    has_contact = db.scalar(select(func.count()).select_from(Contact).where(Contact.job_id == job.id)) > 0 if job.id else False
    has_tailored = db.scalar(select(func.count()).select_from(ResumeVersion).where(ResumeVersion.job_id == job.id)) > 0 if job.id else False
    has_video = bool(recommend_video(job, videos)) if job.video_required else False
    pscore, pbreak = priority_score(job, profile, settings, has_contact=has_contact, has_tailored_resume=has_tailored,
                                    has_matching_video=has_video,
                                    category_success=success if success is not None else category_success_rates(db))
    job.priority_score = pscore
    job.priority_breakdown = pbreak

    if job.application_status in {"DISCOVERED", "QUALIFIED", "SKIPPED"}:
        min_score = settings.get("min_match_score", 60)
        if result.score >= min_score and fr.status != "rejected":
            if job.application_status == "DISCOVERED":
                job.application_status = "QUALIFIED"
        elif job.application_status == "QUALIFIED":
            job.application_status = "DISCOVERED"
        # Only jobs that PASS every hard filter enter the queue automatically ("review" waits for the user).
        job.in_queue = (fr.status == "passed" and result.score >= settings.get("queue_min_score", 70)
                        and job.application_status == "QUALIFIED" and not job.archived)
    elif fr.status == "rejected" and job.application_status == "READY":
        job.in_queue = False

    if notify_high and previous is None and fr.status == "passed" and result.score >= settings.get("notify_min_match_score", 85):
        notify(db, "high_match_job", f"New {result.classification} match: {job.title}",
               f"{job.company or 'Unknown company'} · score {result.score:.0f}", link=f"/jobs/{job.id}",
               entity_type="job", entity_id=job.id, dedupe_key=f"high_match:{job.id}")
    if notify_high and previous is None and fr.status == "passed" and job.video_required and result.score >= settings.get("min_match_score", 60):
        notify(db, "video_required", f"Video required: {job.title}", f"{job.company or ''} asks for a video.",
               link=f"/jobs/{job.id}", entity_type="job", entity_id=job.id, dedupe_key=f"video_required:{job.id}")
    db.flush()
    return job


def rescore_all(db: Session) -> int:
    settings = get_all_settings(db)
    profile = get_profile(db)
    videos = db.scalars(select(Video).where(Video.is_active.is_(True))).all()
    success = category_success_rates(db)
    jobs = db.scalars(select(Job).where(Job.archived.is_(False))).all()
    for job in jobs:
        rescore_job(db, job, settings=settings, profile=profile, videos=videos, success=success, notify_high=False)
    db.commit()
    return len(jobs)


def apply_queue(db: Session, limit: int = 100) -> list[Job]:
    return list(
        db.scalars(
            select(Job)
            .where(Job.in_queue.is_(True), Job.archived.is_(False), Job.application_status.in_(["QUALIFIED", "READY"]),
                   Job.filter_status != "rejected")
            .order_by(Job.priority_score.desc().nullslast(), Job.match_score.desc().nullslast())
            .limit(limit)
        ).all()
    )
