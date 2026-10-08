from app.services.dedupe import compare_jobs
from app.services.normalization import normalize_job
from app.services.salary import parse_salary, to_monthly_usd
from app.services.scoring import classify
from app.services.text_utils import canonical_url
from tests.conftest import SAMPLE_PROFILE, SDR_JOB


def test_salary_parsing():
    s = parse_salary("Compensation: $2,500 - $4,000 per month")
    assert (s.min, s.max, s.currency, s.period) == (2500, 4000, "USD", "month")
    s = parse_salary("Pay: $60-80k annually")
    assert (s.min, s.max, s.period) == (60000, 80000, "year")
    s = parse_salary("€3000/month")
    assert s.currency == "EUR" and s.period == "month"
    assert parse_salary("3-5 years of experience") is None
    assert to_monthly_usd(60000, "USD", "year") == 5000
    assert to_monthly_usd(20, "USD", "hour") == 3200


def test_normalization():
    nj = normalize_job({**SDR_JOB, "description": "<p>" + SDR_JOB["description"] + "</p>"})
    assert nj.remote_type == "remote"
    assert nj.category == "sales"
    assert nj.salary_monthly_usd_min == 2500 and nj.salary_monthly_usd_max == 3500
    assert nj.video_required is True
    assert nj.video_details["duration_minutes"] == 5
    assert nj.canonical_url == "https://jobs.example.com/gamma/sdr-123"
    assert "<p>" not in nj.description
    assert nj.employment_type == "full_time"


def test_canonical_url_variants():
    assert canonical_url("https://www.linkedin.com/jobs/view/sdr-at-gamma-3812345678/?trk=abc") == "https://linkedin.com/jobs/view/3812345678"
    assert canonical_url("https://www.indeed.com/viewjob?jk=abc123&from=serp") == "https://indeed.com/viewjob?jk=abc123"


def test_duplicate_detection_across_sources(client):
    r1 = client.post("/api/jobs", json={**SDR_JOB, "source": "manual"}).json()
    assert r1["created"] is True
    # Same job from another board: different URL, same company/title/description
    r2 = client.post("/api/jobs", json={**SDR_JOB, "source_url": "https://remotive.com/remote-jobs/sales/sdr-999", "source": "remotive",
                                        "company": "Gamma, Inc.", "title": "Sales Development Representative"}).json()
    assert r2["created"] is False
    assert r2["job"]["id"] == r1["job"]["id"]
    assert {ref["source"] for ref in r2["job"]["refs"]} == {"manual", "remotive"}
    # Same canonical URL with tracking params
    r3 = client.post("/api/jobs", json={"title": "Whatever", "source_url": "https://jobs.example.com/gamma/sdr-123?utm_campaign=x"}).json()
    assert r3["created"] is False and r3["duplicate_reason"] == "canonical_url"
    # Different job at same company is NOT a duplicate
    r4 = client.post("/api/jobs", json={"title": "Head of Finance", "company": "Gamma Inc", "description": "Lead the finance team, CPA required."}).json()
    assert r4["created"] is True
    assert client.get("/api/jobs").json()["total"] == 2


def test_compare_jobs_description_similarity():
    a = normalize_job({"title": "Support Agent", "company": "Foo LLC", "description": "Answer customer tickets in Zendesk, handle chat and email support for our SaaS product across time zones."})
    b = normalize_job({"title": "Support Agent", "company": "Foo", "description": "Answer customer tickets in Zendesk, handle chat and email support for our SaaS product across time zones. Apply now!"})
    c = normalize_job({"title": "Support Agent", "company": "Foo", "description": "Night shift warehouse picker and packer, forklift license required, onsite in Texas."})
    assert compare_jobs(a, b)[0] is True
    assert compare_jobs(a, c)[0] is False


def test_job_scoring_strong_match(client):
    client.put("/api/profile", json=SAMPLE_PROFILE)
    job = client.post("/api/jobs", json=SDR_JOB).json()["job"]
    assert job["match_score"] >= 80, job["score_breakdown"]
    assert job["classification"] in ("STRONG", "EXCELLENT")
    comps = job["score_breakdown"]["components"]
    assert set(comps) == {"salary", "skills", "experience", "role_relevance", "remote_location", "education_certifications",
                          "language", "seniority", "application_difficulty"}
    assert job["match_reasons"] and isinstance(job["concerns"], list)
    assert job["application_status"] == "QUALIFIED" and job["in_queue"] is True
    assert job["priority_score"] > 0


def test_job_scoring_dealbreakers(client):
    client.put("/api/profile", json=SAMPLE_PROFILE)
    low = client.post("/api/jobs", json={**SDR_JOB, "source_url": None, "title": "SDR", "company": "Cheap Co",
                                         "description": "Remote SDR, HubSpot. Pay: $800 per month."}).json()["job"]
    assert low["match_score"] <= 55 and low["classification"] == "SKIP"
    assert any("below your" in c for c in low["concerns"])
    onsite = client.post("/api/jobs", json={"title": "Sales Development Representative", "company": "Office Co",
                                            "description": "On-site in our Miami office. HubSpot, cold calling. $4,000/month",
                                            "remote_type": "onsite"}).json()["job"]
    assert onsite["match_score"] <= 50


def test_custom_weights_change_score(client):
    client.put("/api/profile", json=SAMPLE_PROFILE)
    job = client.post("/api/jobs", json={"title": "Operations Specialist", "company": "NoSalary", "description": "Remote operations role with Excel."}).json()["job"]
    before = job["match_score"]
    weights = {k: 0 for k in job["score_breakdown"]["weights"]}
    weights["salary"] = 100  # salary unknown → 50
    client.put("/api/settings", json={"score_weights": weights})
    after = client.get(f"/api/jobs/{job['id']}").json()["match_score"]
    assert after == 50 and before != after


def test_classification_thresholds():
    assert [classify(s) for s in (95, 85, 75, 65, 30)] == ["EXCELLENT", "STRONG", "GOOD", "MAYBE", "SKIP"]


def test_apply_queue_sorted_by_priority(client):
    client.put("/api/profile", json=SAMPLE_PROFILE)
    client.post("/api/jobs", json=SDR_JOB)
    client.post("/api/jobs", json={"title": "Operations Specialist", "company": "Ops Co", "description": "Remote. Process improvement, Excel, Zapier, HubSpot. 3+ years experience. $3,800/month. Fluent English."})
    q = client.get("/api/queue").json()
    assert len(q) >= 1
    prios = [j["priority_score"] for j in q]
    assert prios == sorted(prios, reverse=True)


def test_job_update_and_rescore(client):
    client.put("/api/profile", json=SAMPLE_PROFILE)
    job = client.post("/api/jobs", json={"title": "SDR", "company": "X", "description": "Remote SDR with HubSpot."}).json()["job"]
    assert job["salary_monthly_usd_max"] is None
    upd = client.put(f"/api/jobs/{job['id']}", json={"description": "Remote SDR with HubSpot. Salary $3,000 - $4,000 per month."}).json()
    assert upd["salary_monthly_usd_max"] == 4000
