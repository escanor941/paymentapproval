import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def _to_json(data: Any) -> str | None:
    if data is None:
        return None
    return json.dumps(data, default=str)


def log_change(
    db: Session,
    *,
    entity: str,
    entity_id: int,
    action: str,
    old_value: Any = None,
    new_value: Any = None,
    changed_by: int | None = None,
) -> None:
    row = AuditLog(
        entity=entity,
        entity_id=entity_id,
        action=action,
        old_value=_to_json(old_value),
        new_value=_to_json(new_value),
        changed_by=changed_by,
    )
    db.add(row)
