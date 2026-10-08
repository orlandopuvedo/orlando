import pytest

from app.services.detection import detect_video_requirement
from tests.conftest import SAMPLE_PROFILE, SDR_JOB


@pytest.mark.parametrize("text", [
    "Please record a video introducing yourself.",
    "Submit a video explaining your experience.",
    "Send us a 5 minute video about you.",
    "Include a short video introduction.",
    "This role includes a video interview.",
    "Share a Loom with your answers.",
    "Record yourself answering the questions below.",
    "Tell us about your experience on video.",
])
def test_video_phrases_detected(text):
    assert detect_video_requirement(text).required is True


def test_no_false_positive_for_tool_lists():
    assert detect_video_requirement("Our stack: Slack, Loom, Notion, Figma.").required is False
    assert detect_video_requirement("You will edit marketing videos for YouTube.").required is False


def test_submission_type_detection():
    assert detect_video_requirement("Please upload a video file (mp4) introducing yourself").submission_type == "file"
    assert detect_video_requirement("Complete a one-way video interview on HireVue").submission_type == "platform"
    assert detect_video_requirement("Send a Loom video link").submission_type == "url"


def _add_videos(client):
    ids = {}
    for name, tags in [("General Professional Introduction", ["general", "introduction"]),
                       ("Sales Introduction", ["sales", "sdr"]),
                       ("Operations Introduction", ["operations"]),
                       ("AI/Automation Introduction", ["ai", "automation"])]:
        r = client.post("/api/videos", json={"name": name, "tags": tags, "url": f"https://www.loom.com/share/{'a' * 32}",
                                             "duration_minutes": 5, "is_active": True})
        assert r.status_code == 200
        ids[name] = r.json()["id"]
    return ids


def test_video_library_crud_and_loom_normalization(client):
    r = client.post("/api/videos", json={"name": "Intro", "url": "https://loom.com/share/" + "b" * 32 + "?sid=xyz", "tags": ["general"]})
    v = r.json()
    assert v["platform"] == "loom" and v["url"] == "https://www.loom.com/share/" + "b" * 32
    r = client.put(f"/api/videos/{v['id']}", json={"is_active": False, "transcript": "Hi I'm Ana"})
    assert r.json()["is_active"] is False
    assert client.delete(f"/api/videos/{v['id']}").json()["ok"]


@pytest.mark.parametrize("title,description,expected", [
    ("SDR", "Outbound SDR role. Please submit a 5-minute video.", "Sales Introduction"),
    ("Operations Specialist", "Ops role, record a short video introducing yourself.", "Operations Introduction"),
    ("AI Automation Specialist", "Build Zapier and n8n automations. Send a Loom video.", "AI/Automation Introduction"),
    ("Bookkeeper", "Record a video about your experience.", "General Professional Introduction"),
])
def test_video_recommendation(client, title, description, expected):
    _add_videos(client)
    job = client.post("/api/jobs", json={"title": title, "company": "Co", "description": description + " Remote."}).json()["job"]
    assert job["video_required"] is True
    rec = client.get(f"/api/videos/recommend/{job['id']}").json()["recommendation"]
    assert rec["name"] == expected


def test_package_includes_video_and_approval(client):
    client.put("/api/profile", json=SAMPLE_PROFILE)
    _add_videos(client)
    job = client.post("/api/jobs", json=SDR_JOB).json()["job"]
    app_id = client.post(f"/api/jobs/{job['id']}/application", json={}).json()["application_id"]
    app = client.get(f"/api/applications/{app_id}").json()
    assert app["package"]["video"]["required"] is True
    assert app["package"]["video"]["recommendation"]["name"] == "Sales Introduction"
    kinds = {a["kind"] for a in app["approvals"]}
    assert "video" in kinds
