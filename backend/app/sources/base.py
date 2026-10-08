"""JobSourceAdapter interface. Every job source implements this — no scraping, no bypassing protections."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import get_settings
from app.services.normalization import NormalizedJob, normalize_job

AUTOMATION_STATUSES = ("allowed", "review_required", "manual_only", "unknown")


class SourceNotSupported(RuntimeError):
    """Raised when a source has no permitted automated access (manual import only)."""


@dataclass
class SearchQuery:
    query: str = ""
    limit: int = 50
    remote_only: bool = True
    categories: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)


class JobSourceAdapter(ABC):
    key: str = "base"
    name: str = "Base"
    base_url: str = ""
    automation_status: str = "unknown"          # searching / reading listings
    apply_automation_status: str = "manual_only"  # submitting applications through the platform
    has_official_api: bool = False
    terms_note: str = ""
    min_interval_minutes: int = 0  # politeness / ToS-requested rate limit
    _last_call: dict[str, float] = {}

    def __init__(self, client: httpx.Client | None = None):
        self._client = client

    # -- HTTP helper (honours rate limits; identifies itself honestly)
    def http(self) -> httpx.Client:
        if self._client is None:
            s = get_settings()
            self._client = httpx.Client(timeout=s.http_timeout_seconds, follow_redirects=True,
                                        headers={"User-Agent": s.http_user_agent, "Accept": "application/json, application/rss+xml, */*"})
        return self._client

    def _respect_rate_limit(self) -> None:
        if not self.min_interval_minutes:
            return
        last = JobSourceAdapter._last_call.get(self.key)
        if last and time.time() - last < self.min_interval_minutes * 60:
            raise SourceNotSupported(f"{self.name}: rate limit — wait {self.min_interval_minutes} min between searches (source terms).")
        JobSourceAdapter._last_call[self.key] = time.time()

    @abstractmethod
    def search_jobs(self, q: SearchQuery) -> list[dict]:
        """Return raw job dicts (already mapped to our loose schema keys)."""

    def get_job(self, external_id: str, config: dict | None = None) -> dict | None:
        return None

    def normalize_job(self, raw: dict, usd_rates: dict | None = None) -> NormalizedJob:
        return normalize_job(raw, source=self.key, usd_rates=usd_rates)

    def detect_duplicate(self, db, nj: NormalizedJob):
        from app.services.dedupe import find_duplicate

        return find_duplicate(db, nj)

    def info(self) -> dict:
        return {"key": self.key, "name": self.name, "base_url": self.base_url, "automation_status": self.automation_status,
                "apply_automation_status": self.apply_automation_status, "has_official_api": self.has_official_api,
                "terms_note": self.terms_note, "searchable": self.automation_status in ("allowed", "review_required")}


def keyword_match(raw: dict, query: str) -> bool:
    if not query:
        return True
    blob = " ".join(str(raw.get(k) or "") for k in ("title", "company", "description", "category", "tags")).lower()
    terms = [t.strip().lower() for t in query.replace(" OR ", "|").split("|") if t.strip()]
    return any(all(w in blob for w in t.split()) for t in terms)


class ManualOnlyAdapter(JobSourceAdapter):
    """Sources without a permitted public API: use manual import (paste URL / description)."""

    def __init__(self, key: str, name: str, base_url: str, note: str, automation_status: str = "manual_only"):
        super().__init__()
        self.key, self.name, self.base_url, self.terms_note = key, name, base_url, note
        self.automation_status = automation_status

    def search_jobs(self, q: SearchQuery) -> list[dict]:
        raise SourceNotSupported(f"{self.name} has no permitted automated search. Import jobs manually (paste link + description).")
