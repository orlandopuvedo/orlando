"""Pick the best video from the Video Library for a job."""
from __future__ import annotations

from app.services.detection import CATEGORY_KEYWORDS, CATEGORY_LABELS
from app.services.text_utils import contains_term, normalize_text, tokens

CATEGORY_TAG_ALIASES = {
    "sales": ["sales", "sdr", "bdr", "business development", "account executive"],
    "customer_support": ["customer support", "support", "customer service", "customer success", "cx"],
    "operations": ["operations", "ops", "operations introduction"],
    "ai_automation": ["ai", "automation", "ai/automation", "ai automation", "no-code"],
    "project_management": ["project management", "pm", "operations"],
    "admin_assistant": ["virtual assistant", "admin", "assistant", "operations"],
}
GENERAL_TAGS = {"general", "introduction", "experience", "professional", "remote work"}


def score_video(job, video) -> float:
    if not getattr(video, "is_active", True):
        return -1
    tags = [normalize_text(t) for t in (video.tags or [])]
    name = normalize_text(video.name)
    cat = job.category or "other"
    aliases = CATEGORY_TAG_ALIASES.get(cat, []) + [normalize_text(CATEGORY_LABELS.get(cat, cat))]
    score = 0.0
    if any(normalize_text(a) in tags or contains_term(name, a) for a in aliases):
        score += 50
    title = normalize_text(job.title)
    for t in tags:
        if t and t not in GENERAL_TAGS and contains_term(title, t):
            score += 15
    for kw in CATEGORY_KEYWORDS.get(cat, [])[:6]:
        if contains_term(normalize_text(video.description or ""), kw):
            score += 5
    if GENERAL_TAGS & set(tags) or "general" in name:
        score += 10  # sensible fallback
    if video.url:
        score += 5
    # Respect required duration (e.g. a 5-minute video)
    want = (job.video_details or {}).get("duration_minutes")
    if want and video.duration_seconds:
        diff = abs(video.duration_seconds / 60 - want)
        score -= min(15, diff * 3)
    _ = tokens  # keep import for future fuzzy matching
    return score


def recommend_video(job, videos: list) -> dict | None:
    ranked = sorted(((score_video(job, v), v) for v in videos), key=lambda x: x[0], reverse=True)
    ranked = [(s, v) for s, v in ranked if s >= 0]
    if not ranked:
        return None
    s, v = ranked[0]
    alternatives = [{"id": a.id, "name": a.name, "score": round(sc, 1)} for sc, a in ranked[1:4]]
    return {"video_id": v.id, "name": v.name, "url": v.url, "platform": v.platform,
            "duration_seconds": v.duration_seconds, "score": round(s, 1), "alternatives": alternatives}
