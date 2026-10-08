"""Follow-up reminders: recommendations, message generation, mark sent, postpone, due notifications."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import get_provider
from app.models import Application, Contact, FollowUp, Interview, Job, utcnow
from app.services.crm import add_activity, create_interview_follow_ups, is_upcoming
from app.services.generation import generate_follow_up
from app.services.notifications import notify
from app.services.pipeline import TransitionError, transition_job
from app.services.profile_service import get_profile
from app.services.settings_service import get_all_settings, get_setting


def generate_message(db: Session, fu: FollowUp) -> FollowUp:
    settings = get_all_settings(db)
    provider = get_provider(settings.get("ai_provider"), settings.get("ai_model") or None)
    job = db.get(Job, fu.job_id) if fu.job_id else None
    app = db.get(Application, fu.application_id) if fu.application_id else None
    if job is None and app is not None:
        job = app.job
    contact = db.get(Contact, fu.contact_id) if fu.contact_id else None
    iv = db.get(Interview, fu.interview_id) if fu.interview_id else None
    kind = fu.kind if fu.kind in {"application", "interview_thank_you", "interview_follow_up", "contact"} else "application"
    g = generate_follow_up(kind, get_profile(db), job, contact, iv, provider)
    fu.message = g.text
    db.flush()
    return fu


def mark_sent(db: Session, fu: FollowUp, channel: str | None = None) -> FollowUp:
    fu.status = "SENT"
    fu.sent_at = utcnow()
    fu.channel = channel or fu.channel
    if fu.contact_id:
        contact = db.get(Contact, fu.contact_id)
        if contact:
            add_activity(db, contact, "follow_up", fu.title, fu.message, channel=fu.channel)
    if fu.application_id:
        app = db.get(Application, fu.application_id)
        if app and app.status == "APPLIED":
            try:
                transition_job(db, app.job, "FOLLOW_UP", "Follow-up sent")
            except TransitionError:
                pass
    db.flush()
    return fu


def postpone(db: Session, fu: FollowUp, days: int = 2) -> FollowUp:
    base = max(fu.due_date, date.today())
    fu.due_date = base + timedelta(days=days)
    fu.postponed_count = (fu.postponed_count or 0) + 1
    db.flush()
    return fu


def refresh_reminders(db: Session) -> dict:
    """Create recommended follow-ups and due/upcoming notifications. Idempotent."""
    cfg = get_setting(db, "follow_up") or {}
    today = date.today()
    created = 0
    # 1) Applications without response
    days = cfg.get("after_application_days", 7)
    for app in db.scalars(select(Application).where(Application.status == "APPLIED", Application.response_received_at.is_(None),
                                                     Application.applied_at.is_not(None))):
        key = f"app_followup:{app.id}"
        if db.scalar(select(FollowUp).where(FollowUp.dedupe_key == key)):
            continue
        applied = app.applied_at.date()
        db.add(FollowUp(kind="application", title=f"Follow up: {app.job.title} @ {app.job.company or 'company'}",
                        due_date=max(applied + timedelta(days=days), today), application_id=app.id, job_id=app.job_id,
                        contact_id=app.contact_id, auto_generated=True, dedupe_key=key))
        created += 1
    # 2) Completed interviews → thank-you + follow-up
    for iv in db.scalars(select(Interview).where(Interview.status == "COMPLETED")):
        created += len(create_interview_follow_ups(db, iv))
    # 3) Contacts with no reply
    nr = cfg.get("contact_no_reply_days", 5)
    for c in db.scalars(select(Contact).where(Contact.status == "CONTACTED", Contact.last_contact_date.is_not(None))):
        if c.last_contact_date <= today - timedelta(days=nr):
            key = f"contact_followup:{c.id}:{c.last_contact_date}"
            if not db.scalar(select(FollowUp).where(FollowUp.dedupe_key == key)):
                db.add(FollowUp(kind="contact", title=f"Follow up with {c.full_name}", due_date=today, contact_id=c.id,
                                job_id=c.job_id, auto_generated=True, dedupe_key=key))
                created += 1
    # 4) Contacts with an explicit next follow-up date
    for c in db.scalars(select(Contact).where(Contact.next_follow_up_date.is_not(None))):
        key = f"contact_next:{c.id}:{c.next_follow_up_date}"
        if not db.scalar(select(FollowUp).where(FollowUp.dedupe_key == key)):
            db.add(FollowUp(kind="contact", title=f"Follow up with {c.full_name}", due_date=c.next_follow_up_date,
                            contact_id=c.id, job_id=c.job_id, dedupe_key=key))
            created += 1
    db.flush()
    # Notifications: due follow-ups, upcoming interviews
    for fu in db.scalars(select(FollowUp).where(FollowUp.status == "PENDING", FollowUp.due_date <= today)):
        notify(db, "follow_up_due", f"Follow-up due: {fu.title}", f"Due {fu.due_date.isoformat()}", link="/followups",
               entity_type="follow_up", entity_id=fu.id, dedupe_key=f"fu_due:{fu.id}:{fu.due_date}")
    for iv in db.scalars(select(Interview).where(Interview.status == "SCHEDULED", Interview.scheduled_at.is_not(None))):
        if is_upcoming(iv):
            notify(db, "interview_upcoming", f"Interview soon: {iv.company or ''}", f"{iv.interview_type} at {iv.scheduled_at:%Y-%m-%d %H:%M}",
                   link="/interviews", entity_type="interview", entity_id=iv.id, dedupe_key=f"int_upcoming:{iv.id}:{iv.scheduled_at}")
    db.commit()
    return {"created": created}
