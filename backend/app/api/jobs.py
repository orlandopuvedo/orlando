from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import DB, get_or_404, to_dict
from app.models import Application, Contact, Job, Video
from app.services.detection import CATEGORY_LABELS
from app.services.jobs_service import apply_queue, ingest_dict, rescore_all, rescore_job
from app.services.normalization import normalize_job
from app.services.pipeline import ALL_STATUSES, PIPELINE, TransitionError, ensure_application, transition_job
from app.services.settings_service import get_all_settings
from app.services.url_import import UrlImportError, import_from_url
from app.services.video_matching import recommend_video

router = APIRouter(prefix="/api", tags=["jobs"])

LIST_EXCLUDE = {"description", "requirements", "application_questions", "score_breakdown", "priority_breakdown"}


def job_summary(j: Job) -> dict:
    d = to_dict(j, exclude=LIST_EXCLUDE)
    d["sources"] = sorted({r.source for r in j.refs})
    d["category_label"] = CATEGORY_LABELS.get(j.category or "other", "Other")
    return d


def job_detail(db: Session, j: Job) -> dict:
    d = to_dict(j)
    d["category_label"] = CATEGORY_LABELS.get(j.category or "other", "Other")
    d["refs"] = [{"source": r.source, "url": r.url, "external_id": r.external_id, "duplicate_reason": r.duplicate_reason,
                  "discovered_at": r.discovered_at} for r in j.refs]
    app = db.scalar(select(Application).where(Application.job_id == j.id))
    d["application_id"] = app.id if app else None
    d["contacts"] = [to_dict(c) for c in db.scalars(select(Contact).where(Contact.job_id == j.id))]
    if j.video_required:
        d["video_recommendation"] = recommend_video(j, db.scalars(select(Video).where(Video.is_active.is_(True))).all())
    return d


@router.get("/jobs")
def list_jobs(q: str | None = None, status: str | None = None, min_score: float | None = None, source: str | None = None,
              category: str | None = None, remote_type: str | None = None, video_required: bool | None = None,
              archived: bool = False, sort: str = "priority", limit: int = 200, offset: int = 0, db: Session = DB):
    stmt = select(Job).where(Job.archived.is_(archived))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Job.title.ilike(like), Job.company.ilike(like), Job.description.ilike(like)))
    if status:
        stmt = stmt.where(Job.application_status.in_(status.upper().split(",")))
    if min_score is not None:
        stmt = stmt.where(Job.match_score >= min_score)
    if source:
        stmt = stmt.where(Job.source == source)
    if category:
        stmt = stmt.where(Job.category == category)
    if remote_type:
        stmt = stmt.where(Job.remote_type == remote_type)
    if video_required is not None:
        stmt = stmt.where(Job.video_required.is_(video_required))
    order = {"priority": Job.priority_score.desc().nullslast(), "match": Job.match_score.desc().nullslast(),
             "recent": Job.discovered_at.desc(), "salary": Job.salary_monthly_usd_max.desc().nullslast(),
             "posted": Job.posted_at.desc().nullslast()}.get(sort, Job.priority_score.desc().nullslast())
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.order_by(order).limit(limit).offset(offset)).all()
    return {"total": total, "items": [job_summary(j) for j in items]}


@router.post("/jobs")
def create_job(data: dict[str, Any], db: Session = DB):
    if not (data.get("title") or "").strip():
        raise HTTPException(422, "title is required")
    res = ingest_dict(db, data, source=data.get("source") or "manual")
    if data.get("notes"):
        res.job.notes = data["notes"]
    db.commit()
    return {"job": job_detail(db, res.job), "created": res.created, "duplicate_reason": res.duplicate_reason}


@router.post("/jobs/preview")
def preview_job(data: dict[str, Any]):
    """Normalize without saving (used by the Add Job form to show detected fields)."""
    nj = normalize_job(data, source=data.get("source") or "manual")
    return nj.to_dict()


@router.post("/jobs/import-url")
def import_url(data: dict[str, Any], db: Session = DB):
    try:
        raw, source = import_from_url(data.get("url", ""))
    except UrlImportError as e:
        raise HTTPException(400, str(e)) from e
    res = ingest_dict(db, raw, source=source)
    db.commit()
    return {"job": job_detail(db, res.job), "created": res.created, "duplicate_reason": res.duplicate_reason}


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = DB):
    return job_detail(db, get_or_404(db, Job, job_id))


EDITABLE = {"title", "company", "company_url", "source_url", "apply_url", "description", "requirements", "application_questions",
            "salary_min", "salary_max", "salary_currency", "salary_period", "location", "remote_type", "employment_type",
            "category", "seniority", "posted_at", "applicants_count", "easy_apply", "notes", "archived", "in_queue"}


