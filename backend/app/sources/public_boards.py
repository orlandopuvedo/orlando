"""Adapters for job boards that publish an official public API / feed."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from app.sources.base import JobSourceAdapter, SearchQuery, SourceSchemaError, expect, first, keyword_match


class RemotiveAdapter(JobSourceAdapter):
    key, name, base_url = "remotive", "Remotive", "https://remotive.com"
    automation_status = "allowed"
    has_official_api = True
    min_interval_minutes = 60
    terms_note = ("Official public API (remotive.com/api/remote-jobs). Terms: link back to Remotive as the source and "
                  "avoid excessive requests (a few times per day). Apply on Remotive/company site manually.")

    def search_jobs(self, q: SearchQuery) -> list[dict]:
        self._respect_rate_limit()
        params = {"limit": q.limit}
        if q.query:
            params["search"] = q.query
        r = self.http().get("https://remotive.com/api/remote-jobs", params=params)
        r.raise_for_status()
        out = []
        for j in expect(r.json(), dict, "jobs", self.name):
            out.append({
                "title": j.get("title"), "company": first(j, "company_name", "company"), "source_url": j.get("url"), "apply_url": j.get("url"),
                "description": j.get("description"), "location": j.get("candidate_required_location"), "remote_type": "remote",
                "employment_type": j.get("job_type"), "posted_at": j.get("publication_date"), "job_id_external": j.get("id"),
                "salary_text": j.get("salary"), "raw": {"category": j.get("category"), "tags": j.get("tags")},
            })
        return out


class RemoteOKAdapter(JobSourceAdapter):
    key, name, base_url = "remoteok", "Remote OK", "https://remoteok.com"
    automation_status = "allowed"
    has_official_api = True
    min_interval_minutes = 60
    terms_note = "Public JSON API (remoteok.com/api). Terms: credit Remote OK and link back to the listing URL."

    def search_jobs(self, q: SearchQuery) -> list[dict]:
        self._respect_rate_limit()
        r = self.http().get("https://remoteok.com/api")
        r.raise_for_status()
        out = []
        for j in expect(r.json(), list, None, self.name):
            if not isinstance(j, dict) or "position" not in j:
                continue  # first element is the legal notice
            raw = {"title": j.get("position"), "company": j.get("company"), "source_url": j.get("url"),
                   "apply_url": j.get("apply_url") or j.get("url"), "description": j.get("description"),
                   "location": j.get("location") or "Remote", "remote_type": "remote", "posted_at": j.get("date") or j.get("epoch"),
                   "job_id_external": j.get("id"), "salary_min": j.get("salary_min") or None, "salary_max": j.get("salary_max") or None,
                   "salary_currency": "USD" if j.get("salary_min") else None, "salary_period": "year" if j.get("salary_min") else None,
                   "tags": " ".join(j.get("tags") or []), "raw": {"tags": j.get("tags")}}
            if keyword_match(raw, q.query):
                out.append(raw)
            if len(out) >= q.limit:
                break
        return out


class HimalayasAdapter(JobSourceAdapter):
    key, name, base_url = "himalayas", "Himalayas", "https://himalayas.app"
    automation_status = "allowed"
    has_official_api = True
    min_interval_minutes = 30
    terms_note = "Public jobs API (himalayas.app/jobs/api). Attribute Himalayas and link to the job page."

    def search_jobs(self, q: SearchQuery) -> list[dict]:
        self._respect_rate_limit()
        out: list[dict] = []
        offset = 0
        while len(out) < q.limit and offset < 300:
            r = self.http().get("https://himalayas.app/jobs/api", params={"limit": 20, "offset": offset})
            r.raise_for_status()
            jobs = expect(r.json(), dict, "jobs", self.name)
            if not jobs:
                break
            for j in jobs:
                company = first(j, "companyName", "company_name", "company.name")
                if isinstance(company, dict):
                    company = company.get("name")
                period = str(first(j, "salaryPeriod", "salary_period", default="") or "").lower()
                period = {"annual": "year", "yearly": "year", "year": "year", "monthly": "month", "month": "month",
                          "hourly": "hour", "hour": "hour"}.get(period)
                smin = first(j, "minSalary", "min_salary", "salaryMin")
                link = first(j, "applicationLink", "applyUrl", "application_url", "url", "guid")
                raw = {"title": j.get("title"), "company": company, "source_url": link, "apply_url": link,
                       "description": first(j, "description", "excerpt"),
                       "location": ", ".join(first(j, "locationRestrictions", "location_restrictions", default=[]) or []) or "Remote",
                       "remote_type": "remote", "employment_type": first(j, "employmentType", "employment_type"),
                       "posted_at": first(j, "pubDate", "publishedAt", "published_at"),
                       "job_id_external": first(j, "guid", "id", "job_id", "applicationLink"),
                       "salary_min": smin, "salary_max": first(j, "maxSalary", "max_salary", "salaryMax"),
                       "salary_currency": first(j, "currency", "salaryCurrency") or ("USD" if smin else None),
                       "salary_period": period or ("year" if smin else None),
                       "tags": " ".join(first(j, "categories", default=[]) or []),
                       "raw": {"categories": j.get("categories"), "seniority": j.get("seniority")}}
                if not raw["title"]:
                    raise SourceSchemaError(f"{self.name}: listing without a title — the API format may have changed")
                if keyword_match(raw, q.query):
                    out.append(raw)
            offset += 20
        return out[: q.limit]


class WeWorkRemotelyAdapter(JobSourceAdapter):
    key, name, base_url = "weworkremotely", "We Work Remotely", "https://weworkremotely.com"
    automation_status = "allowed"
    has_official_api = True
    min_interval_minutes = 30
    terms_note = "Official RSS feeds (weworkremotely.com/remote-jobs.rss and category feeds). Link back to listings."
    FEEDS = {
        "all": "https://weworkremotely.com/remote-jobs.rss",
        "customer_support": "https://weworkremotely.com/categories/remote-customer-support-jobs.rss",
        "sales": "https://weworkremotely.com/categories/remote-sales-and-marketing-jobs.rss",
        "operations": "https://weworkremotely.com/categories/remote-management-and-finance-jobs.rss",
    }

    def search_jobs(self, q: SearchQuery) -> list[dict]:
        self._respect_rate_limit()
        feeds = [self.FEEDS[c] for c in q.categories if c in self.FEEDS] or [self.FEEDS["all"]]
        out: list[dict] = []
        for url in feeds:
            r = self.http().get(url)
            r.raise_for_status()
            out.extend(parse_wwr_rss(r.text))
        return [j for j in out if keyword_match(j, q.query)][: q.limit]


def parse_wwr_rss(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise SourceSchemaError(f"We Work Remotely: feed is not valid RSS/XML ({e})") from e
    out = []
    for item in root.iter("item"):
        title_raw = (item.findtext("title") or "").strip()
        company, title = (title_raw.split(":", 1) + [""])[:2] if ":" in title_raw else (None, title_raw)
        link = item.findtext("link")
        out.append({"title": (title or title_raw).strip(), "company": (company or "").strip() or None, "source_url": link,
                    "apply_url": link, "description": item.findtext("description"), "location": item.findtext("region") or "Remote",
                    "remote_type": "remote", "employment_type": item.findtext("type"), "posted_at": item.findtext("pubDate"),
                    "job_id_external": item.findtext("guid") or link, "raw": {"category": item.findtext("category")}})
    return out


# ---------------------------------------------------------------- company career pages (official ATS job-board APIs)
class GreenhouseAdapter(JobSourceAdapter):
    apply_automation_status = "review_required"
    key, name, base_url = "greenhouse", "Company boards (Greenhouse)", "https://boards.greenhouse.io"
    automation_status = "allowed"
    has_official_api = True
    terms_note = "Greenhouse Job Board API (public, read-only). Configure company board tokens in Settings → Company boards."

    def search_jobs(self, q: SearchQuery) -> list[dict]:
        out = []
        for token in q.config.get("boards", []):
            r = self.http().get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", params={"content": "true"})
            if r.status_code == 404:
                continue
            r.raise_for_status()
            for j in expect(r.json(), dict, "jobs", self.name):
                out.append(self._map(j, token))
        return [j for j in out if keyword_match(j, q.query)][: q.limit]

    def get_job(self, external_id: str, config: dict | None = None) -> dict | None:
        token = (config or {}).get("board")
        r = self.http().get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{external_id}")
        if r.status_code != 200:
            return None
        return self._map(r.json(), token)

    @staticmethod
    def _map(j: dict, token: str) -> dict:
        return {"title": j.get("title"), "company": (j.get("company_name") or token).replace("-", " ").title() if not j.get("company_name") else j.get("company_name"),
                "source_url": j.get("absolute_url"), "apply_url": j.get("absolute_url"), "description": j.get("content"),
                "location": (j.get("location") or {}).get("name"), "posted_at": j.get("updated_at"),
                "job_id_external": f"{token}:{j.get('id')}"}


class LeverAdapter(JobSourceAdapter):
    apply_automation_status = "review_required"
    key, name, base_url = "lever", "Company boards (Lever)", "https://jobs.lever.co"
    automation_status = "allowed"
    has_official_api = True
    terms_note = "Lever Postings API (public, read-only). Configure company site names in Settings → Company boards."

    def search_jobs(self, q: SearchQuery) -> list[dict]:
        out = []
        for site in q.config.get("boards", []):
            r = self.http().get(f"https://api.lever.co/v0/postings/{site}", params={"mode": "json"})
            if r.status_code == 404:
                continue
            r.raise_for_status()
            for j in expect(r.json(), list, None, self.name):
                out.append(self._map(j, site))
        return [j for j in out if keyword_match(j, q.query)][: q.limit]

    @staticmethod
    def _map(j: dict, site: str) -> dict:
        cats = j.get("categories") or {}
        sal = j.get("salaryRange") or {}
        lists = "\n".join(f"{x.get('text')}\n{re.sub('<[^>]+>', ' ', x.get('content') or '')}" for x in j.get("lists") or [])
        interval = {"per-year-salary": "year", "per-month-salary": "month", "per-hour-wage": "hour"}.get(sal.get("interval"))
        return {"title": j.get("text"), "company": site.replace("-", " ").title(), "source_url": j.get("hostedUrl"),
                "apply_url": j.get("applyUrl") or j.get("hostedUrl"),
                "description": "\n".join(x for x in [j.get("descriptionPlain"), lists, j.get("additionalPlain")] if x),
                "location": cats.get("location"), "employment_type": cats.get("commitment"),
                "remote_type": {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite"}.get((j.get("workplaceType") or "").lower()),
                "posted_at": j.get("createdAt"), "job_id_external": f"{site}:{j.get('id')}",
                "salary_min": sal.get("min"), "salary_max": sal.get("max"), "salary_currency": sal.get("currency"), "salary_period": interval}


class AshbyAdapter(JobSourceAdapter):
    apply_automation_status = "review_required"
    key, name, base_url = "ashby", "Company boards (Ashby)", "https://jobs.ashbyhq.com"
    automation_status = "allowed"
    has_official_api = True
    terms_note = "Ashby public Job Postings API (read-only). Configure company board names in Settings → Company boards."

    def search_jobs(self, q: SearchQuery) -> list[dict]:
        out = []
        for board in q.config.get("boards", []):
            r = self.http().get(f"https://api.ashbyhq.com/posting-api/job-board/{board}", params={"includeCompensation": "true"})
            if r.status_code == 404:
                continue
            r.raise_for_status()
            for j in expect(r.json(), dict, "jobs", self.name):
                wt = str(j.get("workplaceType") or "").lower()
                remote = "remote" if (j.get("isRemote") or wt == "remote") else {"hybrid": "hybrid", "onsite": "onsite", "on-site": "onsite"}.get(wt)
                out.append({"title": j.get("title"), "company": board.replace("-", " ").title(), "source_url": j.get("jobUrl"),
                            "apply_url": j.get("applyUrl") or j.get("jobUrl"), "description": j.get("descriptionPlain") or j.get("descriptionHtml"),
                            "location": j.get("location"), "employment_type": j.get("employmentType"),
                            "remote_type": remote, "posted_at": j.get("publishedAt"),
                            "job_id_external": f"{board}:{j.get('id')}",
                            "salary_text": first(j, "compensation.compensationTierSummary",
                                                 "compensation.scrapeableCompensationSalarySummary", "compensationTierSummary", default="")})
        return [j for j in out if keyword_match(j, q.query)][: q.limit]
