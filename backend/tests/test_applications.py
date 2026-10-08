import pytest

from app.services.guardrails import check_fabrication
from tests.conftest import SAMPLE_PROFILE, SDR_JOB


def _setup(client, job=SDR_JOB):
    client.put("/api/profile", json=SAMPLE_PROFILE)
    return client.post("/api/jobs", json=job).json()["job"]


def test_application_package_generation(client):
    job = _setup(client, {**SDR_JOB, "application_questions": "Why do you want to work at Gamma?\nWhat are your salary expectations?\nAre you authorized to work in the US?"})
    # Fill one library answer (the user's own words)
    answers = client.get("/api/answers").json()
    why = next(a for a in answers if a["question"].startswith("Why do you want"))
    client.put(f"/api/answers/{why['id']}", json={"answer": "I admire {company}'s product and want to help grow its pipeline as {role}."})
    client.put("/api/settings", json={"cover_letter_policy": "always"})
    app_id = client.post(f"/api/jobs/{job['id']}/application", json={}).json()["application_id"]
    app = client.get(f"/api/applications/{app_id}").json()
    pkg = app["package"]
    assert app["status"] == "READY" and app["job"]["application_status"] == "READY"
    assert pkg["tailored_resume"]["id"] == app["resume_version_id"]
    assert pkg["cover_letter"]["id"] == app["cover_letter_id"]
    cover = next(d for d in app["documents"] if d["kind"] == "cover_letter")
    assert "Ana Rivera" in cover["content"] and "Beta Software" in cover["content"]  # most relevant (SDR) experience
    assert any(d["kind"] == "recruiter_message" for d in app["documents"])
    by_q = {a["question"]: a for a in pkg["screening_answers"]}
    assert "Gamma" in by_q["Why do you want to work at Gamma?"]["answer"]
    assert by_q["What are your salary expectations?"]["kind"] == "salary"
    assert "2,500" in by_q["What are your salary expectations?"]["answer"]
    assert by_q["Are you authorized to work in the US?"]["kind"] == "legal"
    kinds = {a["kind"] for a in app["approvals"]}
    assert {"salary", "legal"} <= kinds
    assert pkg["availability_answer"] == SAMPLE_PROFILE["availability"]
    assert [c["key"] for c in pkg["checklist"]][-1] == "submit"


def test_cover_letter_has_no_fabrication_warnings(client):
    job = _setup(client)
    doc = client.post("/api/documents", json={"job_id": job["id"], "kind": "cover_letter"}).json()
    assert doc["content"]
    assert doc["warnings"] == [], doc["warnings"]
    # Editing in a fabricated claim gets flagged
    edited = client.put(f"/api/documents/{doc['id']}", json={"content": doc["content"] + "\nI hold a PMP certification and grew revenue 300% at Google Cloud."}).json()
    assert edited["edited"] is True
    assert any("300" in w for w in edited["warnings"])
    assert any("certification" in w.lower() or "PMP" in w for w in edited["warnings"])


def test_guardrail_flags_unknown_numbers_and_companies():
    corpus = "Ana Rivera\nOperations Coordinator at Acme Logistics\nReduced processing time by 30%"
    assert check_fabrication("At Acme Logistics I reduced processing time by 30%.", corpus) == []
    w = check_fabrication("At Microsoftt Azure Labs I increased sales by 45%.", corpus)
    assert any("45" in x for x in w) and any("Microsoftt" in x for x in w)


def test_approval_resolution_updates_package(client):
    job = _setup(client, {**SDR_JOB, "application_questions": "What are your salary expectations?"})
    app_id = client.post(f"/api/jobs/{job['id']}/application", json={}).json()["application_id"]
    approvals = client.get("/api/approvals").json()
    salary = next(a for a in approvals if a["kind"] == "salary")
    r = client.post(f"/api/approvals/{salary['id']}/resolve", json={"action": "edit", "value": "USD 3,000/month"})
    assert r.json()["status"] == "EDITED"
    pkg = client.get(f"/api/applications/{app_id}").json()["package"]
    q = next(a for a in pkg["screening_answers"] if a["kind"] == "salary")
    assert q["answer"] == "USD 3,000/month" and q["approved"] is True
    video = next(a for a in client.get("/api/approvals").json() if a["kind"] == "video")
    assert client.post(f"/api/approvals/{video['id']}/resolve", json={"action": "skip"}).json()["status"] == "SKIPPED"
    assert client.post(f"/api/approvals/{video['id']}/resolve", json={"action": "bogus"}).status_code == 422