@router.put("/jobs/{job_id}")
def update_job(job_id: int, data: dict[str, Any], db: Session = DB):
    from app.services.normalization import parse_datetime

    job = get_or_404(db, Job, job_id)
    for k, v in data.items():
        if k in EDITABLE:
            setattr(job, k, parse_datetime(v) if k == "posted_at" else v)
    if any(k in data for k in ("title", "description", "requirements", "application_questions", "salary_min", "salary_max",
                               "salary_currency", "salary_period", "location", "remote_type")):
        nj = normalize_job(to_dict(job), source=job.source)
        for f in ("salary_min", "salary_max", "salary_currency", "salary_period", "salary_monthly_usd_min",
                  "salary_monthly_usd_max", "video_required", "video_details", "detected_requirements", "remote_type"):
            setattr(job, f, getattr(nj, f))
        if "category" not in data:
            job.category = nj.category
        if "seniority" not in data:
            job.seniority = nj.seniority
    rescore_job(db, job, notify_high=False)
    db.commit()
    return job_detail(db, job)


@router.delete("/jobs/{job_id}")
def delete_job(job_id: int, db: Session = DB):
    db.delete(get_or_404(db, Job, job_id))
    db.commit()
    return {"ok": True}


@router.post("/jobs/{job_id}/score")
def score_one(job_id: int, db: Session = DB):
    job = get_or_404(db, Job, job_id)
    rescore_job(db, job, notify_high=False)
    db.commit()
    return job_detail(db, job)


@router.post("/jobs/rescore-all")
def score_all(db: Session = DB):
    return {"rescored": rescore_all(db)}


@router.post("/jobs/{job_id}/status")
def move_job(job_id: int, data: dict[str, Any], db: Session = DB):
    job = get_or_404(db, Job, job_id)
    target = (data.get("status") or "").upper()
    try:
        if target == "READY" and job.application_status in ("DISCOVERED", "QUALIFIED", "SKIPPED") and data.get("build_package", True):
            from app.services.application_engine import build_package

            build_package(db, job)
        else:
            transition_job(db, job, target, data.get("note"), force=bool(data.get("force")))
    except TransitionError as e:
        raise HTTPException(409, str(e)) from e
    db.commit()
    return job_summary(job)


@router.post("/jobs/{job_id}/queue")
def toggle_queue(job_id: int, data: dict[str, Any], db: Session = DB):
    job = get_or_404(db, Job, job_id)
    job.in_queue = bool(data.get("in_queue", True))
    if job.in_queue and job.application_status == "DISCOVERED":
        job.application_status = "QUALIFIED"
    db.commit()
    return job_summary(job)


@router.get("/queue")
def get_queue(limit: int = 100, db: Session = DB):
    out = []
    for j in apply_queue(db, limit):
        d = job_summary(j)
        app = db.scalar(select(Application).where(Application.job_id == j.id))
        d["application_id"] = app.id if app else None
        d["priority_breakdown"] = j.priority_breakdown
        out.append(d)
    return out


@router.get("/pipeline")
def pipeline(db: Session = DB):
    cols = {s: [] for s in PIPELINE}
    jobs = db.scalars(select(Job).where(Job.archived.is_(False), Job.application_status.in_(PIPELINE))
                      .order_by(Job.priority_score.desc().nullslast())).all()
    apps = {a.job_id: a for a in db.scalars(select(Application))}
    for j in jobs:
        if j.application_status == "DISCOVERED" and len(cols["DISCOVERED"]) >= 150:
            continue
        d = job_summary(j)
        d["application_id"] = apps[j.id].id if j.id in apps else None
        cols[j.application_status].append(d)
    counts = dict(db.execute(select(Job.application_status, func.count()).group_by(Job.application_status)).all())
    return {"columns": [{"status": s, "count": counts.get(s, 0), "items": cols[s]} for s in PIPELINE], "statuses": ALL_STATUSES}


@router.post("/jobs/{job_id}/application")
def create_application(job_id: int, data: dict[str, Any] | None = None, db: Session = DB):
    from app.services.application_engine import build_package

    job = get_or_404(db, Job, job_id)
    data = data or {}
    if data.get("package", True):
        app = build_package(db, job, mode=data.get("mode"))
    else:
        app = ensure_application(db, job, data.get("mode"))
        if job.application_status in ("DISCOVERED", "QUALIFIED"):
            transition_job(db, job, "READY", "Application created")
    db.commit()
    return {"application_id": app.id}
