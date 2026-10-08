"""In-process scheduler for the daily job hunt (times configurable in Settings)."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from app.db import SessionLocal
from app.services.settings_service import get_setting

log = logging.getLogger(__name__)


class JobHuntScheduler:
    def __init__(self, check_seconds: int = 30):
        self.check_seconds = check_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_fired: set[str] = set()
        self._lock = threading.Lock()
        self.last_run_at: datetime | None = None
        self.last_reminder_refresh: datetime | None = None
        self.running_cycle = False

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
        finally:
            db.close()
        return {"thread_alive": bool(self._thread and self._thread.is_alive()), "enabled": cfg.get("enabled", False),
                "times": cfg.get("times", []), "last_run_at": self.last_run_at, "running": self.running_cycle,
                "next_run": self.next_run(cfg)}

    @staticmethod
    def next_run(cfg: dict) -> str | None:
        if not cfg.get("enabled"):
            return None
        now = datetime.now()
        upcoming = []
        for t in cfg.get("times", []):
            try:
                hh, mm = (int(x) for x in t.split(":"))
            except ValueError:
                continue
            cand = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if cand <= now:
                cand += timedelta(days=1)
            upcoming.append(cand)
        return min(upcoming).isoformat() if upcoming else None

    def run_now(self, trigger: str = "manual"):
        from app.services.job_hunt import run_job_hunt_cycle

        with self._lock:
            self.running_cycle = True
            db = SessionLocal()
            try:
                run = run_job_hunt_cycle(db, trigger=trigger)
                self.last_run_at = datetime.now()
                return run.id
            finally:
                self.running_cycle = False
                db.close()

    def _loop(self) -> None:
        while not self._stop.wait(self.check_seconds):
            try:
                self._tick()
            except Exception:  # never let the scheduler thread die
                log.exception("Scheduler tick failed")

    def _tick(self) -> None:
        now = datetime.now()
        db = SessionLocal()
        try:
            cfg = get_setting(db, "scheduler") or {}
            if self.last_reminder_refresh is None or (now - self.last_reminder_refresh).total_seconds() > 900:
                from app.services.followups import refresh_reminders

                refresh_reminders(db)
                self.last_reminder_refresh = now
        finally:
            db.close()
        if not cfg.get("enabled"):
            return
        stamp = now.strftime("%H:%M")
        key = now.strftime("%Y-%m-%d ") + stamp
        if stamp in cfg.get("times", []) and key not in self._last_fired:
            self._last_fired.add(key)
            log.info("Scheduled job hunt at %s", key)
            self.run_now(trigger="scheduled")


scheduler = JobHuntScheduler()
