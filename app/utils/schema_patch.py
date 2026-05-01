from sqlalchemy import inspect, text


REQUIRED_PURCHASE_REQUEST_COLUMNS = {
    "geo_latitude": "ALTER TABLE purchase_requests ADD COLUMN geo_latitude FLOAT",
    "geo_longitude": "ALTER TABLE purchase_requests ADD COLUMN geo_longitude FLOAT",
    "geo_accuracy_m": "ALTER TABLE purchase_requests ADD COLUMN geo_accuracy_m FLOAT",
    "geo_captured_at": "ALTER TABLE purchase_requests ADD COLUMN geo_captured_at TIMESTAMP",
    "is_in_factory": "ALTER TABLE purchase_requests ADD COLUMN is_in_factory BOOLEAN",
    "distance_from_factory_m": "ALTER TABLE purchase_requests ADD COLUMN distance_from_factory_m FLOAT",
}


def ensure_schema_patch(engine) -> None:
    insp = inspect(engine)

    if insp.has_table("purchase_requests"):
        existing = {c["name"] for c in insp.get_columns("purchase_requests")}
        missing = [ddl for name, ddl in REQUIRED_PURCHASE_REQUEST_COLUMNS.items() if name not in existing]
        if missing:
            with engine.begin() as conn:
                for ddl in missing:
                    conn.execute(text(ddl))

    if not insp.has_table("user_presence"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE user_presence (
                        id INTEGER PRIMARY KEY,
                        user_id INTEGER NOT NULL UNIQUE,
                        factory_id INTEGER,
                        latitude FLOAT NOT NULL,
                        longitude FLOAT NOT NULL,
                        accuracy_m FLOAT,
                        is_in_factory BOOLEAN,
                        distance_from_factory_m FLOAT,
                        last_seen_at TIMESTAMP,
                        FOREIGN KEY(user_id) REFERENCES users(id),
                        FOREIGN KEY(factory_id) REFERENCES factories(id)
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_user_presence_user_id ON user_presence (user_id)"))
