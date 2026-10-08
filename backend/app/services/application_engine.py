"""Application Engine: inspects a job and builds a complete, truthful APPLICATION PACKAGE."""
from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import get_provider
from app.models import (
    Application, ApplicationAnswer, ApprovalRequest, Contact, GeneratedDocument, Job, Resume, ResumeVersion, Video, utcnow,
)
from app.services import generation as gen
from app.services.notifications import notify
from app.services.pipeline import ensure_application, transition_job
from app.services.profile_service import get_profile
from app.services.resume_tailor import build_tailored_resume, render_text
from app.services.settings_service import get_all_settings
from app.services.text_utils import normalize_text, tokens
from app.services.video_matching import recommend_video

SALARY_Q = re.compile(r"salary|compensation|pay (?:range|expectation)|expected (?:pay|rate)|desired (?:pay|rate)|hourly rate", re.I)
LEGAL_Q = re.compile(r"authori[sz]ed to work|sponsor|visa|work permit|right to work|citizenship|criminal|background check|felony|legally", re.I)
DEMOGRAPHIC_Q = re.compile(r"gender|race|ethnic|veteran|disabilit|sexual orientation|pronoun|age\b|date of birth|religion|marital", re.I)
AVAIL_Q = re.compile(r"start date|when can you start|availability|notice period|available to start", re.I)

STANDARD_QUESTIONS = ["Tell us about yourself.", "Why are you interested in this role?"]


def classify_question(q: str) -> str:
    if DEMOGRAPHIC_Q.search(q):
        return "demographic"
    if LEGAL_Q.search(q):
        return "legal"
    if SALARY_Q.search(q):
        return "salary"
    if AVAIL_Q.search(q):
        return "availability"
    return "general"


def find_best_answer(question: str, answers: list[ApplicationAnswer], job: Job | None = None) -> ApplicationAnswer | None:
    q_tokens = {t for t in tokens(question) if len(t) > 3}
    q_kind = classify_question(question)
    best, best_score = None, 0.0
    for a in answers:
        a_tokens = {t for t in tokens(a.question) if len(t) > 3}
        overlap = len(q_tokens & a_tokens) / max(1, len(q_tokens | a_tokens))
        score = overlap * 10
        tags = {normalize_text(t) for t in a.tags or []}
        if a.category and (a.category == q_kind or normalize_text(a.category) in normalize_text(question)):
            score += 3
        if job and job.category and (job.category in tags or normalize_text(job.category.replace("_", " ")) in tags):
            score += 1.5
        if score > best_score:
            best, best_score = a, score
    return best if best_score >= 2.5 else None


def select_base_resume(db: Session, job: Job) -> Resume | None:
    resumes = db.scalars(select(Resume)).all()
    if not resumes:
        return None
    cat = normalize_text((job.category or "").replace("_", " "))
    title = normalize_text(job.title)

    def score(r: Resume) -> float:
        s = 0.0
        tags = [normalize_text(t) for t in (r.tags or [])] + [normalize_text(r.focus or "")]
        if cat and any(cat and (cat in t or t in cat) for t in tags if t):
            s += 10
        s += sum(2 for t in tags if t and t in title)
        if r.is_default:
            s += 1
        return s

    return max(resumes, key=score)


def needs_cover_letter(job: Job, policy: str) -> bool:
    req = job.detected_requirements or {}
    if policy == "never":
        return bool(req.get("cover_letter_required"))
    if policy == "always":
        return True
    if policy == "when_useful":
        return bool(req.get("cover_letter")) or ((job.match_score or 0) >= 80 and not job.easy_apply)
    return bool(req.get("cover_letter") or req.get("cover_letter_required"))


def _approval(db: Session, app: Application, kind: str, title: str, message: str, field_key: str, proposed: str | None,
              options: list[str] | None = None) -> ApprovalRequest:
    existing = db.scalar(select(ApprovalRequest).where(ApprovalRequest.application_id == app.id, ApprovalRequest.field_key == field_key,
                                                       ApprovalRequest.status == "PENDING"))
    if existing:
        existing.proposed_value = proposed
        existing.message = message
        if options is not None:
            existing.options = options
        return existing
    ap = ApprovalRequest(application_id=app.id, job_id=app.job_id, kind=kind, title=title, message=message,
                         field_key=field_key, proposed_value=proposed, options=options or [])
    db.add(ap)
    db.flush()
    return ap


