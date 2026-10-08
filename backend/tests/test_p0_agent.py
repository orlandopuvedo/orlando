"""P0 supervised agent: approvals for every required unknown, smart dropdowns, multi-step, iframes, ATS strategies,
resume/video handling, CAPTCHA, and confirmation-based submission. All against local HTML fixtures (no live sites)."""
from pathlib import Path

import pytest

from app.browser.ats import select_strategy
from app.browser.select_match import match_option
from app.browser.supervisor import CHECK_YES, MANUAL_ACK, run_supervised
from app.models import AgentRun, Application, FollowUp
from app.services.application_engine import VERIFY_NO, VERIFY_YES
from tests.conftest import SAMPLE_PROFILE
from tests.fake_browser import FakeBrowser

FX = Path(__file__).parent / "fixtures" / "ats"
GH = "https://boards.greenhouse.io/acme/jobs/4000001"
LEVER = "https://jobs.lever.co/acme/0b1c2d3e-0000-4000-8000-123456789abc"
ASHBY = "https://jobs.ashbyhq.com/acme/1f2e3d4c-0000-4000-8000-abcdefabcdef"
LOOM = "https://www.loom.com/share/" + "a" * 32


def page(name: str) -> str:
    return (FX / name).read_text()


def make_app(client, db, url, description="Remote SDR role, HubSpot, cold calling. $3,000 - $4,000 per month.", profile=None,
             mode="supervised", with_video=False):
    client.put("/api/profile", json={**SAMPLE_PROFILE, "phone": "+57 300 000 0000", **(profile or {})})
    if with_video:
        client.post("/api/videos", json={"name": "Sales Introduction", "tags": ["sales"], "url": LOOM, "is_active": True, "duration_minutes": 5})
    job = client.post("/api/jobs", json={"title": "Sales Development Representative", "company": "Acme", "description": description,
                                         "apply_url": url, "source_url": url}).json()["job"]
    app_id = client.post(f"/api/jobs/{job['id']}/application", json={"mode": mode}).json()["application_id"]
    return db.get(Application, app_id)


def run(db, app_id, browser, resume="/tmp/cv.docx", cover_file=None):
    db.expire_all()
    res = run_supervised(db, db.get(Application, app_id), browser, resume_file=resume, cover_letter_text=None, cover_letter_file=cover_file)
    db.commit()
    return res


def pending(client, kind=None):
    items = client.get("/api/approvals").json()
    return [a for a in items if kind is None or a["kind"] == kind]


def resolve(client, ap, action="approve", value=None):
    r = client.post(f"/api/approvals/{ap['id']}/resolve", json={"action": action, "value": value})
    assert r.status_code == 200, r.text
    return r.json()


def gh_browser():
    return FakeBrowser({GH: page("greenhouse_form.html"), GH + "/confirmation": page("greenhouse_confirmation.html")},
                       transitions={(GH, "Submit Application"): GH + "/confirmation"})


