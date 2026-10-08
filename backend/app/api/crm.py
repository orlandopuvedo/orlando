from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import DB, apply_updates, get_or_404, to_dict
from app.models import Application, Contact, ContactActivity, FollowUp, Interview, Job, ProfileView
from app.services import crm, followups
from app.services.jobs_service import get_or_create_company, rescore_job
from app.services.normalization import parse_datetime

router = APIRouter(prefix="/api", tags=["crm"])


def _dates(data: dict, fields: tuple[str, ...]) -> dict:
    out = dict(data)
    for f in fields:
        if isinstance(out.get(f), str):
            out[f] = date.fromisoformat(out[f][:10]) if out[f] else None
    return out


def _datetimes(data: dict, fields: tuple[str, ...]) -> dict:
    out = dict(data)
    for f in fields:
        if f in out:
            out[f] = parse_datetime(out[f]) if out[f] else None
    return out


# ---------------------------------------------------------------- contacts
def contact_out(db: Session, c: Contact, full: bool = False) -> dict:
    d = to_dict(c)
    job = db.get(Job, c.job_id) if c.job_id else None
    d["job"] = {"id": job.id, "title": job.title, "company": job.company} if job else None
    if full:
        d["activities"] = [to_dict(a) for a in sorted(c.activities, key=lambda a: a.occurred_at)]
        d["interviews"] = [to_dict(i) for i in db.scalars(select(Interview).where(Interview.contact_id == c.id).order_by(Interview.scheduled_at))]
        d["follow_ups"] = [to_dict(f) for f in db.scalars(select(FollowUp).where(FollowUp.contact_id == c.id).order_by(FollowUp.due_date))]
        d["profile_views"] = [to_dict(p) for p in db.scalars(select(ProfileView).where(ProfileView.contact_id == c.id))]
    return d


@router.get("/contacts")
def list_contacts(q: str | None = None, status: str | None = None, db: Session = DB):
    stmt = select(Contact).order_by(Contact.updated_at.desc())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Contact.full_name.ilike(like), Contact.company.ilike(like), Contact.email.ilike(like)))
    if status:
        stmt = stmt.where(Contact.status.in_(status.upper().split(",")))
    return [contact_out(db, c) for c in db.scalars(stmt)]


CONTACT_FIELDS = {"full_name", "job_title", "company", "email", "phone", "linkedin_url", "other_url", "contact_source", "job_id",
                  "status", "first_contact_date", "last_contact_date", "next_follow_up_date", "notes", "tags"}


@router.post("/contacts")
def create_contact(data: dict[str, Any], db: Session = DB):
    if not (data.get("full_name") or "").strip():
        raise HTTPException(422, "full_name is required")
    data = _dates(data, ("first_contact_date", "last_contact_date", "next_follow_up_date"))
    c = Contact(full_name=data["full_name"].strip(), tags=data.get("tags") or [], status=data.get("status") or "NEW")
    apply_updates(c, data, CONTACT_FIELDS)
    if c.status not in crm.CONTACT_STATUSES:
        raise HTTPException(422, f"Invalid status {c.status}")
    if c.job_id and not c.company:
        job = db.get(Job, c.job_id)
        c.company = job.company if job else None
    comp = get_or_create_company(db, c.company)
    c.company_id = comp.id if comp else None
    db.add(c)
    db.flush()
    if c.job_id:
        app = db.scalar(select(Application).where(Application.job_id == c.job_id))
        if app and not app.contact_id:
            app.contact_id = c.id
        job = db.get(Job, c.job_id)
        if job:
            rescore_job(db, job, notify_high=False)
    db.commit()
    return contact_out(db, c, full=True)


@router.get("/contacts/pipeline")
def contact_pipeline(db: Session = DB):
    contacts = db.scalars(select(Contact).order_by(Contact.updated_at.desc())).all()
    cols = []
    for col, statuses in crm.PIPELINE_COLUMNS.items():
        cols.append({"column": col, "statuses": statuses, "items": [contact_out(db, c) for c in contacts if c.status in statuses]})
    return {"columns": cols, "statuses": crm.CONTACT_STATUSES}


@router.get("/contacts/{cid}")
def get_contact(cid: int, db: Session = DB):
    return contact_out(db, get_or_404(db, Contact, cid), full=True)


@router.put("/contacts/{cid}")
def update_contact(cid: int, data: dict[str, Any], db: Session = DB):
    c = get_or_404(db, Contact, cid)
    data = _dates(data, ("first_contact_date", "last_contact_date", "next_follow_up_date"))
    if "status" in data and data["status"] not in crm.CONTACT_STATUSES:
        raise HTTPException(422, f"Invalid status {data['status']}")
    apply_updates(c, data, CONTACT_FIELDS)
    if "company" in data:
        comp = get_or_create_company(db, c.company)
        c.company_id = comp.id if comp else None
    db.commit()
    return contact_out(db, c, full=True)


