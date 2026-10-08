from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import get_provider
from app.api.deps import DB, get_or_404, to_dict
from app.api.jobs import job_summary
from app.models import Application, ApprovalRequest, Contact, GeneratedDocument, Job, ResumeVersion, Video, utcnow
from app.services import generation as gen
from app.services.application_engine import build_package, resolve_approval
from app.services.guardrails import check_fabrication
from app.services.pipeline import TransitionError, transition_job
from app.services.profile_service import get_profile, profile_fact_corpus
from app.services.settings_service import get_all_settings

router = APIRouter(prefix="/api", tags=["applications"])


def app_summary(a: Application) -> dict:
    d = to_dict(a, exclude={"package"})
    d["job"] = job_summary(a.job)
    return d


def app_detail(db: Session, a: Application) -> dict:
    d = to_dict(a)
    d["job"] = to_dict(a.job)
    d["history"] = [to_dict(h) for h in a.history]
    d["documents"] = [to_dict(x) for x in db.scalars(select(GeneratedDocument).where(GeneratedDocument.application_id == a.id))]
    d["resume_version"] = to_dict(db.get(ResumeVersion, a.resume_version_id), exclude={"content"}) if a.resume_version_id else None
    d["approvals"] = [to_dict(x) for x in db.scalars(select(ApprovalRequest).where(ApprovalRequest.application_id == a.id)
                                                     .order_by(ApprovalRequest.created_at.desc()))]
    d["contact"] = to_dict(db.get(Contact, a.contact_id)) if a.contact_id else None
    d["video"] = to_dict(db.get(Video, a.video_id)) if a.video_id else None
    return d


@router.get("/applications")
def list_applications(status: str | None = None, db: Session = DB):
    q = select(Application).order_by(Application.updated_at.desc())
    if status:
        q = q.where(Application.status.in_(status.upper().split(",")))
    return [app_summary(a) for a in db.scalars(q)]


@router.get("/applications/{aid}")
def get_application(aid: int, db: Session = DB):
    return app_detail(db, get_or_404(db, Application, aid))


@router.put("/applications/{aid}")
def update_application(aid: int, data: dict[str, Any], db: Session = DB):
    a = get_or_404(db, Application, aid)
    for k in ("notes", "mode", "application_type", "contact_id", "offer_amount_monthly_usd", "applied_via", "resume_id", "video_id"):
        if k in data:
            setattr(a, k, data[k])
    if "package" in data and isinstance(data["package"], dict):
        pkg = dict(a.package or {})
        pkg.update(data["package"])
        a.package = pkg
    if "applied_at" in data and data["applied_at"]:
        from app.services.normalization import parse_datetime

        a.applied_at = parse_datetime(data["applied_at"])
    db.commit()
    return app_detail(db, a)


@router.delete("/applications/{aid}")
def delete_application(aid: int, db: Session = DB):
    a = get_or_404(db, Application, aid)
    job = a.job
    db.delete(a)
    job.application_status = "QUALIFIED" if (job.match_score or 0) >= get_all_settings(db)["min_match_score"] else "DISCOVERED"
    db.commit()
    return {"ok": True}


@router.post("/applications/{aid}/transition")
def transition(aid: int, data: dict[str, Any], db: Session = DB):
    a = get_or_404(db, Application, aid)
    try:
        transition_job(db, a.job, data.get("status", ""), data.get("note"), force=bool(data.get("force")))
    except TransitionError as e:
        raise HTTPException(409, str(e)) from e
    db.commit()
    return app_detail(db, a)


@router.post("/applications/{aid}/mark-applied")
def mark_applied(aid: int, data: dict[str, Any] | None = None, db: Session = DB):
    a = get_or_404(db, Application, aid)
    data = data or {}
    if data.get("application_type"):
        a.application_type = data["application_type"]
    if data.get("applied_via"):
        a.applied_via = data["applied_via"]
    try:
        transition_job(db, a.job, "APPLIED", data.get("note") or "Marked as applied")
    except TransitionError as e:
        raise HTTPException(409, str(e)) from e
    db.commit()
    return app_detail(db, a)


@router.post("/applications/{aid}/regenerate")
def regenerate(aid: int, data: dict[str, Any], db: Session = DB):
    a = get_or_404(db, Application, aid)
    parts = set(data.get("parts") or ["resume", "cover_letter", "recruiter_message", "answers", "video"])
    if "cover_letter" in parts and data.get("force_cover_letter"):
        s = get_all_settings(db)
        g = gen.generate_cover_letter(get_profile(db), a.job, get_provider(s.get("ai_provider"), s.get("ai_model") or None),
                                      data.get("instructions", ""))
        doc = db.get(GeneratedDocument, a.cover_letter_id) if a.cover_letter_id else None
        if doc is None:
            doc = GeneratedDocument(kind="cover_letter", application_id=a.id, job_id=a.job_id, title=f"Cover letter — {a.job.title}")
            db.add(doc)
        doc.content, doc.generated_by, doc.warnings, doc.edited = g.text, g.generated_by, g.warnings, False
        db.flush()
        a.cover_letter_id = doc.id
        pkg = dict(a.package or {})
        pkg["cover_letter"] = {"id": doc.id, "required": False, "warnings": g.warnings}
        a.package = pkg
        parts.discard("cover_letter")
    if parts:
        build_package(db, a.job, regenerate=parts)
    db.commit()
    return app_detail(db, a)


