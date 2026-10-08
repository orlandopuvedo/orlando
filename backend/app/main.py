"""AI Job Hunter — FastAPI application entry point."""
from __future__ import annotations

import base64
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api import applications, crm, jobs, library, profile, resumes, system
from app.config import get_settings
from app.db import SessionLocal

log = logging.getLogger("jobhunter")


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    from app.config import BACKEND_DIR

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.run_migrations_on_startup:
        run_migrations()
    from app.seed import seed

    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
    if settings.scheduler_enabled:
        from app.services.scheduler import scheduler

        scheduler.start()
    yield
    if settings.scheduler_enabled:
        from app.services.scheduler import scheduler

        scheduler.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AI Job Hunter", version="1.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    if settings.app_username and settings.app_password:
        expected_user, expected_pw = settings.app_username, settings.app_password

        @app.middleware("http")
        async def basic_auth(request: Request, call_next):
            header = request.headers.get("authorization", "")
            ok = False
            if header.lower().startswith("basic "):
                try:
                    user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
                    ok = secrets.compare_digest(user, expected_user) and secrets.compare_digest(pw, expected_pw)
                except Exception:
                    ok = False
            if not ok:
                return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="AI Job Hunter"'})
            return await call_next(request)

    for r in (profile.router, resumes.router, library.router, jobs.router, applications.router, crm.router, system.router):
        app.include_router(r)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    dist = settings.frontend_dist
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "Not found"}, status_code=404)
            f = dist / path
            if path and f.is_file():
                return FileResponse(f)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
