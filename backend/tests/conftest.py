import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="jobhunter-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'test.db'}"
os.environ["DATA_DIR"] = str(_tmp / "data")
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["AI_PROVIDER"] = "none"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["GOOGLE_API_KEY"] = ""
os.environ["APP_USERNAME"] = ""
os.environ["APP_PASSWORD"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app, run_migrations  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    run_migrations()
    yield


@pytest.fixture(autouse=True)
def _clean_db():
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
        conn.execute(text("PRAGMA foreign_keys=ON"))
    from app.sources.base import JobSourceAdapter

    JobSourceAdapter._last_call.clear()
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


SAMPLE_PROFILE = {
    "full_name": "Ana Rivera",
    "email": "ana@example.com",
    "location": "Medellín, Colombia",
    "country": "Colombia",
    "headline": "Operations & Sales Specialist",
    "professional_summary": "Operations and B2B sales professional who builds efficient processes and CRM pipelines.",
    "skills": ["HubSpot", "Salesforce", "Lead generation", "Cold calling", "Process improvement", "Excel", "Zapier", "Customer service"],
    "tools": ["Notion", "Google Sheets"],
    "work_experience": [
        {"title": "Operations Coordinator", "company": "Acme Logistics", "start_date": "2021-01", "end_date": None, "current": True,
         "description": "Coordinated order operations and process improvement for a logistics company.",
         "highlights": ["Reduced order processing time by 30%", "Built Zapier automations between HubSpot and Google Sheets"], "skills": []},
        {"title": "Sales Development Representative", "company": "Beta Software", "start_date": "2018-06", "end_date": "2020-12",
         "current": False, "description": "Outbound prospecting and cold calling for B2B SaaS.",
         "highlights": ["Booked 40 qualified meetings per month", "Managed Salesforce pipeline"], "skills": []},
    ],
    "education": [{"institution": "Universidad de Antioquia", "degree": "Bachelor of Business Administration", "end_date": "2018"}],
    "languages": [{"language": "Spanish", "proficiency": "Native"}, {"language": "English", "proficiency": "C1"}],
    "preferred_roles": ["SDR", "Operations Specialist", "Sales Development Representative"],
    "work_arrangements": ["remote"],
    "employment_types": ["full_time", "contract"],
    "min_salary": 2000, "target_salary": 2500, "target_salary_max": 4000, "salary_period": "month", "salary_currency": "USD",
    "availability": "I can start within two weeks.",
    "work_authorization": "Colombian citizen; I work as an independent contractor for foreign companies.",
}

SDR_JOB = {
    "title": "Sales Development Representative (Remote)",
    "company": "Gamma Inc",
    "source_url": "https://jobs.example.com/gamma/sdr-123?utm_source=linkedin",
    "location": "Remote - LATAM",
    "description": (
        "We are hiring a remote SDR. You will do outbound prospecting, cold calling and lead generation using HubSpot and Salesforce. "
        "Requirements: 2+ years of B2B sales experience. Fluent English required. Salary: $2,500 - $3,500 per month. "
        "Please submit a 5-minute video introducing yourself (Loom link is fine)."
    ),
    "employment_type": "full_time",
}
