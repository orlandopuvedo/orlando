"""Fabrication guard: flags claims in generated text that are not backed by the Master Profile.

It is deliberately conservative — it cannot *prove* truth, but it surfaces every number,
company-like proper noun, degree and certification that does not appear in the user's own
profile (or the job post itself) so the user can verify it before sending.
"""
from __future__ import annotations

import re

from app.services.text_utils import normalize_text

NUMBER_RE = re.compile(r"(?<![\w])(\$?\d[\d,.]*\s?(?:%|k|K|\+)?(?:\s?(?:years?|yrs?|months?|clients?|customers?|people|users?|deals?|accounts?))?)")
PROPER_RE = re.compile(r"\b([A-Z][a-zA-Z0-9&.\-]+(?:[ \t]+(?:[A-Z][a-zA-Z0-9&.\-]+|of|and|&)){0,4})")
CLAIM_WORDS = re.compile(r"\b(certified|certification|degree|bachelor|master|mba|phd|award|promoted|led a team of|managed a team of)\b", re.I)

COMMON_CAPS = set("""I I'm I've I'd Dear Hi Hello Thank Thanks Best Regards Sincerely Kind The This That These My We Our
You Your As In At On For With From By To And But Also If When While During Over Since After Before Please Looking
Remote Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May June July August
September October November December Hiring Manager Team Re Subject LinkedIn Loom Zoom Google Microsoft English Spanish
Portuguese French German USD US EST PST UTC GMT AI CRM SQL API SDR BDR Sales Operations Customer Support Success
Automation Experience Summary Skills Education Certifications Languages Projects Achievements Professional
Contact Email Phone Location Portfolio References Here Today Tomorrow Yes No Hope Excited Happy Glad Thank-you""".split())


def _norm_num(s: str) -> str:
    return re.sub(r"[^\d.%]", "", s).rstrip(".")


def check_fabrication(text: str, profile_corpus: str, job_text: str = "", extra_allowed: str = "") -> list[str]:
    if not text:
        return []
    allowed_raw = "\n".join([profile_corpus or "", job_text or "", extra_allowed or ""])
    allowed_norm = normalize_text(allowed_raw)
    allowed_nums = {_norm_num(m) for m in re.findall(r"\d[\d,.]*%?", allowed_raw)}
    allowed_nums |= {n.replace(",", "") for n in allowed_nums}
    warnings: list[str] = []

    for m in NUMBER_RE.finditer(text):
        raw = m.group(1).strip()
        n = _norm_num(raw)
        if not n or n in {"1", "2", "3"} and "year" not in raw:  # tiny counts are usually phrasing
            continue
        n_plain = n.rstrip("%").replace(",", "")
        if n not in allowed_nums and n_plain not in allowed_nums and n_plain not in allowed_norm:
            warnings.append(f"Number “{raw}” is not in your profile — verify it is accurate.")

    for m in PROPER_RE.finditer(text):
        phrase = m.group(1).strip(" .-")
        words = [w for w in phrase.split() if w not in COMMON_CAPS and w.lower() not in {"of", "and", "&"}]
        if not words:
            continue
        # sentence-initial single common word → skip
        if len(words) == 1 and (m.start() == 0 or text[max(0, m.start() - 2) : m.start()].strip() in {".", "!", "?", ""}):
            continue
        cand = normalize_text(" ".join(words))
        if cand and cand not in allowed_norm and not all(normalize_text(w) in allowed_norm for w in words):
            warnings.append(f"“{phrase}” does not appear in your profile or the job post — verify.")

    for m in CLAIM_WORDS.finditer(text):
        ctx = text[max(0, m.start() - 40) : m.end() + 40]
        if normalize_text(m.group(1)) not in allowed_norm:
            warnings.append(f"Claim “…{ctx.strip()}…” mentions '{m.group(1)}' which is not in your profile.")
    return list(dict.fromkeys(warnings))[:20]


NO_FABRICATION_RULES = """STRICT TRUTHFULNESS RULES (non-negotiable):
- Use ONLY facts present in the CANDIDATE PROFILE. The profile is the single source of truth.
- Never invent or embellish experience, employers, job titles, dates, years of experience, degrees, certifications,
  languages, skills, tools, metrics, numbers, achievements or legal/work authorization.
- You may reorganize, summarize, prioritize and rephrase real information to fit the job.
- If the job asks for something the profile does not contain, do not claim it; you may express willingness to learn.
- Never include placeholders like [Company] unless the information is genuinely unknown; prefer omitting."""
