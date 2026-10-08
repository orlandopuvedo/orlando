"""Small text helpers shared by parsing, scoring and dedupe."""
from __future__ import annotations

import html
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_BLOCK_TAGS = re.compile(r"</?(p|div|br|li|ul|ol|h[1-6]|tr|section|article)[^>]*>", re.I)

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "refid", "trk",
    "trackingid", "src", "source", "gh_src", "lever-source", "lever-origin", "fbclid", "gclid", "from",
}


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    text = html.unescape(value)
    if "<" in text and ">" in text:
        text = re.sub(r"<li[^>]*>", "\n• ", text, flags=re.I)
        text = _BLOCK_TAGS.sub("\n", text)
        text = _TAG_RE.sub("", text)
        text = html.unescape(text)
    lines = [_WS_RE.sub(" ", ln).strip() for ln in text.splitlines()]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()


def strip_accents(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    v = strip_accents(value.lower())
    v = re.sub(r"[^a-z0-9+#.\s]", " ", v)
    return re.sub(r"\s+", " ", v).strip()


COMPANY_SUFFIXES = re.compile(
    r"\b(inc|incorporated|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|gmbh|s\.a|sa|srl|plc|bv|ag|pty|oy|ab)\b\.?",
    re.I,
)


def normalize_company(value: str | None) -> str:
    if not value:
        return ""
    v = strip_accents(value.lower())
    v = COMPANY_SUFFIXES.sub(" ", v)
    v = re.sub(r"[^a-z0-9]+", " ", v)
    return re.sub(r"\s+", " ", v).strip()


TITLE_NOISE = re.compile(r"\b(remote|100%|fully|anywhere|worldwide|wfh|work from home|urgent|hiring|immediate start)\b", re.I)


def normalize_title(value: str | None) -> str:
    if not value:
        return ""
    v = re.sub(r"\(.*?\)|\[.*?\]", " ", value)
    v = TITLE_NOISE.sub(" ", v)
    v = v.replace("Sr.", "Senior").replace("Sr ", "Senior ").replace("Jr.", "Junior").replace("Jr ", "Junior ")
    v = normalize_text(v)
    v = re.sub(r"\s*[-|/–]\s*$", "", v)
    return v.strip(" -|")


def canonical_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        return None
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]
    path = re.sub(r"/+$", "", parts.path) or "/"
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False) if k.lower() not in TRACKING_PARAMS]
    # LinkedIn: /jobs/view/<slug>-<id> → id only
    m = re.search(r"linkedin\.com$", host) and re.search(r"/jobs/view/(?:.*-)?(\d{6,})", path)
    if m:
        return f"https://linkedin.com/jobs/view/{m.group(1)}"
    if "indeed." in host:
        jk = dict(query).get("jk") or dict(query).get("vjk")
        if jk:
            return f"https://{host}/viewjob?jk={jk}"
    return urlunsplit(("https", host, path, urlencode(sorted(query)), ""))


def tokens(value: str | None) -> list[str]:
    return [t for t in normalize_text(value).split() if t]


STOPWORDS = set(
    """a an and are as at be by for from has have in is it its of on or that the this to was were will with you your
    we our us they their them i me my he she his her not but if so than then there these those can could should would
    may might must do does did done about into over under up down out more most other some such only own same too very
    just also any each few all both who whom which what when where why how""".split()
)


def shingles(text: str | None, k: int = 3) -> set[str]:
    words = [w for w in tokens(text) if w not in STOPWORDS]
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + k]) for i in range(len(words) - k + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def text_similarity(a: str | None, b: str | None) -> float:
    """Shingle Jaccard similarity of two descriptions (0..1)."""
    return jaccard(shingles(a), shingles(b))


def contains_term(text_norm: str, term: str) -> bool:
    """Whole-word / phrase match of a (normalized) term within normalized text."""
    t = normalize_text(term)
    if not t:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", text_norm) is not None
