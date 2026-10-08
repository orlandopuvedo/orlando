from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import provider_status
from app.api.deps import DB, apply_updates, get_or_404, to_dict
from app.models import Company, JobSearch, JobSearchRun, JobSource, Notification
from app.services.analytics import compute_analytics, compute_dashboard
from app.services.detection import CATEGORY_LABELS
from app.services.followups import refresh_reminders
from app.services.jobs_service import ingest_job, rescore_all, _rates
from app.services.scheduler import scheduler
from app.services.settings_service import DEFAULTS, get_all_settings, update_settings
from app.sources import SearchQuery, SourceNotSupported, get_adapter, sync_sources

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/dashboard")
def dashboard(db: Session = DB):
    refresh_reminders(db)
    return compute_dashboard(db)


@router.get("/analytics")
def analytics(db: Session = DB):
    return compute_analytics(db)


@router.get("/meta")
def meta():
    return {"categories": CATEGORY_LABELS}


# ---------------------------------------------------------------- notifications
@router.get("/notifications")
def notifications(unread_only: bool = False, limit: int = 50, db: Session = DB):
    q = select(Notification).order_by(Notification.created_at.desc()).limit(limit)
    if unread_only:
        q = q.where(Notification.is_read.is_(False))
    unread = db.scalar(select(func.count()).select_from(Notification).where(Notification.is_read.is_(False)))
    return {"unread": unread, "items": [to_dict(n) for n in db.scalars(q)]}


@router.post("/notifications/{nid}/read")
def read_notification(nid: int, db: Session = DB):
    n = get_or_404(db, Notification, nid)
    n.is_read = True
    db.commit()
    return to_dict(n)


@router.post("/notifications/read-all")
def read_all(db: Session = DB):
    for n in db.scalars(select(Notification).where(Notification.is_read.is_(False))):
        n.is_read = True
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- settings
@router.get("/settings")
def get_settings_api(db: Session = DB):
    return {"settings": get_all_settings(db), "defaults": DEFAULTS, "ai": provider_status()}


@router.put("/settings")
def put_settings(data: dict[str, Any], db: Session = DB):
    if "application_mode" in data and data["application_mode"] not in ("copilot", "supervised", "auto"):
        raise HTTPException(422, "application_mode must be copilot, supervised or auto")
    rescore = any(k in data for k in ("score_weights", "priority_weights", "min_match_score", "queue_min_score",
                                      "excluded_categories", "preferred_categories", "job_search", "usd_rates"))
    s = update_settings(db, data)
    if rescore:
        rescore_all(db)
    return {"settings": s, "ai": provider_status(s.get("ai_provider"), s.get("ai_model") or None)}


@router.post("/settings/ai-test")
def ai_test(db: Session = DB):
    s = get_all_settings(db)
    from app.ai.registry import test_provider

    return test_provider(s.get("ai_provider"), s.get("ai_model") or None)


@router.get("/settings/ai-status")
def ai_status(db: Session = DB):
    s = get_all_settings(db)
    return provider_status(s.get("ai_provider"), s.get("ai_model") or None)


# ---------------------------------------------------------------- sources & searches
@router.get("/sources")
def list_sources(db: Session = DB):
    return [to_dict(s) for s in sync_sources(db)]


@router.put("/sources/{key}")
def update_source(key: str, data: dict[str, Any], db: Session = DB):
    src = db.scalar(select(JobSource).where(JobSource.key == key))
    if not src:
        raise HTTPException(404, "Unknown source")
    if data.get("enabled") and src.automation_status != "allowed":
        raise HTTPException(409, f"{src.name} is {src.automation_status}: automated search is not enabled. Use manual import.")
    apply_updates(src, data, {"enabled", "config"})
    db.commit()
    return to_dict(src)


