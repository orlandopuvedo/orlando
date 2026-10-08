"""Notification center helpers."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Notification

TYPES = {"high_match_job", "recruiter_contact", "interview_upcoming", "follow_up_due", "application_blocked",
         "video_required", "approval_required", "offer", "system"}


def notify(db: Session, type: str, title: str, message: str | None = None, link: str | None = None,
           entity_type: str | None = None, entity_id: int | None = None, dedupe_key: str | None = None) -> Notification | None:
    if dedupe_key and db.scalar(select(Notification).where(Notification.dedupe_key == dedupe_key)):
        return None
    n = Notification(type=type, title=title, message=message, link=link, entity_type=entity_type,
                     entity_id=entity_id, dedupe_key=dedupe_key)
    db.add(n)
    db.flush()
    return n
