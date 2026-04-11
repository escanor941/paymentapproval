from app.database import Base, SessionLocal, engine
from app.utils.seed import seed_defaults


def run() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_defaults(db)
    finally:
        db.close()


if __name__ == "__main__":
    run()
