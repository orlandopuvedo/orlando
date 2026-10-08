"""P0 hard search filters: user constraints are enforced BEFORE scoring/queueing and a high score never overrides them."""
from tests.conftest import SAMPLE_PROFILE

ANNUAL = {**SAMPLE_PROFILE, "min_salary": 80000, "target_salary": 120000, "target_salary_max": None, "max_salary": None,
          "salary_period": "year", "salary_currency": "USD"}
STRONG = ("Remote Sales Development Representative. Outbound prospecting, cold calling and lead generation with HubSpot and "
          "Salesforce. 2+ years of B2B sales experience. Fluent English.")


def job(client, title="Sales Development Representative", company="Acme", desc=STRONG, **kw):
    return client.post("/api/jobs", json={"title": title, "company": company, "description": desc, **kw}).json()["job"]


def test_salary_minimum_rejects_even_high_scoring_job(client):
    client.put("/api/profile", json=ANNUAL)
    low = job(client, desc=STRONG + " Salary: $45,000 per year.")
    assert low["filter_status"] == "rejected" and any("below your minimum" in r for r in low["filter_reasons"])
    assert low["in_queue"] is False and low["application_status"] == "DISCOVERED"
    ok = job(client, company="Beta", desc=STRONG + " Salary: $90,000 - $130,000 per year.")
    assert ok["filter_status"] == "passed" and ok["in_queue"] is True and ok["application_status"] == "QUALIFIED"
    queue_ids = [j["id"] for j in client.get("/api/queue").json()]
    assert ok["id"] in queue_ids and low["id"] not in queue_ids


def test_the_80k_vs_40k_example(client):
    client.put("/api/profile", json=ANNUAL)
    j = job(client, desc=STRONG + " Compensation: $40,000/year.")
    assert j["filter_status"] == "rejected"
    assert j["id"] not in [x["id"] for x in client.get("/api/queue").json()]


def test_salary_maximum_and_no_maximum(client):
    client.put("/api/profile", json={**ANNUAL, "max_salary": 100000})
    high = job(client, desc=STRONG + " $150,000 - $200,000 per year.")
    assert high["filter_status"] == "rejected" and any("maximum" in r for r in high["filter_reasons"])
    client.put("/api/profile", json={**ANNUAL, "max_salary": None})  # "no limit"
    assert client.get(f"/api/jobs/{high['id']}").json()["filter_status"] == "passed"


def test_salary_periods_and_currency_normalized(client):
    client.put("/api/profile", json={**SAMPLE_PROFILE, "min_salary": 40, "target_salary": 50, "salary_period": "hour", "salary_currency": "USD"})
    monthly = job(client, desc=STRONG + " Pay: $5,000 per month.")  # $40/h ≈ $6,400/mo
    assert monthly["filter_status"] == "rejected"
    eur = job(client, company="Euro Co", desc=STRONG + " Salary: €7,000 per month.")  # ≈ $7,560/mo
    assert eur["filter_status"] == "passed"


def test_unknown_salary_policy(client):
    client.put("/api/profile", json=ANNUAL)
    j = job(client)  # no salary published
    assert j["filter_status"] == "passed" and "Note: Salary not published." in j["filter_reasons"]
    client.put("/api/settings", json={"job_search": {"salary_unknown_policy": "review"}})
    j = client.get(f"/api/jobs/{j['id']}").json()
    assert j["filter_status"] == "review" and j["in_queue"] is False
    client.put("/api/settings", json={"job_search": {"salary_unknown_policy": "reject"}})
    assert client.get(f"/api/jobs/{j['id']}").json()["filter_status"] == "rejected"


def test_location_arrangement_type_seniority_company_keywords(client):
    client.put("/api/profile", json={**SAMPLE_PROFILE, "employment_types": ["full_time"]})
    client.put("/api/settings", json={"job_search": {"locations": ["Colombia", "LATAM"], "seniority": ["junior", "mid", "senior"],
                                                     "excluded_companies": ["Evil Corp"], "required_keywords": ["HubSpot"],
                                                     "optional_keywords": ["SaaS"]}})
    us_only = job(client, desc=STRONG + " This role is US only.")
    assert any("Restricted to candidates in US" in r for r in us_only["filter_reasons"])
    latam = job(client, company="Latam Co", desc=STRONG + " Open to candidates in LATAM. B2B SaaS.")
    assert latam["filter_status"] == "passed" and any("SaaS" in r for r in latam["match_reasons"])
    onsite = job(client, company="Office Co", desc=STRONG, remote_type="onsite", location="Miami, FL")
    assert onsite["filter_status"] == "rejected"
    contract = job(client, company="Gig Co", desc=STRONG, employment_type="contract")
    assert any("Employment type" in r for r in contract["filter_reasons"])
    director = job(client, title="Director of Sales Development", company="Big Co")
    assert any("Seniority" in r for r in director["filter_reasons"])
    evil = job(client, company="Evil Corp Inc.")
    assert any("excluded" in r for r in evil["filter_reasons"])
    no_kw = job(client, company="Other Co", desc="Remote SDR role with Salesforce, cold calling. Fluent English.")
    assert any("required keyword" in r for r in no_kw["filter_reasons"])
    client.put("/api/settings", json={"excluded_categories": ["sales"]})
    assert client.get(f"/api/jobs/{latam['id']}").json()["filter_status"] == "rejected"


def test_no_hardcoded_salary(client):
    p = client.get("/api/profile").json()
    assert p["min_salary"] is None and p["target_salary"] is None and p["max_salary"] is None
    j = job(client, desc=STRONG + " Salary: $500 per month.")
    assert j["filter_status"] == "passed"  # without a configured minimum, nothing is assumed
    d = client.get("/api/dashboard").json()
    assert d["salary"]["monthly_target"] is None
