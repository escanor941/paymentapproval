import os
from secrets import token_urlsafe
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.database import Base, SessionLocal, engine
from app.routers import auth, masters, pages, reports, requests
from app.utils.schema_patch import ensure_schema_patch
from app.utils.seed import seed_defaults

app = FastAPI(title="Factory Purchase Approval System", version="1.0.0")
app_env = os.getenv("APP_ENV", "development").lower()
is_production = app_env in {"production", "prod"}

session_https_only = os.getenv("SESSION_HTTPS_ONLY", "true" if is_production else "false").lower() == "true"
session_secret = os.getenv("SESSION_SECRET", "change-this-secret-key")
if is_production and session_secret == "change-this-secret-key":
    # Keep the service bootable even when env var is missing, and log clearly.
    session_secret = token_urlsafe(32)
    print("[startup] WARNING: SESSION_SECRET is not set in production; using ephemeral secret for this boot")

app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    max_age=60 * 60 * 12,
    https_only=session_https_only,
    same_site="lax",
)

static_dir = Path("app/static")
storage_backend = os.getenv("STORAGE_BACKEND", "local").lower()

app.mount("/static", StaticFiles(directory=static_dir), name="static")
if storage_backend == "local":
    upload_dir = Path(os.getenv("UPLOAD_DIR", "uploads"))
    upload_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")

app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(requests.router)
app.include_router(reports.router)
app.include_router(masters.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.on_event("startup")
def on_startup() -> None:
    auto_create_default = "false" if is_production else "true"
    auto_create = os.getenv("AUTO_CREATE_SCHEMA", auto_create_default).lower() == "true"
    try:
        # Always bootstrap tables on first deployment if schema is empty.
        has_users_table = inspect(engine).has_table("users")
        if auto_create or not has_users_table:
            Base.metadata.create_all(bind=engine)
        ensure_schema_patch(engine)
        db: Session = SessionLocal()
        try:
            seed_defaults(db)
        finally:
            db.close()
    except Exception as exc:
        # Do not fail service boot; keep /health reachable and log actionable details.
        print(f"[startup] WARNING: database initialization skipped due to error: {exc}")
