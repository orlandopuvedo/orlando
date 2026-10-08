from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import get_provider
from app.api.deps import DB, apply_updates, get_or_404, to_dict
from app.config import get_settings
from app.models import Application, Job, Resume, ResumeVersion
from app.services.profile_service import get_profile
from app.services.resume_parser import ResumeParseError, extract_text, parse_resume_text
from app.services.resume_tailor import build_tailored_resume, render_docx, render_text
from app.services.settings_service import get_all_settings

router = APIRouter(prefix="/api", tags=["resumes"])
MAX_UPLOAD = 10 * 1024 * 1024


def resume_out(db: Session, r: Resume) -> dict:
    d = to_dict(r, exclude={"stored_filename"})
    d["version_count"] = len(r.versions)
    d["used_in_applications"] = len(db.scalars(select(Application.id).where(Application.resume_id == r.id)).all())
    return d


@router.get("/resumes")
def list_resumes(db: Session = DB):
    return [resume_out(db, r) for r in db.scalars(select(Resume).order_by(Resume.created_at.desc()))]


@router.post("/resumes")
async def upload_resume(file: UploadFile = File(...), name: str = Form(""), focus: str = Form(""), tags: str = Form(""),
                        is_default: bool = Form(False), db: Session = DB):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File too large (max 10 MB)")
    filename = file.filename or "resume.txt"
    ext = Path(filename).suffix.lower()
    if ext not in {".pdf", ".docx", ".txt", ".md"}:
        raise HTTPException(400, "Use PDF, DOCX or TXT")
    try:
        text = extract_text(data, filename, file.content_type)
    except ResumeParseError as e:
        raise HTTPException(400, str(e)) from e
    stored = f"{uuid.uuid4().hex}{ext}"
    (get_settings().uploads_dir / stored).write_bytes(data)
    settings = get_all_settings(db)
    parsed = parse_resume_text(text, get_provider(settings.get("ai_provider"), settings.get("ai_model") or None))
    if is_default:
        for other in db.scalars(select(Resume)):
            other.is_default = False
    r = Resume(name=name or Path(filename).stem, focus=focus or None, tags=[t.strip() for t in tags.split(",") if t.strip()],
               original_filename=filename, stored_filename=stored, mime_type=file.content_type, file_size=len(data),
               raw_text=text, parsed_data=parsed, is_default=is_default or not db.scalar(select(Resume.id).limit(1)))
    db.add(r)
    db.commit()
    return resume_out(db, r)


@router.get("/resumes/{rid}")
def get_resume(rid: int, db: Session = DB):
    r = get_or_404(db, Resume, rid)
    d = resume_out(db, r)
    d["versions"] = [to_dict(v, exclude={"content", "content_text"}) for v in r.versions]
    return d


@router.put("/resumes/{rid}")
def update_resume(rid: int, data: dict[str, Any], db: Session = DB):
    r = get_or_404(db, Resume, rid)
    if data.get("is_default"):
        for other in db.scalars(select(Resume)):
            other.is_default = False
    apply_updates(r, data, {"name", "description", "focus", "tags", "parsed_data", "is_default"})
    db.commit()
    return resume_out(db, r)


@router.post("/resumes/{rid}/reparse")
def reparse_resume(rid: int, db: Session = DB):
    r = get_or_404(db, Resume, rid)
    settings = get_all_settings(db)
    r.parsed_data = parse_resume_text(r.raw_text or "", get_provider(settings.get("ai_provider"), settings.get("ai_model") or None))
    db.commit()
    return resume_out(db, r)


@router.delete("/resumes/{rid}")
def delete_resume(rid: int, db: Session = DB):
    r = get_or_404(db, Resume, rid)
    if r.stored_filename:
        (get_settings().uploads_dir / r.stored_filename).unlink(missing_ok=True)
    db.delete(r)
    db.commit()
    return {"ok": True}


@router.get("/resumes/{rid}/download")
def download_original(rid: int, db: Session = DB):
    r = get_or_404(db, Resume, rid)
    path = get_settings().uploads_dir / (r.stored_filename or "")
    if not r.stored_filename or not path.exists():
        raise HTTPException(404, "Original file not found")
    return FileResponse(path, filename=r.original_filename or path.name, media_type=r.mime_type or "application/octet-stream")


# ---------------------------------------------------------------- versions (tailored resumes)
@router.get("/resume-versions")
def list_versions(job_id: int | None = None, db: Session = DB):
    q = select(ResumeVersion).order_by(ResumeVersion.created_at.desc())
    if job_id:
        q = q.where(ResumeVersion.job_id == job_id)
    return [to_dict(v, exclude={"content_text"}) for v in db.scalars(q)]


@router.post("/resume-versions")
def create_version(data: dict[str, Any], db: Session = DB):
    """Generate a tailored resume for a job (job_id) or a focus (e.g. 'sales')."""
    settings = get_all_settings(db)
    provider = get_provider(settings.get("ai_provider"), settings.get("ai_model") or None)
    job = db.get(Job, data["job_id"]) if data.get("job_id") else None
    content, warnings, by = build_tailored_resume(get_profile(db), job, focus=data.get("focus"), provider=provider)
    v = ResumeVersion(resume_id=data.get("resume_id"), job_id=job.id if job else None,
                      name=data.get("name") or (f"{job.title} — {job.company or ''}".strip(" —") if job else f"{data.get('focus') or 'General'} resume"),
                      focus=data.get("focus") or (job.category if job else None), content=content, content_text=render_text(content),
                      generated_by=by, warnings=warnings)
    db.add(v)
    db.commit()
    return to_dict(v)


@router.get("/resume-versions/{vid}")
def get_version(vid: int, db: Session = DB):
    return to_dict(get_or_404(db, ResumeVersion, vid))


@router.put("/resume-versions/{vid}")
def update_version(vid: int, data: dict[str, Any], db: Session = DB):
    v = get_or_404(db, ResumeVersion, vid)
    if "content" in data:
        v.content = data["content"]
        v.content_text = render_text(v.content)
        v.generated_by = "edited"
    if "name" in data:
        v.name = data["name"]
    db.commit()
    return to_dict(v)


@router.delete("/resume-versions/{vid}")
def delete_version(vid: int, db: Session = DB):
    db.delete(get_or_404(db, ResumeVersion, vid))
    db.commit()
    return {"ok": True}


@router.get("/resume-versions/{vid}/download")
def download_version(vid: int, format: str = "docx", db: Session = DB):
    v = get_or_404(db, ResumeVersion, vid)
    name = re.sub(r"[^A-Za-z0-9]+", "_", ((v.content or {}).get("header", {}).get("full_name") or "Resume")).strip("_") + "_Resume"
    if format == "docx":
        return Response(render_docx(v.content), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": f'attachment; filename="{name}.docx"'})
    if format == "md":
        return Response(render_text(v.content, markdown=True), media_type="text/markdown",
                        headers={"Content-Disposition": f'attachment; filename="{name}.md"'})
    return Response(render_text(v.content), media_type="text/plain", headers={"Content-Disposition": f'attachment; filename="{name}.txt"'})
