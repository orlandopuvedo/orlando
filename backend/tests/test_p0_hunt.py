"""P0 job discovery: explicit outcomes (never a silent 0), source failure isolation, source health, and the full
DISCOVER → NORMALIZE → DEDUPE → FILTER → SCORE → QUEUE → PACKAGE pipeline through real adapter code + mocked HTTP."""
import httpx

from app.models import JobSearchRun, JobSource
from app.services.job_hunt import run_job_hunt_cycle
from app.sources.base import JobSourceAdapter


def reset_rate_limits():
    JobSourceAdapter._last_call.clear()
from app.sources.public_boards import RemotiveAdapter
from tests.conftest import SAMPLE_PROFILE

DESC = ("<p>Remote SDR: outbound prospecting, cold calling and lead generation with HubSpot and Salesforce. "
        "2+ years of B2B sales experience. Fluent English.</p>")
REMOTIVE_PAYLOAD = {"0-legal-notice": "Remotive API ...", "job-count": 3, "jobs": [
    {"id": 1001, "url": "https://remotive.com/remote-jobs/sales/sdr-1001", "title": "Sales Development Representative",
     "company_name": "Alpha", "category": "Sales", "job_type": "full_time", "publication_date": "2026-10-07T10:00:00",
     "candidate_required_location": "LATAM", "salary": "$3,500 - $4,500 per month", "description": DESC},
    {"id": 1002, "url": "https://remotive.com/remote-jobs/sales/sdr-1002", "title": "Sales Development Representative",
     "company_name": "Cheap Co", "category": "Sales", "job_type": "full_time", "publication_date": "2026-10-07T10:00:00",
     "candidate_required_location": "Worldwide", "salary": "$900 per month", "description": DESC},
    {"id": 1003, "url": "https://remotive.com/remote-jobs/support/1003", "title": "Night Warehouse Picker",
     "company_name": "Box Co", "category": "Other", "job_type": "full_time", "publication_date": "2026-10-07T10:00:00",
     "candidate_required_location": "USA only", "salary": "", "description": "<p>Onsite warehouse, forklift.</p>"},
]}


def remotive(payload=REMOTIVE_PAYLOAD, status=200):
    def handler(req):
        assert req.url.host == "remotive.com" and req.url.path == "/api/remote-jobs"
        return httpx.Response(status, json=payload)
    return RemotiveAdapter(httpx.Client(transport=httpx.MockTransport(handler)))


class Broken(JobSourceAdapter):
    key, name, automation_status = "himalayas", "Himalayas", "allowed"

    def search_jobs(self, q):
        raise httpx.ConnectError("connection refused")


def setup(client):
    client.put("/api/profile", json={**SAMPLE_PROFILE, "preferred_roles": ["SDR"]})
    client.get("/api/sources")


def test_no_sources_enabled_is_explicit(client, db):
    setup(client)
    run = run_job_hunt_cycle(db)
    assert run.outcome == "no_sources_enabled" and "Enable at least one source" in run.message
    assert run.status == "completed" and run.stats["found"] == 0


def test_full_pipeline_with_filters(client, db):
    setup(client)
    run = run_job_hunt_cycle(db, adapters={"remotive": remotive()}, source_keys=["remotive"])
    s = run.stats
    assert run.outcome == "ok" and run.status == "completed", run.message
    assert s["sources_checked"] == 1 and s["found"] == 3 and s["new"] == 3
    assert s["rejected_by_filters"] == 2 and s["filter_reasons"]["salary"] == 1
    assert s["qualified"] == 1 and s["queued"] == 1 and s["packaged"] == 1
    q = client.get("/api/queue").json()
    assert [j["company"] for j in q] == ["Alpha"] and q[0]["application_status"] == "READY"
    src = db.query(JobSource).filter_by(key="remotive").one()
    assert src.last_status == "ok" and src.last_found_count == 3 and src.last_error is None
    # Remotive's terms: max ~1 search/hour → an immediate second run is skipped and SAYS so (not "0 jobs")
    run_rl = run_job_hunt_cycle(db, adapters={"remotive": remotive()}, source_keys=["remotive"])
    assert run_rl.outcome == "rate_limited" and "terms" in run_rl.message
    # Later (rate limit elapsed): same listings → only duplicates, explicitly reported
    reset_rate_limits()
    run2 = run_job_hunt_cycle(db, adapters={"remotive": remotive()}, source_keys=["remotive"])
    assert run2.outcome == "only_duplicates" and run2.stats["duplicates"] == 3


def test_source_failure_isolated_and_recorded(client, db):
    setup(client)
    run = run_job_hunt_cycle(db, adapters={"remotive": remotive(), "himalayas": Broken()}, source_keys=["remotive", "himalayas"])
    assert run.status == "completed_with_errors" and run.outcome == "ok"
    assert run.stats["sources_failed"] == 1 and "connection refused" in run.stats["sources"]["himalayas"]["error"]
    src = db.query(JobSource).filter_by(key="himalayas").one()
    assert src.last_status == "error" and "connection refused" in src.last_error
    sources = {s["key"]: s for s in client.get("/api/sources").json()}
    assert sources["himalayas"]["last_status"] == "error"


def test_all_sources_failed(client, db):
    setup(client)
    run = run_job_hunt_cycle(db, adapters={"himalayas": Broken()}, source_keys=["himalayas"])
    assert run.outcome == "all_sources_failed" and run.status == "failed"


def test_schema_change_reported_not_silent(client, db):
    setup(client)
    run = run_job_hunt_cycle(db, adapters={"remotive": remotive({"error": "rate limited"})}, source_keys=["remotive"])
    assert run.outcome == "all_sources_failed"
    assert "API format may have changed" in run.stats["sources"]["remotive"]["error"]


def test_zero_results_and_no_matching(client, db):
    setup(client)
    run = run_job_hunt_cycle(db, adapters={"remotive": remotive({"jobs": []})}, source_keys=["remotive"])
    assert run.outcome == "no_results" and "returned no listings" in run.message
    reset_rate_limits()
    only_bad = {"jobs": [REMOTIVE_PAYLOAD["jobs"][1]]}
    run = run_job_hunt_cycle(db, adapters={"remotive": remotive(only_bad)}, source_keys=["remotive"])
    assert run.outcome == "no_matching_jobs" and run.stats["rejected_by_filters"] == 1


def test_company_boards_without_config_are_reported(client, db):
    setup(client)
    from app.sources.public_boards import GreenhouseAdapter

    run = run_job_hunt_cycle(db, adapters={"greenhouse": GreenhouseAdapter()}, source_keys=["greenhouse"])
    assert "no company boards configured" in run.stats["sources"]["greenhouse"]["error"]


def test_run_endpoint_tracks_run(client, db):
    setup(client)
    r = client.post("/api/automation/run").json()
    run = client.get(f"/api/automation/runs/{r['run_id']}").json()  # background task finished within the request cycle
    assert run["status"] == "completed" and run["outcome"] == "no_sources_enabled" and run["message"]
    assert db.query(JobSearchRun).count() == 1


def test_manual_add_job_still_works_independently(client):
    setup(client)
    r = client.post("/api/jobs", json={"title": "SDR", "company": "Manual Co", "description": DESC}).json()
    assert r["created"] and r["job"]["filter_status"] in ("passed", "review")
