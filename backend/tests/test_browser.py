from app.browser import detectors
from app.browser.base import BrowserAgent
from app.browser.supervisor import run_supervised
from app.models import Application
from tests.conftest import SAMPLE_PROFILE

FORM = """<html><head><title>Apply</title></head><body><form>
<label for="fn">First name</label><input id="fn" name="first_name" required>
<label for="ln">Last name</label><input id="ln" name="last_name" required>
<label for="em">Email</label><input id="em" type="email" name="email" required>
<label for="li">LinkedIn profile</label><input id="li" name="linkedin">
<label for="cv">Resume/CV</label><input id="cv" type="file" name="resume">
<label for="sal">What are your salary expectations?</label><input id="sal" name="salary" required>
<label for="why">Why do you want to work here?</label><textarea id="why" name="why"></textarea>
<label for="g">Gender</label><select id="g" name="gender"><option>Female</option><option>Male</option><option>Decline to self-identify</option></select>
<button type="submit">Submit application</button></form></body></html>"""

CAPTCHA = '<html><body><div class="g-recaptcha" data-sitekey="x"></div><form><input name="email"></form></body></html>'
LOGIN = '<html><body><h1>Sign in to apply</h1><form><input name="u"><input type="password" name="p"></form></body></html>'
TWOFA = '<html><body><p>Enter the code we sent to your phone</p><input autocomplete="one-time-code" name="otp"></body></html>'


class FakeAgent(BrowserAgent):
    def __init__(self, html: str, after_submit: str = "<html><body>Thanks!</body></html>"):
        self.html, self.after, self.actions, self.closed = html, after_submit, [], False

    def open_page(self, url):
        self.actions.append(("open", url))

    def navigate(self, url):
        self.open_page(url)

    def page_html(self):
        return self.html

    def current_url(self):
        return "https://boards.greenhouse.io/acme/jobs/1"

    def click(self, selector):
        self.actions.append(("click", selector))
        self.html = self.after

    def type(self, selector, text):
        self.actions.append(("type", selector, text))

    def select(self, selector, value):
        self.actions.append(("select", selector, value))

    def upload_file(self, selector, path):
        self.actions.append(("upload", selector, path))

    def close(self):
        self.closed = True


def test_detectors():
    assert detectors.detect_captcha(CAPTCHA) and not detectors.detect_captcha(FORM)
    assert detectors.detect_login(LOGIN) and not detectors.detect_login(FORM)
    assert detectors.detect_2fa(TWOFA) and not detectors.detect_2fa(FORM)
    assert detectors.detect_video("<p>Please record a 3 minute video introducing yourself</p>")
    fields = detectors.extract_fields(FORM)
    labels = [f["label"] for f in fields]
    assert labels[:3] == ["First name", "Last name", "Email"]
    assert any(f["type"] == "file" for f in fields)
    assert next(f for f in fields if f["name"] == "gender")["options"][-1] == "Decline to self-identify"
    assert detectors.find_submit(FORM) == "button"


def _app(client, db, mode="supervised", apply_url="https://boards.greenhouse.io/acme/jobs/1"):
    client.put("/api/profile", json=SAMPLE_PROFILE)
    job = client.post("/api/jobs", json={"title": "SDR", "company": "Acme", "description": "Remote SDR, HubSpot. $3,000/month",
                                         "apply_url": apply_url, "source_url": apply_url}).json()["job"]
    app_id = client.post(f"/api/jobs/{job['id']}/application", json={"mode": mode}).json()["application_id"]
    return db.get(Application, app_id)


def test_supervised_stops_on_captcha(client, db):
    app = _app(client, db)
    agent = FakeAgent(CAPTCHA)
    res = run_supervised(db, app, agent)
    assert res.status == "blocked" and "CAPTCHA" in res.message
    assert not [a for a in agent.actions if a[0] in ("type", "click")]
    assert agent.closed
    db.commit()
    assert any(n["type"] == "application_blocked" for n in client.get("/api/notifications").json()["items"])
    assert client.get(f"/api/applications/{app.id}").json()["status"] == "READY"


def test_supervised_stops_on_login_and_2fa(client, db):
    app = _app(client, db)
    assert run_supervised(db, app, FakeAgent(LOGIN)).status == "blocked"
    assert run_supervised(db, app, FakeAgent(TWOFA)).status == "blocked"


def test_copilot_and_manual_only_sites_not_automated(client, db):
    app = _app(client, db, mode="copilot")
    assert run_supervised(db, app, FakeAgent(FORM)).status == "not_allowed"
    app2 = _app(client, db, mode="supervised", apply_url="https://www.linkedin.com/jobs/view/123456789")
    assert run_supervised(db, app2, FakeAgent(FORM)).status == "not_allowed"


def test_auto_mode_requires_explicit_permission(client, db):
    app = _app(client, db, mode="auto")
    res = run_supervised(db, app, FakeAgent(FORM))
    assert res.status == "not_allowed" and "AUTO" in res.message


def test_supervised_full_flow_with_approvals(client, db):
    app = _app(client, db)
    # 1st run: fills safe fields, asks approval for salary + gender + uncertain textarea, does NOT submit
    agent = FakeAgent(FORM)
    res = run_supervised(db, app, agent, resume_file="/tmp/cv.docx")
    db.commit()
    assert res.status == "awaiting_approval"
    typed = {a[1]: a[2] for a in agent.actions if a[0] == "type"}
    assert typed["#fn"] == "Ana" and typed["#ln"] == "Rivera" and typed["#em"] == "ana@example.com"
    assert ("upload", "#cv", "/tmp/cv.docx") in agent.actions
    assert not any(a[0] == "click" for a in agent.actions)
    pending = client.get("/api/approvals").json()
    kinds = {p["kind"] for p in pending}
    assert {"salary", "demographic"} <= kinds
    for p in pending:
        client.post(f"/api/approvals/{p['id']}/resolve", json={"action": "approve" if p["proposed_value"] else "edit",
                                                                 "value": p["proposed_value"] or "Because I love the product."})
    # 2nd run: everything approved except final submission
    db.expire_all()
    res = run_supervised(db, db.get(Application, app.id), FakeAgent(FORM))
    db.commit()
    assert res.status == "ready_to_submit"
    final = next(p for p in client.get("/api/approvals").json() if p["kind"] == "final_submit")
    client.post(f"/api/approvals/{final['id']}/resolve", json={"action": "approve"})
    # 3rd run: submits
    db.expire_all()
    agent = FakeAgent(FORM)
    res = run_supervised(db, db.get(Application, app.id), agent)
    db.commit()
    assert res.status == "submitted"
    assert ("click", "button") in agent.actions
    assert client.get(f"/api/applications/{app.id}").json()["status"] == "APPLIED"
