"""Application Priority Score — decides what to apply to first (Apply Queue order)."""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.settings_service import DEFAULT_PRIORITY_WEIGHTS


def _recency_score(posted_at: datetime | None, discovered_at: datetime | None) -> float:
    ref = posted_at or discovered_at
    if ref is None:
        return 50
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - ref).total_seconds() / 86400
    if days <= 1:
        return 100
    if days <= 3:
        return 90
    if days <= 7:
        return 75
    if days <= 14:
        return 55
    if days <= 30:
        return 35
    return 15


def priority_score(
    job,
    profile,
    settings: dict | None = None,
    *,
    has_contact: bool = False,
    has_tailored_resume: bool = False,
    has_matching_video: bool = False,
    category_success: dict[str, float] | None = None,
) -> tuple[float, dict]:
    settings = settings or {}
    weights = {**DEFAULT_PRIORITY_WEIGHTS, **(settings.get("priority_weights") or {})}
    comps: dict[str, float] = {}
    comps["match"] = job.match_score or 0

    target = profile.target_salary or 2500
    top = job.salary_monthly_usd_max or job.salary_monthly_usd_min
    if top is None:
        comps["salary"] = 50
    else:
        comps["salary"] = max(0, min(100, 100 * top / max(target * 1.4, 1)))

    comps["recency"] = _recency_score(job.posted_at, job.discovered_at)
    diff = ((job.score_breakdown or {}).get("components") or {}).get("application_difficulty", {}).get("score", 70)
    comps["ease"] = diff
    if job.applicants_count is None:
        comps["competition"] = 60
    else:
        comps["competition"] = max(5, 100 - min(job.applicants_count, 500) / 5)
    comps["contact"] = 100 if has_contact else 40
    if job.video_required:
        comps["video_readiness"] = 90 if has_matching_video else 20
    else:
        comps["video_readiness"] = 100
    comps["tailored_resume"] = 100 if has_tailored_resume else 50
    comps["quick_apply"] = 100 if job.easy_apply else 50
    rate = (category_success or {}).get(job.category or "other")
    comps["historical_success"] = 50 if rate is None else max(0, min(100, 30 + rate * 350))

    total_w = sum(max(0, w) for w in weights.values()) or 1
    score = sum(comps[k] * max(0, weights.get(k, 0)) for k in comps) / total_w
    breakdown = {"components": {k: round(v, 1) for k, v in comps.items()}, "weights": weights}
    return round(score, 1), breakdown