# ------------------------------------------------------------------ Greenhouse end-to-end (approvals → submit → confirm)
def test_greenhouse_full_supervised_flow(client, db):
    app = make_app(client, db, GH, description="Remote SDR. HubSpot. $3,000-$4,000 per month. Please share a Loom video introducing yourself.",
                   with_video=True)
    # Run 1: safe fields filled, resume attached, everything uncertain → approvals; nothing submitted
    b = gh_browser()
    res = run(db, app.id, b)
    assert res.status == "awaiting_approval", res.message
    typed = b.typed()
    assert typed['[id="first_name"]'] == "Ana" and typed['[id="last_name"]'] == "Rivera"
    assert typed['[id="email"]'] == "ana@example.com" and typed['[id="phone"]'] == "+57 300 000 0000"
    assert ("upload", '[id="resume"]', "/tmp/cv.docx") in b.actions          # hidden ATS file input still handled
    assert not b.did("click")                                                # never submitted
    assert not any(a[1] == '[id="news"]' for a in b.actions)                 # optional preference untouched
    aps = pending(client)
    by_title = {a["message"]: a for a in aps}
    consent = next(a for a in aps if "Privacy Policy" in (a["message"] or ""))
    assert consent["kind"] == "legal" and CHECK_YES in consent["options"]    # never auto-accept legal terms
    radio = [a for a in aps if "Eastern Time" in (a["message"] or "")]
    assert len(radio) == 1 and radio[0]["options"] == ["Yes", "No"]          # ONE approval for the radio group
    auth = next(a for a in aps if "authorized to work" in (a["message"] or ""))
    assert auth["kind"] == "legal" and auth["options"] == ["Yes", "No"]
    video = next(a for a in aps if a["kind"] == "video")
    assert video["proposed_value"] == LOOM                                   # recommended, never invented
    gender = next(a for a in aps if a["kind"] == "demographic" and a["field_key"].startswith("field:"))
    assert gender["proposed_value"] == "Decline To Self Identify"           # smart match of "prefer not to answer"
    assert by_title  # (all approvals actionable)

    resolve(client, consent, "edit", CHECK_YES)
    resolve(client, radio[0], "edit", "Yes")
    resolve(client, auth, "edit", "Yes")
    for a in pending(client):
        if a["kind"] in ("video", "demographic", "salary"):
            resolve(client, a, "approve")
    # Run 2: everything answered → filled → final approval required (no submit)
    n_before = len(client.get("/api/approvals?status=ALL").json())
    b2 = gh_browser()
    res = run(db, app.id, b2)
    assert res.status == "ready_to_submit", res.message
    assert ("check", '[id="gdpr"]', None) in b2.actions
    assert b2.typed()['[id="q_loom"]'] == LOOM
    assert b2.typed()['[id="q_auth"]'] == "Yes"
    assert not b2.did("click")
    n_after = len(client.get("/api/approvals?status=ALL").json())
    assert n_after == n_before + 1  # only the final-submit approval; answered questions are not asked again
    final = pending(client, "final_submit")[0]
    resolve(client, final, "approve")
    # Run 3: submits and VERIFIES confirmation
    b3 = gh_browser()
    res = run(db, app.id, b3)
    assert res.status == "submitted", res.message
    assert ("click", '[id="submit_app"]', None) in b3.actions
    db.expire_all()
    a = db.get(Application, app.id)
    assert a.status == "APPLIED" and a.submission_status == "confirmed" and a.ats == "greenhouse"
    assert a.final_url.endswith("/confirmation") and "Thank you for applying" in a.confirmation_text
    assert a.submission_snapshot["video_url"] == LOOM and a.submission_snapshot["resume_file"] == "cv.docx"
    assert a.submission_snapshot["answers"]
    assert db.query(FollowUp).filter_by(application_id=app.id, kind="application").count() == 1
    runs = client.get(f"/api/applications/{app.id}/agent-runs").json()
    assert [r["status"] for r in runs] == ["submitted", "ready_to_submit", "awaiting_approval"]
    assert runs[0]["submission_attempted"] and runs[0]["confirmation"]["confirmed"]
    assert any(e["kind"] == "fill" for e in runs[0]["events"]) and runs[2]["approvals_requested"] >= 5
    # A 4th run must never submit twice
    assert run(db, app.id, gh_browser()).status == "not_allowed"


def test_final_submission_always_requires_approval_by_default(client, db):
    app = make_app(client, db, GH)
    for a in pending(client):
        resolve(client, a, "edit", a["options"][0] if a["options"] else "x") if a["options"] else resolve(client, a, "approve" if a["proposed_value"] else "edit", a["proposed_value"] or "x")
    b = gh_browser()
    res = run(db, app.id, b)
    while res.status == "awaiting_approval":
        for a in pending(client):
            resolve(client, a, "edit", a["options"][0]) if a["options"] else resolve(client, a, "edit", a["proposed_value"] or "x")
        b = gh_browser()
        res = run(db, app.id, b)
    assert res.status == "ready_to_submit" and not b.did("click")


# ------------------------------------------------------------------ unconfirmed submission
def _submit_ready(client, db, url, browser_factory, **kw):
    app = make_app(client, db, url, **kw)
    for _ in range(6):
        res = run(db, app.id, browser_factory())
        if res.status != "awaiting_approval":
            break
        for a in pending(client):
            if a["options"]:
                resolve(client, a, "edit", CHECK_YES if CHECK_YES in a["options"] else a["options"][0])
            else:
                resolve(client, a, "edit", a["proposed_value"] or LOOM)
    assert res.status == "ready_to_submit", res.message
    resolve(client, pending(client, "final_submit")[0], "approve")
    return app


