"""Application pipeline: statuses, allowed transitions and their side effects."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application, ApplicationStatusHistory, FollowUp, Job, utcnow
from app.services.notifications import notify
from app.services.settings_service import get_setting

PIPELINE = ["DISCOVERED", "QUALIFIED", "READY", "APPLYING", "APPLIED", "FOLLOW_UP", "INTERVIEW", "OFFER", "REJECTED"]
EXTRA = ["HIRED", "WITHDRAWN", "SKIPPED"]
ALL_STATUSES = PIPELINE + EXTRA
JOB_ONLY = {"DISCOVERED", "QUALIFIED", "SKIPPED"}
APPLIED_OR_LATER = {"APPLIED", "FOLLOW_UP", "INTERVIEW", "OFFER", "HIRED", "REJECTED", "WITHDRAWN"}

TRANSITIONS: dict[str, set[str]] = {
    "DISCOVERED": {"QUALIFIED", "READY", "APPLYING", "APPLIED", "SKIPPED"},
    "QUALIFIED": {"DISCOVERED", "READY", "APPLYING", "APPLIED", "SKIPPED"},
    "READY": {"QUALIFIED", "APPLYING", "APPLIED", "SKIPPED"},
    "APPLYING": {"READY", "APPLIED", "SKIPPED"},
    "APPLIED": {"FOLLOW_UP", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN"},
    "FOLLOW_UP": {"APPLIED", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN"},
    "INTERVIEW": {"FOLLOW_UP", "OFFER", "REJECTED", "WITHDRAWN"},
    "OFFER": {"HIRED", "REJECTED", "WITHDRAWN", "INTERVIEW"},
    "HIRED": set(),
    "REJECTED": set(),
    "WITHDRAWN": set(),
    "SKIPPED": {"DISCOVERED", "QUALIFIED", "READY"},
}


class TransitionError(ValueError):
    pass


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, set())


def ensure_application(db: Session, job: Job, mode: str | None = None) -> Application:
    app = db.scalar(select(Application).where(Application.job_id == job.id))
    if app is None:
        app = Application(job_id=job.id, status="READY", mode=mode or get_setting(db, "application_mode") or "copilot", package={})
        db.add(app)
        db.flush()
        db.add(ApplicationStatusHistory(application_id=app.id, from_status=job.application_status, to_status="READY", note="Application created"))
    return app


def transition_job(db: Session, job: Job, target: str, note: str | None = None, force: bool = False) -> Job:
    target = target.upper()
    if target not in ALL_STATUSES:
        raise TransitionError(f"Unknown status {target}")
    current = job.application_status
    if current == target:
        return job
    if not force and not can_transition(current, target):
        raise TransitionError(f"Cannot move from {current} to {target}")
    app = db.scalar(select(Application).where(Application.job_id == job.id))
    if target not in JOB_ONLY or app is not None:
        if app is None:
            app = ensure_application(db, job)
        _apply_side_effects(db, job, app, current, target)
        app.status = target
        db.add(ApplicationStatusHistory(application_id=app.id, from_status=current, to_status=target, note=note))
    job.application_status = target
    job.in_queue = target in {"QUALIFIED", "READY"} and job.in_queue
    if target == "SKIPPED":
        job.in_queue = False
    db.flush()
    return job


def transition_application(db: Session, app: Application, target: str, note: str | None = None, force: bool = False) -> Application:
    transition_job(db, app.job, target, note, force)
    return app


def _apply_side_effects(db: Session, job: Job, app: Application, current: str, target: str) -> None:
    now = utcnow()
    if target == "APPLIED" and app.applied_at is None:
        app.applied_at = now
        days = (get_setting(db, "follow_up") or {}).get("after_application_days", 7)
        key = f"app_followup:{app.id}"
        if not db.scalar(select(FollowUp).where(FollowUp.dedupe_key == key)):
            db.add(FollowUp(kind="application", title=f"Follow up: {job.title} @ {job.company or 'company'}",
                            due_date=(now + timedelta(days=days)).date(), application_id=app.id, job_id=job.id,
                            contact_id=app.contact_id, auto_generated=True, dedupe_key=key))
        _bump_usage(db, app)
    if target in {"INTERVIEW", "OFFER"} and app.response_received_at is None:
        app.response_received_at = now
    if target == "REJECTED" and current in APPLIED_OR_LATER and app.response_received_at is None:
        app.response_received_at = now
    if target in {"REJECTED", "WITHDRAWN", "HIRED"}:
        for fu in db.scalars(select(FollowUp).where(FollowUp.application_id == app.id, FollowUp.status == "PENDING")):
            fu.status = "CANCELLED"
    if target == "OFFER":
        notify(db, "offer", f"Offer: {job.title}", f"{job.company or ''} made an offer!", link=f"/applications/{app.id}",
               entity_type="application", entity_id=app.id, dedupe_key=f"offer:{app.id}")


def _bump_usage(db: Session, app: Application) -> None:
    from app.models import ApplicationAnswer, Video

    pkg = app.package or {}
    for ans in pkg.get("screening_answers") or []:
        if ans.get("answer_id"):
            a = db.get(ApplicationAnswer, ans["answer_id"])
            if a:
                a.times_used = (a.times_used or 0) + 1
                a.last_used_at = utcnow()
    if app.video_id:
        v = db.get(Video, app.video_id)
        if v:
            v.times_used = (v.times_used or 0) + 1
