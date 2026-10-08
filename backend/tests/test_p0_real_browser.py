"""Integration: the REAL Playwright agent (headless Chromium) against local HTML pages served over HTTP.

This verifies the real DOM plumbing (element tagging, hidden inputs, selects, radios, checkboxes, file upload,
multi-step navigation, same-origin iframes, form submission + confirmation). It does NOT prove compatibility
with live ATS websites. Skipped automatically when Playwright/Chromium is unavailable.
"""
import functools
import http.server
import os
import shutil
import threading
from pathlib import Path

import pytest

from app.browser.supervisor import CHECK_YES, run_supervised
from app.config import get_settings
from app.models import Application
from tests.conftest import SAMPLE_PROFILE

pw = pytest.importorskip("playwright.sync_api")
CHROMIUM = os.environ.get("BROWSER_EXECUTABLE_PATH") or ("/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None)
pytestmark = pytest.mark.skipif(CHROMIUM is None and shutil.which("chromium") is None, reason="no Chromium available")
FX = Path(__file__).parent / "fixtures" / "realbrowser"


@pytest.fixture(scope="module")
def server():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FX))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture
def agent_factory(tmp_path):
    from app.browser.playwright_agent import PlaywrightBrowserAgent

    s = get_settings()
    old = (s.browser_executable_path, s.browser_user_data_dir)
    s.browser_executable_path, s.browser_user_data_dir = CHROMIUM, tmp_path / "profile"
    yield lambda: PlaywrightBrowserAgent(headless=True)
    s.browser_executable_path, s.browser_user_data_dir = old


def _app(client, db, url, company="Acme"):
    client.put("/api/profile", json=SAMPLE_PROFILE)
    job = client.post("/api/jobs", json={"title": "SDR", "company": company, "description": "Remote SDR, HubSpot. $3,000/month",
                                         "apply_url": url, "source_url": url}).json()["job"]
    return client.post(f"/api/jobs/{job['id']}/application", json={"mode": "supervised"}).json()["application_id"]


def _answer_all(client):
    for a in client.get("/api/approvals").json():
        if a["options"]:
            v = CHECK_YES if CHECK_YES in a["options"] else a["options"][0]
            client.post(f"/api/approvals/{a['id']}/resolve", json={"action": "edit", "value": v})
        else:
            client.post(f"/api/approvals/{a['id']}/resolve", json={"action": "approve" if a["proposed_value"] else "edit",
                                                                 "value": a["proposed_value"] or "x"})


def _drive(client, db, app_id, agent_factory, resume):
    statuses = []
    for _ in range(5):
        db.expire_all()
        res = run_supervised(db, db.get(Application, app_id), agent_factory(), resume_file=str(resume))
        db.commit()
        statuses.append(res.status)
        if res.status in ("submitted", "submitted_unconfirmed", "blocked", "error", "not_allowed"):
            return res, statuses
        _answer_all(client)
    return res, statuses


def test_real_browser_single_page(server, client, db, agent_factory, tmp_path):
    resume = tmp_path / "cv.docx"
    resume.write_bytes(b"fake docx")
    app_id = _app(client, db, f"{server}/apply.html")
    res, statuses = _drive(client, db, app_id, agent_factory, resume)
    assert statuses[0] == "awaiting_approval" and "ready_to_submit" in statuses, (statuses, res.message)
    assert res.status == "submitted", res.message
    db.expire_all()
    a = db.get(Application, app_id)
    assert a.status == "APPLIED" and a.confirmation_id == "REF-9931" and "confirmation.html" in a.final_url
    assert "first_name=Ana" in a.final_url and "consent=on" in a.final_url and "hours=y" in a.final_url
    assert "country=Colombia" in a.final_url and "trap=&" in a.final_url + "&"  # hidden trap field left empty


def test_real_browser_multistep_and_iframe(server, client, db, agent_factory, tmp_path):
    resume = tmp_path / "cv.docx"
    resume.write_bytes(b"fake docx")
    app_id = _app(client, db, f"{server}/step1.html")
    res, statuses = _drive(client, db, app_id, agent_factory, resume)
    assert res.status == "submitted", (statuses, res.message)
    app2 = _app(client, db, f"{server}/embed.html", company="Embedded Co")  # distinct job (same title+company would dedupe)
    res, statuses = _drive(client, db, app2, agent_factory, resume)
    assert res.status == "submitted", (statuses, res.message)
    db.expire_all()
    run = db.get(Application, app2)
    assert run.confirmation_id == "REF-9931"
