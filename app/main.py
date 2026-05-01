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

# ── Storage validation ──
storage_backend = os.getenv("STORAGE_BACKEND", "local").lower()
if is_production and storage_backend not in {"s3", "r2"}:
    raise RuntimeError(
        f"Production requires STORAGE_BACKEND='r2' but got '{storage_backend}'. "
        "Local storage is only for development."
    )

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

app.mount("/static", StaticFiles(directory=static_dir), name="static")
# Only mount /uploads in development; production uses R2
if storage_backend == "local" and not is_production:
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


@app.get("/health/storage")
def health_storage():
    """Admin-facing R2/local storage connectivity check."""
    import os, time
    from uuid import uuid4
    backend = os.getenv("STORAGE_BACKEND", "local").lower()
    if backend in {"s3", "r2"}:
        try:
            import boto3
            from botocore.client import Config
            endpoint   = os.getenv("S3_ENDPOINT_URL") or os.getenv("R2_ENDPOINT_URL")
            bucket     = os.getenv("S3_BUCKET")       or os.getenv("R2_BUCKET")
            region     = os.getenv("S3_REGION")       or os.getenv("R2_REGION") or "auto"
            access_key = os.getenv("S3_ACCESS_KEY")   or os.getenv("R2_ACCESS_KEY")
            secret_key = os.getenv("S3_SECRET_KEY")   or os.getenv("R2_SECRET_KEY")
            if not all([endpoint, bucket, access_key, secret_key]):
                return {"backend": backend, "ok": False, "error": "Missing R2/S3 env vars"}
            s3 = boto3.client(
                "s3",
                endpoint_url=endpoint,
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )
            probe_key = f"_health_probe/{uuid4().hex}.txt"
            t0 = time.monotonic()
            s3.put_object(Bucket=bucket, Key=probe_key, Body=b"ok", ContentType="text/plain")
            s3.delete_object(Bucket=bucket, Key=probe_key)
            latency_ms = round((time.monotonic() - t0) * 1000)
            return {"backend": backend, "ok": True, "bucket": bucket, "latency_ms": latency_ms}
        except Exception as exc:
            return {"backend": backend, "ok": False, "error": str(exc)}
    else:
        # Local storage – just confirm the upload dir is writable
        try:
            from pathlib import Path
            upload_dir = Path(os.getenv("UPLOAD_DIR", "uploads"))
            upload_dir.mkdir(parents=True, exist_ok=True)
            probe = upload_dir / f"_probe_{uuid4().hex}.txt"
            probe.write_text("ok"); probe.unlink()
            return {"backend": "local", "ok": True, "path": str(upload_dir.resolve())}
        except Exception as exc:
            return {"backend": "local", "ok": False, "error": str(exc)}


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
