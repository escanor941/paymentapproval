import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.database import Base, SessionLocal, engine
from app.routers import auth, masters, pages, reports, requests
from app.utils.seed import seed_defaults

app = FastAPI(title="Factory Purchase Approval System", version="1.0.0")
session_https_only = os.getenv("SESSION_HTTPS_ONLY", "false").lower() == "true"
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "change-this-secret-key"),
    max_age=60 * 60 * 12,
    https_only=session_https_only,
    same_site="lax",
)

static_dir = Path("app/static")
upload_dir = Path(os.getenv("UPLOAD_DIR", "uploads"))
upload_dir.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")
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
    auto_create = os.getenv("AUTO_CREATE_SCHEMA", "true").lower() == "true"
    if auto_create:
        Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()
    try:
        seed_defaults(db)
    finally:
        db.close()
