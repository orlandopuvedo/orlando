"""Normalize raw job data (from any source / manual entry) into the canonical job schema."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from app.services import detection as det
from app.services.salary import parse_salary, to_monthly_usd
from app.services.text_utils import canonical_url, html_to_text


@dataclass
class NormalizedJob:
    title: str
    company: str | None = None
    company_url: str | None = None
    source: str = "manual"
    source_url: str | None = None
    canonical_url: str | None = None
    apply_url: str | None = None
    description: str | None = None
    requirements: str | None = None
    application_questions: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    salary_monthly_usd_min: float | None = None
    salary_monthly_usd_max: float | None = None
    location: str | None = None
    remote_type: str = "unknown"
    employment_type: str | None = None
    category: str | None = None
    seniority: str | None = None
    posted_at: datetime | None = None
    job_id_external: str | None = None
    applicants_count: int | None = None
    easy_apply: bool = False
    video_required: bool = False
    video_details: dict = field(default_factory=dict)
    detected_requirements: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("raw", None)
        return d


def parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1e12:  # ms
            v /= 1000
        return datetime.fromtimestamp(v, tz=timezone.utc)
    s = str(value).strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(s)
    except (TypeError, ValueError):
        return None


def _num(v: Any) -> float | None:
    if v in (None, "", 0, "0"):
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def normalize_job(data: dict[str, Any], source: str = "manual", usd_rates: dict | None = None) -> NormalizedJob:
    """Accepts loosely-structured dicts (adapter output or manual form) and returns a NormalizedJob."""
    title = (data.get("title") or "").strip() or "Untitled role"
    description = data.get("description") or ""
    if "<" in description and ">" in description:
        description = html_to_text(description)
    requirements = html_to_text(data.get("requirements")) if data.get("requirements") else None
    questions = data.get("application_questions") or None
    full_text = "\n".join(x for x in [title, description, requirements, questions, data.get("salary_text")] if x)

    smin, smax = _num(data.get("salary_min")), _num(data.get("salary_max"))
    cur = (data.get("salary_currency") or None)
    period = data.get("salary_period") or None
    if smin is None and smax is None:
        parsed = parse_salary(data.get("salary_text") or "") or parse_salary(description[:4000])
        if parsed:
            smin, smax, cur, period = parsed.min, parsed.max, parsed.currency, parsed.period
    if (smin or smax) and not period:
        ref = smax or smin or 0
        period = "hour" if ref < 200 else "month" if ref < 20000 else "year"
    if (smin or smax) and not cur:
        cur = "USD"

    location = data.get("location") or None
    remote_type = data.get("remote_type") or det.detect_remote_type(title, location, description[:3000])
    if remote_type not in {"remote", "hybrid", "onsite", "unknown"}:
        remote_type = det.detect_remote_type(remote_type)
    employment_type = data.get("employment_type") or det.detect_employment_type(title, description[:3000])
    employment_type = _norm_employment(employment_type)
    video = det.detect_video_requirement(description, requirements, questions)
    reqs = det.detect_requirements(description, requirements, questions)
    if questions:
        reqs["screening_questions"] = list(dict.fromkeys(det.extract_questions(questions) + reqs["screening_questions"]))[:15]

    src_url = data.get("source_url") or data.get("url")
    apply_url = data.get("apply_url") or src_url
    nj = NormalizedJob(
        title=title[:300],
        company=(data.get("company") or None),
        company_url=data.get("company_url"),
        source=data.get("source") or source,
        source_url=src_url,
        canonical_url=canonical_url(src_url) or canonical_url(apply_url),
        apply_url=apply_url,
        description=description or None,
        requirements=requirements,
        application_questions=questions,
        salary_min=smin,
        salary_max=smax,
        salary_currency=cur,
        salary_period=period,
        salary_monthly_usd_min=to_monthly_usd(smin, cur, period, usd_rates),
        salary_monthly_usd_max=to_monthly_usd(smax, cur, period, usd_rates),
        location=location,
        remote_type=remote_type,
        employment_type=employment_type,
        category=data.get("category") if data.get("category") in det.CATEGORY_LABELS else det.classify_category(title, description),
        seniority=data.get("seniority") or det.detect_seniority(title),
        posted_at=parse_datetime(data.get("posted_at")),
        job_id_external=str(data["job_id_external"]) if data.get("job_id_external") not in (None, "") else None,
        applicants_count=int(data["applicants_count"]) if data.get("applicants_count") not in (None, "") else None,
        easy_apply=bool(data.get("easy_apply")),
        video_required=video.required,
        video_details=video.as_dict(),
        detected_requirements=reqs,
        raw=data.get("raw") or {},
    )
    return nj


def _norm_employment(v: str | None) -> str | None:
    if not v:
        return None
    s = v.lower().replace("-", "_").replace(" ", "_")
    mapping = {"fulltime": "full_time", "full_time": "full_time", "parttime": "part_time", "part_time": "part_time",
               "contract": "contract", "contractor": "contract", "freelance": "contract", "temporary": "contract",
               "internship": "internship", "intern": "internship"}
    return mapping.get(s, det.detect_employment_type(v) or None)
