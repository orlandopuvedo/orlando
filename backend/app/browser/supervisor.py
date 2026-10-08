"""Supervised application agent.

Flow per run (every run is restartable and idempotent; approvals persist between runs):
  open application page (ATS strategy) → for each step: inspect page + supported frames → stop on CAPTCHA/login/2FA →
  fill safe fields / reuse approved answers / create approvals for anything missing or uncertain → advance through
  confidently-identified Next buttons → at the final page require the final-submission approval → submit →
  VERIFY confirmation → APPLIED (with follow-up) or SUBMITTED_UNCONFIRMED (+ manual verification request).

Never: guesses data, accepts legal terms on the user's behalf, clicks unidentified buttons, uploads unsupported
files, bypasses CAPTCHA/2FA/login, or reports an unconfirmed submission as APPLIED.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.browser import detectors
from app.browser.ats import AtsStrategy, select_strategy
from app.browser.base import BrowserAgent, HumanInterventionRequired
from app.browser.select_match import is_placeholder, match_option
from app.models import AgentRun, Application, ApprovalRequest, GeneratedDocument, JobSource, Resume, ResumeVersion, utcnow
from app.services.application_engine import DEMOGRAPHIC_Q, LEGAL_Q, SALARY_Q, VERIFY_NO, VERIFY_YES, _approval
from app.services.notifications import notify
from app.services.pipeline import TransitionError, transition_job
from app.services.profile_service import get_profile
from app.services.settings_service import get_all_settings
from app.services.text_utils import normalize_text

MANUAL_ONLY_DOMAINS = ("linkedin.com", "indeed.", "wellfound.com", "flexjobs.com", "upwork.com", "glassdoor.")
ATS_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com")
PROFILE_FIELD_PATTERNS = [
    ("first_name", r"first name|given name|^nombre$|nombre\(s\)"),
    ("last_name", r"last name|surname|family name|apellido"),
    ("full_name", r"full name|^name$|your name|nombre completo|legal name"),
    ("email", r"e-?mail"),
    ("phone", r"phone|mobile|tel[eé]fono|celular"),
    ("linkedin_url", r"linkedin"),
    ("portfolio_url", r"portfolio|website|personal site|github"),
    ("country", r"^country|country of residence|pa[ií]s"),
    ("employment_type", r"employment type|type of employment|^job type"),
    ("location", r"location|^city|ciudad|where are you (?:based|located)|current address"),
]
CHECK_YES = "Check this box (I explicitly agree)"
CHECK_NO = "Leave unchecked"
MANUAL_ACK = "I understand — I will complete this part manually"


@dataclass
class AgentRunResult:
    status: str  # not_allowed | blocked | awaiting_approval | ready_to_submit | submitted | submitted_unconfirmed | error
    message: str
    filled: list[dict] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    run_id: int | None = None
    confirmation: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"status": self.status, "message": self.message, "filled": self.filled, "pending": self.pending,
                "run_id": self.run_id, "confirmation": self.confirmation}


class _Stop(Exception):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status, self.message = status, message


# ------------------------------------------------------------------------------------------------ permission
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
    strategy = select_strategy(url)
    if not strategy.supported:
        return False, f"{strategy.name.title()} application forms are not supported for automation yet — apply manually."
    src = db.scalar(select(JobSource).where(JobSource.key == job.source))
    status = src.apply_automation_status if src else "unknown"
    if any(h in host for h in ATS_HOSTS) or job.source == "manual":
        # Company/ATS application forms the user chose — supervised filling, approval before submit.
        status = "allowed" if status == "allowed" else "review_required"
    if status in ("manual_only", "unknown"):
        return False, f"{src.name if src else job.source}: automation status is '{status}' — submit this application manually."
    if app.mode == "auto":
        if status != "allowed" or not (settings.get("auto_apply_permissions") or {}).get(job.source):
            return False, "AUTO mode is only available where automation is explicitly allowed and enabled in Settings. Use Supervised."
    return True, status


def submission_auto_approved(db: Session, app: Application) -> bool:
    """Auto mode with an explicit, deliberately configured permission is the ONLY way to skip final approval."""
    if app.mode != "auto":
        return False
    ok, status = automation_permission(db, app)
    return ok and status == "allowed"


# ------------------------------------------------------------------------------------------------ helpers
def _profile_value(key: str, profile) -> str | None:
    if key == "employment_type":  # only when the user stated exactly ONE preference; otherwise it is a choice → approval
        types = profile.employment_types or []
        return types[0] if len(types) == 1 else None
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


def _approved(db: Session, app: Application, key: str) -> ApprovalRequest | None:
    return db.scalar(select(ApprovalRequest).where(ApprovalRequest.application_id == app.id, ApprovalRequest.field_key == key,
                                                   ApprovalRequest.status.in_(["APPROVED", "EDITED", "SKIPPED"]))
                     .order_by(ApprovalRequest.id.desc()))


def export_resume_for_upload(db: Session, app: Application) -> str | None:
    """The package's resume as a file: tailored version (DOCX) → else the selected uploaded original → else None."""
    from app.config import get_settings
    from app.services.resume_tailor import render_docx

    profile = get_profile(db)
    name = re.sub(r"[^A-Za-z0-9]+", "_", (profile.full_name or "Resume")).strip("_") or "Resume"
    if app.resume_version_id:
        rv = db.get(ResumeVersion, app.resume_version_id)
        if rv and rv.content:
            path = get_settings().exports_dir / f"{name}_Resume_{app.id}.docx"
            path.write_bytes(render_docx(rv.content))
            return str(path)
    if app.resume_id:
        r = db.get(Resume, app.resume_id)
        if r and r.stored_filename:
            p = get_settings().uploads_dir / r.stored_filename
            if p.exists():
                return str(p)
    return None