@router.post("/applications/{aid}/agent-run")
def agent_run(aid: int, db: Session = DB):
    """Supervised browser agent. Requires Playwright; stops on CAPTCHA/login/2FA and before final submission."""
    from app.browser.supervisor import automation_permission, export_resume_for_upload, run_supervised

    a = get_or_404(db, Application, aid)
    ok, info = automation_permission(db, a)
    if not ok:
        return {"status": "not_allowed", "message": info}
    try:
        from app.browser.playwright_agent import PlaywrightBrowserAgent

        agent = PlaywrightBrowserAgent()
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:  # browser failed to launch (no display etc.)
        return {"status": "error", "message": f"Could not start browser: {e}"}
    cover = db.get(GeneratedDocument, a.cover_letter_id).content if a.cover_letter_id and db.get(GeneratedDocument, a.cover_letter_id) else None
    result = run_supervised(db, a, agent, export_resume_for_upload(db, a), cover)
    db.commit()
    return result.as_dict()


# ---------------------------------------------------------------- generated documents
@router.get("/documents")
def list_documents(kind: str | None = None, application_id: int | None = None, contact_id: int | None = None, db: Session = DB):
    q = select(GeneratedDocument).order_by(GeneratedDocument.updated_at.desc())
    if kind:
        q = q.where(GeneratedDocument.kind == kind)
    if application_id:
        q = q.where(GeneratedDocument.application_id == application_id)
    if contact_id:
        q = q.where(GeneratedDocument.contact_id == contact_id)
    return [to_dict(d) for d in db.scalars(q)]


@router.post("/documents")
def create_document(data: dict[str, Any], db: Session = DB):
    """Generate (job_id + kind) or save a document. kinds: cover_letter, recruiter_message."""
    s = get_all_settings(db)
    provider = get_provider(s.get("ai_provider"), s.get("ai_model") or None)
    profile = get_profile(db)
    job = db.get(Job, data["job_id"]) if data.get("job_id") else None
    contact = db.get(Contact, data["contact_id"]) if data.get("contact_id") else None
    kind = data.get("kind", "cover_letter")
    if data.get("content"):
        content, by, warnings = data["content"], "user", []
    elif job and kind == "cover_letter":
        g = gen.generate_cover_letter(profile, job, provider, data.get("instructions", ""))
        content, by, warnings = g.text, g.generated_by, g.warnings
    elif job and kind == "recruiter_message":
        g = gen.generate_recruiter_message(profile, job, contact, provider)
        content, by, warnings = g.text, g.generated_by, g.warnings
    else:
        raise HTTPException(422, "Provide content, or a job_id with kind cover_letter/recruiter_message")
    app = db.scalar(select(Application).where(Application.job_id == job.id)) if job else None
    doc = GeneratedDocument(kind=kind, title=data.get("title") or f"{kind.replace('_', ' ').title()}{(' — ' + job.title) if job else ''}",
                            content=content, generated_by=by, warnings=warnings, job_id=job.id if job else None,
                            contact_id=contact.id if contact else None, application_id=app.id if app else data.get("application_id"))
    db.add(doc)
    db.flush()
    if app and kind == "cover_letter" and data.get("attach", True):
        app.cover_letter_id = doc.id
    db.commit()
    return to_dict(doc)


@router.put("/documents/{did}")
def update_document(did: int, data: dict[str, Any], db: Session = DB):
    d = get_or_404(db, GeneratedDocument, did)
    if "content" in data:
        d.content = data["content"]
        d.edited = True
        job = db.get(Job, d.job_id) if d.job_id else None
        job_text = "\n".join(x for x in [job.title, job.company, job.description] if x) if job else ""
        d.warnings = check_fabrication(d.content, profile_fact_corpus(get_profile(db)), job_text)
    if "title" in data:
        d.title = data["title"]
    if "application_id" in data:
        d.application_id = data["application_id"]
        app = db.get(Application, data["application_id"]) if data["application_id"] else None
        if app and d.kind == "cover_letter":
            app.cover_letter_id = d.id
    db.commit()
    return to_dict(d)


@router.delete("/documents/{did}")
def delete_document(did: int, db: Session = DB):
    db.delete(get_or_404(db, GeneratedDocument, did))
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- approvals
@router.get("/approvals")
def list_approvals(status: str = "PENDING", db: Session = DB):
    q = select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc())
    if status != "ALL":
        q = q.where(ApprovalRequest.status == status.upper())
    out = []
    for ap in db.scalars(q):
        d = to_dict(ap)
        job = db.get(Job, ap.job_id) if ap.job_id else None
        d["job"] = {"id": job.id, "title": job.title, "company": job.company} if job else None
        out.append(d)
    return out


@router.post("/approvals/{apid}/resolve")
def resolve(apid: int, data: dict[str, Any], db: Session = DB):
    ap = get_or_404(db, ApprovalRequest, apid)
    try:
        resolve_approval(db, ap, data.get("action", ""), data.get("value"))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    ap.updated_at = utcnow()
    db.commit()
    return to_dict(ap)
