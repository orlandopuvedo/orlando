"""Import a single job from a URL the user provides.

* Greenhouse / Lever / Ashby URLs → their official public job-board APIs.
* Sites that prohibit automated access (LinkedIn, Indeed, ...) → refused; paste the description instead.
* Other company career pages → one user-initiated fetch, reading only schema.org JobPosting JSON-LD.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

import httpx

from app.config import get_settings
from app.services.text_utils import html_to_text

BLOCKED = {"linkedin.com": "LinkedIn", "indeed.": "Indeed", "glassdoor.": "Glassdoor", "wellfound.com": "Wellfound",
           "flexjobs.com": "FlexJobs", "upwork.com": "Upwork", "ziprecruiter.": "ZipRecruiter"}


class UrlImportError(ValueError):
    pass


def _client() -> httpx.Client:
    s = get_settings()
    return httpx.Client(timeout=s.http_timeout_seconds, follow_redirects=True, headers={"User-Agent": s.http_user_agent})


def import_from_url(url: str, client: httpx.Client | None = None) -> tuple[dict, str]:
    """Returns (raw job dict, source key)."""
    url = url.strip()
    host = urlsplit(url).netloc.lower()
    for dom, name in BLOCKED.items():
        if dom in host:
            raise UrlImportError(f"{name} does not allow automated access. Open the job, copy the description and use “Paste job”.")
    c = client or _client()
    m = re.search(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)", url)
    if m:
        from app.sources.public_boards import GreenhouseAdapter

        raw = GreenhouseAdapter(c).get_job(m.group(2), {"board": m.group(1)})
        if raw:
            return raw, "greenhouse"
    m = re.search(r"jobs\.lever\.co/([\w-]+)/([0-9a-f-]{36})", url)
    if m:
        r = c.get(f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}", params={"mode": "json"})
        if r.status_code == 200:
            from app.sources.public_boards import LeverAdapter

            return LeverAdapter._map(r.json(), m.group(1)), "lever"
    try:
        r = c.get(url)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise UrlImportError(f"Could not fetch the page ({e}). Paste the description instead.") from e
    raw = parse_jsonld_jobposting(r.text)
    if not raw:
        raise UrlImportError("No structured job data found on this page. Paste the description instead.")
    raw.setdefault("source_url", url)
    raw.setdefault("apply_url", url)
    return raw, "manual"


def parse_jsonld_jobposting(html: str) -> dict | None:
    for m in re.finditer(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", html or "", re.S | re.I):
        try:
            data = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for it in items:
            if isinstance(it, dict) and it.get("@type") in ("JobPosting", ["JobPosting"]):
                return _map_jobposting(it)
    return None


def _map_jobposting(it: dict) -> dict:
    org = it.get("hiringOrganization") or {}
    loc = it.get("jobLocation") or {}
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    addr = (loc.get("address") or {}) if isinstance(loc, dict) else {}
    sal = it.get("baseSalary") or {}
    val = sal.get("value") or {} if isinstance(sal, dict) else {}
    unit = (val.get("unitText") or "").lower() if isinstance(val, dict) else ""
    return {
        "title": it.get("title"), "company": org.get("name") if isinstance(org, dict) else org,
        "company_url": org.get("sameAs") if isinstance(org, dict) else None,
        "description": html_to_text(it.get("description") or ""),
        "location": ", ".join(x for x in [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry") if isinstance(addr.get("addressCountry"), str) else None] if x) or None,
        "remote_type": "remote" if it.get("jobLocationType") == "TELECOMMUTE" else None,
        "employment_type": it.get("employmentType") if isinstance(it.get("employmentType"), str) else None,
        "posted_at": it.get("datePosted"),
        "salary_min": val.get("minValue") if isinstance(val, dict) else None,
        "salary_max": val.get("maxValue") if isinstance(val, dict) else None,
        "salary_currency": sal.get("currency") if isinstance(sal, dict) else None,
        "salary_period": {"hour": "hour", "day": "day", "week": "week", "month": "month", "year": "year"}.get(unit),
        "job_id_external": (it.get("identifier") or {}).get("value") if isinstance(it.get("identifier"), dict) else None,
        "source_url": it.get("url"),
    }