def export_cover_letter_for_upload(db: Session, app: Application) -> str | None:
    import docx

    from app.config import get_settings

    doc = db.get(GeneratedDocument, app.cover_letter_id) if app.cover_letter_id else None
    if not doc or not (doc.content or "").strip():
        return None
    d = docx.Document()
    for para in doc.content.split("\n"):
        d.add_paragraph(para)
    path = get_settings().exports_dir / f"Cover_Letter_{app.id}.docx"
    d.save(str(path))
    return str(path)


# ------------------------------------------------------------------------------------------------ the run
class SupervisedRun:
    def __init__(self, db: Session, app: Application, agent: BrowserAgent, resume_file: str | None,
                 cover_letter_text: str | None, cover_letter_file: str | None = None):
        self.db, self.app, self.agent = db, app, agent
        self.job = app.job
        self.profile = get_profile(db)
        self.settings = get_all_settings(db)
        self.pkg = dict(app.package or {})
        self.resume_file = resume_file
        self.cover_text = cover_letter_text
        self.cover_file = cover_letter_file
        self.filled: list[dict] = []
        self.pending: list[str] = []
        self.answers: dict[str, str] = {}
        self.strategy: AtsStrategy = select_strategy(self.job.apply_url or self.job.source_url or "")
        self.run = AgentRun(application_id=app.id, job_id=app.job_id, mode=app.mode, ats=self.strategy.name, status="running", events=[])
        db.add(self.run)
        db.flush()

    # -- observability
    def log(self, kind: str, msg: str, **data) -> None:
        ev = {"at": utcnow().isoformat(), "step": self.run.current_step, "kind": kind, "msg": msg}
        if data:
            ev["data"] = data
        self.run.events = list(self.run.events or []) + [ev]
        self.db.flush()

    def ask(self, kind: str, title: str, message: str, key: str, proposed: str | None = None,
            options: list[str] | None = None, label: str | None = None) -> None:
        _approval(self.db, self.app, kind, f"{title}: {self.job.title}", message, key, proposed, options)
        self.run.approvals_requested += 1
        self.pending.append(label or title)
        self.log("approval", f"{title} — {message}", key=key, options=options or [])

    def set(self, f: dict, value: str, verb: str = "type", reason: str = "") -> None:
        self.agent.act(verb, f["selector"], value, frame=f.get("frame"))
        shown = value if verb != "upload" else value.rsplit("/", 1)[-1]
        self.filled.append({"field": f["label"] or f["selector"], "value": shown[:80]})
        self.answers[f["label"] or f["selector"]] = shown[:500]
        self.run.fields_filled += 1
        self.log("fill", f"{f['label'] or f['selector']} ← {shown[:60]}", reason=reason)

    # -- inspection across the page + supported frames
    def inspect(self) -> dict:
        url = self.agent.current_url()
        top = self.agent.page_html()
        contexts = [(None, top)]
        unsupported, inaccessible = [], []
        for fr in self.agent.list_frames():
            if not self.strategy.frame_supported(fr.url, url):
                unsupported.append(fr.url)
                continue
            if not fr.accessible:
                inaccessible.append(fr.url)
                continue
            try:
                contexts.append((fr.id, self.agent.frame_html(fr.id)))
            except HumanInterventionRequired:
                inaccessible.append(fr.url)
        snap = {"url": url, "fields": [], "buttons": [], "errors": [], "text": "", "unsupported_frames": unsupported,
                "inaccessible_frames": inaccessible, "captcha": False, "login": False, "two_factor": False, "passive_captcha": False}
        for frame_id, html in contexts:
            form = detectors.extract_form(html)
            for f in form["fields"]:
                f["frame"] = frame_id
                snap["fields"].append(f)
            for b in form["buttons"]:
                b["frame"] = frame_id
                snap["buttons"].append(b)
            snap["errors"] += form["errors"]
            snap["text"] += "\n" + detectors.html_text(html)
            snap["captcha"] |= detectors.detect_captcha(html)
            snap["login"] |= detectors.detect_login(html)
            snap["two_factor"] |= detectors.detect_2fa(html)
            snap["passive_captcha"] |= detectors.detect_passive_captcha(html)
        snap["fields"] = [f for f in snap["fields"] if not (f.get("hidden") and f["type"] != "file")]
        return snap

    def check_blockers(self, snap: dict) -> None:
        if snap["captcha"]:
            raise HumanInterventionRequired("CAPTCHA challenge detected — complete it yourself in the browser, then re-run or submit manually.", "captcha")
        if snap["two_factor"]:
            raise HumanInterventionRequired("Two-factor / one-time code verification required — complete it yourself.", "two_factor")
        if snap["login"]:
            raise HumanInterventionRequired("Login required — log in yourself in the agent browser window, then re-run.", "login")

    # -- field resolution
    def resolve(self, f: dict) -> None:
        label = (f.get("label") or f.get("name") or "").strip()
        low = label.lower()
        req = f.get("required")
        if f.get("value") and not is_placeholder(f["value"]) and f["type"] not in ("file", "radio_group", "checkbox"):
            self.log("skip", f"{label}: already filled on the page")
            return
        key = f"field:{f['key']}"
        if f["type"] == "file":
            return self.resolve_file(f, label, low, key)
        prior = _approved(self.db, self.app, key)
        if prior is not None:
            return self.use_approved(f, prior, label)
        if f["type"] == "checkbox":
            return self.resolve_checkbox(f, label, key)
        sensitive = ("demographic" if DEMOGRAPHIC_Q.search(label) else "legal" if LEGAL_Q.search(label)
                     else "salary" if SALARY_Q.search(label) else None)
        if sensitive:
            proposal = (self.pkg.get("salary_answer") if sensitive == "salary" else
                        self.profile.work_authorization if sensitive == "legal" else "I prefer not to answer")
            opts = self.real_options(f)
            if opts:
                m = match_option(proposal, opts)
                proposal = m.option
            if not req and sensitive == "demographic" and not opts:
                self.log("skip", f"{label}: optional demographic question left blank")
                return
            return self.ask(sensitive, f"{sensitive.capitalize()} question", label, key, proposal, opts or None, label)
        for pkey, pat in PROFILE_FIELD_PATTERNS:
            if re.search(pat, low):
                return self.resolve_profile(f, label, key, pkey)
        if re.search(r"cover letter|motivation letter", low) and f["type"] in ("textarea", "text"):
            if self.cover_text:
                return self.set(f, self.cover_text, reason="cover letter")
            if req:
                return self.ask("uncertain", "Cover letter required", f"{label} — generate or write a cover letter in the package.", key, None, None, label)
            return
        if re.search(r"video|loom", low) and f["type"] in ("text", "url", "textarea"):
            return self.resolve_video_url(f, label, key)
        ans = _match_answer(label, self.pkg)
        if ans and ans.get("answer") and (not ans.get("needs_approval") or ans.get("approved")):
            return self.apply_text_answer(f, label, key, ans["answer"])
        if req:
            opts = self.real_options(f)
            return self.ask("uncertain", "Answer needed", label, key, ans.get("answer") if ans else None, opts or None, label)
        self.log("skip", f"{label or f['selector']}: optional and no confident answer — left blank")

    def real_options(self, f: dict) -> list[str]:
        return [o for o in (f.get("options") or []) if not is_placeholder(o)]

    def use_approved(self, f: dict, prior: ApprovalRequest, label: str) -> None:
        if prior.status == "SKIPPED":
            if f.get("required"):
                raise _Stop("blocked", f"You skipped the required field “{label}”. Answer it in Approvals (or finish manually).")
            self.log("skip", f"{label}: skipped by you")
            return
        value = prior.final_value or ""
        if f["type"] == "checkbox":
            if value == CHECK_YES:
                return self.set(f, "", verb="check", reason="explicitly approved by you")
            self.log("skip", f"{label}: left unchecked (your decision)")
            if f.get("required"):
                raise _Stop("blocked", f"“{label}” is required but you chose to leave it unchecked — the form cannot be submitted.")
            return
        if f["type"] == "radio_group":
            m = match_option(value, f["options"])
            if not m.ok:
                return self.ask("uncertain", "Choose an option", f"{label} (your earlier answer “{value}” no longer matches)", f"field:{f['key']}:v2",
                                None, self.real_options(f), label)
            return self.set({**f, "selector": f["option_selectors"][m.option]}, m.option, verb="check", reason="approved")
        if f["type"] == "select":
            m = match_option(value, f["options"])
            if not m.ok:
                return self.ask("uncertain", "Choose an option", f"{label} (“{value}” is not an available option)", f"field:{f['key']}:v2",
                                None, self.real_options(f), label)
            return self.set(f, m.option, verb="select", reason="approved")
        if not value and f.get("required"):
            raise _Stop("blocked", f"No value approved for the required field “{label}”.")
        if value:
            self.set(f, value, reason="approved")

    def resolve_checkbox(self, f: dict, label: str, key: str) -> None:
        if f.get("value") == "checked":
            self.log("skip", f"{label}: already checked")
            return
        if f.get("consent"):
            if f.get("required"):
                return self.ask("legal", "Consent / legal checkbox", f"The form requires: “{label}”. Only you can accept this.",
                                key, None, [CHECK_YES, CHECK_NO], label)
            self.log("skip", f"{label}: optional consent/preference — left unchecked")
            return
        if f.get("required"):
            return self.ask("uncertain", "Required checkbox", label, key, None, [CHECK_YES, CHECK_NO], label)
        self.log("skip", f"{label}: optional checkbox — left unchanged")

    def resolve_profile(self, f: dict, label: str, key: str, pkey: str) -> None:
        val = _profile_value(pkey, self.profile)
        if not val:
            if f.get("required"):
                return self.ask("missing_profile", "Missing profile information",
                                f"The form requires “{label}” but your profile has no {pkey.replace('_', ' ')}. Provide it (and add it to your Profile).",
                                key, None, self.real_options(f) or None, label)
            self.log("skip", f"{label}: no {pkey} in profile (optional)")
            return
        if f["type"] in ("select", "radio_group"):
            return self.apply_choice(f, label, key, str(val), reason=f"profile.{pkey}")
        self.set(f, str(val), reason=f"profile.{pkey}")

    def apply_text_answer(self, f: dict, label: str, key: str, answer: str) -> None:
        if f["type"] in ("select", "radio_group"):
            return self.apply_choice(f, label, key, answer, reason="package answer")
        self.set(f, answer, reason="package answer")

    def apply_choice(self, f: dict, label: str, key: str, value: str, reason: str) -> None:
        opts = self.real_options(f)
        m = match_option(value, opts)
        if m.ok:
            if f["type"] == "radio_group":
                return self.set({**f, "selector": f["option_selectors"][m.option]}, m.option, verb="check", reason=f"{reason} ({m.method})")
            return self.set(f, m.option, verb="select", reason=f"{reason} ({m.method})")
        why = "several options could match" if m.method == "ambiguous" else "no option matches safely"
        if f.get("required") or f["type"] == "select":
            return self.ask("uncertain", "Choose an option", f"{label} — {why} “{value}”.", key,
                            m.candidates[0] if len(m.candidates) == 1 else None, opts, label)

    def resolve_video_url(self, f: dict, label: str, key: str) -> None:
        url = (self.pkg.get("video") or {}).get("approved_url")
        if url:
            return self.set(f, url, reason="approved video URL")
        prior = _approved(self.db, self.app, "video")
        if prior is not None and prior.status == "SKIPPED":
            if f.get("required"):
                raise _Stop("blocked", f"“{label}” requires a video link, but you skipped the video approval.")
            self.log("skip", f"{label}: video skipped by you")
            return
        rec = ((self.pkg.get("video") or {}).get("recommendation") or {}).get("url")
        if rec:
            return self.ask("video", "Video URL", f"{label} — approve the recommended video link (or edit it).", "video", rec, None, label)
        if f.get("required"):
            return self.ask("video", "Video required", f"{label} — add a video (e.g. Loom) to your Video Library first. No URL is ever invented.",
                            "video", None, None, label)
        self.log("skip", f"{label}: optional video link — none available")

    def resolve_file(self, f: dict, label: str, low: str, key: str) -> None:
        req = f.get("required")
        if self.strategy.is_resume_field(f):
            if not self.resume_file:
                if not req:
                    self.log("skip", f"{label}: optional resume upload — no resume file in this package")
                    return
                raise _Stop("blocked", "The form needs a resume file, but this application has no resume (tailored version or upload). "
                                       "Generate the tailored resume in the package first.")
            return self.set(f, self.resume_file, verb="upload", reason="package resume")
        if re.search(r"cover", low):
            if self.cover_file:
                return self.set(f, self.cover_file, verb="upload", reason="package cover letter")
            if req:
                return self.ask("uncertain", "Cover letter file required", f"{label} — generate a cover letter in the package first.", key, None, None, label)
            self.log("skip", f"{label}: optional cover-letter upload (no cover letter generated)")
            return
        if re.search(r"video|mp4|mov", low + " " + (f.get("accept") or "")):
            if not req:
                self.log("skip", f"{label}: optional video file upload — not supported, left empty")
                return
            if _approved(self.db, self.app, key) is None:
                return self.ask("video_file", "Video FILE upload required",
                                f"{label} — uploading video files is not supported. Upload it yourself in the browser, or apply manually.",
                                key, None, [MANUAL_ACK], label)
            raise _Stop("blocked", f"“{label}” requires a video FILE upload, which the agent never does. Finish this application manually.")
        if req:
            prior = _approved(self.db, self.app, key)
            if prior is None:
                return self.ask("manual_action", "Unsupported required file upload",
                                f"{label} — the agent only uploads your resume and cover letter. Attach this file yourself.", key, None, [MANUAL_ACK], label)
            raise _Stop("blocked", f"Required file “{label}” must be attached manually — finish this application in the browser.")
        self.log("skip", f"{label}: optional file upload left empty")

    # -- navigation
    def pick_button(self, snap: dict) -> tuple[str | None, dict | None]:
        submit = nxt = None
        for b in snap["buttons"]:
            if b.get("disabled") or b.get("hidden"):
                continue
            kind = self.strategy.classify_button(b["text"])
            if kind == "submit" and submit is None:
                submit = b
            elif kind == "next" and nxt is None:
                nxt = b
        if nxt is not None and submit is None:
            return "next", nxt
        if submit is not None:
            return "submit", submit
        return None, None

    def signature(self, snap: dict) -> str:
        return snap["url"] + "|" + "|".join(sorted(f["key"] for f in snap["fields"]))

    # -- main
    def execute(self) -> AgentRunResult:
        db, job, app = self.db, self.job, self.app
        try:
            ok, info = automation_permission(db, app)
            if not ok:
                raise _Stop("not_allowed", info)
            if app.submission_status in ("confirmed", "manual_confirmed") or job.application_status == "APPLIED":
                raise _Stop("not_allowed", "This application is already submitted — the agent will not submit it again.")
            if job.application_status == "SUBMITTED_UNCONFIRMED":
                raise _Stop("not_allowed", "A submission was already attempted. Verify it first in Approvals (to avoid a duplicate application).")
            if job.application_status in ("READY", "QUALIFIED"):
                transition_job(db, job, "APPLYING", "Supervised agent started")
            target = self.strategy.application_url(job.apply_url or job.source_url)
            self.log("start", f"Opening {target} (strategy: {self.strategy.name})")
            self.agent.open_page(target)
            max_steps = int(self.settings.get("agent_max_steps") or 8)
            seen: list[str] = []
            for step in range(1, max_steps + 1):
                self.run.current_step = step
                snap = self.inspect()
                if step == 1 and self.strategy.name == "generic":
                    better = select_strategy(snap["url"], self.agent.page_html())
                    if better.name != "generic":
                        self.strategy = better
                        self.run.ats = better.name
                        self.log("info", f"Detected embedded {better.name} application form")
                        snap = self.inspect()
                self.check_blockers(snap)
                if snap["passive_captcha"]:
                    self.log("info", "Passive reCAPTCHA present (handled by the browser; the agent will stop if a challenge appears).")
                if not snap["fields"]:
                    if snap["inaccessible_frames"] or snap["unsupported_frames"]:
                        hosts = ", ".join(urlsplit(u).netloc for u in (snap["inaccessible_frames"] + snap["unsupported_frames"]))
                        raise HumanInterventionRequired(f"The application form is inside an embedded frame that cannot be automated ({hosts}). Apply manually.", "frame")
                    raise HumanInterventionRequired("No application form found on this page — open it manually.", "no_form")
                sig = self.signature(snap)
                if sig in seen:
                    errs = "; ".join(snap["errors"][:3])
                    raise _Stop("blocked", f"The form did not advance (same page again){': ' + errs if errs else ''}. Finish it manually.")
                seen.append(sig)
                self.log("step", f"Step {step}: {len(snap['fields'])} fields on {snap['url']}")
                for f in snap["fields"]:
                    self.resolve(f)
                if self.pending:
                    raise _Stop("awaiting_approval", f"{len(self.pending)} field(s) need your input (see Approvals). Re-run the agent after answering.")
                kind, btn = self.pick_button(snap)
                if kind == "next":
                    self.log("navigate", f"Clicking “{btn['text']}”")
                    self.agent.act("click", btn["selector"], frame=btn.get("frame"))
                    self.agent.wait_for_settle()
                    continue
                if kind == "submit":
                    return self.submit(btn)
                raise _Stop("blocked", "No recognizable Next/Submit button — the agent will not click unidentified buttons. Finish manually.")
            raise _Stop("blocked", f"Stopped after {max_steps} form steps (safety limit).")
        except HumanInterventionRequired as e:
            _approval(db, app, "blocked", f"Application blocked: {job.title}", e.reason, f"blocked:{e.kind}", None, [MANUAL_ACK])
            notify(db, "application_blocked", f"Application blocked: {job.title}", e.reason, link=f"/applications/{app.id}",
                   entity_type="application", entity_id=app.id, dedupe_key=f"blocked:{app.id}:{self.run.id}")
            return self.finish("blocked", e.reason, blocked=True)
        except _Stop as s:
            if s.status == "awaiting_approval":
                notify(db, "approval_required", f"Agent needs your input: {job.title}", ", ".join(self.pending)[:300], link="/approvals",
                       entity_type="application", entity_id=app.id, dedupe_key=f"agent_pending:{app.id}:{self.run.id}")
            return self.finish(s.status, s.message, blocked=s.status == "blocked")
        except Exception as e:  # browser errors
            self.run.error = f"{type(e).__name__}: {e}"
            return self.finish("error", f"{type(e).__name__}: {e}")

    def submit(self, btn: dict) -> AgentRunResult:
        db, app, job = self.db, self.app, self.job
        approved = self.pkg.get("submit_approved") is True or submission_auto_approved(db, app)
        if not approved:
            summary = f"{len(self.filled)} field(s) filled on {self.run.current_step} step(s). Approve to let the agent click “{btn['text']}”, then re-run the agent."
            _approval(db, app, "final_submit", f"Application is ready to submit: {job.title}", summary, "final_submit", "submit")
            self.run.approvals_requested += 1
            self.log("approval", "Final submission requires your approval")
            return self.finish("ready_to_submit", "Form filled. Approve the final submission in Approvals, then re-run the agent.")
        # consume the approval: one approval = one submission attempt
        self.pkg["submit_approved"] = False
        self.run.submission_attempted = True
        app.submitted_at = utcnow()
        self.log("submit", f"Clicking “{btn['text']}” (approved)")
        self.agent.act("click", btn["selector"], frame=btn.get("frame"))
        self.agent.wait_for_settle()
        snap = self.inspect()
        conf = self.strategy.confirmation(snap["url"], snap["text"])
        still_form = any(b for b in snap["buttons"] if self.strategy.classify_button(b["text"]) == "submit") and snap["fields"]
        app.final_url, app.ats = snap["url"], self.strategy.name
        app.submission_snapshot = {
            "submitted_at": app.submitted_at.isoformat(), "ats": self.strategy.name, "final_url": snap["url"],
            "resume_file": (self.resume_file or "").rsplit("/", 1)[-1] or None, "resume_version_id": app.resume_version_id,
            "video_url": (self.pkg.get("video") or {}).get("approved_url"), "answers": self.answers, "agent_run_id": self.run.id}
        if conf.confirmed and not snap["errors"] and not snap["captcha"]:
            app.submission_status = "confirmed"
            app.confirmation_text, app.confirmation_id = conf.text, conf.confirmation_id
            app.applied_via = snap["url"]
            self.run.confirmation = {"confirmed": True, "signal": conf.signal, "text": conf.text, "id": conf.confirmation_id}
            transition_job(db, job, "APPLIED", f"Submitted by supervised agent — confirmed ({conf.signal})")
            self.log("confirmed", f"Submission confirmed: {conf.signal}")
            return self.finish("submitted", "Application submitted and confirmed.")
        if snap["errors"] and still_form:
            app.submitted_at = None
            self.log("rejected", "The form reported errors after submit: " + "; ".join(snap["errors"][:3]))
            self.ask("uncertain", "Form rejected the submission", "; ".join(snap["errors"][:3]) or "Validation errors", "submit_errors", None, None)
            transition_job(db, job, "READY", "Submit rejected by the form (validation errors)")
            return self.finish("blocked", "The form rejected the submission — see the errors; nothing was recorded as applied.", blocked=True)
        # Clicked, but no reliable confirmation → never report APPLIED
        app.submission_status = "unconfirmed"
        reason = "a CAPTCHA appeared after submitting" if snap["captcha"] else "no confirmation message, ID or success page was detected"
        self.run.confirmation = {"confirmed": False, "reason": reason}
        transition_job(db, job, "SUBMITTED_UNCONFIRMED", f"Submit clicked but {reason}")
        _approval(db, app, "verify_submission", f"Verify submission: {job.title}",
                  f"The agent clicked submit, but {reason}. Check your email / the ATS page and confirm.", "verify_submission", None,
                  [VERIFY_YES, VERIFY_NO])
        self.run.approvals_requested += 1
        self.log("unconfirmed", f"Submission NOT confirmed: {reason}")
        notify(db, "approval_required", f"Verify submission: {job.title}", reason, link="/approvals",
               entity_type="application", entity_id=app.id, dedupe_key=f"verify:{app.id}:{self.run.id}")
        return self.finish("submitted_unconfirmed", f"Submit was clicked, but {reason}. Please verify — it is NOT marked as applied.")

    def finish(self, status: str, message: str, blocked: bool = False) -> AgentRunResult:
        job = self.job
        if status in ("blocked", "awaiting_approval", "ready_to_submit", "error") and job.application_status == "APPLYING":
            try:
                transition_job(self.db, job, "READY", f"Agent stopped: {status}")
            except TransitionError:
                pass
        self.app.package = {**self.pkg, "agent_last_run": {"run_id": self.run.id, "status": status, "message": message,
                                                           "at": utcnow().isoformat()}}
        self.run.status = status
        if blocked or status in ("not_allowed",):
            self.run.blocked_reason = message
        self.run.finished_at = utcnow()
        self.log("end", f"{status}: {message}")
        self.db.flush()
        return AgentRunResult(status, message, self.filled, self.pending, self.run.id, self.run.confirmation or {})


def run_supervised(db: Session, app: Application, agent: BrowserAgent, resume_file: str | None = None,
                   cover_letter_text: str | None = None, cover_letter_file: str | None = None) -> AgentRunResult:
    try:
        ok, info = automation_permission(db, app)
        if not ok:  # nothing is opened, filled or logged when automation isn't permitted
            return AgentRunResult("not_allowed", info)
        return SupervisedRun(db, app, agent, resume_file, cover_letter_text, cover_letter_file).execute()
    finally:
        try:
            agent.close()
        except Exception:
            pass
