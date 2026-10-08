"""Video Library + Application Answer Library."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DB, apply_updates, get_or_404, to_dict
from app.models import ApplicationAnswer, Job, Video
from app.services.application_engine import find_best_answer
from app.services.loom import detect_platform, fetch_loom_metadata, is_loom_url, normalize_loom_url
from app.services.video_matching import recommend_video

router = APIRouter(prefix="/api", tags=["library"])


def _clean_video(data: dict) -> dict:
    data = dict(data)
    if data.get("url"):
        if is_loom_url(data["url"]):
            data["url"] = normalize_loom_url(data["url"])
        data.setdefault("platform", detect_platform(data["url"]))
    if isinstance(data.get("date_created"), str) and data["date_created"]:
        data["date_created"] = date.fromisoformat(data["date_created"][:10])
    if data.get("duration_minutes") is not None and data.get("duration_seconds") is None:
        data["duration_seconds"] = int(float(data["duration_minutes"]) * 60)
    return data


@router.get("/videos")
def list_videos(db: Session = DB):
    return [to_dict(v) for v in db.scalars(select(Video).order_by(Video.is_active.desc(), Video.name))]


@router.post("/videos")
def create_video(data: dict[str, Any], db: Session = DB):
    v = Video(name=data.get("name") or "Untitled video", tags=[], meta={})
    apply_updates(v, _clean_video(data))
    if v.date_created is None:
        v.date_created = date.today()
    db.add(v)
    db.commit()
    return to_dict(v)


@router.put("/videos/{vid}")
def update_video(vid: int, data: dict[str, Any], db: Session = DB):
    v = get_or_404(db, Video, vid)
    apply_updates(v, _clean_video(data))
    db.commit()
    return to_dict(v)


@router.delete("/videos/{vid}")
def delete_video(vid: int, db: Session = DB):
    db.delete(get_or_404(db, Video, vid))
    db.commit()
    return {"ok": True}


@router.get("/videos/recommend/{job_id}")
def recommend_for_job(job_id: int, db: Session = DB):
    job = get_or_404(db, Job, job_id)
    videos = db.scalars(select(Video).where(Video.is_active.is_(True))).all()
    return {"video_required": job.video_required, "details": job.video_details, "recommendation": recommend_video(job, videos)}


@router.post("/videos/loom-metadata")
def loom_metadata(data: dict[str, Any]):
    return fetch_loom_metadata(data.get("url", ""))


# ---------------------------------------------------------------- answers
@router.get("/answers")
def list_answers(db: Session = DB):
    return [to_dict(a) for a in db.scalars(select(ApplicationAnswer).order_by(ApplicationAnswer.category, ApplicationAnswer.id))]


@router.post("/answers")
def create_answer(data: dict[str, Any], db: Session = DB):
    a = ApplicationAnswer(question=data.get("question", ""), answer=data.get("answer", ""), tags=data.get("tags") or [])
    apply_updates(a, data)
    db.add(a)
    db.commit()
    return to_dict(a)


@router.put("/answers/{aid}")
def update_answer(aid: int, data: dict[str, Any], db: Session = DB):
    a = get_or_404(db, ApplicationAnswer, aid)
    apply_updates(a, data)
    db.commit()
    return to_dict(a)


@router.delete("/answers/{aid}")
def delete_answer(aid: int, db: Session = DB):
    db.delete(get_or_404(db, ApplicationAnswer, aid))
    db.commit()
    return {"ok": True}


@router.post("/answers/suggest")
def suggest_answer(data: dict[str, Any], db: Session = DB):
    job = db.get(Job, data["job_id"]) if data.get("job_id") else None
    answers = [a for a in db.scalars(select(ApplicationAnswer)) if a.answer.strip()]
    best = find_best_answer(data.get("question", ""), answers, job)
    return {"answer": to_dict(best) if best else None}
