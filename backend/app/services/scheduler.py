"""In-process scheduler for the daily job hunt.

REQUIRES the backend process to be running: nothing runs while the server is stopped.
Catch-up policy: if scheduled slot(s) were missed while the server was offline, at most ONE catch-up
run is executed (for the most recent missed slot within the last 24 h) — never one per missed slot.
State (last fired slot) is persisted in the settings table so restarts don't re-run or skip slots.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from app.db import SessionLocal
from app.models import JobSearchRun, Setting
from app.services.settings_service import get_setting

log = logging.getLogger(__name__)
STATE_KEY = "_scheduler_state"
CATCH_UP_WINDOW = timedelta(hours=24)


def resolve_tz(name: str | None):
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return datetime.now().astimezone().tzinfo  # server local time


def parse_times(times: list[str]) -> list[tuple[int, int]]:
    out = []
    for t in times or []:
        try:
            hh, mm = (int(x) for x in str(t).split(":"))
            if 0 <= hh < 24 and 0 <= mm < 60:
                out.append((hh, mm))
        except ValueError:
            continue
    return sorted(set(out))


def slots_between(start: datetime, end: datetime, times: list[tuple[int, int]], tz) -> list[datetime]:
    """All scheduled slot datetimes (aware, in tz) with start < slot <= end."""
    out = []
    day = start.astimezone(tz).date() - timedelta(days=1)
    last_day = end.astimezone(tz).date()
    while day <= last_day:
        for hh, mm in times:
            s = datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
            if start < s <= end:
                out.append(s)
        day += timedelta(days=1)
    return sorted(out)


def due_slot(now: datetime, cfg: dict, last_fired: datetime | None) -> tuple[datetime | None, bool]:
    """Pure decision: which slot (if any) should run now, and whether it is a catch-up.

    Returns (slot, is_catch_up). At most one slot is ever returned, even if several were missed.
    """
    if not cfg.get("enabled"):
        return None, False
    times = parse_times(cfg.get("times", []))
    if not times:
        return None, False
    tz = resolve_tz(cfg.get("timezone"))
    if last_fired is None:
        return None, False  # first activation: start counting from now; never run past slots
    window_start = max(last_fired, now - CATCH_UP_WINDOW)
    slots = slots_between(window_start, now, times, tz)
    if not slots:
        return None, False
    latest = slots[-1]
    is_catch_up = (now - latest) > timedelta(minutes=2)
    if is_catch_up and not cfg.get("catch_up", True):
        return None, False
    return latest, is_catch_up


def next_run(now: datetime, cfg: dict) -> datetime | None:
    if not cfg.get("enabled"):
        return None
    times = parse_times(cfg.get("times", []))
    if not times:
        return None
    tz = resolve_tz(cfg.get("timezone"))
    slots = slots_between(now, now + timedelta(days=2), times, tz)
    return slots[0] if slots else None


def _load_state(db) -> dict:
    row = db.get(Setting, STATE_KEY)
    return dict(row.value) if row and isinstance(row.value, dict) else {}


def _save_state(db, state: dict) -> None:
    row = db.get(Setting, STATE_KEY)
    if row is None:
        db.add(Setting(key=STATE_KEY, value=state))
    else:
        row.value = state
    db.commit()


class JobHuntScheduler:
    def __init__(self, check_seconds: int = 30):
        self.check_seconds = check_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.last_reminder_refresh: datetime | None = None
        self.running_cycle = False
        self.last_tick_error: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="job-hunt-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict:
        db = SessionLocal()
        try:
            cfg = get_setting(db, "scheduler") or {}
            state = _load_state(db)
            last = db.scalars(select(JobSearchRun).order_by(JobSearchRun.started_at.desc()).limit(1)).first()
            last_sched = db.scalars(select(JobSearchRun).where(JobSearchRun.trigger.in_(["scheduled", "catch_up"]))
                                    .order_by(JobSearchRun.started_at.desc()).limit(1)).first()
        finally:
            db.close()
        now = datetime.now(timezone.utc)
        nr = next_run(now, cfg)

        def run_info(r):
            if not r:
                return None
            return {"id": r.id, "trigger": r.trigger, "status": r.status, "outcome": r.outcome, "message": r.message,
                    "started_at": r.started_at, "finished_at": r.finished_at, "stats": r.stats}

        return {"thread_alive": bool(self._thread and self._thread.is_alive()), "enabled": cfg.get("enabled", False),
                "times": cfg.get("times", []), "timezone": cfg.get("timezone") or str(resolve_tz(None)),
                "catch_up": cfg.get("catch_up", True), "running": self.running_cycle,
                "next_run": nr.isoformat() if nr else None, "last_fired_slot": state.get("last_fired"),
                "last_run": run_info(last), "last_scheduled_run": run_info(last_sched), "last_tick_error": self.last_tick_error,
                "note": "The scheduler only runs while the backend process is running."}

    def run_now(self, trigger: str = "manual", run_id: int | None = None):
        from app.services.job_hunt import run_job_hunt_cycle

        with self._lock:
            self.running_cycle = True
            db = SessionLocal()
            try:
                run = run_job_hunt_cycle(db, trigger=trigger, run_id=run_id)
                return run.id
            finally:
                self.running_cycle = False
                db.close()

    def _loop(self) -> None:
        while not self._stop.wait(self.check_seconds):
            try:
                self.tick()
                self.last_tick_error = None
            except Exception as e:  # never let the scheduler thread die
                self.last_tick_error = f"{type(e).__name__}: {e}"
                log.exception("Scheduler tick failed")

    def tick(self, now: datetime | None = None) -> str | None:
        """One scheduler step. Returns the trigger fired ('scheduled' / 'catch_up') or None."""
        now = now or datetime.now(timezone.utc)
        db = SessionLocal()
        try:
            cfg = get_setting(db, "scheduler") or {}
            if self.last_reminder_refresh is None or (now - self.last_reminder_refresh).total_seconds() > 900:
                from app.services.followups import refresh_reminders

                refresh_reminders(db)
                self.last_reminder_refresh = now
            state = _load_state(db)
            if not cfg.get("enabled"):
                if state.get("last_fired"):
                    _save_state(db, {**state, "last_fired": None})  # re-enabling later must not trigger a stale catch-up
                return None
            last = datetime.fromisoformat(state["last_fired"]) if state.get("last_fired") else None
            if last is None:
                _save_state(db, {**state, "last_fired": now.isoformat()})  # baseline on first activation
                return None
            slot, catch_up = due_slot(now, cfg, last)
            if slot is None or self.running_cycle:
                return None
            _save_state(db, {**state, "last_fired": now.isoformat(), "last_slot": slot.isoformat()})
        finally:
            db.close()
        trigger = "catch_up" if catch_up else "scheduled"
        log.info("Job hunt %s for slot %s", trigger, slot)
        self.run_now(trigger=trigger)
        return trigger


scheduler = JobHuntScheduler()
