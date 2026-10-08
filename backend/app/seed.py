"""First-run seed: Video Library placeholders and Answer Library questions (WITHOUT invented answers)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApplicationAnswer, Setting, Video
from app.services.profile_service import get_profile
from app.sources.registry import sync_sources

VIDEOS = [
    ("General Professional Introduction", ["general", "experience", "introduction", "remote work", "professional"]),
    ("Sales Introduction", ["sales", "sdr", "bdr", "business development"]),
    ("Operations Introduction", ["operations", "ops", "project management", "virtual assistant"]),
    ("Customer Support Introduction", ["customer support", "customer service", "customer success"]),
    ("AI/Automation Introduction", ["ai", "automation", "no-code"]),
]

QUESTIONS = [
    ("Tell us about yourself.", "general", ["general", "introduction"], False),
    ("Why do you want to work here?", "motivation", ["motivation"], False),
    ("Why are you interested in this role?", "motivation", ["motivation"], False),
    ("What are your salary expectations?", "salary", ["salary"], True),
    ("What is your availability / when can you start?", "availability", ["availability"], False),
    ("Describe your experience working remotely.", "remote", ["remote work"], False),
    ("Why should we hire you?", "general", ["general"], False),
    ("Describe your most relevant experience for this role.", "experience", ["experience"], False),
    ("Are you legally authorized to work in this country? Will you require sponsorship?", "legal", ["legal", "work authorization"], True),
]


def seed(db: Session) -> None:
    get_profile(db)
    sync_sources(db)
    if db.get(Setting, "_seeded"):
        return
    if not db.scalar(select(Video.id).limit(1)):
        for name, tags in VIDEOS:
            db.add(Video(name=name, platform="loom", url=None, duration_seconds=300, tags=tags, is_active=False, meta={},
                         description="Add your Loom URL and activate this video."))
    if not db.scalar(select(ApplicationAnswer.id).limit(1)):
        for q, cat, tags, approval in QUESTIONS:
            # Answers intentionally left empty: only YOU can write truthful answers.
            db.add(ApplicationAnswer(question=q, answer="", category=cat, tags=tags, requires_approval=approval))
    db.add(Setting(key="_seeded", value=True))
    db.commit()
