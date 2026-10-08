"""ATS strategy layer: per-platform knowledge for application-form detection, progression buttons,
resume inputs and submission confirmation. Unknown/unsupported platforms stop for manual handling.

Only *read-only knowledge* lives here (URL shapes, button wording, success messages). No protection
bypassing, no hidden APIs, no submission without the supervisor's approval checks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

NEXT_RE = re.compile(r"^(?:next|continue|save (?:and|&) continue|next step|proceed|siguiente|continuar)\b", re.I)
SUBMIT_RE = re.compile(r"^(?:submit(?: (?:my )?application)?|send application|apply(?: now)?|complete application|finish(?: application)?|enviar(?: solicitud)?|postular(?:me)?)\b", re.I)
NEVER_CLICK = re.compile(r"\b(back|previous|cancel|save (?:as )?draft|sign in|log ?in|register|create account|upload|attach|add (?:another|more)|remove|delete|clear|search|subscribe|share|linkedin|google|indeed|apply with)\b", re.I)

GENERIC_SUCCESS = [r"thank(?:s| you) for (?:your )?appl(?:ying|ication)", r"application (?:has been |was )?(?:successfully )?(?:submitted|received|sent)",
                   r"we(?:'ve| have) received your application", r"your application (?:is|has been) (?:complete|submitted|received)",
                   r"successfully applied", r"gracias por (?:tu|su) (?:postulaci[oó]n|solicitud)"]
CONFIRMATION_ID = re.compile(r"(?:application|confirmation|reference|submission)\s*(?:id|number|no\.?|#|code)\s*[:#]?\s*([A-Z0-9][A-Z0-9-]{3,40})", re.I)


@dataclass
class Confirmation:
    confirmed: bool
    signal: str | None = None
    text: str | None = None
    confirmation_id: str | None = None


def _host(url: str) -> str:
    return urlsplit(url or "").netloc.lower().removeprefix("www.")


class AtsStrategy:
    name = "generic"
    supported = True
    host_patterns: tuple[str, ...] = ()
    frame_hosts: tuple[str, ...] = ("boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com")
    success_url_patterns: tuple[str, ...] = ()
    success_text_patterns: tuple[str, ...] = ()
    resume_names = re.compile(r"resume|\bcv\b|curr[ií]cul", re.I)

    def matches(self, url: str) -> bool:
        h = _host(url)
        return any(h == p or h.endswith("." + p) for p in self.host_patterns)

    def application_url(self, url: str) -> str:
        return url

    def frame_supported(self, frame_url: str, top_url: str) -> bool:
        fh, th = _host(frame_url), _host(top_url)
        if not fh or frame_url.startswith(("about:", "javascript:")):
            return False
        return fh == th or any(fh == h or fh.endswith("." + h) for h in self.frame_hosts)

    def classify_button(self, text: str) -> str | None:
        t = re.sub(r"\s+", " ", text or "").strip()
        if not t or NEVER_CLICK.search(t):
            return None
        if SUBMIT_RE.match(t):
            return "submit"
        if NEXT_RE.match(t):
            return "next"
        return None

    def is_resume_field(self, field: dict) -> bool:
        return field["type"] == "file" and bool(self.resume_names.search(f"{field.get('label')} {field.get('name')}"))

    def confirmation(self, url: str, text: str) -> Confirmation:
        u = url or ""
        for pat in self.success_url_patterns:
            if re.search(pat, u, re.I):
                return Confirmation(True, f"url:{pat}", _snippet(text), _conf_id(text))
        for pat in tuple(self.success_text_patterns) + tuple(GENERIC_SUCCESS):
            m = re.search(pat, text or "", re.I)
            if m:
                return Confirmation(True, f"text:{m.group(0)}", _snippet(text, m.start()), _conf_id(text))
        return Confirmation(False)


def _snippet(text: str | None, at: int = 0) -> str | None:
    if not text:
        return None
    start = max(0, at - 80)
    return re.sub(r"\s+", " ", text[start: start + 300]).strip()


def _conf_id(text: str | None) -> str | None:
    m = CONFIRMATION_ID.search(text or "")
    return m.group(1) if m else None


class GreenhouseStrategy(AtsStrategy):
    name = "greenhouse"
    host_patterns = ("boards.greenhouse.io", "job-boards.greenhouse.io")
    success_url_patterns = (r"/confirmation\b", r"[?&]submitted=true")
    success_text_patterns = (r"thank you for applying", r"your application has been submitted")


class LeverStrategy(AtsStrategy):
    name = "lever"
    host_patterns = ("jobs.lever.co", "jobs.eu.lever.co")
    success_url_patterns = (r"/thanks/?(?:\?|$)",)
    success_text_patterns = (r"application submitted", r"thanks for applying")

    def application_url(self, url: str) -> str:
        m = re.match(r"(https?://jobs(?:\.eu)?\.lever\.co/[^/]+/[0-9a-f-]{36})(/apply)?", url or "", re.I)
        return f"{m.group(1)}/apply" if m else url


class AshbyStrategy(AtsStrategy):
    name = "ashby"
    host_patterns = ("jobs.ashbyhq.com",)
    success_text_patterns = (r"your application was successfully submitted", r"thank you for applying", r"application submitted")

    def application_url(self, url: str) -> str:
        m = re.match(r"(https?://jobs\.ashbyhq\.com/[^/]+/[0-9a-f-]{36})(/application)?", url or "", re.I)
        return f"{m.group(1)}/application" if m else url


class UnsupportedStrategy(AtsStrategy):
    supported = False

    def __init__(self, name: str):
        self.name = name


UNSUPPORTED_ATS = {"myworkdayjobs.com": "workday", "workday.com": "workday", "icims.com": "icims", "taleo.net": "taleo",
                   "successfactors": "successfactors", "smartrecruiters.com": "smartrecruiters", "workable.com": "workable",
                   "bamboohr.com": "bamboohr", "jobvite.com": "jobvite", "recruitee.com": "recruitee", "teamtailor.com": "teamtailor",
                   "breezy.hr": "breezy", "ultipro.com": "ultipro", "adp.com": "adp", "oraclecloud.com": "oracle"}
STRATEGIES = [GreenhouseStrategy(), LeverStrategy(), AshbyStrategy()]


def select_strategy(url: str, html: str = "") -> AtsStrategy:
    for s in STRATEGIES:
        if s.matches(url):
            return s
    h = _host(url)
    for key, name in UNSUPPORTED_ATS.items():
        if key in h:
            return UnsupportedStrategy(name)
    # Company page embedding a supported ATS form (e.g. Greenhouse iframe) → that ATS's knowledge applies
    low = (html or "").lower()
    if "boards.greenhouse.io/embed" in low or "grnhse_iframe" in low:
        return GreenhouseStrategy()
    return AtsStrategy()