@router.post("/contacts/{cid}/status")
def set_contact_status(cid: int, data: dict[str, Any], db: Session = DB):
    c = get_or_404(db, Contact, cid)
    status = (data.get("status") or "").upper()
    if status in crm.PIPELINE_COLUMNS:  # dropped onto a Kanban column
        if c.status in crm.PIPELINE_COLUMNS[status]:
            return contact_out(db, c)
        status = crm.PIPELINE_COLUMNS[status][0]
    if status not in crm.CONTACT_STATUSES:
        raise HTTPException(422, f"Invalid status {status}")
    old = c.status
    c.status = status
    crm.add_activity(db, c, "note", f"Status changed: {old} → {status}", auto_status=False)
    db.commit()
    return contact_out(db, c)


@router.delete("/contacts/{cid}")
def delete_contact(cid: int, db: Session = DB):
    db.delete(get_or_404(db, Contact, cid))
    db.commit()
    return {"ok": True}


@router.post("/contacts/{cid}/activities")
def add_activity(cid: int, data: dict[str, Any], db: Session = DB):
    c = get_or_404(db, Contact, cid)
    try:
        act = crm.add_activity(db, c, data.get("type", "note"), data.get("summary"), data.get("details"),
                               parse_datetime(data.get("occurred_at")) if data.get("occurred_at") else None,
                               data.get("channel"), auto_status=data.get("auto_status", True))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    db.commit()
    return to_dict(act)


@router.put("/activities/{aid}")
def update_activity(aid: int, data: dict[str, Any], db: Session = DB):
    a = get_or_404(db, ContactActivity, aid)
    apply_updates(a, _datetimes(data, ("occurred_at",)), {"type", "summary", "details", "occurred_at", "channel"})
    db.commit()
    return to_dict(a)


@router.delete("/activities/{aid}")
def delete_activity(aid: int, db: Session = DB):
    db.delete(get_or_404(db, ContactActivity, aid))
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- profile views
@router.get("/profile-views")
def list_profile_views(db: Session = DB):
    return [to_dict(p) for p in db.scalars(select(ProfileView).order_by(ProfileView.viewed_on.desc()))]


@router.post("/profile-views")
def create_profile_view(data: dict[str, Any], db: Session = DB):
    data = _dates(data, ("viewed_on",))
    data.setdefault("viewed_on", date.today())
    if data.get("create_contact") and data.get("person_name") and not data.get("contact_id"):
        c = Contact(full_name=data["person_name"], company=data.get("company"), job_title=data.get("person_title"),
                    contact_source=f"Profile view ({data.get('platform') or 'LinkedIn'})", tags=[], status="NEW")
        db.add(c)
        db.flush()
        data["contact_id"] = c.id
    fields = {"contact_id", "person_name", "person_title", "company", "platform", "viewed_on", "notes", "source"}
    pv = crm.record_profile_view(db, {k: v for k, v in data.items() if k in fields})
    db.commit()
    return to_dict(pv)


@router.delete("/profile-views/{pid}")
def delete_profile_view(pid: int, db: Session = DB):
    db.delete(get_or_404(db, ProfileView, pid))
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- interviews
INTERVIEW_FIELDS = {"company", "job_id", "application_id", "contact_id", "interview_type", "scheduled_at", "duration_minutes",
                    "meeting_url", "interview_number", "is_final", "status", "notes", "questions_asked", "answers_lessons",
                    "next_steps", "follow_up_date"}
INTERVIEW_STATUSES = ["SCHEDULED", "COMPLETED", "RESCHEDULED", "CANCELLED", "NO_SHOW"]


def interview_out(db: Session, i: Interview) -> dict:
    d = to_dict(i)
    job = db.get(Job, i.job_id) if i.job_id else None
    contact = db.get(Contact, i.contact_id) if i.contact_id else None
    d["job"] = {"id": job.id, "title": job.title, "company": job.company} if job else None
    d["contact"] = {"id": contact.id, "full_name": contact.full_name} if contact else None
    return d


@router.get("/interviews")
def list_interviews(status: str | None = None, db: Session = DB):
    q = select(Interview).order_by(Interview.scheduled_at.desc().nullslast())
    if status:
        q = q.where(Interview.status.in_(status.upper().split(",")))
    return [interview_out(db, i) for i in db.scalars(q)]


