from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import admin_required
from app.models import Factory, ItemCategory, PaymentMode, Unit, User, Vendor
from app.security import get_password_hash
from app.utils.audit import log_change

router = APIRouter(prefix="/masters", tags=["masters"])


MODEL_MAP = {
    "users": User,
    "factories": Factory,
    "vendors": Vendor,
    "categories": ItemCategory,
    "units": Unit,
    "payment-modes": PaymentMode,
}


def _row_to_dict(row):
    data = {"id": row.id, "name": getattr(row, "name", "")}
    for attr in ["location", "mobile", "address", "gst_no", "role", "username", "is_active"]:
        if hasattr(row, attr):
            data[attr] = getattr(row, attr)
    return data


class MasterPayload(BaseModel):
    name: str
    extra1: str | None = None
    extra2: str | None = None
    extra3: str | None = None


@router.get("/{master_type}")
def get_master(master_type: str, db: Session = Depends(get_db), _=Depends(admin_required)):
    model = MODEL_MAP.get(master_type)
    if not model:
        raise HTTPException(404, "Master type not found")

    q = select(model)
    if hasattr(model, "is_deleted"):
        q = q.where(model.is_deleted.is_(False))
    rows = db.scalars(q.order_by(model.id.desc())).all()
    return {"items": [_row_to_dict(x) for x in rows]}


@router.post("/{master_type}")
def create_master(
    master_type: str,
    payload: MasterPayload,
    db: Session = Depends(get_db),
    admin=Depends(admin_required),
):
    if master_type == "factories":
        obj = Factory(name=payload.name, location=payload.extra1 or "")
    elif master_type == "vendors":
        obj = Vendor(
            name=payload.name,
            mobile=payload.extra1,
            address=payload.extra2,
            gst_no=payload.extra3,
        )
    elif master_type == "users":
        username = (payload.extra1 or "").strip()
        role = (payload.extra2 or "factory").strip() or "factory"
        password = (payload.extra3 or "factory123").strip() or "factory123"
        if role not in ["admin", "factory"]:
            raise HTTPException(400, "Role must be admin or factory")
        exists = db.scalar(select(User).where(User.username == username))
        if exists:
            raise HTTPException(400, "Username already exists")
        if not username:
            raise HTTPException(400, "Username is required")
        obj = User(
            name=payload.name,
            username=username,
            password_hash=get_password_hash(password),
            role=role,
            is_active=True,
        )
    elif master_type == "categories":
        obj = ItemCategory(name=payload.name)
    elif master_type == "units":
        obj = Unit(name=payload.name)
    elif master_type == "payment-modes":
        obj = PaymentMode(name=payload.name)
    else:
        raise HTTPException(404, "Master type not found")

    db.add(obj)
    db.flush()
    log_change(db, entity=master_type, entity_id=obj.id, action="CREATE", new_value={"name": payload.name}, changed_by=admin.id)
    db.commit()
    return {"message": "Created", "id": obj.id}


@router.put("/{master_type}/{item_id}")
def update_master(
    master_type: str,
    item_id: int,
    payload: MasterPayload,
    db: Session = Depends(get_db),
    admin=Depends(admin_required),
):
    model = MODEL_MAP.get(master_type)
    if not model:
        raise HTTPException(404, "Master type not found")

    obj = db.get(model, item_id)
    if not obj:
        raise HTTPException(404, "Item not found")

    old = {"name": getattr(obj, "name", "")}
    if hasattr(obj, "name"):
        obj.name = payload.name
    if master_type == "factories":
        obj.location = payload.extra1 or ""
    if master_type == "vendors":
        obj.mobile = payload.extra1
        obj.address = payload.extra2
        obj.gst_no = payload.extra3
    if master_type == "users":
        if payload.extra1:
            username_exists = db.scalar(
                select(User).where(User.username == payload.extra1, User.id != obj.id)
            )
            if username_exists:
                raise HTTPException(400, "Username already exists")
            obj.username = payload.extra1
        if payload.extra2 in ["admin", "factory"]:
            obj.role = payload.extra2
        if payload.extra3:
            obj.password_hash = get_password_hash(payload.extra3)

    log_change(db, entity=master_type, entity_id=item_id, action="UPDATE", old_value=old, new_value={"name": payload.name}, changed_by=admin.id)
    db.commit()
    return {"message": "Updated"}


@router.delete("/{master_type}/{item_id}")
def delete_master(
    master_type: str,
    item_id: int,
    db: Session = Depends(get_db),
    admin=Depends(admin_required),
):
    model = MODEL_MAP.get(master_type)
    if not model:
        raise HTTPException(404, "Master type not found")

    obj = db.get(model, item_id)
    if not obj:
        raise HTTPException(404, "Item not found")

    if master_type == "users":
        obj.is_active = False
    elif hasattr(obj, "is_deleted"):
        obj.is_deleted = True
    else:
        db.delete(obj)

    log_change(db, entity=master_type, entity_id=item_id, action="DELETE", old_value={"name": getattr(obj, "name", "")}, changed_by=admin.id)
    db.commit()
    return {"message": "Deleted"}
