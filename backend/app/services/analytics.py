"""Funnel metrics, breakdowns, time series and learning-based recommendations."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Application, ApplicationStatusHistory, ApprovalRequest, Contact, FollowUp, Interview, Job, Resume, Video,
)
from app.services.detection import CATEGORY_LABELS
from app.services.profile_service import get_profile, profile_completeness
from app.services.settings_service import get_all_settings

INTERVIEW_STAGES = {"INTERVIEW", "OFFER", "HIRED"}
OFFER_STAGES = {"OFFER", "HIRED"}


def _app_facts(db: Session) -> list[dict]:
    """One row per submitted application with the furthest stage reached."""
    apps = db.scalars(select(Application).where(Application.applied_at.is_not(None))).all()
    hist: dict[int, set[str]] = defaultdict(set)
    for h in db.scalars(select(ApplicationStatusHistory)):
        hist[h.application_id].add(h.to_status)
    iv_by_app: dict[int, list[Interview]] = defaultdict(list)
    iv_by_job: dict[int, list[Interview]] = defaultdict(list)
    for iv in db.scalars(select(Interview).where(Interview.status != "CANCELLED")):
        if iv.application_id:
            iv_by_app[iv.application_id].append(iv)
        if iv.job_id:
            iv_by_job[iv.job_id].append(iv)
    resumes = {r.id: r.name for r in db.scalars(select(Resume))}
    contacts = {c.id: c.contact_source for c in db.scalars(select(Contact))}
    rows = []
    for a in apps:
        stages = hist[a.id] | {a.status}
        ivs = iv_by_app.get(a.id) or iv_by_job.get(a.job_id) or []
        job = a.job
        top = job.salary_monthly_usd_max or job.salary_monthly_usd_min
        rows.append({
            "id": a.id, "job_id": a.job_id, "applied_at": a.applied_at, "status": a.status,
            "source": job.source or "manual", "category": job.category or "other", "company": job.company or "Unknown",
            "salary": top, "match": job.match_score,
            "resume": resumes.get(a.resume_id) or ("Tailored from profile" if a.resume_version_id else "None"),
            "application_type": a.application_type or ("easy_apply" if job.easy_apply else "standard"),
            "contact_source": contacts.get(a.contact_id) or "none",
            "responded": a.response_received_at is not None,
            "interview": bool(stages & INTERVIEW_STAGES) or bool(ivs),
            "final": any(iv.is_final for iv in ivs) or bool(stages & OFFER_STAGES),
            "offer": bool(stages & OFFER_STAGES), "hired": "HIRED" in stages,
            "offer_amount": a.offer_amount_monthly_usd or (top if stages & OFFER_STAGES else None),
        })
    return rows


def _rate(n: int, d: int) -> float:
    return round(n / d, 4) if d else 0.0


def _k(v: float) -> str:
    return f"{v / 1000:.1f}".rstrip("0").rstrip(".") + "k"


def salary_bucket(v: float | None, edges: list[float] | None = None) -> str:
    """Bucket by the USER'S configured salary bounds (min / target / stretch), monthly USD."""
    if v is None:
        return "Not listed"
    edges = sorted({e for e in (edges or []) if e})
    if not edges:
        return "Listed"
    if v < edges[0]:
        return f"< ${_k(edges[0])}"
    for a, b in zip(edges, edges[1:]):
        if v < b:
            return f"${_k(a)}–{_k(b)}"
    return f"${_k(edges[-1])}+"


def breakdown(rows: list[dict], key: str, label_map: dict | None = None, edges: list[float] | None = None) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        k = r[key] if key != "salary" else salary_bucket(r["salary"], edges)
        groups[str(k)].append(r)
    out = []
    for k, items in groups.items():
        n = len(items)
        resp = sum(i["responded"] for i in items)
        ivs = sum(i["interview"] for i in items)
        offers = sum(i["offer"] for i in items)
        matches = [i["match"] for i in items if i["match"] is not None]
        out.append({"key": k, "label": (label_map or {}).get(k, k), "applications": n, "responses": resp, "interviews": ivs,
                    "offers": offers, "response_rate": _rate(resp, n), "interview_rate": _rate(ivs, n), "offer_rate": _rate(offers, n),
                    "avg_match": round(sum(matches) / len(matches), 1) if matches else None})
    return sorted(out, key=lambda x: x["applications"], reverse=True)