def test_unconfirmed_submission_is_never_marked_applied(client, db):
    factory = lambda: FakeBrowser({GH: page("greenhouse_form.html"), GH + "/x": page("processing.html")},  # noqa: E731
                                  transitions={(GH, "Submit Application"): GH + "/x"})
    app = _submit_ready(client, db, GH, factory)
    res = run(db, app.id, factory())
    assert res.status == "submitted_unconfirmed"
    db.expire_all()
    a = db.get(Application, app.id)
    assert a.status == "SUBMITTED_UNCONFIRMED" and a.submission_status == "unconfirmed" and a.applied_at is None
    assert db.query(FollowUp).filter_by(application_id=app.id).count() == 0
    verify = pending(client, "verify_submission")[0]
    assert verify["options"] == [VERIFY_YES, VERIFY_NO]
    # Re-running cannot double-submit while unverified
    assert run(db, app.id, factory()).status == "not_allowed"
    # User checks and confirms → APPLIED + follow-up
    resolve(client, verify, "edit", VERIFY_YES)
    db.expire_all()
    a = db.get(Application, app.id)
    assert a.status == "APPLIED" and a.submission_status == "manual_confirmed"
    assert db.query(FollowUp).filter_by(application_id=app.id, kind="application").count() == 1


def test_unconfirmed_submission_reported_not_submitted_goes_back_to_ready(client, db):
    factory = lambda: FakeBrowser({GH: page("greenhouse_form.html"), GH + "/x": page("processing.html")},  # noqa: E731
                                  transitions={(GH, "Submit Application"): GH + "/x"})
    app = _submit_ready(client, db, GH, factory)
    run(db, app.id, factory())
    resolve(client, pending(client, "verify_submission")[0], "edit", VERIFY_NO)
    db.expire_all()
    assert db.get(Application, app.id).status == "READY"


# ------------------------------------------------------------------ Lever & Ashby strategies
def test_lever_strategy_div_labels_and_confirmation(client, db):
    apply_url = LEVER + "/apply"
    factory = lambda: FakeBrowser({apply_url: page("lever_form.html"), LEVER + "/thanks": page("lever_thanks.html")},  # noqa: E731
                                  transitions={(apply_url, "Submit application"): LEVER + "/thanks"})
    app = make_app(client, db, LEVER)
    b = factory()
    res = run(db, app.id, b)
    assert b.actions[0] == ("open", apply_url)                     # strategy maps the posting to its /apply form
    assert res.status == "awaiting_approval"
    t = b.typed()
    assert t['input[name="name"]'] == "Ana Rivera" and t['input[name="email"]'] == "ana@example.com"
    assert t['input[name="location"]'] == "Medellín, Colombia"
    assert ("upload", '[id="resume-upload-input"]', "/tmp/cv.docx") in b.actions
    visa = pending(client, "legal")[0]
    assert "visa sponsorship" in visa["message"] and visa["options"] == ["Yes", "No"]
    resolve(client, visa, "edit", "No")
    res = run(db, app.id, factory())
    assert res.status == "ready_to_submit"
    resolve(client, pending(client, "final_submit")[0], "approve")
    res = run(db, app.id, factory())
    assert res.status == "submitted"
    db.expire_all()
    assert db.get(Application, app.id).ats == "lever"


def test_ashby_dropdowns_and_confirmation_id(client, db):
    form = ASHBY + "/application"
    factory = lambda: FakeBrowser({form: page("ashby_form.html"), form + "/done": page("ashby_done.html")},  # noqa: E731
                                  transitions={(form, "Submit Application"): form + "/done"})
    app = make_app(client, db, ASHBY)
    b = factory()
    res = run(db, app.id, b)
    assert b.actions[0] == ("open", form)
    assert b.typed()['[id="country_q"]'] == "Colombia (CO)"        # profile country → safe normalized option match
    sched = pending(client)
    assert len(sched) == 1 and "Preferred schedule" in sched[0]["message"]  # unknown required select → approval with options
    assert sched[0]["options"] == ["Full Time - Morning", "Full Time - Evening"]
    resolve(client, sched[0], "edit", "Full Time - Morning")
    assert run(db, app.id, factory()).status == "ready_to_submit"
    resolve(client, pending(client, "final_submit")[0], "approve")
    assert run(db, app.id, factory()).status == "submitted"
    db.expire_all()
    a = db.get(Application, app.id)
    assert a.confirmation_id == "ASH-77821" and a.ats == "ashby"


# ------------------------------------------------------------------ multi-step & loops
MS = "https://careers.acme-example.com/apply/42"


def ms_browser(step1="multistep_1.html"):
    return FakeBrowser({MS: page(step1), MS + "/2": page("multistep_2.html"), MS + "/3": page("multistep_3.html"),
                        MS + "/done": page("multistep_done.html")},
                       transitions={(MS, "Next"): MS + "/2", (MS + "/2", "Save & Continue"): MS + "/3",
                                    (MS + "/3", "Submit application"): MS + "/done"})