@router.post("/interviews")
def create_interview(data: dict[str, Any], db: Session = DB):
    data = _datetimes(_dates(data, ("follow_up_date",)), ("scheduled_at",))
    iv = crm.create_interview(db, {k: v for k, v in data.items() if k in INTERVIEW_FIELDS})
    db.commit()
    return interview_out(db, iv)


@router.get("/interviews/{iid}")
def get_interview(iid: int, db: Session = DB):
    return interview_out(db, get_or_404(db, Interview, iid))


@router.put("/interviews/{iid}")
def update_interview(iid: int, data: dict[str, Any], db: Session = DB):
    iv = get_or_404(db, Interview, iid)
    data = _datetimes(_dates(data, ("follow_up_date",)), ("scheduled_at",))
    if data.get("status") and data["status"] not in INTERVIEW_STATUSES:
        raise HTTPException(422, "Invalid interview status")
    if data.get("status") == "COMPLETED" and iv.status != "COMPLETED":
        crm.complete_interview(db, iv)
    apply_updates(iv, data, INTERVIEW_FIELDS)
    if iv.follow_up_date:
        crm.create_interview_follow_ups(db, iv) if iv.status == "COMPLETED" else None
    db.commit()
    return interview_out(db, iv)


@router.post("/interviews/{iid}/complete")
def complete_interview(iid: int, data: dict[str, Any] | None = None, db: Session = DB):
    iv = get_or_404(db, Interview, iid)
    data = data or {}
    crm.complete_interview(db, iv, data.get("notes"), data.get("questions_asked"), data.get("answers_lessons"), data.get("next_steps"))
    db.commit()
    return interview_out(db, iv)


@router.delete("/interviews/{iid}")
def delete_interview(iid: int, db: Session = DB):
    db.delete(get_or_404(db, Interview, iid))
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- follow-ups
def followup_out(db: Session, f: FollowUp) -> dict:
    d = to_dict(f)
    contact = db.get(Contact, f.contact_id) if f.contact_id else None
    job = db.get(Job, f.job_id) if f.job_id else None
    d["contact"] = {"id": contact.id, "full_name": contact.full_name, "email": contact.email, "linkedin_url": contact.linkedin_url} if contact else None
    d["job"] = {"id": job.id, "title": job.title, "company": job.company} if job else None
    d["overdue"] = f.status == "PENDING" and f.due_date < date.today()
    return d


@router.get("/followups")
def list_followups(status: str | None = "PENDING", db: Session = DB):
    q = select(FollowUp).order_by(FollowUp.due_date)
    if status and status != "ALL":
        q = q.where(FollowUp.status.in_(status.upper().split(",")))
    return [followup_out(db, f) for f in db.scalars(q)]


@router.post("/followups")
def create_followup(data: dict[str, Any], db: Session = DB):
    data = _dates(data, ("due_date",))
    fu = FollowUp(kind=data.get("kind") or "custom", title=data.get("title") or "Follow up", due_date=data.get("due_date") or date.today())
    apply_updates(fu, data, {"message", "channel", "application_id", "contact_id", "interview_id", "job_id"})
    db.add(fu)
    db.commit()
    return followup_out(db, fu)


@router.put("/followups/{fid}")
def update_followup(fid: int, data: dict[str, Any], db: Session = DB):
    fu = get_or_404(db, FollowUp, fid)
    apply_updates(fu, _dates(data, ("due_date",)), {"title", "due_date", "status", "message", "channel", "kind"})
    db.commit()
    return followup_out(db, fu)


@router.post("/followups/{fid}/generate")
def generate_followup(fid: int, db: Session = DB):
    fu = followups.generate_message(db, get_or_404(db, FollowUp, fid))
    db.commit()
    return followup_out(db, fu)


@router.post("/followups/{fid}/sent")
def followup_sent(fid: int, data: dict[str, Any] | None = None, db: Session = DB):
    fu = followups.mark_sent(db, get_or_404(db, FollowUp, fid), (data or {}).get("channel"))
    db.commit()
    return followup_out(db, fu)


@router.post("/followups/{fid}/postpone")
def followup_postpone(fid: int, data: dict[str, Any] | None = None, db: Session = DB):
    fu = followups.postpone(db, get_or_404(db, FollowUp, fid), int((data or {}).get("days", 2)))
    db.commit()
    return followup_out(db, fu)


@router.delete("/followups/{fid}")
def delete_followup(fid: int, db: Session = DB):
    db.delete(get_or_404(db, FollowUp, fid))
    db.commit()
    return {"ok": True}


@router.post("/followups/refresh")
def refresh(db: Session = DB):
    return followups.refresh_reminders(db)


_ = datetime  # (typing helper)