def time_series(rows: list[dict]) -> dict:
    today = date.today()
    per_day = {(today - timedelta(days=i)).isoformat(): 0 for i in range(29, -1, -1)}
    per_week: dict[str, int] = {}
    for i in range(11, -1, -1):
        d = today - timedelta(weeks=i)
        per_week[f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"] = 0
    per_month: dict[str, int] = {}
    y, m = today.year, today.month
    months = []
    for _ in range(12):
        months.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    for k in reversed(months):
        per_month[k] = 0
    for r in rows:
        d = r["applied_at"].astimezone().date() if r["applied_at"].tzinfo else r["applied_at"].date()
        if d.isoformat() in per_day:
            per_day[d.isoformat()] += 1
        wk = f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"
        if wk in per_week:
            per_week[wk] += 1
        mk = f"{d.year}-{d.month:02d}"
        if mk in per_month:
            per_month[mk] += 1
    return {"per_day": [{"date": k, "count": v} for k, v in per_day.items()],
            "per_week": [{"week": k, "count": v} for k, v in per_week.items()],
            "per_month": [{"month": k, "count": v} for k, v in per_month.items()]}


def recommendations(rows: list[dict], by_category: list[dict], extra: dict | None = None) -> list[dict]:
    recs: list[dict] = []
    extra = extra or {}
    n = len(rows)
    overall_iv = _rate(sum(r["interview"] for r in rows), n)
    eligible = [c for c in by_category if c["applications"] >= 5]
    if eligible:
        best = sorted(eligible, key=lambda c: (c["interview_rate"], c["response_rate"]), reverse=True)
        winners = [c for c in best if c["interview_rate"] > 0 and c["interview_rate"] >= overall_iv][:2]
        if winners:
            names = " and ".join(CATEGORY_LABELS.get(c["key"], c["key"]) for c in winners)
            recs.append({"type": "increase", "priority": "high",
                         "message": f"Increase {names} applications.",
                         "detail": "; ".join(f"{CATEGORY_LABELS.get(c['key'], c['key'])}: {c['applications']} apps → {c['interviews']} interviews ({c['interview_rate']:.0%})" for c in winners)})
        for c in best[::-1]:
            if c["applications"] >= 15 and (c["interview_rate"] < overall_iv / 2 or c["interviews"] == 0):
                recs.append({"type": "reduce", "priority": "medium",
                             "message": f"Reduce or rethink {CATEGORY_LABELS.get(c['key'], c['key'])} applications.",
                             "detail": f"{c['applications']} apps → {c['responses']} responses, {c['interviews']} interviews."})
                break
    if n >= 20 and _rate(sum(r["responded"] for r in rows), n) < 0.05:
        recs.append({"type": "quality", "priority": "high", "message": "Response rate is under 5%. Tighten targeting (raise the minimum match score) and tailor resumes for every application."})
    if extra.get("today_applications", 0) < extra.get("daily_target", 0):
        recs.append({"type": "volume", "priority": "medium",
                     "message": f"{extra['daily_target'] - extra['today_applications']} more application(s) to reach today's target ({extra['daily_target']})."})
    if extra.get("queue_size", 0) == 0:
        recs.append({"type": "pipeline", "priority": "medium", "message": "Apply Queue is empty — add jobs or run a job search."})
    if extra.get("video_jobs_without_video"):
        recs.append({"type": "video", "priority": "medium", "message": "Some good matches require a video. Add your Loom introduction(s) to the Video Library."})
    if extra.get("profile_percent", 100) < 80:
        recs.append({"type": "profile", "priority": "high", "message": f"Your Master Profile is {extra['profile_percent']}% complete — better data means better matches."})
    return recs


def _salary_edges(db: Session) -> list[float]:
    from app.services.profile_service import salary_bounds_monthly_usd

    b = salary_bounds_monthly_usd(get_profile(db), get_all_settings(db).get("usd_rates") or {})
    return [x for x in (b["min"], b["target"], b["target_max"]) if x]


def compute_analytics(db: Session) -> dict:
    rows = _app_facts(db)
    by_cat = breakdown(rows, "category", CATEGORY_LABELS)
    n = len(rows)
    salaries = [r["salary"] for r in rows if r["salary"]]
    matches = [r["match"] for r in rows if r["match"] is not None]
    return {
        "totals": {"applications": n, "responses": sum(r["responded"] for r in rows), "interviews": sum(r["interview"] for r in rows),
                   "offers": sum(r["offer"] for r in rows)},
        "rates": {"response_rate": _rate(sum(r["responded"] for r in rows), n), "interview_rate": _rate(sum(r["interview"] for r in rows), n),
                  "offer_rate": _rate(sum(r["offer"] for r in rows), n)},
        "average_salary": round(sum(salaries) / len(salaries)) if salaries else None,
        "average_match_score": round(sum(matches) / len(matches), 1) if matches else None,
        "time_series": time_series(rows),
        "breakdowns": {
            "source": breakdown(rows, "source"), "category": by_cat, "company": breakdown(rows, "company")[:20],
            "salary_range": breakdown(rows, "salary", edges=_salary_edges(db)), "resume_version": breakdown(rows, "resume"),
            "application_type": breakdown(rows, "application_type"), "contact_source": breakdown(rows, "contact_source"),
        },
        "recommendations": recommendations(rows, by_cat),
    }


PROGRESS_STAGES = [("hired", 100, "Hired 🎉"), ("offer", 90, "Offer received"), ("final", 75, "Final interview"),
                   ("interview", 55, "Interviewing"), ("responded", 35, "Getting responses"), ("applied", 15, "Applying")]


def compute_dashboard(db: Session) -> dict:
    settings = get_all_settings(db)
    profile = get_profile(db)
    rows = _app_facts(db)
    n_apps = len(rows)
    jobs_found = db.scalar(select(func.count()).select_from(Job)) or 0
    qualified = db.scalar(select(func.count()).select_from(Job).where(Job.match_score >= settings["min_match_score"])) or 0
    responses = sum(r["responded"] for r in rows)
    interviews_apps = sum(r["interview"] for r in rows)
    finals = sum(r["final"] for r in rows)
    offers = sum(r["offer"] for r in rows)
    hired = sum(r["hired"] for r in rows)
    contacts = db.scalar(select(func.count()).select_from(Contact)) or 0
    interviews_total = db.scalar(select(func.count()).select_from(Interview).where(Interview.status != "CANCELLED")) or 0
    finals_total = db.scalar(select(func.count()).select_from(Interview).where(Interview.is_final.is_(True), Interview.status != "CANCELLED")) or 0

    offer_values = [r["offer_amount"] for r in rows if r["offer"] and r["offer_amount"]]
    applied_salaries = [r["salary"] for r in rows if r["salary"]]
    today = date.today()
    today_apps = sum(1 for r in rows if (r["applied_at"].astimezone().date() if r["applied_at"].tzinfo else r["applied_at"].date()) == today)
    queue_size = db.scalar(select(func.count()).select_from(Job).where(Job.in_queue.is_(True), Job.archived.is_(False))) or 0
    has_video = (db.scalar(select(func.count()).select_from(Video).where(Video.is_active.is_(True), Video.url.is_not(None))) or 0) > 0
    video_jobs = db.scalar(select(func.count()).select_from(Job).where(Job.video_required.is_(True), Job.in_queue.is_(True))) or 0

    stage_flags = {"hired": hired > 0, "offer": offers > 0, "final": finals > 0 or finals_total > 0,
                   "interview": interviews_apps > 0 or interviews_total > 0, "responded": responses > 0, "applied": n_apps > 0}
    progress, stage_label = 5, "Getting started"
    for key, pct, label in PROGRESS_STAGES:
        if stage_flags[key]:
            progress, stage_label = pct, label
            break

    upcoming = db.scalars(select(Interview).where(Interview.status == "SCHEDULED", Interview.scheduled_at.is_not(None))
                          .order_by(Interview.scheduled_at).limit(5)).all()
    due = db.scalars(select(FollowUp).where(FollowUp.status == "PENDING", FollowUp.due_date <= today + timedelta(days=2))
                     .order_by(FollowUp.due_date).limit(8)).all()
    queue = db.scalars(select(Job).where(Job.in_queue.is_(True), Job.archived.is_(False))
                       .order_by(Job.priority_score.desc().nullslast()).limit(6)).all()
    pending_approvals = db.scalar(select(func.count()).select_from(ApprovalRequest).where(ApprovalRequest.status == "PENDING")) or 0
    completeness = profile_completeness(profile)
    by_cat = breakdown(rows, "category", CATEGORY_LABELS)

    from app.services.profile_service import salary_bounds_monthly_usd

    bounds = salary_bounds_monthly_usd(profile, settings.get("usd_rates") or {})
    min_target = bounds["min"]
    return {
        "metrics": {"jobs_found": jobs_found, "qualified": qualified, "applications": n_apps, "responses": responses,
                    "contacts": contacts, "interviews": max(interviews_apps, interviews_total),
                    "final_interviews": max(finals, finals_total), "offers": offers, "hired": hired},
        "funnel": [
            {"stage": "Jobs Found", "count": jobs_found}, {"stage": "Qualified", "count": qualified},
            {"stage": "Applications", "count": n_apps}, {"stage": "Responses", "count": responses},
            {"stage": "Interviews", "count": max(interviews_apps, interviews_total)},
            {"stage": "Final Interviews", "count": max(finals, finals_total)}, {"stage": "Offers", "count": offers},
            {"stage": "Hired", "count": hired},
        ],
        "salary": {"monthly_target": min_target, "target_range": [bounds["target"], bounds["target_max"] or bounds["max"]],
                   "current_offer_value": max(offer_values) if offer_values else None,
                   "average_target_salary": round(sum(applied_salaries) / len(applied_salaries)) if applied_salaries else None,
                   "offer_meets_target": bool(offer_values and min_target is not None and max(offer_values) >= min_target)},
        "rates": {"application_success_rate": _rate(responses, n_apps), "interview_rate": _rate(interviews_apps, n_apps),
                  "offer_rate": _rate(offers, n_apps)},
        "progress": {"percent": progress, "stage": stage_label, "today_applications": today_apps,
                     "daily_target": settings["daily_application_target"]},
        "queue": [{"id": j.id, "title": j.title, "company": j.company, "match_score": j.match_score, "priority_score": j.priority_score,
                   "classification": j.classification, "video_required": j.video_required,
                   "salary_max": j.salary_monthly_usd_max or j.salary_monthly_usd_min} for j in queue],
        "queue_size": queue_size,
        "upcoming_interviews": [{"id": i.id, "company": i.company, "scheduled_at": i.scheduled_at, "interview_type": i.interview_type,
                                 "interview_number": i.interview_number, "is_final": i.is_final, "meeting_url": i.meeting_url} for i in upcoming],
        "due_follow_ups": [{"id": f.id, "title": f.title, "due_date": f.due_date, "kind": f.kind} for f in due],
        "pending_approvals": pending_approvals,
        "profile_completeness": completeness,
        "recommendations": recommendations(rows, by_cat, {"today_applications": today_apps, "daily_target": settings["daily_application_target"],
                                                          "queue_size": queue_size, "video_jobs_without_video": video_jobs > 0 and not has_video,
                                                          "profile_percent": completeness["percent"]}),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
