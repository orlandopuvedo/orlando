"""Supervised application runner: fills what it safely can, stops for every human decision.

Re-runnable: each run re-opens the page, refills the form with the (approved) package and only submits
when the final-submission approval has been granted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.browser.base import BrowserAgent, FormField, HumanInterventionRequired
from app.models import Application, ApprovalRequest, JobSource, ResumeVersion, utcnow
from app.services.application_engine import DEMOGRAPHIC_Q, LEGAL_Q, SALARY_Q, _approval
from app.services.notifications import notify
from app.services.pipeline import transition_job
from app.services.profile_service import get_profile
from app.services.settings_service import get_all_settings
from app.services.text_utils import normalize_text

MANUAL_ONLY_DOMAINS = ("linkedin.com", "indeed.", "wellfound.com", "flexjobs.com", "upwork.com", "glassdoor.")
ATS_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "bamboohr.com", "smartrecruiters.com",
             "breezy.hr", "recruitee.com", "teamtailor.com", "jobvite.com")
PROFILE_FIELD_PATTERNS = [
    ("first_name", r"first name|given name|nombre(?! completo)"),
    ("last_name", r"last name|surname|family name|apellido"),
    ("full_name", r"full name|^name$|your name|nombre completo"),
    ("email", r"e-?mail"),
    ("phone", r"phone|mobile|tel[eé]fono|celular"),
    ("linkedin_url", r"linkedin"),
    ("portfolio_url", r"portfolio|website|personal site|github"),
    ("location", r"location|city|ciudad|where are you based|country of residence"),
]


@dataclass
class AgentRunResult:
    status: str  # blocked | awaiting_approval | ready_to_submit | submitted | not_allowed | error
    message: str
    filled: list[dict] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"status": self.status, "message": self.message, "filled": self.filled, "pending": self.pending}


def automation_permission(db: Session, app: Application) -> tuple[bool, str]:
    job = app.job
    settings = get_all_settings(db)
    if app.mode == "copilot":
        return False, "Copilot mode: the AI prepared everything; you submit manually."
    url = job.apply_url or job.source_url or ""
    host = urlsplit(url).netloc.lower()
    if not url:
        return False, "Job has no application URL."
    if any(d in host for d in MANUAL_ONLY_DOMAINS):
        return False, f"{host} does not permit automated applications — apply manually (Copilot)."
    src = db.scalar(select(JobSource).where(JobSource.key == job.source))
    status = src.apply_automation_status if src else "unknown"
    if any(h in host for h in ATS_HOSTS) or job.source == "manual":
        # Company application forms (user-chosen) — supervised filling with approval before submit.
        status = "allowed" if status == "allowed" else "review_required"
    if status in ("manual_only", "unknown"):
        return False, f"{src.name if src else job.source}: automation status is '{status}' — submit this application manually."
    if app.mode == "auto":
        if status != "allowed" or not (settings.get("auto_apply_permissions") or {}).get(job.source):
            return False, "AUTO mode is only available where automation is explicitly allowed and enabled in Settings. Use Supervised."
    return True, status


def _profile_value(key: str, profile) -> str | None:
    if key == "first_name":
        return (profile.full_name or "").split(" ")[0] or None
    if key == "last_name":
        parts = (profile.full_name or "").split(" ")
        return " ".join(parts[1:]) or None
    return getattr(profile, key, None)


def _match_answer(label: str, package: dict) -> dict | None:
    ln = normalize_text(label)
    best, best_ratio = None, 0.0
    for a in package.get("screening_answers") or []:
        q = normalize_text(a["question"])
        qs, ls = set(q.split()), set(ln.split())
        ratio = len(qs & ls) / max(1, len(qs | ls))
        if q and (q in ln or ln in q):
            ratio = 1.0
        if ratio > best_ratio:
            best, best_ratio = a, ratio
    return best if best_ratio >= 0.5 else None


def run_supervised(db: Session, app: Application, agent: BrowserAgent, resume_file: str | None = None,
                   cover_letter_text: str | None = None) -> AgentRunResult:
    ok, info = automation_permission(db, app)
    if not ok:
        return AgentRunResult("not_allowed", info)
    job = app.job
    profile = get_profile(db)
    pkg = dict(app.package or {})
    filled: list[dict] = []
    pending: list[str] = []
    try:
        if job.application_status in ("READY", "QUALIFIED"):
            transition_job(db, job, "APPLYING", "Supervised agent started")
        agent.open_page(job.apply_url or job.source_url)
        page = agent.inspect_page()
        if page.captcha:
            agent.request_human_approval("CAPTCHA detected — complete it yourself, then re-run or submit manually.")
        if page.two_factor:
            agent.request_human_approval("Two-factor verification required — complete it yourself.")
        if page.login:
            agent.request_human_approval("Login required — log in yourself in the agent browser window, then re-run.")
        if page.video_required and not (pkg.get("video") or {}).get("approved_url"):
            _approval(db, app, "video", f"Application requires video: {job.title}", "The application page asks for a video.", "video",
                      ((pkg.get("video") or {}).get("recommendation") or {}).get("url"))
            pending.append("video")

        for f in page.fields:
            res = _fill_field(db, app, agent, f, profile, pkg, resume_file, cover_letter_text)
            if res == "pending":
                pending.append(f.label or f.selector)
            elif res:
                filled.append({"field": f.label or f.selector, "value": res})

        pkg.setdefault("agent_log", []).append({"at": utcnow().isoformat(), "filled": len(filled), "pending": pending})
        app.package = pkg
        if pending:
            db.flush()
            notify(db, "approval_required", f"Agent needs your input: {job.title}", ", ".join(pending)[:300], link="/approvals",
                   entity_type="application", entity_id=app.id, dedupe_key=f"agent_pending:{app.id}:{len(pending)}:{utcnow():%Y%m%d%H}")
            return AgentRunResult("awaiting_approval", "Some fields need your approval before the agent can continue.", filled, pending)

        approved = pkg.get("submit_approved") is True
        if not approved:
            _approval(db, app, "final_submit", f"Application is ready to submit: {job.title}",
                      f"{len(filled)} fields filled. Approve to let the agent click submit (re-run the agent after approving).",
                      "final_submit", "submit")
            db.flush()
            return AgentRunResult("ready_to_submit", "Form filled. Approve final submission in the Approval queue.", filled)
        agent.submit(page.submit_selector, approved=True)
        after = agent.inspect_page()
        if after.captcha:
            agent.request_human_approval("CAPTCHA appeared after submit — finish it yourself.")
        transition_job(db, job, "APPLIED", "Submitted by supervised agent (approved)")
        app.applied_via = after.url
        db.flush()
        return AgentRunResult("submitted", "Application submitted after your approval.", filled)
    except HumanInterventionRequired as e:
        _approval(db, app, "blocked", f"Application blocked: {job.title}", e.reason, f"blocked:{e.kind}", None)
        notify(db, "application_blocked", f"Application blocked: {job.title}", e.reason, link=f"/applications/{app.id}",
               entity_type="application", entity_id=app.id, dedupe_key=f"blocked:{app.id}:{utcnow():%Y%m%d%H%M}")
        if job.application_status == "APPLYING":
            transition_job(db, job, "READY", "Agent stopped: human intervention required")
        db.flush()
        return AgentRunResult("blocked", e.reason, filled, pending)
    except Exception as e:  # browser errors
        if job.application_status == "APPLYING":
            transition_job(db, job, "READY", f"Agent error: {e}")
        return AgentRunResult("error", f"{type(e).__name__}: {e}", filled, pending)
    finally:
        try:
            agent.close()
        except Exception:
            pass


def _approved_value(db: Session, app: Application, field_key: str) -> str | None:
    ap = db.scalar(select(ApprovalRequest).where(ApprovalRequest.application_id == app.id, ApprovalRequest.field_key == field_key,
                                                 ApprovalRequest.status.in_(["APPROVED", "EDITED"])).order_by(ApprovalRequest.id.desc()))
    return ap.final_value if ap else None


def _fill_field(db, app, agent: BrowserAgent, f: FormField, profile, pkg: dict, resume_file, cover_letter_text) -> str | None:
    label = (f.label or f.name or "").strip()
    low = label.lower()
    if f.type == "file":
        if re.search(r"resume|cv|curr[ií]culum", low) and resume_file:
            agent.upload_file(f.selector, resume_file)
            return "tailored resume uploaded"
        if re.search(r"cover", low) and cover_letter_text is not None:
            return None  # file cover letters: user uploads (we only provide text)
        if re.search(r"video", low):
            return "pending"
        return None
    if f.type in ("checkbox", "radio"):
        return "pending" if f.required else None
    # Sensitive questions → approval (or use approved value)
    key = f"field:{normalize_text(label)[:150]}"
    sensitive = DEMOGRAPHIC_Q.search(label) and "demographic" or LEGAL_Q.search(label) and "legal" or SALARY_Q.search(label) and "salary"
    if sensitive:
        val = _approved_value(db, app, key)
        if val is None:
            proposal = (pkg.get("salary_answer") if sensitive == "salary" else
                        (profile.work_authorization if sensitive == "legal" else "I prefer not to answer"))
            _approval(db, app, sensitive, f"{sensitive.capitalize()} question: {app.job.title}", label, key, proposal)
            return "pending"
        _set(agent, f, val)
        return val
    for pkey, pat in PROFILE_FIELD_PATTERNS:
        if re.search(pat, low):
            val = _profile_value(pkey, profile)
            if val:
                _set(agent, f, str(val))
                return str(val)
            return "pending" if f.required else None
    if re.search(r"cover letter|motivation", low) and cover_letter_text:
        _set(agent, f, cover_letter_text)
        return "cover letter"
    if re.search(r"video|loom", low):
        url = (pkg.get("video") or {}).get("approved_url")
        if url:
            _set(agent, f, url)
            return url
        return "pending"
    ans = _match_answer(label, pkg)
    if ans and ans.get("answer") and (not ans.get("needs_approval") or ans.get("approved")):
        _set(agent, f, ans["answer"])
        return ans["answer"][:60]
    if f.required or f.tag == "textarea":
        val = _approved_value(db, app, key)
        if val is not None:
            _set(agent, f, val)
            return val
        _approval(db, app, "uncertain", f"Uncertain answer: {app.job.title}", label, key, ans.get("answer") if ans else None)
        return "pending"
    return None


def _set(agent: BrowserAgent, f: FormField, value: str) -> None:
    if f.tag == "select":
        agent.select(f.selector, value)
    else:
        agent.type(f.selector, value)


def export_resume_for_upload(db: Session, app: Application) -> str | None:
    from app.config import get_settings
    from app.services.resume_tailor import render_docx

    if not app.resume_version_id:
        return None
    rv = db.get(ResumeVersion, app.resume_version_id)
    if not rv:
        return None
    profile = get_profile(db)
    name = re.sub(r"[^A-Za-z0-9]+", "_", (profile.full_name or "Resume")).strip("_") or "Resume"
    path = get_settings().exports_dir / f"{name}_Resume_{app.id}.docx"
    path.write_bytes(render_docx(rv.content))
    return str(path)
