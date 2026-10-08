"""Rule-based detectors over job text: category, seniority, work arrangement, video & other requirements."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.text_utils import contains_term, normalize_text

# ---------------------------------------------------------------- categories
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "sales": ["sdr", "bdr", "sales development", "business development", "account executive", "sales representative",
              "sales", "closer", "appointment setter", "lead generation", "outbound", "cold calling", "quota"],
    "customer_support": ["customer support", "customer service", "support specialist", "help desk", "helpdesk",
                         "customer success", "technical support", "support agent", "customer experience", "cx"],
    "operations": ["operations", "ops", "operations manager", "operations specialist", "business operations",
                   "process improvement", "logistics", "supply chain", "revenue operations", "revops", "sales operations"],
    "ai_automation": ["ai", "artificial intelligence", "automation", "machine learning", "llm", "prompt engineer",
                      "zapier", "make.com", "n8n", "workflow automation", "chatbot", "generative ai", "gpt", "rpa"],
    "project_management": ["project manager", "project coordinator", "program manager", "scrum master", "pmo",
                           "project management", "delivery manager"],
    "admin_assistant": ["virtual assistant", "executive assistant", "administrative assistant", "admin assistant",
                        "data entry", "office manager", "personal assistant"],
    "marketing": ["marketing", "seo", "content", "social media", "growth", "copywriter", "brand", "ppc", "email marketing"],
    "engineering": ["software engineer", "developer", "backend", "frontend", "full stack", "fullstack", "devops",
                    "sre", "mobile engineer", "qa engineer", "programmer"],
    "data": ["data analyst", "data scientist", "data engineer", "business intelligence", "analytics", "bi analyst"],
    "finance": ["accountant", "bookkeeper", "finance", "financial analyst", "payroll", "accounts payable", "controller"],
    "recruiting_hr": ["recruiter", "talent acquisition", "sourcer", "human resources", "hr ", "people operations"],
    "design": ["designer", "ux", "ui designer", "product designer", "graphic designer"],
    "product": ["product manager", "product owner", "product operations"],
}

CATEGORY_LABELS = {
    "sales": "Sales / SDR", "customer_support": "Customer Support", "operations": "Operations",
    "ai_automation": "AI / Automation", "project_management": "Project Management",
    "admin_assistant": "Admin / Assistant", "marketing": "Marketing", "engineering": "Engineering",
    "data": "Data", "finance": "Finance", "recruiting_hr": "Recruiting / HR", "design": "Design",
    "product": "Product", "other": "Other",
}


def classify_category(title: str | None, description: str | None = None) -> str:
    """Category based primarily on the title, falling back to description keyword density."""
    t = normalize_text(title)
    best, best_score = "other", 0.0
    d = normalize_text(description)[:6000]
    for cat, kws in CATEGORY_KEYWORDS.items():
        score = 0.0
        for kw in kws:
            if contains_term(t, kw):
                score += 3 + len(kw.split())  # multiword title hits are strongest
            elif d and contains_term(d, kw):
                score += 0.4
        if score > best_score:
            best, best_score = cat, score
    return best if best_score >= 1.0 else "other"


# ---------------------------------------------------------------- seniority
SENIORITY_LEVELS = ["intern", "entry", "junior", "mid", "senior", "lead", "manager", "director", "executive"]
_SENIORITY_PATTERNS = [
    ("executive", r"\b(vp|vice president|chief|cxo|ceo|coo|cto|cfo|head of)\b"),
    ("director", r"\bdirector\b"),
    ("lead", r"\b(lead|staff|principal|team lead)\b"),
    ("manager", r"\bmanager\b"),
    ("senior", r"\b(senior|sr)\b"),
    ("junior", r"\b(junior|jr)\b"),
    ("entry", r"\b(entry level|entry-level|associate|trainee|graduate)\b"),
    ("intern", r"\b(intern|internship)\b"),
]


def detect_seniority(title: str | None) -> str:
    t = (title or "").lower()
    for level, pat in _SENIORITY_PATTERNS:
        if re.search(pat, t):
            return level
    return "mid"


# ---------------------------------------------------------------- arrangement / type
def detect_remote_type(*texts: str | None) -> str:
    blob = " ".join(x or "" for x in texts).lower()
    if re.search(r"\bhybrid\b", blob):
        return "hybrid"
    if re.search(r"\b(remote|work from home|wfh|work from anywhere|distributed team|fully distributed|telecommute|remoto)\b", blob):
        if re.search(r"\b(not remote|no remote|on-site only|onsite only)\b", blob):
            return "onsite"
        return "remote"
    if re.search(r"\b(on-site|onsite|in office|in-office|office-based)\b", blob):
        return "onsite"
    return "unknown"


def detect_employment_type(*texts: str | None) -> str | None:
    blob = " ".join(x or "" for x in texts).lower()
    if re.search(r"\binternship\b|\bintern\b", blob):
        return "internship"
    if re.search(r"\b(contract|contractor|freelance|1099|b2b contract|fixed-term)\b", blob):
        return "contract"
    if re.search(r"\b(part[- ]time)\b", blob):
        return "part_time"
    if re.search(r"\b(full[- ]time|full_time|permanent)\b", blob):
        return "full_time"
    return None


_REGION_RESTRICTIONS = [
    ("US", r"\b(us|u\.s\.|usa|united states)[- ]?(only|based|residents?|citizens?)\b|must (?:be )?(?:located|based|reside) in the (?:us|united states)|(?:authorized|eligible) to work in the (?:us|united states)"),
    ("Canada", r"\bcanada[- ]?(only|based)\b|must (?:be )?(?:located|based|reside) in canada"),
    ("UK", r"\b(uk|united kingdom)[- ]?(only|based)\b|must (?:be )?(?:located|based|reside) in the (?:uk|united kingdom)|right to work in the uk"),
    ("EU", r"\b(eu|europe)[- ]?(only|based)\b|must (?:be )?(?:located|based|reside) in (?:the )?(?:eu|europe)"),
    ("LATAM", r"\b(latam|latin america)[- ]?(only|based)?\b"),
]


def detect_location_restrictions(text: str | None) -> list[str]:
    blob = (text or "").lower()
    found = []
    for region, pat in _REGION_RESTRICTIONS:
        if re.search(pat, blob):
            found.append(region)
    return found


def detect_timezone_requirement(text: str | None) -> str | None:
    m = re.search(r"\b(est|edt|cst|pst|pdt|mst|et|pt|ct|gmt|utc|cet)\b[^.\n]{0,40}\b(hours|time ?zone|overlap)\b", (text or "").lower())
    if m:
        return m.group(0)
    m = re.search(r"\b(?:overlap|work)\s+(?:with\s+)?(?:\w+\s+){0,3}(est|pst|cst|et|pt|utc|gmt|cet)\b", (text or "").lower())
    return m.group(0) if m else None


# ---------------------------------------------------------------- experience / education / languages
def detect_years_required(text: str | None) -> float | None:
    blob = (text or "").lower()
    vals = []
    for m in re.finditer(r"(\d{1,2})(?:\s*\+|\s*(?:-|–|to)\s*\d{1,2})?\s*\+?\s*(?:years?|yrs?)(?:'|’)?\s*(?:of\s+)?(?:[a-z0-9/\-]+\s+){0,4}(?:experience|exp\b)", blob):
        v = float(m.group(1))
        if 0 < v <= 25:
            vals.append(v)
    if not vals:
        m = re.search(r"(?:minimum|at least|min\.?)\s+(?:of\s+)?(\d{1,2})\s+years?", blob)
        if m:
            vals.append(float(m.group(1)))
    return min(vals) if vals else None


DEGREE_LEVELS = {"none": 0, "high_school": 1, "associate": 2, "bachelor": 3, "master": 4, "phd": 5}


def detect_degree_requirement(text: str | None) -> dict:
    blob = (text or "").lower()
    level = None
    for key, pat in [("phd", r"\b(ph\.?d|doctorate)\b"), ("master", r"\b(master'?s|mba|msc|m\.s\.)\b"),
                     ("bachelor", r"\b(bachelor'?s|ba/bs|bs/ba|b\.?s\.?c?|b\.a\.|undergraduate degree|college degree|university degree|degree in)\b"),
                     ("associate", r"\bassociate'?s degree\b"), ("high_school", r"\b(high school|ged)\b")]:
        if re.search(pat, blob):
            level = key
            break
    if not level:
        return {"level": None, "flexible": True, "required": False}
    flexible = bool(re.search(r"or equivalent|equivalent (practical |work )?experience|preferred|nice to have|a plus", blob))
    return {"level": level, "flexible": flexible, "required": not flexible}


KNOWN_LANGUAGES = ["english", "spanish", "portuguese", "french", "german", "italian", "dutch", "mandarin", "chinese",
                   "japanese", "korean", "arabic", "russian", "hindi", "tagalog", "polish", "turkish"]


def detect_languages_required(text: str | None) -> list[str]:
    blob = (text or "").lower()
    found: list[str] = []
    for lang in KNOWN_LANGUAGES:
        pats = [
            rf"\b(fluent|fluency|native|proficient|proficiency|bilingual|business[- ]level|advanced|professional)\b[^.\n]{{0,40}}\b{lang}\b",
            rf"\b{lang}\b[^.\n]{{0,25}}\b(fluency|fluent|native|proficiency|required|speaker|c1|c2|b2)\b",
        ]
        if any(re.search(p, blob) for p in pats):
            found.append(lang)
    if "bilingual" in blob and not found:
        found = ["english"]
    return found


CERT_PATTERNS = {
    "PMP": r"\bpmp\b", "CAPM": r"\bcapm\b", "CPA": r"\bcpa\b", "Scrum Master (CSM/PSM)": r"\b(csm|psm|certified scrummaster)\b",
    "AWS Certification": r"\baws certified\b", "Salesforce Certification": r"\bsalesforce (certified|certification)\b",
    "HubSpot Certification": r"\bhubspot (certified|certification)\b", "Google Analytics Certification": r"\bgoogle analytics (certified|certification)\b",
    "SHRM": r"\bshrm-?(cp|scp)?\b", "Six Sigma": r"\bsix sigma\b", "ITIL": r"\bitil\b", "CompTIA": r"\bcomptia\b",
}


def detect_certifications(text: str | None) -> list[str]:
    blob = (text or "").lower()
    return [name for name, pat in CERT_PATTERNS.items() if re.search(pat, blob)]


# ---------------------------------------------------------------- video requirement
VIDEO_PATTERNS = [
    r"record (?:a|an|your|yourself|short)?\s*(?:short|brief|quick)?\s*(?:\d+[- ]?(?:minute|min)\s*)?video",
    r"submit (?:a|an)?\s*(?:short|brief)?\s*(?:\d+[- ]?(?:minute|min)\s*)?video",
    r"\b\d+[- ]?(?:minute|min)s?\s+video\b",
    r"video (?:introduction|intro|cover letter|resume|response|submission|pitch)",
    r"video interview",
    r"\bloom\b",
    r"record yourself",
    r"(?:tell|explain)[^.\n]{0,60}\bon video\b",
    r"(?:send|share|include|attach|upload) (?:us )?(?:a|an)?\s*(?:short|brief)?\s*video",
    r"one[- ]way (?:video )?interview",
    r"\b(?:vidyard|hirevue|willo|spark hire|sparkhire|videoask)\b",
    r"grabar un video|video de presentaci[oó]n",
]
VIDEO_UPLOAD_HINTS = r"upload (?:a|an|your)? ?video( file)?|attach (?:a|an|your)? ?video file|\.mp4|\.mov|video file"
VIDEO_URL_HINTS = r"\bloom\b|video (?:link|url)|link to (?:a|your) video|youtube|vimeo|share (?:a|the) link"


@dataclass
class VideoRequirement:
    required: bool = False
    phrases: list[str] = field(default_factory=list)
    duration_minutes: float | None = None
    platform_hint: str | None = None
    submission_type: str = "unknown"  # url | file | platform | unknown

    def as_dict(self) -> dict:
        return {
            "required": self.required, "phrases": self.phrases, "duration_minutes": self.duration_minutes,
            "platform_hint": self.platform_hint, "submission_type": self.submission_type,
        }


def detect_video_requirement(*texts: str | None) -> VideoRequirement:
    blob = " \n".join(t or "" for t in texts)
    low = blob.lower()
    result = VideoRequirement()
    for pat in VIDEO_PATTERNS:
        for m in re.finditer(pat, low):
            phrase = low[max(0, m.start() - 20) : m.end() + 20].strip()
            # "Loom" as a mere tool listing (e.g. "Tools: Slack, Loom, Notion") is weak evidence
            if pat == r"\bloom\b" and not re.search(r"video|record|send|share|submit|link", phrase):
                continue
            result.phrases.append(blob[m.start() : m.end()])
    if result.phrases:
        result.required = True
        result.phrases = list(dict.fromkeys(result.phrases))[:6]
        d = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to)?\s*(?:\d+)?[- ]?(?:minute|min)s?\b[^.\n]{0,25}video|video[^.\n]{0,40}?(\d+(?:\.\d+)?)[- ]?(?:minute|min)s?", low)
        if d:
            result.duration_minutes = float(d.group(1) or d.group(2))
        for platform in ["loom", "vidyard", "hirevue", "willo", "spark hire", "videoask", "youtube", "vimeo"]:
            if platform in low:
                result.platform_hint = platform
                break
        if re.search(r"hirevue|willo|spark hire|sparkhire|one[- ]way (?:video )?interview|videoask", low):
            result.submission_type = "platform"
        elif re.search(VIDEO_UPLOAD_HINTS, low):
            result.submission_type = "file"
        elif re.search(VIDEO_URL_HINTS, low):
            result.submission_type = "url"
    return result


# ---------------------------------------------------------------- other requirements
def detect_requirements(*texts: str | None) -> dict:
    blob = " \n".join(t or "" for t in texts).lower()
    req = {
        "cover_letter": bool(re.search(r"cover letter|letter of motivation|motivation letter|why you(?:'re| are) a (?:good|great) fit", blob)),
        "cover_letter_required": bool(re.search(r"(?:include|attach|submit|send|required?)[^.\n]{0,30}cover letter|cover letter[^.\n]{0,20}(?:is )?required", blob)),
        "portfolio": bool(re.search(r"\bportfolio\b|work samples|writing samples", blob)),
        "assessment": bool(re.search(r"assessment|skills test|take-home|take home|test project|trial task|paid trial|personality test|disc test|culture index|criteria cognitive", blob)),
        "references": bool(re.search(r"\breferences\b", blob)),
        "salary_question": bool(re.search(r"salary expectation|expected salary|desired (?:salary|compensation|pay)|compensation expectation|rate expectation", blob)),
        "work_authorization_question": bool(re.search(r"authori[sz]ed to work|work authori[sz]ation|require sponsorship|visa sponsorship|right to work", blob)),
        "availability_question": bool(re.search(r"start date|when can you start|notice period|availability", blob)),
        "file_upload": bool(re.search(r"upload|attach", blob)),
    }
    req["screening_questions"] = extract_questions(blob)
    return req


def extract_questions(text: str | None) -> list[str]:
    """Pull explicit questions (lines/sentences ending with '?') out of a description / questions block."""
    if not text:
        return []
    qs: list[str] = []
    for raw in re.split(r"[\n\r]+|(?<=\?)\s+", text):
        line = raw.strip(" •-*\t0123456789.)")
        if line.endswith("?") and 12 <= len(line) <= 300:
            qs.append(line[0].upper() + line[1:])
    return list(dict.fromkeys(qs))[:15]
