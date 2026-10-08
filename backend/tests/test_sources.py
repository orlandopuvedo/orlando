import json

import httpx
import pytest

from app.services.url_import import UrlImportError, import_from_url, parse_jsonld_jobposting
from app.sources.base import SearchQuery, SourceNotSupported
from app.sources.public_boards import (
    GreenhouseAdapter, HimalayasAdapter, LeverAdapter, RemoteOKAdapter, RemotiveAdapter, WeWorkRemotelyAdapter, parse_wwr_rss,
)
from app.sources.registry import all_adapters
from tests.conftest import SAMPLE_PROFILE

REMOTIVE = {"jobs": [{"id": 101, "url": "https://remotive.com/remote-jobs/sales/sdr-101", "title": "SDR", "company_name": "Acme",
                      "category": "Sales", "job_type": "full_time", "publication_date": "2026-10-07T10:00:00",
                      "candidate_required_location": "Worldwide", "salary": "$2,500 - $3,500 per month",
                      "description": "<p>Remote SDR using HubSpot.</p>"}]}
REMOTEOK = [{"legal": "notice"}, {"id": "55", "position": "Operations Manager", "company": "Ops Inc", "url": "https://remoteok.com/remote-jobs/55",
                                  "apply_url": "https://ops.example/apply", "description": "Remote ops", "location": "Worldwide",
                                  "salary_min": 50000, "salary_max": 70000, "date": "2026-10-06T00:00:00+00:00", "tags": ["operations"]}]
HIMALAYAS = {"jobs": [{"title": "Customer Support Specialist", "companyName": "Help Co", "applicationLink": "https://himalayas.app/companies/help/jobs/1",
                       "guid": "hc-1", "description": "Support via Zendesk", "employmentType": "Full Time", "pubDate": 1791374400,
                       "minSalary": 30000, "maxSalary": 40000, "currency": "USD", "locationRestrictions": ["Mexico"], "categories": ["Support"]}]}
WWR = """<?xml version="1.0"?><rss><channel><item><title>Zeta: Executive Assistant</title><link>https://weworkremotely.com/remote-jobs/zeta-ea</link>
<guid>wwr-1</guid><pubDate>Tue, 06 Oct 2026 10:00:00 +0000</pubDate><region>Anywhere in the World</region><type>Full-Time</type>
<description>&lt;p&gt;Support our CEO&lt;/p&gt;</description></item></channel></rss>"""
GREENHOUSE = {"jobs": [{"id": 9, "title": "Revenue Operations Specialist", "absolute_url": "https://boards.greenhouse.io/acme/jobs/9",
                        "location": {"name": "Remote"}, "updated_at": "2026-10-05T00:00:00Z", "content": "&lt;p&gt;RevOps with HubSpot&lt;/p&gt;"}]}
LEVER = [{"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "text": "SDR", "hostedUrl": "https://jobs.lever.co/acme/aaaa", "applyUrl": "https://jobs.lever.co/acme/aaaa/apply",
          "categories": {"commitment": "Full-time", "location": "Remote"}, "descriptionPlain": "Outbound SDR", "workplaceType": "remote",
          "createdAt": 1791374400000, "salaryRange": {"min": 40000, "max": 60000, "currency": "USD", "interval": "per-year-salary"}}]


def mock_client(routes: dict) -> httpx.Client:
    def handler(request: httpx.Request):
        for frag, payload in routes.items():
            if frag in str(request.url):
                if isinstance(payload, str):
                    return httpx.Response(200, text=payload)
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_adapters_have_automation_status():
    for key, a in all_adapters().items():
        assert a.automation_status in ("allowed", "review_required", "manual_only", "unknown"), key
    adapters = all_adapters()
    for k in ("linkedin", "indeed", "wellfound", "flexjobs"):
        assert adapters[k].automation_status == "manual_only"
        with pytest.raises(SourceNotSupported):
            adapters[k].search_jobs(SearchQuery())


def test_remotive_adapter():
    a = RemotiveAdapter(mock_client({"remotive.com/api": REMOTIVE}))
    raws = a.search_jobs(SearchQuery(query="sdr"))
    nj = a.normalize_job(raws[0])
    assert nj.source == "remotive" and nj.job_id_external == "101" and nj.salary_monthly_usd_max == 3500
    assert nj.remote_type == "remote" and nj.employment_type == "full_time"
    with pytest.raises(SourceNotSupported):  # ToS-requested rate limit
        a.search_jobs(SearchQuery())


def test_remoteok_skips_legal_notice():
    raws = RemoteOKAdapter(mock_client({"remoteok.com/api": REMOTEOK})).search_jobs(SearchQuery())
    assert len(raws) == 1
    nj = RemoteOKAdapter().normalize_job(raws[0])
    assert nj.salary_monthly_usd_min == pytest.approx(4166.67, 0.01) and nj.apply_url == "https://ops.example/apply"