def test_status_transitions(client):
    job = _setup(client)
    jid = job["id"]
    # Invalid: QUALIFIED → OFFER
    assert client.post(f"/api/jobs/{jid}/status", json={"status": "OFFER"}).status_code == 409
    assert client.post(f"/api/jobs/{jid}/status", json={"status": "READY"}).json()["application_status"] == "READY"
    app_id = client.get(f"/api/jobs/{jid}").json()["application_id"]
    r = client.post(f"/api/applications/{app_id}/mark-applied", json={"application_type": "company_site"}).json()
    assert r["status"] == "APPLIED" and r["applied_at"]
    # Follow-up automatically scheduled after applying
    fus = client.get("/api/followups").json()
    assert any(f["kind"] == "application" for f in fus)
    for s in ("FOLLOW_UP", "INTERVIEW", "OFFER", "HIRED"):
        r = client.post(f"/api/applications/{app_id}/transition", json={"status": s})
        assert r.status_code == 200, (s, r.text)
    app = r.json()
    assert [h["to_status"] for h in app["history"]][-4:] == ["FOLLOW_UP", "INTERVIEW", "OFFER", "HIRED"]
    assert app["response_received_at"]
    # Terminal state
    assert client.post(f"/api/applications/{app_id}/transition", json={"status": "APPLIED"}).status_code == 409
    # Force allows corrections
    assert client.post(f"/api/applications/{app_id}/transition", json={"status": "APPLIED", "force": True}).status_code == 200
    # Pending follow-ups cancelled when hired
    assert not [f for f in client.get("/api/followups").json() if f["application_id"] == app_id]


def test_rejection_counts_as_response_and_cancels_followups(client):
    job = _setup(client)
    app_id = client.post(f"/api/jobs/{job['id']}/application", json={"package": False}).json()["application_id"]
    client.post(f"/api/applications/{app_id}/mark-applied", json={})
    r = client.post(f"/api/applications/{app_id}/transition", json={"status": "REJECTED"}).json()
    assert r["response_received_at"]
    assert client.get("/api/followups?status=CANCELLED").json()


def test_pipeline_board(client):
    _setup(client)
    board = client.get("/api/pipeline").json()
    assert [c["status"] for c in board["columns"]] == ["DISCOVERED", "QUALIFIED", "READY", "APPLYING", "APPLIED", "FOLLOW_UP", "INTERVIEW", "OFFER", "REJECTED"]
    assert board["columns"][1]["count"] == 1


def test_company_limit_warning(client):
    client.put("/api/profile", json=SAMPLE_PROFILE)
    client.put("/api/settings", json={"max_applications_per_company": 1})
    j1 = client.post("/api/jobs", json={**SDR_JOB}).json()["job"]
    a1 = client.post(f"/api/jobs/{j1['id']}/application", json={"package": False}).json()["application_id"]
    client.post(f"/api/applications/{a1}/mark-applied", json={})
    j2 = client.post("/api/jobs", json={"title": "Account Executive", "company": "Gamma Inc", "description": "Remote AE, closing deals with HubSpot."}).json()["job"]
    a2 = client.post(f"/api/jobs/{j2['id']}/application", json={}).json()["application_id"]
    assert any("Gamma" in w for w in client.get(f"/api/applications/{a2}").json()["package"]["warnings"])


@pytest.mark.parametrize("q,kind", [
    ("What are your salary expectations?", "salary"), ("Do you require visa sponsorship?", "legal"),
    ("What is your gender?", "demographic"), ("When can you start?", "availability"), ("Why this company?", "general")])
def test_question_classification(q, kind):
    from app.services.application_engine import classify_question

    assert classify_question(q) == kind
