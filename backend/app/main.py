import logging
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, incidents
from app.auth import migrate_legacy_demo_user
from app.config import get_settings
from app.db import init_db
from app.groq import client as groq
from app.hindsight import client as hindsight
from app.observability import configure_logging
from app.schemas import HealthResponse

configure_logging()
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    migrate_legacy_demo_user()
    yield
    await groq.aclose()
    await hindsight.aclose()


app = FastAPI(title="Incident Response Agent", version="1.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(auth.router)
app.include_router(incidents.router)


@app.exception_handler(sqlite3.Error)
async def database_error(_: Request, exc: sqlite3.Error) -> JSONResponse:
    log.error("Database error: %s", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "The incident database is temporarily unavailable."})


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Public connectivity check (cached); never reveals keys, only whether they are configured."""
    s = get_settings()
    return HealthResponse(
        status="ok",
        groq={"configured": bool(s.groq_api_key), "model": s.groq_model},
        hindsight=await hindsight.health(),
        hindsight_configured=bool(s.hindsight_api_key),
    )
