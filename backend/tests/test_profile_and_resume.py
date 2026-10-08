import io

import docx

from tests.conftest import SAMPLE_PROFILE

RESUME_TXT = """MARIA GOMEZ
Customer Support Specialist
maria.gomez@example.com | +52 55 1234 5678 | linkedin.com/in/mariagomez
Guadalajara, Mexico

Summary
Bilingual customer support specialist focused on SaaS.

Experience
Customer Support Specialist | Zeta SaaS | Mar 2020 - Present
• Resolved 60 tickets per day in Zendesk
• Maintained 95% CSAT
Support Agent - Omega Corp - 2018 - 2020
• Handled phone and chat support

Education
Bachelor of Communication, Universidad de Guadalajara, 2017

Skills
Zendesk, Intercom, Customer service, Excel

Languages
Spanish (Native), English (C1)
"""


def test_profile_crud(client):
    r = client.get("/api/profile")
    assert r.status_code == 200
    assert r.json()["min_salary"] is None  # salary is never assumed — the user configures it
    r = client.put("/api/profile", json=SAMPLE_PROFILE)
    body = r.json()
    assert body["full_name"] == "Ana Rivera"
    assert body["total_experience_years"] > 4
    assert body["completeness"]["percent"] >= 80


def test_resume_txt_parsing(client):
    r = client.post("/api/resumes", files={"file": ("maria.txt", RESUME_TXT.encode(), "text/plain")}, data={"name": "Support CV", "tags": "support"})
    assert r.status_code == 200, r.text
    parsed = r.json()["parsed_data"]
    assert parsed["email"] == "maria.gomez@example.com"
    assert parsed["full_name"] == "Maria Gomez"
    assert parsed["location"] == "Guadalajara, Mexico"
    assert "Zendesk" in parsed["skills"]
    titles = [e["title"] for e in parsed["work_experience"]]
    assert "Customer Support Specialist" in titles
    first = parsed["work_experience"][0]
    assert first["company"] == "Zeta SaaS" and first["current"] is True and first["start_date"] == "2020-03"
    assert {"language": "English", "proficiency": "C1"} in parsed["languages"]
    assert r.json()["is_default"] is True


def test_resume_docx_parsing_and_download(client):
    d = docx.Document()
    for line in RESUME_TXT.splitlines():
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    r = client.post("/api/resumes", files={"file": ("maria.docx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    assert r.json()["parsed_data"]["email"] == "maria.gomez@example.com"
    dl = client.get(f"/api/resumes/{rid}/download")
    assert dl.status_code == 200 and dl.content == buf.getvalue()


def test_resume_rejects_unsupported(client):
    r = client.post("/api/resumes", files={"file": ("x.png", b"\x89PNG", "image/png")})
    assert r.status_code == 400


def test_profile_import_requires_confirmation(client):
    client.put("/api/profile", json={"full_name": "Existing Name"})
    r = client.post("/api/profile/import", files={"file": ("cv.txt", RESUME_TXT.encode(), "text/plain")})
    assert r.status_code == 200
    proposal = {p["field"]: p for p in r.json()["proposal"]}
    assert proposal["full_name"]["proposed"] == "Maria Gomez"
    # Nothing saved yet
    assert client.get("/api/profile").json()["full_name"] == "Existing Name"
    # Apply only confirmed fields
    r = client.post("/api/profile/import/apply", json={"fields": {"email": proposal["email"]["proposed"], "skills": proposal["skills"]["proposed"]}})
    p = r.json()
    assert p["email"] == "maria.gomez@example.com"
    assert p["full_name"] == "Existing Name"
    assert "Zendesk" in p["skills"]


def test_tailored_resume_never_invents(client):
    client.put("/api/profile", json=SAMPLE_PROFILE)
    job = client.post("/api/jobs", json={"title": "Operations Specialist", "company": "Delta", "description": "Process improvement with Zapier, Excel and HubSpot. Remote."}).json()["job"]
    v = client.post("/api/resume-versions", json={"job_id": job["id"]}).json()
    content = v["content"]
    companies = {e["company"] for e in content["experience"]}
    assert companies == {"Acme Logistics", "Beta Software"}
    assert content["skills"][0] in {"Process improvement", "Excel", "Zapier", "HubSpot"}  # relevant skills first
    assert set(content["skills"]) <= set(SAMPLE_PROFILE["skills"] + SAMPLE_PROFILE["tools"])
    for fmt in ("docx", "txt", "md"):
        r = client.get(f"/api/resume-versions/{v['id']}/download?format={fmt}")
        assert r.status_code == 200 and len(r.content) > 100
