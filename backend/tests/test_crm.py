from datetime import date, datetime, timedelta, timezone

from tests.conftest import SAMPLE_PROFILE, SDR_JOB


def _applied_job(client):
    client.put("/api/profile", json=SAMPLE_PROFILE)
    job = client.post("/api/jobs", json=SDR_JOB).json()["job"]
    app_id = client.post(f"/api/jobs/{job['id']}/application", json={"package": False}).json()["application_id"]
    client.post(f"/api/applications/{app_id}/mark-applied", json={})
    return job, app_id


def test_contact_creation_and_validation(client):
    assert client.post("/api/contacts", json={"full_name": ""}).status_code == 422
    assert client.post("/api/contacts", json={"full_name": "X", "status": "BOGUS"}).status_code == 422
    c = client.post("/api/contacts", json={"full_name": "Laura Smith", "job_title": "Recruiter", "company": "Gamma Inc",
                                           "email": "laura@gamma.io", "linkedin_url": "https://linkedin.com/in/laura",
                                           "contact_source": "LinkedIn", "tags": ["recruiter"], "next_follow_up_date": "2030-01-01"}).json()
    assert c["status"] == "NEW" and c["company_id"]
    assert client.get("/api/contacts?q=laura").json()[0]["id"] == c["id"]
    assert client.put(f"/api/contacts/{c['id']}", json={"notes": "Met at webinar"}).json()["notes"] == "Met at webinar"


def test_contact_timeline_progression(client):
    job, app_id = _applied_job(client)
    c = client.post("/api/contacts", json={"full_name": "Laura Smith", "job_id": job["id"]}).json()
    cid = c["id"]
    assert c["company"] == "Gamma Inc"
    steps = [
        ("profile_view", "Profile viewed", "PROFILE_VIEWED"),
        ("message_received", "Recruiter contacted me", "CONTACTED"),
        ("message_sent", "I replied", "REPLIED"),
        ("screening", "Screening call", "SCREENING"),
        ("interview", "Interview #1", "INTERVIEW_SCHEDULED"),
        ("offer", "Offer", "OFFER"),
    ]
    base = datetime(2026, 10, 8, 10, tzinfo=timezone.utc)
    for i, (typ, summary, expected) in enumerate(steps):
        r = client.post(f"/api/contacts/{cid}/activities", json={"type": typ, "summary": summary, "occurred_at": (base + timedelta(days=i)).isoformat()})
        assert r.status_code == 200, r.text
        assert client.get(f"/api/contacts/{cid}").json()["status"] == expected, typ
    full = client.get(f"/api/contacts/{cid}").json()
    assert [a["summary"] for a in full["activities"]] == [s[1] for s in steps]
    assert full["first_contact_date"] == "2026-10-09" and full["last_contact_date"] == "2026-10-13"
    # Contact activities moved the linked application forward
    app = client.get(f"/api/applications/{app_id}").json()
    assert app["status"] == "OFFER" and app["response_received_at"]
    # Notification for recruiter contact
    types = {n["type"] for n in client.get("/api/notifications").json()["items"]}
    assert "recruiter_contact" in types and "offer" in types
    assert client.post(f"/api/contacts/{cid}/activities", json={"type": "dance"}).status_code == 422


def test_status_never_moves_backwards_automatically(client):
    c = client.post("/api/contacts", json={"full_name": "Bob", "status": "SCREENING"}).json()
    client.post(f"/api/contacts/{c['id']}/activities", json={"type": "message_received"})
    assert client.get(f"/api/contacts/{c['id']}").json()["status"] == "SCREENING"
    client.post(f"/api/contacts/{c['id']}/activities", json={"type": "rejection"})
    assert client.get(f"/api/contacts/{c['id']}").json()["status"] == "REJECTED"


def test_contact_pipeline_drag_and_drop(client):
    c = client.post("/api/contacts", json={"full_name": "Kim"}).json()
    r = client.post(f"/api/contacts/{c['id']}/status", json={"status": "INTERVIEW"})
    assert r.json()["status"] == "INTERVIEW_SCHEDULED"
    cols = {col["column"]: col for col in client.get("/api/contacts/pipeline").json()["columns"]}
    assert [x["id"] for x in cols["INTERVIEW"]["items"]] == [c["id"]]
    assert list(cols)[:8] == ["NEW", "CONTACTED", "REPLIED", "SCREENING", "INTERVIEW", "FINAL", "OFFER", "HIRED"]


