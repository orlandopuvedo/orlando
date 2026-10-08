"""Cross-source duplicate detection → one canonical Job with many JobSourceRefs."""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Job, JobSourceRef
from app.services.text_utils import normalize_company, normalize_text, normalize_title, text_similarity


@dataclass
class DuplicateMatch:
    job: Job
    reason: str
    confidence: float


def _locations_compatible(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return True
    na, nb = normalize_text(a), normalize_text(b)
    if na == nb or "remote" in na or "remote" in nb or "anywhere" in na or "anywhere" in nb:
        return True
    ta, tb = set(na.split()), set(nb.split())
    return bool(ta & tb)


def compare_jobs(a, b) -> tuple[bool, str, float]:
    """Pure comparison of two job-like objects (no DB). Returns (is_dup, reason, confidence)."""
    if a.canonical_url and b.canonical_url and a.canonical_url == b.canonical_url:
        return True, "canonical_url", 1.0
    ca, cb = normalize_company(a.company), normalize_company(b.company)
    if not ca or not cb or ca != cb:
        return False, "", 0.0
    ta, tb = normalize_title(a.title), normalize_title(b.title)
    title_ratio = 1.0 if ta == tb else SequenceMatcher(None, ta, tb).ratio()
    if title_ratio < 0.85:
        return False, "", 0.0
    if not _locations_compatible(a.location, b.location):
        return False, "", 0.0
    if a.description and b.description:
        sim = text_similarity(a.description, b.description)
        if title_ratio == 1.0 and sim >= 0.45:
            return True, f"company+title+description ({sim:.2f})", 0.9
        if sim >= 0.8:
            return True, f"company+similar title+description ({sim:.2f})", 0.85
        return False, "", 0.0
    if title_ratio == 1.0:
        return True, "company+title+location", 0.75
    return False, "", 0.0


def find_duplicate(db: Session, nj, exclude_id: int | None = None) -> DuplicateMatch | None:
    # 1) same source listing already ingested
    if nj.job_id_external:
        ref = db.scalar(select(JobSourceRef).where(JobSourceRef.source == nj.source, JobSourceRef.external_id == nj.job_id_external))
        if ref and ref.job_id != exclude_id:
            return DuplicateMatch(ref.job, "external_id", 1.0)
    # 2) canonical URL across jobs and refs
    if nj.canonical_url:
        job = db.scalar(select(Job).where(Job.canonical_url == nj.canonical_url, Job.id != (exclude_id or -1)))
        if job:
            return DuplicateMatch(job, "canonical_url", 1.0)
        ref = db.scalar(select(JobSourceRef).where(JobSourceRef.canonical_url == nj.canonical_url))
        if ref and ref.job_id != exclude_id:
            return DuplicateMatch(ref.job, "canonical_url", 1.0)
    # 3) same company + (near) same title + compatible location + similar description
    comp = normalize_company(nj.company)
    if not comp:
        return None
    first_word = comp.split()[0]
    candidates = db.scalars(
        select(Job).where(Job.company.is_not(None), Job.id != (exclude_id or -1), or_(Job.company.ilike(f"%{first_word}%")))
    ).all()
    best: DuplicateMatch | None = None
    for cand in candidates:
        is_dup, reason, conf = compare_jobs(nj, cand)
        if is_dup and (best is None or conf > best.confidence):
            best = DuplicateMatch(cand, reason, conf)
    return best
