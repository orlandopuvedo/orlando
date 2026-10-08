"""Loom integration — URL storage + optional metadata via Loom's public oEmbed endpoint.

Loom's official developer offering (recordSDK / embedSDK) is for embedding recording into *your own* web app;
it does not let a third party fetch or submit a user's videos into job applications. So this adapter only:
  * validates/normalizes share URLs, and
  * reads public metadata (title, duration, thumbnail) through oEmbed when reachable.
No scraping, no private API usage.
"""
from __future__ import annotations

import re

import httpx

from app.config import get_settings

LOOM_RE = re.compile(r"^https?://(?:www\.)?loom\.com/(?:share|embed)/([a-f0-9]{16,})", re.I)


def is_loom_url(url: str | None) -> bool:
    return bool(url and LOOM_RE.match(url.strip()))


def normalize_loom_url(url: str) -> str:
    m = LOOM_RE.match(url.strip())
    return f"https://www.loom.com/share/{m.group(1)}" if m else url.strip()


def detect_platform(url: str | None) -> str:
    u = (url or "").lower()
    for key, name in [("loom.com", "loom"), ("youtube.com", "youtube"), ("youtu.be", "youtube"), ("vimeo.com", "vimeo"),
                      ("drive.google.com", "google_drive"), ("vidyard.com", "vidyard"), ("dropbox.com", "dropbox")]:
        if key in u:
            return name
    return "other"


def fetch_loom_metadata(url: str, client: httpx.Client | None = None) -> dict:
    if not is_loom_url(url):
        return {"ok": False, "error": "Not a Loom share URL"}
    s = get_settings()
    c = client or httpx.Client(timeout=s.http_timeout_seconds, headers={"User-Agent": s.http_user_agent})
    try:
        r = c.get("https://www.loom.com/v1/oembed", params={"url": normalize_loom_url(url)})
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        return {"ok": False, "error": f"Could not fetch Loom metadata: {e}"}
    duration = data.get("duration")
    return {"ok": True, "title": data.get("title"), "duration_seconds": int(float(duration)) if duration else None,
            "thumbnail_url": data.get("thumbnail_url"), "provider": data.get("provider_name", "Loom")}
