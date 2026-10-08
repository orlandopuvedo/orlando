"""Text generation (cover letters, messages, answers) — AI when available, deterministic templates otherwise.

Every output is passed through the fabrication guard and returned with its warnings.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.ai.base import AIProvider, AIProviderError
from app.services.detection import CATEGORY_LABELS
from app.services.guardrails import NO_FABRICATION_RULES, check_fabrication
from app.services.profile_service import profile_fact_corpus, profile_skill_terms, total_experience_years
from app.services.text_utils import contains_term, normalize_text


@dataclass
class Generated:
    text: str
    generated_by: str
    warnings: list[str] = field(default_factory=list)


def profile_context(profile) -> str:
    data = {
        "name": profile.full_name, "headline": profile.headline, "location": profile.location,
        "time_zone": profile.time_zone, "summary": profile.professional_summary, "skills": profile.skills,
        "tools": profile.tools, "work_experience": profile.work_experience, "education": profile.education,
        "certifications": profile.certifications, "languages": profile.languages, "achievements": profile.achievements,
        "projects": profile.projects, "industries": profile.industries, "availability": profile.availability,
        "linkedin": profile.linkedin_url, "portfolio": profile.portfolio_url,
    }
    return json.dumps({k: v for k, v in data.items() if v}, ensure_ascii=False, default=str)


def job_context(job) -> str:
    parts = [f"Title: {job.title}", f"Company: {job.company or 'Unknown'}", f"Location: {job.location or ''} ({job.remote_type})"]
    if job.description:
        parts.append("Description:\n" + job.description[:7000])
    if job.application_questions:
        parts.append("Application questions:\n" + job.application_questions[:2000])
    return "\n".join(parts)


def _job_text(job) -> str:
    return "\n".join(x for x in [job.title, job.company, job.description, job.requirements, job.application_questions] if x) if job else ""


def _finish(text: str, by: str, profile, job, extra_allowed: str = "") -> Generated:
    years = total_experience_years(profile)
    derived = f"{years} {int(years)} {int(years)}+"  # facts computed from the profile's own dates
    warnings = check_fabrication(text, profile_fact_corpus(profile), _job_text(job), f"{extra_allowed} {derived}")
    return Generated(text.strip(), by, warnings)


def _ai(provider: AIProvider | None, system: str, prompt: str, max_tokens: int = 1500) -> str | None:
    if provider is None or not provider.is_available():
        return None
    try:
        return provider.complete(system, prompt, max_tokens)
    except AIProviderError:
        return None


# ----------------------------------------------------------------- relevance helpers
def relevant_skills(profile, job, limit: int = 6) -> list[str]:
    text = normalize_text(_job_text(job))
    skills = profile_skill_terms(profile)
    hits = [s for s in skills if contains_term(text, s)]
    return (hits or skills)[:limit]


def most_relevant_experience(profile, job) -> dict | None:
    text = normalize_text(_job_text(job))
    best, best_score = None, -1
    for exp in profile.work_experience or []:
        blob = " ".join([exp.get("title") or "", exp.get("description") or "", " ".join(exp.get("highlights") or [])])
        score = sum(1 for w in set(normalize_text(blob).split()) if len(w) > 3 and contains_term(text, w))
        if exp.get("current"):
            score += 2
        if score > best_score:
            best, best_score = exp, score
    return best


def relevant_highlights(profile, job, limit: int = 3) -> list[str]:
    text = normalize_text(_job_text(job))
    scored = []
    for exp in profile.work_experience or []:
        for h in exp.get("highlights") or []:
            s = sum(1 for w in set(normalize_text(h).split()) if len(w) > 3 and contains_term(text, w))
            scored.append((s, h))
    for a in profile.achievements or []:
        a_text = a.get("description") if isinstance(a, dict) else str(a)
        s = sum(1 for w in set(normalize_text(a_text).split()) if len(w) > 3 and contains_term(text, w))
        scored.append((s, a_text))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [h for _, h in scored[:limit] if h]


# ----------------------------------------------------------------- cover letter
def generate_cover_letter(profile, job, provider: AIProvider | None = None, instructions: str = "") -> Generated:
    ai = _ai(
        provider,
        "You write concise, specific, human cover letters for remote job applications.\n" + NO_FABRICATION_RULES,
        f"CANDIDATE PROFILE (JSON):\n{profile_context(profile)}\n\nJOB:\n{job_context(job)}\n\n"
        f"Write a cover letter of 180-280 words. Plain text, no markdown, no subject line. "
        f"Lead with genuine fit, mention 2-3 concrete, real pieces of the candidate's experience relevant to this job. "
        f"Sign with the candidate's name.{(' Extra instructions: ' + instructions) if instructions else ''}",
    )
    if ai:
        return _finish(ai, provider.label, profile, job)
    name = profile.full_name or ""
    exp = most_relevant_experience(profile, job)
    skills = relevant_skills(profile, job, 5)
    highlights = relevant_highlights(profile, job, 2)
    years = total_experience_years(profile)
    lines = [f"Dear {job.company + ' ' if job.company else ''}Hiring Team,", ""]
    title = clean_title(job.title)
    intro = f"I'm applying for the {title} position"
    intro += f" at {job.company}." if job.company else "."
    if profile.headline:
        head = profile.headline.strip().rstrip(".")
        intro += f" I'm {'an' if head[:1].lower() in 'aeiou' else 'a'} {head}"
        intro += f" with {int(years)}+ years of professional experience." if years >= 1 else "."
    lines.append(intro)
    lines.append("")
    if exp:
        verb = "In my current role" if exp.get("current") else "In my role"
        p = f"{verb} as {exp.get('title')} at {exp.get('company')}"
        p += f", my focus is: {exp['description'].strip().rstrip('.')}." if exp.get("current") and exp.get("description") else (
            f", my focus was: {exp['description'].strip().rstrip('.')}." if exp.get("description") else ".")
        lines.append(p)
    if highlights:
        lines.append("Some relevant results from my experience:")
        lines.extend(f"• {h.strip()}" for h in highlights)
    if skills:
        lines.append("")
        lines.append(f"I bring hands-on experience with {', '.join(skills[:-1]) + (' and ' + skills[-1] if len(skills) > 1 else skills[0])}, which map directly to what this role needs.")
    lines.append("")
    closing = ""
    if "remote" in (profile.work_arrangements or []):
        closing = "I'm specifically seeking a remote role"
        if profile.location:
            closing += f" and I'm based in {profile.location}" + (f" ({profile.time_zone})" if profile.time_zone else "")
        closing += ". "
    lines.append(closing + "I'd welcome the chance to discuss how I can contribute to your team.")
    lines.append("")
    lines.append("Best regards,")
    if name:
        lines.append(name)
    contact_bits = [x for x in [profile.email, profile.linkedin_url] if x]
    if contact_bits:
        lines.append(" · ".join(contact_bits))
    return _finish("\n".join(lines), "template", profile, job)


# ----------------------------------------------------------------- recruiter message
def generate_recruiter_message(profile, job, contact=None, provider: AIProvider | None = None) -> Generated:
    who = contact.full_name.split()[0] if contact and contact.full_name else None
    ai = _ai(
        provider,
        "You write short, warm, specific LinkedIn/email messages to recruiters. Max 90 words.\n" + NO_FABRICATION_RULES,
        f"CANDIDATE PROFILE:\n{profile_context(profile)}\n\nJOB:\n{job_context(job)}\n\nRecipient: "
        f"{(contact.full_name + ', ' + (contact.job_title or '')) if contact else 'the recruiter/hiring manager'}\n"
        "Write the message (plain text).",
        600,
    )
    if ai:
        return _finish(ai, provider.label, profile, job, extra_allowed=contact.full_name if contact else "")
    skills = relevant_skills(profile, job, 3)
    exp = most_relevant_experience(profile, job)
    msg = f"Hi {who or 'there'}, I just applied for the {clean_title(job.title)} role{(' at ' + job.company) if job.company else ''}. "
    if exp:
        msg += f"I've worked as {exp.get('title')} at {exp.get('company')}"
        msg += f" with {', '.join(skills)}" if skills else ""
        msg += ", and I believe I can add value quickly. "
    msg += "Would you be open to a short chat? Thank you!" + (f"\n{profile.full_name}" if profile.full_name else "")
    return _finish(msg, "template", profile, job, extra_allowed=contact.full_name if contact else "")


# ----------------------------------------------------------------- follow-ups
FOLLOW_UP_KINDS = {"application", "interview_thank_you", "interview_follow_up", "contact", "custom"}


def generate_follow_up(kind: str, profile, job=None, contact=None, interview=None, provider: AIProvider | None = None) -> Generated:
    role = clean_title(job.title) if job else "the role"
    company = (job.company if job else None) or (interview.company if interview else None) or (contact.company if contact else None)
    first = contact.full_name.split()[0] if contact and contact.full_name else None
    context = {"kind": kind, "role": role, "company": company, "contact": contact.full_name if contact else None,
               "interview_notes": interview.notes if interview else None,
               "interview_type": interview.interview_type if interview else None}
    ai = _ai(
        provider,
        "You write brief, professional follow-up messages for a job seeker. Max 110 words. Plain text.\n" + NO_FABRICATION_RULES,
        f"CANDIDATE PROFILE:\n{profile_context(profile)}\n\nCONTEXT:\n{json.dumps(context, default=str)}\n\nWrite the message.",
        600,
    )
    extra = " ".join(x for x in [contact.full_name if contact else "", company or "", interview.notes if interview and interview.notes else ""] if x)
    if ai:
        return _finish(ai, provider.label, profile, job, extra_allowed=extra)
    greet = f"Hi {first}," if first else "Hello,"
    at = f" at {company}" if company else ""
    if kind == "interview_thank_you":
        body = (f"Thank you for taking the time to speak with me about the {role} position{at}. I enjoyed learning more "
                "about the team and the role, and I'm even more excited about the opportunity. Please let me know if there's "
                "anything else I can provide.")
    elif kind == "interview_follow_up":
        body = (f"I wanted to follow up on my interview for the {role} position{at}. I remain very interested and would "
                "appreciate any update you can share on next steps.")
    elif kind == "contact":
        body = f"I wanted to follow up on my previous message regarding the {role} opportunity{at}. I'd love to connect when you have a moment."
    else:
        body = (f"I recently applied for the {role} position{at} and wanted to reiterate my strong interest. "
                "I'd be happy to share more about my experience or answer any questions.")
    text = f"{greet}\n\n{body}\n\nBest regards,\n{profile.full_name or ''}".strip()
    return _finish(text, "template", profile, job, extra_allowed=extra)


# ----------------------------------------------------------------- answers
def salary_answer(profile, job=None) -> str:
    cur = profile.salary_currency or "USD"
    per = {"month": "per month", "year": "per year", "hour": "per hour"}.get(profile.salary_period or "month", "per month")
    if profile.target_salary and profile.target_salary_max:
        return (f"My target compensation is in the range of {cur} {profile.target_salary:,.0f}–{profile.target_salary_max:,.0f} {per}, "
                "depending on the full scope of the role and benefits. I'm open to discussing.")
    if profile.target_salary:
        return f"My target compensation is around {cur} {profile.target_salary:,.0f} {per}, and I'm open to discussing based on the scope of the role."
    if profile.min_salary:
        return f"I'm looking for compensation starting at {cur} {profile.min_salary:,.0f} {per}, open to discussion."
    return ""


def availability_answer(profile) -> str:
    return profile.availability or ""


def work_authorization_answer(profile) -> str:
    return profile.work_authorization or ""


def personalize_answer(question: str, base_answer: str | None, profile, job, provider: AIProvider | None = None) -> Generated:
    ai = _ai(
        provider,
        "You answer job application screening questions for a candidate, in first person, concise (40-150 words).\n" + NO_FABRICATION_RULES,
        f"CANDIDATE PROFILE:\n{profile_context(profile)}\n\nJOB:\n{job_context(job)}\n\nQUESTION: {question}\n"
        + (f"\nCANDIDATE'S SAVED ANSWER (reuse its facts, adapt to this job):\n{base_answer}\n" if base_answer else "")
        + "\nIf the profile lacks the information needed, reply exactly: NEEDS_USER_INPUT",
        800,
    )
    if ai:
        if "NEEDS_USER_INPUT" in ai:
            return Generated("", provider.label, ["Profile lacks the information to answer this — please answer manually."])
        return _finish(ai, provider.label, profile, job, extra_allowed=base_answer or "")
    if base_answer:
        text = base_answer
        if job and job.company:
            text = text.replace("{company}", job.company).replace("{role}", job.title)
        return _finish(text, "answer_library", profile, job, extra_allowed=base_answer)
    return Generated("", "none", ["No saved answer — please answer manually or add one to the Answer Library."])


def tailored_summary(profile, job, provider: AIProvider | None = None) -> Generated:
    ai = _ai(
        provider,
        "You rewrite a resume professional summary to target a specific job (3-4 sentences).\n" + NO_FABRICATION_RULES,
        f"CANDIDATE PROFILE:\n{profile_context(profile)}\n\nJOB:\n{job_context(job)}\n\nWrite only the summary.",
        500,
    )
    if ai:
        return _finish(ai, provider.label, profile, job)
    base = (profile.professional_summary or "").strip()
    if not base:
        return Generated("", "template", ["Add a professional summary to your profile."])
    return Generated(base, "template", [])


def clean_title(title: str | None) -> str:
    import re

    t = re.sub(r"\s*[\(\[][^)\]]*(remote|anywhere|worldwide|latam|us|eu|wfh)[^)\]]*[\)\]]", "", title or "", flags=re.I)
    t = re.sub(r"\s*[-–|]\s*(remote|100% remote|fully remote)\s*$", "", t, flags=re.I)
    return t.strip() or (title or "")


def category_label(cat: str | None) -> str:
    return CATEGORY_LABELS.get(cat or "other", "General")
