from app.database import Base, SessionLocal, engine
from app.utils.schema_patch import ensure_schema_patch
from app.utils.seed import seed_defaults


def run() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_schema_patch(engine)
    db = SessionLocal()
    try:
        seed_defaults(db)
    finally:
        db.close()


if __name__ == "__main__":
    run()
