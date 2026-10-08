"""Job Match Score (0-100) with an explainable, weight-configurable breakdown.

The score is deterministic so it is reproducible and auditable; AI is never used to
invent a fit that the Master Profile does not support.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services import detection as det
from app.services.profile_service import (
    experience_years_for_keywords,
    profile_fact_corpus,
    profile_languages,
    profile_skill_terms,
    total_experience_years,
)
from app.services.settings_service import DEFAULT_SCORE_WEIGHTS
from app.services.text_utils import contains_term, normalize_text, tokens

COMMON_SKILLS = [
    # sales / cs / ops
    "salesforce", "hubspot", "pipedrive", "zoho", "close.com", "outreach", "salesloft", "apollo", "linkedin sales navigator",
    "cold calling", "cold email", "prospecting", "lead generation", "lead qualification", "crm", "negotiation", "closing",
    "account management", "customer success", "zendesk", "intercom", "freshdesk", "gorgias", "help scout", "jira",
    "confluence", "asana", "trello", "monday.com", "clickup", "notion", "airtable", "excel", "google sheets",
    "google workspace", "microsoft office", "power bi", "tableau", "looker", "sql", "data analysis", "reporting",
    "process improvement", "project management", "agile", "scrum", "kanban", "sop", "documentation", "logistics",
    "inventory", "supply chain", "quickbooks", "xero", "bookkeeping", "payroll", "shopify", "amazon seller central",
    "ecommerce", "e-commerce", "customer service", "technical support", "troubleshooting", "onboarding", "training",
    "recruiting", "sourcing", "ats", "greenhouse", "lever", "workday", "bamboohr",
    # marketing
    "seo", "sem", "google ads", "facebook ads", "meta ads", "copywriting", "content writing", "social media",
    "email marketing", "mailchimp", "klaviyo", "canva", "figma", "wordpress", "webflow", "google analytics",
    # AI / automation / tech
    "zapier", "make.com", "n8n", "integromat", "power automate", "rpa", "uipath", "api", "apis", "webhooks", "python",
    "javascript", "typescript", "node.js", "react", "chatgpt", "openai", "claude", "llm", "llms", "prompt engineering",
    "machine learning", "ai", "automation", "workflow automation", "no-code", "low-code", "gohighlevel", "retool",
    "aws", "gcp", "azure", "docker", "git", "html", "css", "rest", "json",
]


@dataclass
class ScoreResult:
    score: float
    classification: str
    breakdown: dict[str, Any]
    reasons: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)


def classify(score: float) -> str:
    if score >= 90:
        return "EXCELLENT"
    if score >= 80:
        return "STRONG"
    if score >= 70:
        return "GOOD"
    if score >= 60:
        return "MAYBE"
    return "SKIP"


def _job_text(job) -> str:
    return "\n".join(x for x in [job.title, job.description, job.requirements, job.application_questions] if x)


# ----------------------------------------------------------------- components
def score_salary(job, profile) -> tuple[float, list[str], list[str]]:
    lo, hi = job.salary_monthly_usd_min, job.salary_monthly_usd_max
    minimum = profile.min_salary or 2000
    target = profile.target_salary or max(minimum, 2500)
    target_hi = profile.target_salary_max or max(target, 4000)
    if (profile.salary_period or "month") == "year":
        minimum, target, target_hi = minimum / 12, target / 12, target_hi / 12
    if lo is None and hi is None:
        return 50, [], ["Salary not listed — confirm compensation early."]
    top = hi or lo
    bottom = lo or hi
    if top < minimum:
        return 5, [], [f"Pays ~${top:,.0f}/mo, below your ${minimum:,.0f}/mo minimum."]
    if top >= target_hi:
        return 100, [f"Top of range ~${top:,.0f}/mo meets your stretch target (${target_hi:,.0f}+)."], []
    if top >= target:
        s = 85 + 15 * (top - target) / max(target_hi - target, 1)
        return round(s), [f"Salary up to ~${top:,.0f}/mo is within your target range."], []
    s = 55 + 30 * (top - minimum) / max(target - minimum, 1)
    concerns = [f"Salary (~${bottom:,.0f}-{top:,.0f}/mo) meets the minimum but is below target ${target:,.0f}/mo."]
    return round(s), [], concerns


def score_skills(job, profile) -> tuple[float, list[str], list[str], dict]:
    text = normalize_text(_job_text(job))
    mine = profile_skill_terms(profile)
    matched = [s for s in mine if contains_term(text, s)]
    mine_norm = {normalize_text(s) for s in mine}
    corpus = normalize_text(profile_fact_corpus(profile))
    required_known = [s for s in COMMON_SKILLS if contains_term(text, s)]
    missing = [s for s in required_known if normalize_text(s) not in mine_norm and not contains_term(corpus, s) and not any(
        contains_term(normalize_text(m), s) or contains_term(normalize_text(s), m) for m in mine)]
    detail = {"matched": matched[:25], "missing": missing[:15]}
    if not mine:
        return 40, [], ["Add skills to your Master Profile to improve matching."], detail
    demand = len(matched) + len(missing)
    if demand == 0:
        return 55, [], ["Could not identify specific skills in the job description."], detail
    coverage = len(matched) / demand
    score = min(100, 25 + 75 * coverage + min(len(matched), 8) * 2)
    reasons = [f"Skills match: {', '.join(matched[:8])}."] if matched else []
    concerns = [f"Skills mentioned that are not in your profile: {', '.join(missing[:6])}."] if missing else []
    return round(score), reasons, concerns, detail


def score_experience(job, profile) -> tuple[float, list[str], list[str], dict]:
    required = det.detect_years_required(_job_text(job))
    total = total_experience_years(profile)
    cat_kw = det.CATEGORY_KEYWORDS.get(job.category or "", [])
    relevant = experience_years_for_keywords(profile, cat_kw + tokens(job.title)[:3]) if cat_kw else 0.0
    have = max(relevant, min(total, relevant + total * 0.5)) if relevant else total * 0.6
    detail = {"required_years": required, "total_years": total, "relevant_years": relevant}
    if not profile.work_experience:
        return 40, [], ["Add your work experience to the Master Profile."], detail
    if required is None:
        return (85 if have >= 1 else 65), ([f"{total:g} years total experience."] if total else []), [], detail
    if have >= required:
        return 100, [f"You have ~{have:.1f} relevant years vs {required:g} required."], [], detail
    ratio = have / required if required else 1
    concern = [f"Asks for {required:g}+ years; you have ~{have:.1f} relevant years."]
    return round(max(10, ratio * 85)), [], concern, detail


def score_role(job, profile, settings: dict) -> tuple[float, list[str], list[str]]:
    title_tokens = set(tokens(job.title)) - {"remote", "senior", "junior", "sr", "jr", "lead", "i", "ii", "iii"}
    best = 0.0
    best_role = None
    for role in profile.preferred_roles or []:
        rt = set(tokens(role))
        if not rt:
            continue
        if normalize_text(role) in normalize_text(job.title):
            sim = 1.0
        else:
            sim = len(rt & title_tokens) / len(rt | title_tokens) if title_tokens else 0
            sim = min(1.0, sim * 1.6)
        if sim > best:
            best, best_role = sim, role
    for exp in profile.work_experience or []:
        et = set(tokens(exp.get("title")))
        if et and title_tokens:
            sim = len(et & title_tokens) / len(et | title_tokens) * 1.3
            best = max(best, min(sim, 0.9))
    preferred_cats = set(profile.preferred_categories or []) | set(settings.get("preferred_categories") or [])
    reasons, concerns = [], []
    score = best * 100
    if job.category and job.category in preferred_cats:
        score = max(score, 80)
        reasons.append(f"Category '{det.CATEGORY_LABELS.get(job.category, job.category)}' is one of your preferred categories.")
    if best_role and best >= 0.5:
        reasons.append(f"Title aligns with your target role '{best_role}'.")
    if not profile.preferred_roles and not preferred_cats:
        concerns.append("Set preferred roles/categories in your profile for better role matching.")
        score = max(score, 50)
    elif score < 40:
        concerns.append("Role is outside your preferred roles.")
    return round(min(100, score)), reasons, concerns


def score_remote(job, profile) -> tuple[float, list[str], list[str], dict]:
    prefs = set(profile.work_arrangements or ["remote"])
    text = _job_text(job) + "\n" + (job.location or "")
    restrictions = det.detect_location_restrictions(text)
    tz = det.detect_timezone_requirement(text)
    detail = {"remote_type": job.remote_type, "restrictions": restrictions, "timezone": tz}
    reasons, concerns = [], []
    rt = job.remote_type or "unknown"
    if rt in prefs:
        score = 100
        if rt == "remote":
            reasons.append("Fully remote role.")
    elif rt == "unknown":
        score, concerns = 60, ["Work arrangement not stated."]
    elif rt == "hybrid" and "remote" in prefs:
        score, concerns = 25, ["Hybrid role — requires office presence."]
    else:
        score, concerns = 5, ["On-site role — does not match your remote preference."]
    country = (profile.country or profile.location or "").lower()
    auth = (profile.work_authorization or "").lower()
    for region in restrictions:
        region_l = region.lower()
        ok = region_l in country or region_l in auth or (region == "US" and ("united states" in country or "usa" in country or "united states" in auth))
        if region == "LATAM" and any(c in country for c in ["mexico", "colombia", "argentina", "chile", "peru", "brazil", "venezuela", "ecuador", "uruguay", "costa rica", "guatemala", "dominican", "bolivia", "paraguay", "panama", "honduras", "el salvador", "nicaragua"]):
            ok = True
        if ok:
            reasons.append(f"Location requirement ({region}) is compatible with your profile.")
        else:
            score = min(score, 20)
            concerns.append(f"May be restricted to candidates in {region}.")
    if tz:
        concerns.append(f"Time-zone requirement: “{tz}”.")
    return score, reasons, concerns, detail


def score_education(job, profile) -> tuple[float, list[str], list[str]]:
    text = _job_text(job)
    req = det.detect_degree_requirement(text)
    certs_req = det.detect_certifications(text)
    my_level = 0
    for ed in profile.education or []:
        deg = normalize_text(" ".join(str(ed.get(k) or "") for k in ("degree", "field")))
        for key, pat in [("phd", "phd doctor"), ("master", "master mba msc"), ("bachelor", "bachelor licenciatura ingenier ba bs bsc degree"),
                         ("associate", "associate tecnico technician"), ("high_school", "high school bachillerato")]:
            if any(w in deg for w in pat.split()):
                my_level = max(my_level, det.DEGREE_LEVELS[key])
                break
    reasons, concerns = [], []
    score = 100.0
    if req["level"]:
        need = det.DEGREE_LEVELS[req["level"]]
        if my_level >= need:
            reasons.append("Meets the education requirement.")
        elif req["flexible"]:
            score = 75
            concerns.append(f"Prefers a {req['level'].replace('_', ' ')} degree (equivalent experience accepted).")
        else:
            score = 30
            concerns.append(f"Requires a {req['level'].replace('_', ' ')} degree.")
    my_certs = normalize_text(" ".join((c.get("name") if isinstance(c, dict) else str(c)) or "" for c in profile.certifications or []))
    for cert in certs_req:
        first = normalize_text(cert.split(" ")[0])
        if first and first in my_certs:
            reasons.append(f"You hold {cert}.")
        else:
            score -= 15
            concerns.append(f"Mentions {cert} certification.")
    return max(0, round(score)), reasons, concerns


def score_language(job, profile) -> tuple[float, list[str], list[str]]:
    required = det.detect_languages_required(_job_text(job))
    mine = profile_languages(profile)
    if not mine:
        return 60, [], ["Add your languages to the Master Profile."]
    if not required:
        return (100 if "english" in mine or "inglés" in mine or "ingles" in mine else 70), [], []
    missing = [lang for lang in required if lang not in mine and not (lang == "english" and ("inglés" in mine or "ingles" in mine)) and not (lang == "spanish" and ("español" in mine or "espanol" in mine))]
    if not missing:
        return 100, [f"Language requirement met ({', '.join(required)})."], []
    return round(100 * (1 - len(missing) / len(required)) * 0.8), [], [f"Requires {', '.join(missing)}."]


def estimate_profile_seniority(years: float) -> str:
    if years < 1:
        return "entry"
    if years < 3:
        return "junior"
    if years < 6:
        return "mid"
    if years < 10:
        return "senior"
    return "lead"


def score_seniority(job, profile) -> tuple[float, list[str], list[str]]:
    job_level = job.seniority or det.detect_seniority(job.title)
    mine = estimate_profile_seniority(total_experience_years(profile))
    order = det.SENIORITY_LEVELS
    try:
        diff = order.index(job_level) - order.index(mine)
    except ValueError:
        return 70, [], []
    if job_level == "manager":
        diff = max(0, diff - 2)
    if diff <= 0:
        s = 100 if diff >= -2 else 70
        return s, ([] if diff >= -2 else []), ([] if diff >= -2 else [f"Role may be junior for your level ({job_level})."])
    if diff == 1:
        return 75, [], [f"Role is a step above your estimated level ({job_level} vs {mine})."]
    return max(10, 75 - 25 * (diff - 1)), [], [f"Seniority gap: {job_level} role vs your estimated {mine} level."]


def score_difficulty(job, profile, videos: list | None = None) -> tuple[float, list[str], list[str]]:
    req = job.detected_requirements or {}
    score = 80.0
    reasons, concerns = [], []
    if job.easy_apply:
        score += 20
        reasons.append("Quick / easy apply.")
    if job.video_required:
        has_video = any(getattr(v, "is_active", True) and getattr(v, "url", None) for v in (videos or []))
        score -= 5 if has_video else 20
        concerns.append("Requires a video" + (" (you have one in your Video Library)." if has_video else " — add one to your Video Library."))
    if req.get("cover_letter_required"):
        score -= 10
    if req.get("assessment"):
        score -= 15
        concerns.append("Includes an assessment / trial task.")
    if len(req.get("screening_questions") or []) > 4:
        score -= 10
    if req.get("portfolio") and not profile.portfolio_url:
        score -= 10
        concerns.append("Asks for a portfolio/work samples.")
    return max(0, min(100, round(score))), reasons, concerns


# ----------------------------------------------------------------- aggregate
def score_job(job, profile, settings: dict | None = None, videos: list | None = None) -> ScoreResult:
    settings = settings or {}
    weights = {**DEFAULT_SCORE_WEIGHTS, **(settings.get("score_weights") or {})}
    reasons: list[str] = []
    concerns: list[str] = []
    components: dict[str, dict] = {}

    def add(key: str, score: float, r: list[str], c: list[str], detail: dict | None = None):
        components[key] = {"score": round(score, 1), "weight": weights.get(key, 0), "reasons": r, "concerns": c, **({"detail": detail} if detail else {})}
        reasons.extend(r)
        concerns.extend(c)

    s, r, c = score_salary(job, profile); add("salary", s, r, c)
    s, r, c, d = score_skills(job, profile); add("skills", s, r, c, d)
    s, r, c, d = score_experience(job, profile); add("experience", s, r, c, d)
    s, r, c = score_role(job, profile, settings); add("role_relevance", s, r, c)
    s, r, c, d = score_remote(job, profile); add("remote_location", s, r, c, d)
    s, r, c = score_education(job, profile); add("education_certifications", s, r, c)
    s, r, c = score_language(job, profile); add("language", s, r, c)
    s, r, c = score_seniority(job, profile); add("seniority", s, r, c)
    s, r, c = score_difficulty(job, profile, videos); add("application_difficulty", s, r, c)

    total_w = sum(max(0, w) for w in weights.values()) or 1
    total = sum(components[k]["score"] * max(0, weights.get(k, 0)) for k in components) / total_w

    # Hard caps: deal-breakers cannot be averaged away.
    caps = []
    if components["salary"]["score"] <= 5:
        caps.append((55, "Below minimum salary"))
    if components["remote_location"]["score"] <= 20:
        caps.append((50, "Location / work arrangement incompatible"))
    excluded_inds = [normalize_text(x) for x in (profile.excluded_industries or [])]
    text = normalize_text(_job_text(job) + " " + (job.company or ""))
    for ind in excluded_inds:
        if ind and contains_term(text, ind):
            caps.append((40, f"Excluded industry: {ind}"))
            concerns.append(f"Matches an excluded industry ({ind}).")
    if job.category and job.category in set(settings.get("excluded_categories") or []):
        caps.append((40, "Excluded category"))
        concerns.append(f"Category {job.category} is excluded in Settings.")
    if job.employment_type and profile.employment_types and job.employment_type not in profile.employment_types:
        caps.append((65, "Employment type not preferred"))
        concerns.append(f"Employment type '{job.employment_type}' is not in your preferences.")
    for cap, _ in caps:
        total = min(total, cap)
    total = round(max(0, min(100, total)), 1)
    breakdown = {"components": components, "caps": [c[1] for c in caps], "weights": weights}
    return ScoreResult(total, classify(total), breakdown, list(dict.fromkeys(reasons)), list(dict.fromkeys(concerns)))
