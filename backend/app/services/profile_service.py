"""Master Profile access + derived facts used by matching and generation."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models import UserProfile

LIST_FIELDS = [
    "other_urls", "skills", "work_experience", "education", "certifications", "languages", "tools", "industries",
    "achievements", "projects", "work_arrangements", "employment_types", "preferred_roles", "preferred_categories",
    "preferred_industries", "excluded_industries", "preferred_schedules",
]


def get_profile(db: Session) -> UserProfile:
    profile = db.get(UserProfile, 1)
    if profile is None:
        profile = UserProfile(id=1, salary_currency="USD", salary_period="month", min_salary=2000,
                              target_salary=2500, target_salary_max=4000, work_arrangements=["remote"],
                              employment_types=["full_time", "contract"])
        for f in LIST_FIELDS:
            if getattr(profile, f) is None:
                setattr(profile, f, [])
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def _parse_ym(value: str | None) -> date | None:
    if not value:
        return None
    v = str(value).strip().lower()
    if v in {"present", "current", "now", "actual", "presente"}:
        return date.today()
    import re

    m = re.match(r"(\d{4})(?:[-/](\d{1,2}))?", v)
    if m:
        return date(int(m.group(1)), int(m.group(2) or 1), 1)
    m = re.match(r"(\d{1,2})[-/](\d{4})", v)
    if m:
        return date(int(m.group(2)), int(m.group(1)), 1)
    return None


def total_experience_years(profile: UserProfile) -> float:
    """Total non-overlapping years across work experience entries."""
    spans = []
    for exp in profile.work_experience or []:
        start = _parse_ym(exp.get("start_date"))
        end = date.today() if exp.get("current") else _parse_ym(exp.get("end_date")) or None
        if start and not end:
            end = start
        if start and end and end >= start:
            spans.append((start, end))
    if not spans:
        return 0.0
    spans.sort()
    merged = [list(spans[0])]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    days = sum((e - s).days for s, e in merged)
    return round(days / 365.25, 1)


def experience_years_for_keywords(profile: UserProfile, keywords: list[str]) -> float:
    from app.services.text_utils import contains_term, normalize_text

    total = 0.0
    for exp in profile.work_experience or []:
        blob = normalize_text(" ".join([exp.get("title") or "", exp.get("description") or "", " ".join(exp.get("highlights") or [])]))
        if any(contains_term(blob, k) for k in keywords):
            start = _parse_ym(exp.get("start_date"))
            end = date.today() if exp.get("current") else _parse_ym(exp.get("end_date"))
            if start and end and end >= start:
                total += (end - start).days / 365.25
    return round(total, 1)


def profile_skill_terms(profile: UserProfile) -> list[str]:
    terms: list[str] = []
    for item in (profile.skills or []) + (profile.tools or []):
        name = item.get("name") if isinstance(item, dict) else item
        if name and str(name).strip():
            terms.append(str(name).strip())
    for exp in profile.work_experience or []:
        for s in exp.get("skills") or []:
            terms.append(str(s))
    return list(dict.fromkeys(terms))


def profile_languages(profile: UserProfile) -> list[str]:
    out = []
    for lang in profile.languages or []:
        name = lang.get("language") if isinstance(lang, dict) else lang
        if name:
            out.append(str(name).lower().strip())
    return out


def profile_completeness(profile: UserProfile) -> dict:
    checks = {
        "full_name": bool(profile.full_name), "email": bool(profile.email),
        "summary": bool(profile.professional_summary), "skills": len(profile.skills or []) >= 5,
        "work_experience": len(profile.work_experience or []) >= 1, "languages": bool(profile.languages),
        "salary": bool(profile.min_salary), "preferred_roles": bool(profile.preferred_roles),
        "work_authorization": bool(profile.work_authorization), "linkedin": bool(profile.linkedin_url),
    }
    done = sum(checks.values())
    return {"percent": round(100 * done / len(checks)), "checks": checks}


def profile_fact_corpus(profile: UserProfile) -> str:
    """Every string the user has stated about themselves (used by the fabrication guard)."""
    parts: list[str] = []

    def walk(v):
        if v is None:
            return
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        else:
            parts.append(str(v))

    for col in UserProfile.__table__.columns.keys():
        walk(getattr(profile, col))
    return "\n".join(parts)