def test_himalayas_and_wwr_and_ats():
    h = HimalayasAdapter(mock_client({"himalayas.app/jobs/api": HIMALAYAS})).search_jobs(SearchQuery(limit=5))
    assert h[0]["company"] == "Help Co"
    assert parse_wwr_rss(WWR)[0]["company"] == "Zeta"
    g = GreenhouseAdapter(mock_client({"boards-api.greenhouse.io": GREENHOUSE})).search_jobs(SearchQuery(config={"boards": ["acme"]}))
    nj = GreenhouseAdapter().normalize_job(g[0])
    assert nj.job_id_external == "acme:9" and "<p>" not in nj.description
    lv = LeverAdapter(mock_client({"api.lever.co": LEVER})).search_jobs(SearchQuery(config={"boards": ["acme"]}))
    nj = LeverAdapter().normalize_job(lv[0])
    assert nj.remote_type == "remote" and nj.salary_period == "year"
    assert WeWorkRemotelyAdapter().automation_status == "allowed"


def test_job_hunt_cycle(client, db):
    from app.services.job_hunt import run_job_hunt_cycle
    from app.sources.base import JobSourceAdapter

    class FakeAdapter(JobSourceAdapter):
        key, name, automation_status = "remotive", "Fake Remotive", "allowed"

        def search_jobs(self, q):
            return [
                {"title": "Sales Development Representative", "company": "Alpha", "source_url": "https://x.io/1", "job_id_external": "1",
                 "description": "Remote SDR. HubSpot, Salesforce, cold calling, lead generation. 2+ years experience. Fluent English. $3,800/month. Submit a 5-minute video."},
                {"title": "Sales Development Representative", "company": "Alpha Inc.", "source_url": "https://x.io/1-copy", "job_id_external": "1b",
                 "description": "Remote SDR. HubSpot, Salesforce, cold calling, lead generation. 2+ years experience. Fluent English. $3,800/month. Submit a 5-minute video."},
                {"title": "Forklift Operator", "company": "Beta", "source_url": "https://x.io/2", "job_id_external": "2",
                 "description": "Onsite warehouse role, $1,200/month", "remote_type": "onsite"},
            ]

    class Broken(JobSourceAdapter):
        key, name, automation_status = "himalayas", "Broken", "allowed"

        def search_jobs(self, q):
            raise httpx.ConnectError("boom")

    client.put("/api/profile", json=SAMPLE_PROFILE)
    client.post("/api/videos", json={"name": "Sales Introduction", "tags": ["sales"], "url": "https://www.loom.com/share/" + "c" * 32, "is_active": True})
    run = run_job_hunt_cycle(db, adapters={"remotive": FakeAdapter(), "himalayas": Broken()}, source_keys=["remotive", "himalayas"])
    s = run.stats
    assert s["found"] == 3 and s["new"] == 2 and s["duplicates"] == 1 and s["errors"] == 1
    assert s["qualified"] == 1 and s["queued"] == 1 and s["packaged"] == 1 and s["video_required"] == 1
    assert run.status == "completed_with_errors"
    queue = client.get("/api/queue").json()
    assert queue[0]["company"] == "Alpha" and queue[0]["application_status"] == "READY"
    app = client.get(f"/api/applications/{queue[0]['application_id']}").json()
    assert app["package"]["video"]["recommendation"]["name"] == "Sales Introduction"


def test_manual_source_cannot_be_enabled(client):
    client.get("/api/sources")
    assert client.put("/api/sources/linkedin", json={"enabled": True}).status_code == 409
    assert client.put("/api/sources/remotive", json={"enabled": True}).json()["enabled"] is True


def test_url_import_rules():
    with pytest.raises(UrlImportError):
        import_from_url("https://www.linkedin.com/jobs/view/123456789")
    html = '<html><script type="application/ld+json">' + json.dumps({
        "@type": "JobPosting", "title": "Ops Analyst", "hiringOrganization": {"name": "Kappa"}, "description": "<p>Remote ops</p>",
        "jobLocationType": "TELECOMMUTE", "baseSalary": {"currency": "USD", "value": {"minValue": 3000, "maxValue": 4000, "unitText": "MONTH"}},
        "datePosted": "2026-10-01"}) + "</script></html>"
    raw = parse_jsonld_jobposting(html)
    assert raw["company"] == "Kappa" and raw["remote_type"] == "remote" and raw["salary_period"] == "month"
    raw, src = import_from_url("https://careers.kappa.io/jobs/1", client=mock_client({"careers.kappa.io": html}))
    assert src == "manual" and raw["title"] == "Ops Analyst"
