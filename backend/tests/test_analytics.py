from datetime import datetime, timedelta, timezone

from app.models import Application
from tests.conftest import SAMPLE_PROFILE


def _make(client, title, desc, n, interviews=0, responses=0, offer=False):
    ids = []
    for i in range(n):
        job = client.post("/api/jobs", json={"title": f"{title} {i}", "company": f"{title} Co {i}", "description": desc}).json()["job"]
        app_id = client.post(f"/api/jobs/{job['id']}/application", json={"package": False}).json()["application_id"]
        client.post(f"/api/applications/{app_id}/mark-applied", json={})
        if i < interviews:
            client.post(f"/api/applications/{app_id}/transition", json={"status": "INTERVIEW"})
        elif i < interviews + responses:
            client.post(f"/api/applications/{app_id}/transition", json={"status": "REJECTED"})
        ids.append(app_id)
    if offer:
        client.post(f"/api/applications/{ids[0]}/transition", json={"status": "OFFER"})
        client.put(f"/api/applications/{ids[0]}", json={"offer_amount_monthly_usd": 3200})
    return ids


def test_analytics_and_recommendations(client):
    client.put("/api/profile", json=SAMPLE_PROFILE)
    _make(client, "SDR", "Remote SDR cold calling HubSpot $3,000/month", 10, interviews=4, offer=True)
    _make(client, "Operations Specialist", "Remote operations, Excel, $3,500/month", 6, interviews=2)
    _make(client, "Customer Support Agent", "Remote customer support Zendesk $1,500/month", 15, responses=1)
    a = client.get("/api/analytics").json()
    assert a["totals"]["applications"] == 31
    assert a["totals"]["interviews"] == 6 and a["totals"]["offers"] == 1
    cats = {c["key"]: c for c in a["breakdowns"]["category"]}
    assert cats["sales"]["applications"] == 10 and cats["sales"]["interviews"] == 4
    assert cats["customer_support"]["interviews"] == 0 and cats["customer_support"]["responses"] == 1
    msgs = " ".join(r["message"] for r in a["recommendations"])
    assert "Increase" in msgs and "Sales" in msgs
    assert "Reduce or rethink Customer Support" in msgs
    assert {b["key"] for b in a["breakdowns"]["salary_range"]} >= {"$2.5k–4k", "< $2k"}
    assert sum(d["count"] for d in a["time_series"]["per_day"]) == 31
    for key in ("source", "company", "resume_version", "application_type", "contact_source"):
        assert a["breakdowns"][key]


def test_dashboard_funnel_and_progress(client, db):
    client.put("/api/profile", json=SAMPLE_PROFILE)
    ids = _make(client, "SDR", "Remote SDR HubSpot cold calling $3,000/month", 3, interviews=1, offer=True)
    client.post("/api/contacts", json={"full_name": "R1"})
    d = client.get("/api/dashboard").json()
    m = d["metrics"]
    assert m["jobs_found"] == 3 and m["applications"] == 3 and m["offers"] == 1 and m["contacts"] == 1
    assert [f["stage"] for f in d["funnel"]] == ["Jobs Found", "Qualified", "Applications", "Responses", "Interviews", "Final Interviews", "Offers", "Hired"]
    assert d["salary"]["current_offer_value"] == 3200 and d["salary"]["offer_meets_target"] is True
    assert d["progress"]["stage"] == "Offer received" and d["progress"]["percent"] == 90
    assert d["progress"]["today_applications"] == 3
    assert d["rates"]["offer_rate"] == round(1 / 3, 4)
    # Applications from a previous day are not counted as today
    a = db.get(Application, ids[1])
    a.applied_at = datetime.now(timezone.utc) - timedelta(days=3)
    db.commit()
    assert client.get("/api/dashboard").json()["progress"]["today_applications"] == 2


def test_notifications_center(client):
    client.put("/api/profile", json=SAMPLE_PROFILE)
    client.post("/api/jobs", json={"title": "Sales Development Representative", "company": "Top Co",
                                   "description": "Remote SDR, HubSpot, Salesforce, cold calling, lead generation. 2+ years experience. Fluent English. $4,500/month"})
    n = client.get("/api/notifications").json()
    assert n["unread"] >= 1 and n["items"][0]["type"] == "high_match_job"
    client.post(f"/api/notifications/{n['items'][0]['id']}/read")
    client.post("/api/notifications/read-all")
    assert client.get("/api/notifications").json()["unread"] == 0


def test_settings_roundtrip(client):
    s = client.get("/api/settings").json()
    assert s["settings"]["score_weights"]["salary"] == 20 and s["ai"]["active"] == "none"
    r = client.put("/api/settings", json={"daily_application_target": 25, "scheduler": {"enabled": True, "times": ["09:00"]}}).json()
    assert r["settings"]["daily_application_target"] == 25
    assert r["settings"]["scheduler"]["times"] == ["09:00"] and r["settings"]["scheduler"]["auto_package"] is True
    assert client.put("/api/settings", json={"application_mode": "yolo"}).status_code == 422