def test_profile_views(client):
    r = client.post("/api/profile-views", json={"person_name": "Jane Recruiter", "company": "Acme", "platform": "LinkedIn",
                                                "viewed_on": "2026-10-08", "create_contact": True}).json()
    assert r["contact_id"] and r["source"] == "manual"
    contact = client.get(f"/api/contacts/{r['contact_id']}").json()
    assert contact["status"] == "PROFILE_VIEWED"
    assert contact["activities"][0]["type"] == "profile_view"
    assert len(client.get("/api/profile-views").json()) == 1


def test_interview_tracking_and_completion(client):
    job, app_id = _applied_job(client)
    c = client.post("/api/contacts", json={"full_name": "Laura", "job_id": job["id"]}).json()
    iv = client.post("/api/interviews", json={"job_id": job["id"], "contact_id": c["id"], "interview_type": "video",
                                              "scheduled_at": (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat(),
                                              "meeting_url": "https://zoom.us/j/1"}).json()
    assert iv["interview_number"] == 1 and iv["company"] == "Gamma Inc" and iv["application_id"] == app_id
    assert client.get(f"/api/applications/{app_id}").json()["status"] == "INTERVIEW"
    # Upcoming notification
    client.post("/api/followups/refresh")
    assert any(n["type"] == "interview_upcoming" for n in client.get("/api/notifications").json()["items"])
    iv2 = client.post("/api/interviews", json={"job_id": job["id"], "contact_id": c["id"], "is_final": True}).json()
    assert iv2["interview_number"] == 2
    done = client.post(f"/api/interviews/{iv['id']}/complete", json={"notes": "Went well", "questions_asked": "Tell me about yourself",
                                                                     "answers_lessons": "Be more concise", "next_steps": "Final round"}).json()
    assert done["status"] == "COMPLETED" and done["completed_at"] and done["answers_lessons"] == "Be more concise"
    assert client.get(f"/api/contacts/{c['id']}").json()["status"] == "INTERVIEW_1"
    fus = client.get("/api/followups").json()
    kinds = {f["kind"] for f in fus if f["interview_id"] == iv["id"]}
    assert kinds == {"interview_thank_you", "interview_follow_up"}
    client.post(f"/api/interviews/{iv2['id']}/complete", json={})
    assert client.get(f"/api/contacts/{c['id']}").json()["status"] == "FINAL_INTERVIEW"
    assert client.put(f"/api/interviews/{iv2['id']}", json={"status": "WEIRD"}).status_code == 422


def test_follow_up_lifecycle(client):
    job, app_id = _applied_job(client)
    c = client.post("/api/contacts", json={"full_name": "Laura Smith", "job_id": job["id"]}).json()
    fu = client.post("/api/followups", json={"title": "Ping Laura", "due_date": date.today().isoformat(), "contact_id": c["id"],
                                             "application_id": app_id, "kind": "contact"}).json()
    gen = client.post(f"/api/followups/{fu['id']}/generate").json()
    assert "Laura" in gen["message"] and "Sales Development Representative" in gen["message"]
    post = client.post(f"/api/followups/{fu['id']}/postpone", json={"days": 3}).json()
    assert post["due_date"] == (date.today() + timedelta(days=3)).isoformat() and post["postponed_count"] == 1
    sent = client.post(f"/api/followups/{fu['id']}/sent", json={"channel": "linkedin"}).json()
    assert sent["status"] == "SENT"
    assert client.get(f"/api/contacts/{c['id']}").json()["activities"][-1]["type"] == "follow_up"
    assert client.get(f"/api/applications/{app_id}").json()["status"] == "FOLLOW_UP"


def test_follow_up_recommendations(client, db):
    from app.models import Application

    job, app_id = _applied_job(client)
    # Pretend the application was sent 10 days ago and its auto follow-up deleted
    a = db.get(Application, app_id)
    a.applied_at = datetime.now(timezone.utc) - timedelta(days=10)
    db.commit()
    for f in client.get("/api/followups").json():
        client.delete(f"/api/followups/{f['id']}")
    c = client.post("/api/contacts", json={"full_name": "Silent Sam", "status": "CONTACTED",
                                           "last_contact_date": (date.today() - timedelta(days=9)).isoformat()}).json()
    r = client.post("/api/followups/refresh").json()
    assert r["created"] >= 2
    fus = client.get("/api/followups").json()
    assert any(f["application_id"] == app_id for f in fus)
    assert any(f["contact_id"] == c["id"] and f["kind"] == "contact" for f in fus)
    assert any(n["type"] == "follow_up_due" for n in client.get("/api/notifications").json()["items"])
    # Idempotent
    assert client.post("/api/followups/refresh").json()["created"] == 0
