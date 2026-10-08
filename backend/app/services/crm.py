"""Recruiter CRM logic: contact status progression, activity timeline, interviews, profile views."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Application, Contact, ContactActivity, FollowUp, Interview, Job, ProfileView, utcnow
from app.services.notifications import notify
from app.services.pipeline import TransitionError, transition_job
from app.services.settings_service import get_setting

CONTACT_STATUSES = ["NEW", "PROFILE_VIEWED", "CONTACTED", "REPLIED", "SCREENING", "INTERVIEW_SCHEDULED", "INTERVIEW_1",
                    "INTERVIEW_2", "FINAL_INTERVIEW", "OFFER", "HIRED", "REJECTED", "NO_RESPONSE"]
STATUS_RANK = {s: i for i, s in enumerate(CONTACT_STATUSES[:11])}

ACTIVITY_TYPES = ["profile_view", "message_received", "message_sent", "email", "call", "screening", "interview",
                  "follow_up", "offer", "rejection", "note"]
COMMUNICATION_TYPES = {"message_received", "message_sent", "email", "call", "screening", "interview", "follow_up", "offer"}

PIPELINE_COLUMNS = {
    "NEW": ["NEW", "PROFILE_VIEWED"], "CONTACTED": ["CONTACTED"], "REPLIED": ["REPLIED"], "SCREENING": ["SCREENING"],
    "INTERVIEW": ["INTERVIEW_SCHEDULED", "INTERVIEW_1", "INTERVIEW_2"], "FINAL": ["FINAL_INTERVIEW"], "OFFER": ["OFFER"],
    "HIRED": ["HIRED"], "CLOSED": ["REJECTED", "NO_RESPONSE"],
}


def advance_status(contact: Contact, target: str) -> bool:
    """Move a contact forward (never backwards automatically). Rejection/no-response always apply."""
    if target in {"REJECTED", "NO_RESPONSE"}:
        if contact.status not in {"HIRED", "OFFER"} or target == "REJECTED":
            contact.status = target
            return True
        return False
    if contact.status in {"REJECTED", "NO_RESPONSE"}:
        contact.status = target  # they came back
        return True
    if STATUS_RANK.get(target, -1) > STATUS_RANK.get(contact.status, -1):
        contact.status = target
        return True
    return False


def _has_activity(db: Session, contact_id: int, type_: str) -> bool:
    return bool(db.scalar(select(func.count()).select_from(ContactActivity).where(ContactActivity.contact_id == contact_id, ContactActivity.type == type_)))


def _linked_application(db: Session, contact: Contact) -> Application | None:
    app = db.scalar(select(Application).where(Application.contact_id == contact.id))
    if app is None and contact.job_id:
        app = db.scalar(select(Application).where(Application.job_id == contact.job_id))
    return app


def add_activity(db: Session, contact: Contact, type_: str, summary: str | None = None, details: str | None = None,
                 occurred_at: datetime | None = None, channel: str | None = None, interview_id: int | None = None,
                 auto_status: bool = True) -> ContactActivity:
    if type_ not in ACTIVITY_TYPES:
        raise ValueError(f"Unknown activity type {type_}")
    occurred_at = occurred_at or utcnow()
    act = ContactActivity(contact_id=contact.id, type=type_, summary=summary or type_.replace("_", " ").capitalize(),
                          details=details, occurred_at=occurred_at, channel=channel, interview_id=interview_id)
    db.add(act)
    day = occurred_at.date()
    if type_ in COMMUNICATION_TYPES:
        if contact.first_contact_date is None or day < contact.first_contact_date:
            contact.first_contact_date = day
        if contact.last_contact_date is None or day > contact.last_contact_date:
            contact.last_contact_date = day
    if auto_status:
        _auto_status(db, contact, type_)
    if type_ == "message_received":
        notify(db, "recruiter_contact", f"{contact.full_name} contacted you", summary, link=f"/contacts/{contact.id}",
               entity_type="contact", entity_id=contact.id, dedupe_key=f"recruiter_contact:{contact.id}:{occurred_at.isoformat()}")
    _sync_application(db, contact, type_)
    db.flush()
    return act


def _auto_status(db: Session, contact: Contact, type_: str) -> None:
    rank = STATUS_RANK.get(contact.status, 0)
    if type_ == "profile_view":
        advance_status(contact, "PROFILE_VIEWED")
    elif type_ == "message_received":
        if rank < STATUS_RANK["CONTACTED"] or contact.status in {"NO_RESPONSE"}:
            advance_status(contact, "CONTACTED")
        elif contact.status == "CONTACTED" and _has_activity(db, contact.id, "message_sent"):
            advance_status(contact, "REPLIED")
    elif type_ in {"message_sent", "email", "call"}:
        if rank < STATUS_RANK["CONTACTED"]:
            advance_status(contact, "CONTACTED")
        elif contact.status == "CONTACTED" and _has_activity(db, contact.id, "message_received"):
            advance_status(contact, "REPLIED")
    elif type_ == "screening":
        advance_status(contact, "SCREENING")
    elif type_ == "interview":
        advance_status(contact, "INTERVIEW_SCHEDULED")
    elif type_ == "offer":
        advance_status(contact, "OFFER")
    elif type_ == "rejection":
        advance_status(contact, "REJECTED")


def _sync_application(db: Session, contact: Contact, type_: str) -> None:
    app = _linked_application(db, contact)
    if not app or app.applied_at is None:
        return
    if type_ in {"message_received", "screening", "interview", "offer", "rejection"} and app.response_received_at is None:
        app.response_received_at = utcnow()
    target = {"screening": "INTERVIEW", "interview": "INTERVIEW", "offer": "OFFER", "rejection": "REJECTED"}.get(type_)
    if target:
        try:
            transition_job(db, app.job, target, f"From contact activity ({type_})")
        except TransitionError:
            pass


# ------------------------------------------------------------------ profile views
def record_profile_view(db: Session, data: dict) -> ProfileView:
    pv = ProfileView(**data)
    db.add(pv)
    db.flush()
    if pv.contact_id:
        contact = db.get(Contact, pv.contact_id)
        if contact:
            add_activity(db, contact, "profile_view", f"Viewed your profile on {pv.platform}", pv.notes,
                         occurred_at=datetime.combine(pv.viewed_on, datetime.min.time()).astimezone())
    return pv


# ------------------------------------------------------------------ interviews
def next_interview_number(db: Session, job_id: int | None, company: str | None) -> int:
    q = select(func.count()).select_from(Interview).where(Interview.status != "CANCELLED")
    if job_id:
        q = q.where(Interview.job_id == job_id)
    elif company:
        q = q.where(func.lower(Interview.company) == company.lower())
    else:
        return 1
    return (db.scalar(q) or 0) + 1


def create_interview(db: Session, data: dict) -> Interview:
    data = dict(data)
    if not data.get("interview_number"):
        data["interview_number"] = next_interview_number(db, data.get("job_id"), data.get("company"))
    if data.get("job_id") and not data.get("company"):
        job = db.get(Job, data["job_id"])
        data["company"] = job.company if job else None
    if data.get("job_id") and not data.get("application_id"):
        app = db.scalar(select(Application).where(Application.job_id == data["job_id"]))
        data["application_id"] = app.id if app else None
    iv = Interview(**data)
    db.add(iv)
    db.flush()
    label = "Final interview" if iv.is_final else f"Interview #{iv.interview_number}"
    if iv.contact_id:
        contact = db.get(Contact, iv.contact_id)
        if contact:
            add_activity(db, contact, "interview", f"{label} scheduled", iv.notes, interview_id=iv.id,
                         occurred_at=utcnow(), auto_status=True)
    if iv.application_id:
        app = db.get(Application, iv.application_id)
        if app and app.status in {"APPLIED", "FOLLOW_UP"}:
            transition_job(db, app.job, "INTERVIEW", f"{label} scheduled")
        if app and app.response_received_at is None:
            app.response_received_at = utcnow()
    return iv


def complete_interview(db: Session, iv: Interview, notes: str | None = None, questions_asked: str | None = None,
                       answers_lessons: str | None = None, next_steps: str | None = None) -> Interview:
    iv.status = "COMPLETED"
    iv.completed_at = utcnow()
    for field, val in [("notes", notes), ("questions_asked", questions_asked), ("answers_lessons", answers_lessons), ("next_steps", next_steps)]:
        if val is not None:
            setattr(iv, field, val)
    label = "Final interview" if iv.is_final else f"Interview #{iv.interview_number}"
    if iv.contact_id:
        contact = db.get(Contact, iv.contact_id)
        if contact:
            add_activity(db, contact, "note", f"{label} completed", iv.notes, interview_id=iv.id, auto_status=False)
            target = "FINAL_INTERVIEW" if iv.is_final else ("INTERVIEW_1" if iv.interview_number <= 1 else "INTERVIEW_2")
            advance_status(contact, target)
    create_interview_follow_ups(db, iv)
    db.flush()
    return iv


def create_interview_follow_ups(db: Session, iv: Interview) -> list[FollowUp]:
    cfg = get_setting(db, "follow_up") or {}
    base = (iv.completed_at or utcnow()).date()
    out = []
    job = db.get(Job, iv.job_id) if iv.job_id else None
    who = iv.company or (job.company if job else "") or "interview"
    for kind, days, title in [
        ("interview_thank_you", cfg.get("thank_you_after_interview_days", 1), f"Send thank-you note ({who})"),
        ("interview_follow_up", cfg.get("after_interview_days", 3), f"Follow up after interview ({who})"),
    ]:
        key = f"{kind}:{iv.id}"
        if db.scalar(select(FollowUp).where(FollowUp.dedupe_key == key)):
            continue
        fu = FollowUp(kind=kind, title=title, due_date=base + timedelta(days=days), interview_id=iv.id,
                      contact_id=iv.contact_id, application_id=iv.application_id, job_id=iv.job_id,
                      auto_generated=True, dedupe_key=key)
        db.add(fu)
        out.append(fu)
    if iv.follow_up_date:
        key = f"interview_custom:{iv.id}:{iv.follow_up_date}"
        if not db.scalar(select(FollowUp).where(FollowUp.dedupe_key == key)):
            db.add(FollowUp(kind="interview_follow_up", title=f"Interview follow-up ({who})", due_date=iv.follow_up_date,
                            interview_id=iv.id, contact_id=iv.contact_id, application_id=iv.application_id,
                            job_id=iv.job_id, dedupe_key=key))
    db.flush()
    return out


def is_upcoming(iv: Interview, within_hours: int = 24) -> bool:
    if iv.status != "SCHEDULED" or not iv.scheduled_at:
        return False
    at = iv.scheduled_at if iv.scheduled_at.tzinfo else iv.scheduled_at.astimezone()
    delta = (at - utcnow()).total_seconds() / 3600
    return 0 <= delta <= within_hours


def _today() -> date:
    return date.today()