def company_application_count(db: Session, job: Job) -> int:
    if not job.company_id:
        return 0
    return db.scalar(
        select(func.count()).select_from(Application).join(Job, Job.id == Application.job_id)
        .where(Job.company_id == job.company_id, Application.applied_at.is_not(None), Job.id != job.id)
    ) or 0


def build_package(db: Session, job: Job, *, mode: str | None = None, regenerate: set[str] | None = None) -> Application:
    """Create (or refresh) the application package for a job. `regenerate` limits which parts are rebuilt."""
    settings = get_all_settings(db)
    profile = get_profile(db)
    provider = get_provider(settings.get("ai_provider"), settings.get("ai_model") or None)
    parts = regenerate or {"resume", "cover_letter", "recruiter_message", "answers", "video"}
    pkg_started = utcnow().isoformat()
    app = ensure_application(db, job, mode or settings.get("application_mode"))
    if mode:
        app.mode = mode
    pkg = dict(app.package or {})
    req = job.detected_requirements or {}
    warnings: list[str] = []

    # --- resume
    if "resume" in parts:
        base = select_base_resume(db, job)
        content, w, by = build_tailored_resume(profile, job, provider=provider)
        version = db.get(ResumeVersion, app.resume_version_id) if app.resume_version_id else None
        if version is None:
            version = ResumeVersion(job_id=job.id, resume_id=base.id if base else None,
                                    name=f"{job.title} — {job.company or 'Company'}", focus=job.category)
            db.add(version)
        version.content, version.content_text, version.generated_by, version.warnings = content, render_text(content), by, w
        db.flush()
        app.resume_id = base.id if base else None
        app.resume_version_id = version.id
        pkg["selected_resume"] = {"id": base.id, "name": base.name} if base else None
        pkg["tailored_resume"] = {"id": version.id, "name": version.name, "warnings": w}
        if not base:
            warnings.append("No resume uploaded yet — the tailored resume is generated from your Master Profile.")

    # --- cover letter
    if "cover_letter" in parts:
        if needs_cover_letter(job, settings.get("cover_letter_policy", "when_required")):
            g = gen.generate_cover_letter(profile, job, provider)
            doc = db.get(GeneratedDocument, app.cover_letter_id) if app.cover_letter_id else None
            if doc is None:
                doc = GeneratedDocument(kind="cover_letter", application_id=app.id, job_id=job.id)
                db.add(doc)
            doc.title, doc.content, doc.generated_by, doc.warnings, doc.edited = f"Cover letter — {job.title}", g.text, g.generated_by, g.warnings, False
            db.flush()
            app.cover_letter_id = doc.id
            pkg["cover_letter"] = {"id": doc.id, "required": bool(req.get("cover_letter_required")), "warnings": g.warnings}
        else:
            pkg["cover_letter"] = None

    # --- recruiter message
    contact = db.get(Contact, app.contact_id) if app.contact_id else db.scalar(select(Contact).where(Contact.job_id == job.id))
    if contact:
        app.contact_id = contact.id
    if "recruiter_message" in parts:
        g = gen.generate_recruiter_message(profile, job, contact, provider if contact else None)
        doc = db.scalar(select(GeneratedDocument).where(GeneratedDocument.application_id == app.id, GeneratedDocument.kind == "recruiter_message"))
        if doc is None:
            doc = GeneratedDocument(kind="recruiter_message", application_id=app.id, job_id=job.id)
            db.add(doc)
        doc.title = f"Recruiter message — {job.company or job.title}"
        doc.content, doc.generated_by, doc.warnings, doc.contact_id = g.text, g.generated_by, g.warnings, contact.id if contact else None
        db.flush()
        pkg["recruiter_message"] = {"id": doc.id, "contact_id": contact.id if contact else None}

    # --- answers
    if "answers" in parts:
        answers_lib = [a for a in db.scalars(select(ApplicationAnswer)) if (a.answer or "").strip()]
        questions = list(req.get("screening_questions") or [])
        for std in STANDARD_QUESTIONS:
            if not any(normalize_text(std)[:20] in normalize_text(q) for q in questions):
                questions.append(std)
        out = []
        for i, q in enumerate(questions):
            kind = classify_question(q)
            lib = find_best_answer(q, answers_lib, job)
            if kind == "salary":
                text, by, w = gen.salary_answer(profile, job), "profile", []
            elif kind == "availability" and profile.availability:
                text, by, w = gen.availability_answer(profile), "profile", []
            elif kind == "legal" and not lib:
                text, by, w = gen.work_authorization_answer(profile), "profile", []
            elif kind == "demographic":
                text, by, w = (lib.answer if lib else "I prefer not to answer."), "answer_library" if lib else "default", []
            else:
                g = gen.personalize_answer(q, lib.answer if lib else None, profile, job, provider)
                text, by, w = g.text, g.generated_by, g.warnings
            is_standard = q in STANDARD_QUESTIONS
            needs_approval = kind in {"salary", "legal", "demographic"} or (not text and not is_standard) or (lib is not None and lib.requires_approval)
            out.append({"question": q, "answer": text, "kind": kind, "answer_id": lib.id if lib else None,
                        "generated_by": by, "warnings": w, "needs_approval": needs_approval, "approved": False})
            if needs_approval:
                label = {"salary": "Application requires salary answer", "legal": "Application requires legal/authorization answer",
                         "demographic": "Application asks a demographic question", "availability": "Availability answer needed"}.get(
                    kind, "Uncertain answer — please review")
                _approval(db, app, kind if kind in {"salary", "legal", "demographic"} else "uncertain", f"{label}: {job.title}",
                          q, f"screening_answers.{i}", text)
        pkg["screening_answers"] = out
        pkg["salary_answer"] = gen.salary_answer(profile, job)
        pkg["availability_answer"] = gen.availability_answer(profile)
        if req.get("salary_question") and not any(a["kind"] == "salary" for a in out):
            _approval(db, app, "salary", f"Application requires salary answer: {job.title}", "Salary expectations",
                      "salary_answer", pkg["salary_answer"])

    # --- video
    if "video" in parts:
        if job.video_required:
            videos = db.scalars(select(Video).where(Video.is_active.is_(True))).all()
            rec = recommend_video(job, videos)
            vd = job.video_details or {}
            pkg["video"] = {"required": True, "details": vd, "recommendation": rec}
            app.video_id = rec["video_id"] if rec else None
            if vd.get("submission_type") == "file":
                msg = "This application requires uploading a video FILE (not a link). Please upload it yourself."
            elif vd.get("submission_type") == "platform":
                msg = "This application uses its own video-interview platform. You must record it there yourself."
            elif rec:
                msg = f"Recommended video: {rec['name']} — {rec.get('url') or 'add the URL in Video Library'}"
            else:
                msg = "No suitable video in your Video Library. Record one (e.g. a 5-minute Loom) and add it."
            _approval(db, app, "video", f"Application requires video: {job.title}", msg, "video", rec.get("url") if rec else None)
        else:
            pkg["video"] = {"required": False}

    # --- limits & checklist
    max_per_company = settings.get("max_applications_per_company", 2)
    n_company = company_application_count(db, job)
    if job.filter_status == "rejected":
        warnings.append("This job does NOT meet your search filters: " + " ".join(job.filter_reasons or []))
    if n_company >= max_per_company:
        warnings.append(f"You already applied to {n_company} role(s) at {job.company}; limit is {max_per_company}.")
    pkg["requirements"] = {k: v for k, v in req.items() if k != "screening_questions"}
    pkg["checklist"] = _checklist(job, pkg)
    pkg["warnings"] = warnings
    pkg["generated_at"] = utcnow().isoformat()
    from app.ai.registry import AI_STATUS

    ai_failed = provider.is_available() and AI_STATUS.get("last_error_at") and AI_STATUS["last_error_at"] >= pkg_started
    pkg["generated_with"] = (f"templates — AI provider {provider.label} FAILED: {AI_STATUS.get('last_error')}" if ai_failed
                             else provider.label if provider.is_available() else "templates (no AI provider configured)")
    app.package = pkg
    if job.application_status in {"DISCOVERED", "QUALIFIED", "SKIPPED"}:
        transition_job(db, job, "READY", "Application package prepared", force=job.application_status == "SKIPPED")
    job.in_queue = job.filter_status != "rejected"
    pending = db.scalar(select(func.count()).select_from(ApprovalRequest).where(ApprovalRequest.application_id == app.id, ApprovalRequest.status == "PENDING"))
    if pending:
        notify(db, "approval_required", f"{pending} approval(s) needed: {job.title}", job.company, link="/approvals",
               entity_type="application", entity_id=app.id, dedupe_key=f"approval:{app.id}:{pending}")
    db.flush()
    return app


