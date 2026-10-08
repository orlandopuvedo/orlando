"""P0 scheduler (timezone, next/last run, one safe catch-up) and AI provider health / visible fallback."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.ai.base import AIProvider, AIProviderError
from app.services import generation as gen
from app.services.scheduler import JobHuntScheduler, due_slot, next_run

BOG = ZoneInfo("America/Bogota")
CFG = {"enabled": True, "times": ["08:00", "12:00", "18:00"], "timezone": "America/Bogota", "catch_up": True}


def at(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=BOG)


def test_disabled_and_first_activation_never_run_past_slots():
    assert due_slot(at(2026, 10, 8, 12, 0), {**CFG, "enabled": False}, at(2026, 10, 8, 7)) == (None, False)
    assert due_slot(at(2026, 10, 8, 12, 0), CFG, None) == (None, False)


def test_slot_fires_on_time_in_configured_timezone():
    slot, catch = due_slot(at(2026, 10, 8, 12, 0, ), CFG, at(2026, 10, 8, 11, 0))
    assert slot == at(2026, 10, 8, 12, 0) and catch is False
    # 12:00 Bogotá == 17:00 UTC
    slot, _ = due_slot(datetime(2026, 10, 8, 17, 0, 30, tzinfo=timezone.utc), CFG, datetime(2026, 10, 8, 16, 0, tzinfo=timezone.utc))
    assert slot == at(2026, 10, 8, 12, 0)
    assert due_slot(at(2026, 10, 8, 12, 30), CFG, at(2026, 10, 8, 12, 1)) == (None, False)  # already fired


def test_multiple_missed_slots_give_exactly_one_catch_up():
    # Server was off from 07:00 to 19:30: 08:00, 12:00 and 18:00 were missed → ONE catch-up for 18:00
    slot, catch = due_slot(at(2026, 10, 8, 19, 30), CFG, at(2026, 10, 8, 7, 0))
    assert slot == at(2026, 10, 8, 18, 0) and catch is True
    assert due_slot(at(2026, 10, 8, 19, 30), {**CFG, "catch_up": False}, at(2026, 10, 8, 7, 0)) == (None, False)
    # After the catch-up fired (last_fired=19:30) nothing else runs until the next slot
    assert due_slot(at(2026, 10, 8, 19, 31), CFG, at(2026, 10, 8, 19, 30)) == (None, False)


def test_catch_up_limited_to_last_24h():
    slot, catch = due_slot(at(2026, 10, 10, 9, 0), CFG, at(2026, 10, 1, 7, 0))
    assert slot == at(2026, 10, 10, 8, 0) and catch  # only the latest slot inside the window, once


def test_next_run():
    assert next_run(at(2026, 10, 8, 12, 30), CFG) == at(2026, 10, 8, 18, 0)
    assert next_run(at(2026, 10, 8, 19, 0), CFG) == at(2026, 10, 9, 8, 0)
    assert next_run(at(2026, 10, 8, 19, 0), {**CFG, "enabled": False}) is None


def test_tick_persists_state_and_runs_once(client, monkeypatch):
    client.put("/api/settings", json={"scheduler": CFG})
    s = JobHuntScheduler()
    fired = []
    monkeypatch.setattr(s, "run_now", lambda trigger="manual", run_id=None: fired.append(trigger))
    assert s.tick(at(2026, 10, 8, 7, 0)) is None                    # first activation → baseline only
    assert s.tick(at(2026, 10, 8, 19, 30)) == "catch_up"            # 3 missed slots → one catch-up
    assert s.tick(at(2026, 10, 8, 19, 31)) is None
    assert s.tick(datetime(2026, 10, 9, 13, 0, 10, tzinfo=timezone.utc)) == "scheduled"  # 08:00 Bogotá
    assert fired == ["catch_up", "scheduled"]
    st = client.get("/api/automation/status").json()
    assert st["enabled"] and st["timezone"] == "America/Bogota" and st["next_run"] and "backend process" in st["note"]
    client.put("/api/settings", json={"scheduler": {**CFG, "enabled": False}})
    assert s.tick(at(2026, 10, 12, 9, 0)) is None and fired == ["catch_up", "scheduled"]
    client.put("/api/settings", json={"scheduler": CFG})
    assert s.tick(at(2026, 10, 12, 9, 0)) is None  # re-enabled: new baseline, no stale catch-up


class Failing(AIProvider):
    name = "fake"

    def __init__(self):
        super().__init__("m")

    def is_available(self):
        return True

    def complete(self, system, prompt, max_tokens=2000):
        raise AIProviderError("401 invalid x-api-key")


def test_ai_failure_is_visible_and_template_used(client, db):
    from app.ai.registry import AI_STATUS
    from app.models import Job
    from app.services.profile_service import get_profile
    from tests.conftest import SAMPLE_PROFILE, SDR_JOB

    client.put("/api/profile", json=SAMPLE_PROFILE)
    jid = client.post("/api/jobs", json=SDR_JOB).json()["job"]["id"]
    g = gen.generate_cover_letter(get_profile(db), db.get(Job, jid), Failing())
    assert g.text and g.generated_by == "template (AI fallback)"
    assert g.warnings[0].startswith("AI provider failed (401 invalid x-api-key)")
    assert AI_STATUS["last_error"] == "401 invalid x-api-key"
    assert client.get("/api/settings/ai-status").json()["last"]["last_error"] == "401 invalid x-api-key"


def test_ai_test_endpoint_without_key(client):
    r = client.post("/api/settings/ai-test").json()
    assert r["ok"] is False and "API key" in r["error"]