def test_multistep_form(client, db):
    app = make_app(client, db, MS, profile={"employment_types": ["full_time"]})
    b = ms_browser()
    res = run(db, app.id, b)
    assert res.status == "awaiting_approval"
    assert ("click", '[id="next1"]', None) in b.actions and ("click", '[id="next2"]', None) in b.actions
    assert not any(a[1] in ('[id="back2"]', '[id="back3"]', '[id="send"]') for a in b.did("click"))  # never Back / never Submit
    assert b.typed()['[id="ph"]'] == "+57 300 000 0000"
    assert ("upload", '[id="cv"]', "/tmp/cv.docx") in b.actions
    assert b.typed()['[id="ws"]'] == "Full-time"  # single stated preference "full_time" → normalized option match
    avail = pending(client)
    assert len(avail) == 1 and avail[0]["options"] == ["Yes", "No"]
    resolve(client, avail[0], "edit", "Yes")
    assert run(db, app.id, ms_browser()).status == "ready_to_submit"
    resolve(client, pending(client, "final_submit")[0], "approve")
    b = ms_browser()
    res = run(db, app.id, b)
    assert res.status == "submitted"
    db.expire_all()
    a = db.get(Application, app.id)
    assert a.confirmation_id == "ACME-2026-0042" and a.status == "APPLIED"


def test_multistep_loop_detection(client, db):
    app = make_app(client, db, MS)
    b = FakeBrowser({MS: page("multistep_1.html"), MS + "/err": page("multistep_error.html")},
                    transitions={(MS, "Next"): MS + "/err", (MS + "/err", "Next"): MS + "/err"})
    res = run(db, app.id, b)
    assert res.status == "blocked" and "did not advance" in res.message


def test_max_step_safety_limit(client, db):
    client.put("/api/settings", json={"agent_max_steps": 1})
    app = make_app(client, db, MS)
    res = run(db, app.id, ms_browser())
    assert res.status == "blocked" and "safety limit" in res.message


# ------------------------------------------------------------------ iframes
COMPANY = "https://careers.acme-example.com/jobs/sdr"
GH_EMBED = "https://boards.greenhouse.io/embed/job_app?for=acme&token=4000001&b=https%3A%2F%2Fcareers.acme.com"


def test_supported_greenhouse_iframe(client, db):
    def factory():
        return FakeBrowser({COMPANY: page("company_embed.html"), "gh": page("greenhouse_form.html"), "ok": page("greenhouse_confirmation.html")},
                           frames={GH_EMBED: "gh"}, transitions={(GH_EMBED, "Submit Application"): "ok"})
    app = make_app(client, db, COMPANY)
    b = factory()
    res = run(db, app.id, b)
    assert res.status == "awaiting_approval"
    assert ("type", '[id="first_name"]', "Ana", GH_EMBED) in b.actions          # filled INSIDE the frame
    for _ in range(4):
        for a in pending(client):
            if a["options"]:
                resolve(client, a, "edit", CHECK_YES if CHECK_YES in a["options"] else a["options"][0])
            else:
                resolve(client, a, "edit", a["proposed_value"] or LOOM)
        res = run(db, app.id, factory())
        if res.status != "awaiting_approval":
            break
    assert res.status == "ready_to_submit"
    resolve(client, pending(client, "final_submit")[0], "approve")
    b = factory()
    assert run(db, app.id, b).status == "submitted"
    db.expire_all()
    assert db.get(Application, app.id).ats == "greenhouse"


def test_unsupported_or_inaccessible_iframe_blocks(client, db):
    app = make_app(client, db, COMPANY)
    b = FakeBrowser({COMPANY: page("company_unsupported_embed.html")})
    res = run(db, app.id, b)
    assert res.status == "blocked" and "embedded frame" in res.message
    blocked = pending(client, "blocked")[0]
    assert blocked["options"] == [MANUAL_ACK]
    b = FakeBrowser({COMPANY: page("company_embed.html")}, frames={GH_EMBED: None})  # supported host but not accessible
    res = run(db, app.id, b)
    assert res.status == "blocked" and "embedded frame" in res.message


# ------------------------------------------------------------------ fields
def test_missing_profile_field_creates_approval_then_reused(client, db):
    app = make_app(client, db, LEVER, profile={"email": None})
    res = run(db, app.id, FakeBrowser({LEVER + "/apply": page("lever_form.html")}))
    assert res.status == "awaiting_approval"
    miss = pending(client, "missing_profile")[0]
    assert "Email" in miss["message"]
    resolve(client, miss, "edit", "ana.other@example.com")
    b = FakeBrowser({LEVER + "/apply": page("lever_form.html")})
    run(db, app.id, b)
    assert b.typed()['input[name="email"]'] == "ana.other@example.com"
    assert not [a for a in pending(client, "missing_profile")]


