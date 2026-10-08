from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai import get_provider
from app.api.deps import DB, apply_updates, to_dict
from app.services.profile_service import get_profile, profile_completeness, total_experience_years
from app.services.resume_parser import ResumeParseError, extract_text, parse_resume_text
from app.services.settings_service import get_all_settings

router = APIRouter(prefix="/api/profile", tags=["profile"])

# Fields considered "important": imported values are only proposed, never saved without confirmation.
IMPORTABLE = ["full_name", "email", "phone", "location", "linkedin_url", "portfolio_url", "other_urls", "headline",
              "professional_summary", "skills", "tools", "work_experience", "education", "certifications", "languages",
              "projects", "achievements", "industries"]


def profile_out(p) -> dict:
    d = to_dict(p)
    d["completeness"] = profile_completeness(p)
    d["total_experience_years"] = total_experience_years(p)
    return d


@router.get("")
def read_profile(db: Session = DB):
    return profile_out(get_profile(db))


@router.put("")
def update_profile(data: dict[str, Any], db: Session = DB):
    p = get_profile(db)
    apply_updates(p, data)
    db.commit()
    from app.services.jobs_service import rescore_all

    if any(k in data for k in ("skills", "work_experience", "min_salary", "target_salary", "preferred_roles", "languages",
                               "work_arrangements", "education", "certifications", "excluded_industries", "employment_types",
                               "preferred_categories", "target_salary_max", "salary_period", "tools", "country", "location")):
        rescore_all(db)
    return profile_out(p)


@router.post("/import")
async def import_resume(file: UploadFile = File(...), db: Session = DB):
    """Parse a resume and return a PROPOSAL (diff vs current profile). Nothing is saved here."""
    data = await file.read()
    try:
        text = extract_text(data, file.filename or "resume.txt", file.content_type)
    except ResumeParseError as e:
        raise HTTPException(400, str(e)) from e
    settings = get_all_settings(db)
    parsed = parse_resume_text(text, get_provider(settings.get("ai_provider"), settings.get("ai_model") or None))
    return {"proposal": build_proposal(get_profile(db), parsed), "method": parsed.get("_method"), "text_preview": text[:3000]}


def build_proposal(profile, parsed: dict) -> list[dict]:
    out = []
    for f in IMPORTABLE:
        new = parsed.get(f)
        if new in (None, "", [], {}):
            continue
        cur = getattr(profile, f)
        out.append({"field": f, "current": cur, "proposed": new, "changed": cur != new, "is_list": isinstance(new, list)})
    return out


class ApplyImport(BaseModel):
    fields: dict[str, Any]
    merge_lists: bool = True


@router.post("/import/apply")
def apply_import(body: ApplyImport, db: Session = DB):
    """Save only the fields the user confirmed."""
    p = get_profile(db)
    for f, v in body.fields.items():
        if f not in IMPORTABLE:
            continue
        cur = getattr(p, f)
        if body.merge_lists and isinstance(cur, list) and isinstance(v, list):
            merged = list(cur)
            for item in v:
                if item not in merged:
                    merged.append(item)
            setattr(p, f, merged)
        else:
            setattr(p, f, v)
    db.commit()
    from app.services.jobs_service import rescore_all

    rescore_all(db)
    return profile_out(p)
