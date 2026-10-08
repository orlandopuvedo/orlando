from app.ai.base import AIProvider, NullProvider, extract_json
from app.ai.registry import get_provider, provider_status
from app.services import generation as gen
from app.services.resume_parser import parse_resume_text


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, reply):
        super().__init__("fake-1")
        self.reply = reply
        self.prompts = []

    def is_available(self):
        return True

    def complete(self, system, prompt, max_tokens=2000):
        self.prompts.append((system, prompt))
        return self.reply


def test_no_provider_falls_back():
    assert isinstance(get_provider("none"), NullProvider)
    assert get_provider("auto").name == "none"  # no keys in test env
    st = provider_status()
    assert st["available"] is False and "anthropic" in st["providers"]


def test_extract_json():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! {"b": [1,2]} done') == {"b": [1, 2]}


def test_ai_output_passes_through_guardrails(client):
    from app.services.profile_service import get_profile
    from app.db import SessionLocal
    from tests.conftest import SAMPLE_PROFILE, SDR_JOB

    client.put("/api/profile", json=SAMPLE_PROFILE)
    job_id = client.post("/api/jobs", json=SDR_JOB).json()["job"]["id"]
    db = SessionLocal()
    from app.models import Job

    job = db.get(Job, job_id)
    p = FakeProvider("I led a team of 25 at Initech and hold an MBA.")
    g = gen.generate_cover_letter(get_profile(db), job, p)
    assert g.generated_by == "fake:fake-1"
    assert any("25" in w for w in g.warnings) and any("Initech" in w for w in g.warnings)
    system = p.prompts[0][0]
    assert "Never invent" in system
    # NEEDS_USER_INPUT → empty answer with warning
    g = gen.personalize_answer("What's your favourite colour?", None, get_profile(db), job, FakeProvider("NEEDS_USER_INPUT"))
    assert g.text == "" and g.warnings
    db.close()


def test_ai_resume_parse_used_when_available():
    p = FakeProvider('{"full_name": "Ana", "skills": ["Excel"]}')
    out = parse_resume_text("Ana\nSkills\nExcel", p)
    assert out["full_name"] == "Ana" and out["_method"] == "ai:fake:fake-1"
    out = parse_resume_text("Ana Lopez\nSkills\nExcel", None)
    assert out["_method"] == "heuristic"
