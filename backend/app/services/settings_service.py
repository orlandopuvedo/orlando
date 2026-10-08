"""Typed, DB-backed application settings with defaults."""
from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm import Session

from app.models import Setting

DEFAULT_SCORE_WEIGHTS = {
    "salary": 20, "skills": 20, "experience": 15, "role_relevance": 15, "remote_location": 10,
    "education_certifications": 5, "language": 5, "seniority": 5, "application_difficulty": 5,
}

DEFAULT_PRIORITY_WEIGHTS = {
    "match": 35, "salary": 15, "recency": 10, "ease": 10, "competition": 5, "contact": 5,
    "video_readiness": 5, "tailored_resume": 5, "quick_apply": 5, "historical_success": 5,
}

DEFAULTS: dict[str, Any] = {
    "min_match_score": 60,
    "queue_min_score": 70,
    "package_min_score": 80,
    "preferred_categories": [],
    "excluded_categories": [],
    "remote_preference": ["remote"],
    "employment_types": ["full_time", "contract"],
    "application_mode": "copilot",  # copilot | supervised | auto
    "daily_application_target": 15,
    "max_applications_per_company": 2,
    "max_applications_per_source_per_day": 40,
    "auto_apply_permissions": {},  # source_key -> bool (only honoured where automation is allowed)
    "follow_up": {
        "after_application_days": 7,
        "thank_you_after_interview_days": 1,
        "after_interview_days": 3,
        "contact_no_reply_days": 5,
    },
    "cover_letter_policy": "when_required",  # when_required | when_useful | always | never
    "ai_provider": "auto",
    "ai_model": "",
    "scheduler": {"enabled": False, "times": ["08:00", "12:00", "18:00"], "auto_package": True},
    "score_weights": DEFAULT_SCORE_WEIGHTS,
    "priority_weights": DEFAULT_PRIORITY_WEIGHTS,
    "usd_rates": {},
    "notify_min_match_score": 85,
    "company_boards": {"greenhouse": [], "lever": [], "ashby": []},
}


def get_setting(db: Session, key: str) -> Any:
    row = db.get(Setting, key)
    default = copy.deepcopy(DEFAULTS.get(key))
    if row is None:
        return default
    if isinstance(default, dict) and isinstance(row.value, dict):
        merged = default
        merged.update(row.value)
        return merged
    return row.value


def get_all_settings(db: Session) -> dict[str, Any]:
    return {k: get_setting(db, k) for k in DEFAULTS}


def set_setting(db: Session, key: str, value: Any) -> None:
    if key not in DEFAULTS:
        raise KeyError(f"Unknown setting: {key}")
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
    db.flush()


def update_settings(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    for k, v in values.items():
        if k in DEFAULTS:
            set_setting(db, k, v)
    db.commit()
    return get_all_settings(db)