def test_required_video_file_is_never_uploaded(client, db):
    url = "https://careers.acme-example.com/apply/video"
    app = make_app(client, db, url)
    b = FakeBrowser({url: page("video_file_form.html")})
    res = run(db, app.id, b)
    assert res.status == "awaiting_approval"
    vf = pending(client, "video_file")[0]
    assert "not supported" in vf["message"] and vf["options"] == [MANUAL_ACK]
    assert not [a for a in b.did("upload") if a[1] == '[id="vid"]']
    resolve(client, vf, "edit", MANUAL_ACK)
    res = run(db, app.id, FakeBrowser({url: page("video_file_form.html")}))
    assert res.status == "blocked" and "video FILE" in res.message


def test_missing_resume_blocks(client, db):
    app = make_app(client, db, LEVER)
    res = run(db, app.id, FakeBrowser({LEVER + "/apply": page("lever_form.html")}), resume=None)
    assert res.status == "blocked" and "resume" in res.message.lower()


def test_visible_captcha_blocks_but_invisible_recaptcha_does_not(client, db):
    url = "https://careers.acme-example.com/apply/captcha"
    app = make_app(client, db, url)
    b = FakeBrowser({url: page("captcha_challenge.html")})
    res = run(db, app.id, b)
    assert res.status == "blocked" and "CAPTCHA" in res.message
    assert not b.did("type") and not b.did("click")
    # Greenhouse fixture loads an INVISIBLE reCAPTCHA → no block
    app2 = make_app(client, db, GH)
    assert run(db, app2.id, gh_browser()).status != "blocked"


def test_agent_run_log_persisted(client, db):
    app = make_app(client, db, LEVER)
    run(db, app.id, FakeBrowser({LEVER + "/apply": page("lever_form.html")}))
    r = db.query(AgentRun).filter_by(application_id=app.id).one()
    assert r.ats == "lever" and r.status == "awaiting_approval" and r.fields_filled >= 4 and r.approvals_requested >= 1
    kinds = [e["kind"] for e in r.events]
    assert kinds[0] == "start" and "fill" in kinds and "approval" in kinds and kinds[-1] == "end"
    detail = client.get(f"/api/applications/{app.id}").json()
    assert detail["last_agent_run"]["id"] == r.id and detail["agent_allowed"] is True


# ------------------------------------------------------------------ strategies & dropdown matching (units)
@pytest.mark.parametrize("url,name", [
    (GH, "greenhouse"), ("https://job-boards.greenhouse.io/acme/jobs/1", "greenhouse"), (LEVER, "lever"), (ASHBY, "ashby"),
    ("https://acme.wd5.myworkdayjobs.com/en-US/careers/job/123", "workday"), ("https://jobs.smartrecruiters.com/Acme/1", "smartrecruiters"),
    ("https://careers.acme-example.com/apply", "generic"),
])
def test_strategy_selection(url, name):
    assert select_strategy(url).name == name


def test_unsupported_ats_requires_manual(client, db):
    app = make_app(client, db, "https://acme.wd5.myworkdayjobs.com/en-US/careers/job/123")
    res = run(db, app.id, FakeBrowser({}))
    assert res.status == "not_allowed" and "Workday" in res.message


@pytest.mark.parametrize("value,options,expected,method", [
    ("United States", ["Select...", "United States of America", "Canada"], "United States of America", "equivalent"),
    ("USA", ["United States", "Mexico"], "United States", "equivalent"),
    ("Full Time", ["Full-time", "Part-time"], "Full-time", "normalized"),
    ("full_time", ["Full-time", "Part-time", "Contractor"], "Full-time", "normalized"),
    ("Colombia", ["Colombia (CO)", "Canada"], "Colombia (CO)", "contains"),
    ("I prefer not to answer", ["Male", "Female", "Decline To Self Identify"], "Decline To Self Identify", "equivalent"),
    ("Yes", ["Yes", "No"], "Yes", "exact"),
])
def test_dropdown_matching(value, options, expected, method):
    m = match_option(value, options)
    assert m.option == expected and m.method == method


def test_dropdown_ambiguous_and_no_match():
    m = match_option("Full Time", ["Full Time - Morning", "Full Time - Evening"])
    assert m.option is None and m.method == "ambiguous" and len(m.candidates) == 2
    assert match_option("Brazil", ["Colombia", "Canada"]).method == "none"
    assert match_option("", ["Yes"]).option is None