@router.post("/sources/{key}/search")
def search_source(key: str, data: dict[str, Any], db: Session = DB):
    adapter = get_adapter(key)
    if not adapter:
        raise HTTPException(404, "Unknown source")
    settings = get_all_settings(db)
    cfg = {"boards": (settings.get("company_boards") or {}).get(key, [])} if key in ("greenhouse", "lever", "ashby") else {}
    try:
        raws = adapter.search_jobs(SearchQuery(query=data.get("query", ""), limit=int(data.get("limit", 30)), config=cfg))
    except SourceNotSupported as e:
        raise HTTPException(409, str(e)) from e
    except Exception as e:
        raise HTTPException(502, f"{adapter.name} search failed: {e}") from e
    created = dup = 0
    for raw in raws:
        res = ingest_job(db, adapter.normalize_job(raw, _rates(settings)), settings=settings)
        created += res.created
        dup += not res.created
    db.commit()
    return {"found": len(raws), "created": created, "duplicates": dup}


@router.post("/sources/{key}/test")
def test_source(key: str, db: Session = DB):
    """Live health check: one small request, parsed and normalized, nothing stored."""
    from app.services.job_hunt import update_source_health

    adapter = get_adapter(key)
    if not adapter:
        raise HTTPException(404, "Unknown source")
    src = db.scalar(select(JobSource).where(JobSource.key == key))
    settings = get_all_settings(db)
    cfg = {"boards": (settings.get("company_boards") or {}).get(key, [])} if key in ("greenhouse", "lever", "ashby") else {}
    if key in ("greenhouse", "lever", "ashby") and not cfg["boards"]:
        return {"ok": False, "error": "No company boards configured for this source."}
    try:
        raws = adapter.search_jobs(SearchQuery(query="", limit=5, config=cfg))
        samples = [adapter.normalize_job(r, _rates(settings)) for r in raws[:5]]
    except SourceNotSupported as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        update_source_health(src, ok=False, error=f"{type(e).__name__}: {e}")
        db.commit()
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    update_source_health(src, ok=True, found=len(raws))
    db.commit()
    return {"ok": True, "count": len(raws), "samples": [{"title": n.title, "company": n.company, "salary_monthly_usd_max": n.salary_monthly_usd_max,
                                                          "remote_type": n.remote_type} for n in samples]}


@router.get("/searches")
def list_searches(db: Session = DB):
    return [to_dict(s) for s in db.scalars(select(JobSearch).order_by(JobSearch.id))]


@router.post("/searches")
def create_search(data: dict[str, Any], db: Session = DB):
    s = JobSearch(name=data.get("name") or data.get("query") or "Search", query=data.get("query", ""), sources=data.get("sources") or [],
                  filters=data.get("filters") or {}, enabled=data.get("enabled", True))
    db.add(s)
    db.commit()
    return to_dict(s)


@router.put("/searches/{sid}")
def update_search(sid: int, data: dict[str, Any], db: Session = DB):
    s = get_or_404(db, JobSearch, sid)
    apply_updates(s, data, {"name", "query", "sources", "filters", "enabled"})
    db.commit()
    return to_dict(s)


@router.delete("/searches/{sid}")
def delete_search(sid: int, db: Session = DB):
    db.delete(get_or_404(db, JobSearch, sid))
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- automation
@router.post("/automation/run")
def run_cycle(background: BackgroundTasks, db: Session = DB):
    if scheduler.running_cycle:
        raise HTTPException(409, "A job-hunt cycle is already running")
    run = JobSearchRun(trigger="manual", status="running", stats={}, log=[])
    db.add(run)
    db.commit()
    background.add_task(scheduler.run_now, "manual", run.id)
    return {"started": True, "run_id": run.id}


@router.get("/automation/runs/{rid}")
def get_run(rid: int, db: Session = DB):
    return to_dict(get_or_404(db, JobSearchRun, rid))


@router.get("/automation/runs")
def list_runs(limit: int = 20, db: Session = DB):
    return [to_dict(r) for r in db.scalars(select(JobSearchRun).order_by(JobSearchRun.started_at.desc()).limit(limit))]


@router.get("/automation/status")
def automation_status():
    return scheduler.status()


@router.get("/companies")
def companies(db: Session = DB):
    return [to_dict(c) for c in db.scalars(select(Company).order_by(Company.name))]
