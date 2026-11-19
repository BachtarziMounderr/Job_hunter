"""Local FastAPI control centre. Secrets, CV contents and database URLs never leave the server."""

import logging
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from alembic import command
from app.config import Settings
from app.database.locking import execution_lock
from app.database.models import JobMatch, JobRecord, Opportunity, SearchExecution, SearchProfile
from app.database.session import create_database_engine, transaction
from app.opportunities import bootstrap_inbox
from app.results import application_link

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)


def iso(value):
    if value is None:
        return None
    return (value.replace(tzinfo=UTC) if value.tzinfo is None else value).isoformat()


class StateChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["available", "applied", "dismissed"]


def create_app(settings: Settings | None = None, *, engine=None, prepare=True) -> FastAPI:
    settings = settings or Settings(_env_file=[ROOT / ".env", ROOT / ".env.neon"])
    database = engine or create_database_engine(settings)
    owned = engine is None
    csrf = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        if prepare:
            from app.cli import migration_config

            try:
                with execution_lock(database):
                    command.upgrade(migration_config(settings), "head")
                    bootstrap_inbox(settings, database)
            except (SQLAlchemyError, RuntimeError) as exc:
                logger.error("Dashboard initialization failed (%s)", type(exc).__name__)
                raise RuntimeError("Impossible de préparer la base du dashboard.") from None
        yield
        if owned:
            database.dispose()

    app = FastAPI(title="Job Hunter · Centre de contrôle", version="0.4.0", lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"]
    )

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin not in {
                str(request.base_url).rstrip("/"),
                "http://127.0.0.1:5173",
                "http://localhost:5173",
            }:
                return JSONResponse({"detail": "Origine non autorisée."}, status_code=403)
            if not secrets.compare_digest(request.headers.get("x-job-hunter-csrf", ""), csrf):
                return JSONResponse(
                    {"detail": "Actualise la page avant cette action."}, status_code=403
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(SQLAlchemyError)
    async def database_unavailable(request, exc):
        logger.error("Dashboard database request failed (%s)", type(exc).__name__)
        return JSONResponse(
            {"detail": "La base est temporairement indisponible. Réessaie dans un instant."},
            status_code=503,
        )

    @app.get("/api/health")
    def health():
        return {"status": "ok", "scope": "algeria"}

    @app.get("/api/dashboard")
    def dashboard(
        status: Literal["available", "applied", "dismissed"] = "available",
        q: str = Query(default="", max_length=150),
        profile: str = Query(default="", max_length=200),
        new_only: bool = False,
        page: int = Query(default=1, ge=1),
        limit: int = Query(default=24, ge=1, le=100),
        sort: Literal["score", "recent"] = "score",
    ):
        tz = ZoneInfo(settings.notification_timezone)
        now = datetime.now(UTC)
        today = now.astimezone(tz).date()
        lower = datetime.combine(today, time.min, tz).astimezone(UTC)
        next_run = datetime.combine(today, time(12), tz)
        if next_run <= now.astimezone(tz):
            next_run += timedelta(days=1)
        active = Opportunity.is_current.is_(True) & (JobRecord.status == "active")
        with transaction(database) as session:
            counts = {}
            for name in ("available", "applied", "dismissed"):
                conditions = [Opportunity.status == name]
                if name == "available":
                    conditions.append(active)
                counts[name] = session.scalar(
                    select(func.count())
                    .select_from(Opportunity)
                    .join(JobRecord, Opportunity.job_id == JobRecord.id)
                    .where(*conditions)
                )
            counts["new_today"] = session.scalar(
                select(func.count())
                .select_from(Opportunity)
                .join(JobRecord, Opportunity.job_id == JobRecord.id)
                .where(
                    Opportunity.status == "available", active, Opportunity.discovered_at >= lower
                )
            )
            conditions = [Opportunity.status == status]
            if status == "available":
                conditions.append(active)
            if q.strip():
                term = "%" + q.strip().casefold().replace("%", r"\%").replace("_", r"\_") + "%"
                conditions.append(
                    or_(
                        *[
                            func.lower(Opportunity.snapshot[field].as_string()).like(
                                term, escape="\\"
                            )
                            for field in ("title", "company", "location")
                        ]
                    )
                )
            if profile:
                conditions.append(Opportunity.snapshot["best_profile"].as_string() == profile)
            if new_only:
                conditions.append(Opportunity.discovered_at >= lower)
            base = (
                select(Opportunity)
                .join(JobRecord, Opportunity.job_id == JobRecord.id)
                .where(*conditions)
            )
            total = session.scalar(select(func.count()).select_from(base.subquery()))
            order = (
                Opportunity.discovered_at.desc()
                if sort == "recent"
                else Opportunity.snapshot["score"].as_float().desc()
            )
            rows = session.scalars(
                base.order_by(order, Opportunity.id.desc()).offset((page - 1) * limit).limit(limit)
            )
            items = [
                {
                    "id": row.id,
                    "status": row.status,
                    "discovered_at": iso(row.discovered_at),
                    "applied_at": iso(row.applied_at),
                    "active": row.is_current,
                    **row.snapshot,
                }
                for row in rows
            ]
            profiles = sorted(
                session.scalars(select(Opportunity.snapshot["best_profile"].as_string()).distinct())
            )
            profiles = sorted(
                set(profiles)
                | set(
                    session.scalars(
                        select(SearchProfile.name)
                        .join(JobMatch, JobMatch.profile_id == SearchProfile.id)
                        .join(Opportunity, Opportunity.job_id == JobMatch.job_id)
                        .where(JobMatch.profile_content_hash == SearchProfile.content_hash)
                        .distinct()
                    )
                )
            )
            executions = list(
                session.scalars(
                    select(SearchExecution).order_by(SearchExecution.started_at.desc()).limit(10)
                )
            )
            history = [
                {
                    "id": run.id,
                    "mode": run.mode,
                    "status": run.status,
                    "started_at": iso(run.started_at),
                    "finished_at": iso(run.finished_at),
                    "details": run.details,
                }
                for run in executions
            ]
        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "stats": counts,
            "profiles": profiles,
            "csrf_token": csrf,
            "history": history,
            "schedule": {
                "time": "12:00",
                "timezone": settings.notification_timezone,
                "next_run": next_run.isoformat(),
                "scheduler": "GitHub Actions",
            },
            "sources": {"gmail_enabled": settings.gmail_enabled, "scope": "Algérie uniquement"},
        }

    @app.post("/api/opportunities/{opportunity_id}/status")
    def change_status(opportunity_id: int, body: StateChange):
        with transaction(database) as session:
            row = session.scalar(
                select(Opportunity).where(Opportunity.id == opportunity_id).with_for_update()
            )
            if row is None:
                raise HTTPException(404, "Offre introuvable.")
            url = application_link(row.snapshot.get("application_url") or "")
            if body.status == "applied" and not url:
                raise HTTPException(
                    409, "Cette offre ne possède pas de lien de candidature valide."
                )
            if row.status != body.status:
                row.status, row.updated_at = body.status, datetime.now(UTC)
                row.applied_at = datetime.now(UTC) if body.status == "applied" else None
            return {
                "id": row.id,
                "status": row.status,
                "applied_at": iso(row.applied_at),
                "application_url": url,
            }

    assets = ROOT / "frontend/dist/assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon():
        return FileResponse(ROOT / "frontend/public/favicon.svg")

    @app.get("/", include_in_schema=False)
    def index():
        path = ROOT / "frontend/dist/index.html"
        if not path.is_file():
            raise HTTPException(503, "Construis le frontend avec npm --prefix frontend run build.")
        return FileResponse(path)

    return app