def _checklist(job: Job, pkg: dict) -> list[dict]:
    items = [{"key": "open", "label": f"Open the application page{(' (' + job.apply_url + ')') if job.apply_url else ''}", "done": False},
             {"key": "resume", "label": "Download & upload the tailored resume", "done": False}]
    if pkg.get("cover_letter"):
        items.append({"key": "cover_letter", "label": "Paste / upload the cover letter", "done": False})
    if pkg.get("screening_answers"):
        items.append({"key": "answers", "label": "Fill screening answers (review flagged ones)", "done": False})
    if (pkg.get("video") or {}).get("required"):
        items.append({"key": "video", "label": "Provide the video (link or upload)", "done": False})
    items.append({"key": "submit", "label": "Submit, then click “Mark as applied”", "done": False})
    return items


def resolve_approval(db: Session, approval: ApprovalRequest, action: str, value: str | None = None) -> ApprovalRequest:
    action = action.lower()
    if action not in {"approve", "edit", "skip"}:
        raise ValueError("action must be approve, edit or skip")
    if action == "edit" and approval.options and value not in approval.options:
        raise ValueError(f"Choose one of: {', '.join(approval.options)}")
    approval.status = {"approve": "APPROVED", "edit": "EDITED", "skip": "SKIPPED"}[action]
    approval.final_value = value if action == "edit" else (approval.proposed_value if action == "approve" else None)
    approval.resolved_at = utcnow()
    app = db.get(Application, approval.application_id) if approval.application_id else None
    if app and approval.kind == "verify_submission":
        _resolve_submission_verification(db, app, approval)
        db.flush()
        return approval
    if app and approval.field_key and action != "skip":
        pkg = dict(app.package or {})
        key = approval.field_key
        if key.startswith("screening_answers."):
            idx = int(key.split(".")[1])
            answers = list(pkg.get("screening_answers") or [])
            if idx < len(answers):
                answers[idx] = {**answers[idx], "answer": approval.final_value or "", "approved": True}
                pkg["screening_answers"] = answers
        elif key == "salary_answer":
            pkg["salary_answer"] = approval.final_value or ""
        elif key == "video":
            v = dict(pkg.get("video") or {})
            v["approved_url"] = approval.final_value
            pkg["video"] = v
        elif key == "final_submit":
            pkg["submit_approved"] = True
            pkg["submit_approved_at"] = utcnow().isoformat()
        app.package = pkg
    db.flush()
    return approval


VERIFY_YES = "Yes — I checked: the application WAS submitted"
VERIFY_NO = "No — it was NOT submitted"


def _resolve_submission_verification(db: Session, app: Application, approval: ApprovalRequest) -> None:
    """Manual verification of an unconfirmed submission. Only an explicit YES marks the application APPLIED."""
    from app.services.pipeline import transition_job

    yes = approval.status in ("APPROVED", "EDITED") and (approval.final_value or "") == VERIFY_YES
    if yes:
        app.submission_status = "manual_confirmed"
        if app.job.application_status != "APPLIED":
            transition_job(db, app.job, "APPLIED", "Submission verified manually by the user")
    elif approval.status != "PENDING" and app.job.application_status == "SUBMITTED_UNCONFIRMED":
        app.submission_status = "not_submitted"
        transition_job(db, app.job, "READY", "User reported the submission did not go through")
