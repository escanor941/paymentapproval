import math
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import admin_required, get_current_user
from app.models import Factory, Payment, PurchaseRequest, User, UserPresence, Vendor
from app.utils.audit import log_change
from app.utils.email_notify import notify_bill_upload, notify_new_request
from app.utils.storage import save_upload
from app.utils.telegram_notify import telegram_bill_upload, telegram_new_request

router = APIRouter(tags=["requests"])


def _compute_amounts(qty: float, rate: float, gst_percent: float) -> tuple[float, float]:
    amount = qty * rate
    final_amount = amount + (amount * gst_percent / 100)
    return round(amount, 2), round(final_amount, 2)

def _as_dict(req: PurchaseRequest) -> dict:
    display_vendor = (req.vendor_mobile or "").strip() or (req.vendor.name if req.vendor else "")
    return {
        "id": req.id,
        "request_date": str(req.request_date),
        "factory_id": req.factory_id,
        "vendor": display_vendor,
        "vendor_id": req.vendor_id,
        "item_category": req.item_category,
        "item_name": req.item_name,
        "qty": req.qty,
        "unit": req.unit,
        "rate": req.rate,
        "amount": req.amount,
        "gst_percent": req.gst_percent,
        "final_amount": req.final_amount,
        "reason": req.reason,
        "urgent_flag": req.urgent_flag,
        "requested_by": req.requested_by,
        "geo_latitude": req.geo_latitude,
        "geo_longitude": req.geo_longitude,
        "geo_accuracy_m": req.geo_accuracy_m,
        "geo_captured_at": str(req.geo_captured_at) if req.geo_captured_at else None,
        "is_in_factory": req.is_in_factory,
        "distance_from_factory_m": req.distance_from_factory_m,
        "bill_image_path": req.bill_image_path,
        "notes": req.notes,
        "approval_status": req.approval_status,
        "approved_amount": req.approved_amount,
        "approval_remark": req.approval_remark,
        "priority": req.priority,
        "expected_payment_date": str(req.expected_payment_date) if req.expected_payment_date else None,
        "approved_by": req.approved_by,
        "approved_at": str(req.approved_at) if req.approved_at else None,
        "payment_status": req.payment_status,
        "is_unread_admin": req.is_unread_admin,
        "created_at": str(req.created_at),
        "updated_at": str(req.updated_at),
    }


def _save_file(upload: UploadFile | None) -> str | None:
    return save_upload(upload)


def _parse_factory_geo(location_text: str | None) -> tuple[float, float, float] | None:
    if not location_text:
        return None
    parts = [x.strip() for x in location_text.split(",") if x.strip()]
    if len(parts) < 2:
        return None
    try:
        lat = float(parts[0])
        lon = float(parts[1])
        radius = float(parts[2]) if len(parts) >= 3 else 250.0
    except ValueError:
        return None
    return (lat, lon, max(radius, 10.0))


def _distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _compute_presence(factory: Factory | None, latitude: float | None, longitude: float | None) -> tuple[bool | None, float | None]:
    if latitude is None or longitude is None or not factory:
        return (None, None)
    geo = _parse_factory_geo(factory.location)
    if not geo:
        return (None, None)
    f_lat, f_lon, radius = geo
    distance = _distance_meters(latitude, longitude, f_lat, f_lon)
    return (distance <= radius, round(distance, 1))


def _upsert_presence(
    db: Session,
    *,
    user_id: int,
    factory_id: int | None,
    latitude: float | None,
    longitude: float | None,
    accuracy_m: float | None,
    captured_at: datetime | None,
    is_in_factory: bool | None,
    distance_from_factory_m: float | None,
) -> None:
    if latitude is None or longitude is None:
        return
    row = db.scalar(select(UserPresence).where(UserPresence.user_id == user_id))
    last_seen = captured_at or datetime.utcnow()
    if row:
        row.factory_id = factory_id
        row.latitude = latitude
        row.longitude = longitude
        row.accuracy_m = accuracy_m
        row.is_in_factory = is_in_factory
        row.distance_from_factory_m = distance_from_factory_m
        row.last_seen_at = last_seen
        return
    db.add(
        UserPresence(
            user_id=user_id,
            factory_id=factory_id,
            latitude=latitude,
            longitude=longitude,
            accuracy_m=accuracy_m,
            is_in_factory=is_in_factory,
            distance_from_factory_m=distance_from_factory_m,
            last_seen_at=last_seen,
        )
    )


def _notify_request_submission(
    db: Session,
    req: PurchaseRequest,
    factory_id: int,
    vendor_id: int,
    vendor_mobile: str | None,
    item_name: str,
    requested_by: str,
    urgent_flag: bool,
) -> bool:
    factory_obj = db.get(Factory, factory_id)
    factory_name = factory_obj.name if factory_obj else str(factory_id)
    vendor_display = (vendor_mobile or "").strip()
    if not vendor_display:
        vendor_obj = db.get(Vendor, vendor_id)
        vendor_display = vendor_obj.name if vendor_obj else str(vendor_id)

    notify_new_request(
        req_id=req.id,
        factory_name=factory_name,
        item_name=item_name,
        vendor=vendor_display,
        final_amount=req.final_amount,
        requested_by=requested_by,
        urgent=urgent_flag,
    )
    return telegram_new_request(
        req_id=req.id,
        factory_name=factory_name,
        item_name=item_name,
        vendor=vendor_display,
        final_amount=req.final_amount,
        requested_by=requested_by,
        urgent=urgent_flag,
    )


@router.post("/requests")
def create_request(
    request_date: date = Form(...),
    factory_id: int = Form(...),
    vendor_id: int = Form(...),
    vendor_mobile: str | None = Form(None),
    item_category: str = Form(...),
    item_name: str = Form(...),
    qty: float = Form(...),
    unit: str = Form(...),
    rate: float = Form(...),
    amount: float = Form(...),
    gst_percent: float = Form(0),
    final_amount: float = Form(...),
    reason: str = Form(...),
    urgent_flag: bool = Form(False),
    requested_by: str = Form(...),
    geo_latitude: float | None = Form(None),
    geo_longitude: float | None = Form(None),
    geo_accuracy_m: float | None = Form(None),
    notes: str | None = Form(None),
    save_as_draft: bool = Form(False),
    bill_image: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role != "admin" and user.role != "factory":
        raise HTTPException(403, "Invalid role")
    if qty <= 0 or rate <= 0:
        raise HTTPException(400, "Quantity and rate must be greater than zero")
    if gst_percent < 0:
        raise HTTPException(400, "GST percent cannot be negative")

    computed_amount, computed_final_amount = _compute_amounts(qty, rate, gst_percent)

    factory_obj = db.get(Factory, factory_id)
    is_in_factory, distance_from_factory_m = _compute_presence(factory_obj, geo_latitude, geo_longitude)

    req = PurchaseRequest(
        request_date=request_date,
        factory_id=factory_id,
        vendor_id=vendor_id,
        vendor_mobile=vendor_mobile,
        item_category=item_category,
        item_name=item_name,
        qty=qty,
        unit=unit,
        rate=rate,
        amount=computed_amount,
        gst_percent=gst_percent,
        final_amount=computed_final_amount,
        reason=reason,
        urgent_flag=urgent_flag,
        requested_by=requested_by,
        requested_by_user_id=user.id,
        geo_latitude=geo_latitude,
        geo_longitude=geo_longitude,
        geo_accuracy_m=geo_accuracy_m,
        geo_captured_at=datetime.utcnow() if geo_latitude is not None and geo_longitude is not None else None,
        is_in_factory=is_in_factory,
        distance_from_factory_m=distance_from_factory_m,
        bill_image_path=_save_file(bill_image),
        notes=notes,
        approval_status="Draft" if save_as_draft else "Pending",
        payment_status="Unpaid",
        is_unread_admin=user.role == "factory",
    )
    db.add(req)
    _upsert_presence(
        db,
        user_id=user.id,
        factory_id=factory_id,
        latitude=geo_latitude,
        longitude=geo_longitude,
        accuracy_m=geo_accuracy_m,
        captured_at=req.geo_captured_at,
        is_in_factory=is_in_factory,
        distance_from_factory_m=distance_from_factory_m,
    )
    db.flush()
    log_change(db, entity="purchase_request", entity_id=req.id, action="CREATE", new_value=_as_dict(req), changed_by=user.id)
    db.commit()

    telegram_sent = True
    if req.approval_status != "Draft":
        telegram_sent = _notify_request_submission(
            db=db,
            req=req,
            factory_id=factory_id,
            vendor_id=vendor_id,
            vendor_mobile=vendor_mobile,
            item_name=item_name,
            requested_by=requested_by,
            urgent_flag=urgent_flag,
        )

    message = "Request saved"
    if req.approval_status != "Draft" and not telegram_sent:
        message = "Request saved, but Telegram notification failed"
    return {"message": message, "id": req.id}


@router.post("/requests/simple-bill")
def create_simple_bill_upload(
    vendor_name: str = Form(...),
    factory_id: int | None = Form(None),
    geo_latitude: float | None = Form(None),
    geo_longitude: float | None = Form(None),
    geo_accuracy_m: float | None = Form(None),
    bill_image: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role != "factory":
        raise HTTPException(403, "Only factory users can upload from this tab")

    clean_vendor_name = (vendor_name or "").strip()
    if not clean_vendor_name:
        raise HTTPException(400, "Vendor name is required")

    bill_path = _save_file(bill_image)
    if not bill_path:
        raise HTTPException(400, "Actual bill image is required")

    default_factory = None
    if factory_id:
        default_factory = db.scalar(
            select(Factory).where(and_(Factory.id == factory_id, Factory.is_deleted.is_(False)))
        )
    if not default_factory:
        default_factory = db.scalar(
            select(Factory).where(Factory.is_deleted.is_(False)).order_by(Factory.id.asc())
        )
    default_vendor = db.scalar(
        select(Vendor).where(Vendor.is_deleted.is_(False)).order_by(Vendor.id.asc())
    )
    if not default_factory:
        raise HTTPException(400, "No active factory found in masters")
    if not default_vendor:
        raise HTTPException(400, "No active vendor found in masters")

    is_in_factory, distance_from_factory_m = _compute_presence(default_factory, geo_latitude, geo_longitude)

    req = PurchaseRequest(
        request_date=date.today(),
        factory_id=default_factory.id,
        vendor_id=default_vendor.id,
        vendor_mobile=clean_vendor_name,
        item_category="Bill Upload",
        item_name="Actual Bill Upload",
        qty=1,
        unit="Nos",
        rate=1,
        amount=1,
        gst_percent=0,
        final_amount=1,
        reason="Actual bill uploaded via simple tab",
        urgent_flag=False,
        requested_by=user.name,
        requested_by_user_id=user.id,
        geo_latitude=geo_latitude,
        geo_longitude=geo_longitude,
        geo_accuracy_m=geo_accuracy_m,
        geo_captured_at=datetime.utcnow() if geo_latitude is not None and geo_longitude is not None else None,
        is_in_factory=is_in_factory,
        distance_from_factory_m=distance_from_factory_m,
        bill_image_path=bill_path,
        notes="Simple bill upload",
        approval_status="Pending",
        payment_status="Unpaid",
        is_unread_admin=True,
    )
    db.add(req)
    _upsert_presence(
        db,
        user_id=user.id,
        factory_id=default_factory.id,
        latitude=geo_latitude,
        longitude=geo_longitude,
        accuracy_m=geo_accuracy_m,
        captured_at=req.geo_captured_at,
        is_in_factory=is_in_factory,
        distance_from_factory_m=distance_from_factory_m,
    )
    db.flush()
    log_change(
        db,
        entity="purchase_request",
        entity_id=req.id,
        action="CREATE_SIMPLE_BILL",
        new_value=_as_dict(req),
        changed_by=user.id,
    )
    db.commit()

    notify_bill_upload(
        req_id=req.id,
        vendor_name=clean_vendor_name,
        uploaded_by=user.name,
    )
    telegram_sent = telegram_bill_upload(
        req_id=req.id,
        vendor_name=clean_vendor_name,
        uploaded_by=user.name,
    )

    message = "Bill uploaded" if telegram_sent else "Bill uploaded, but Telegram notification failed"
    return {"message": message, "id": req.id}


@router.get("/requests")
def list_requests(
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    vendor: str | None = Query(None),
    factory_id: int | None = Query(None),
    status: str | None = Query(None),
    payment_status: str | None = Query(None),
    item_category: str | None = Query(None),
    search: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(PurchaseRequest).where(PurchaseRequest.is_deleted.is_(False))

    if user.role != "admin":
        query = query.where(PurchaseRequest.requested_by_user_id == user.id)

    if from_date:
        query = query.where(PurchaseRequest.request_date >= from_date)
    if to_date:
        query = query.where(PurchaseRequest.request_date <= to_date)
    if factory_id:
        query = query.where(PurchaseRequest.factory_id == factory_id)
    if status:
        query = query.where(PurchaseRequest.approval_status == status)
    if payment_status:
        query = query.where(PurchaseRequest.payment_status == payment_status)
    if item_category:
        query = query.where(PurchaseRequest.item_category == item_category)
    if vendor:
        query = query.join(Vendor, Vendor.id == PurchaseRequest.vendor_id).where(Vendor.name.ilike(f"%{vendor}%"))
    if search:
        query = query.where(
            or_(
                PurchaseRequest.item_name.ilike(f"%{search}%"),
                PurchaseRequest.requested_by.ilike(f"%{search}%"),
                PurchaseRequest.reason.ilike(f"%{search}%"),
            )
        )

    rows = db.scalars(query.order_by(desc(PurchaseRequest.id))).all()
    return {"items": [_as_dict(r) for r in rows]}


@router.put("/requests/{request_id}")
def update_request(
    request_id: int,
    request_date: date = Form(...),
    factory_id: int = Form(...),
    vendor_id: int = Form(...),
    vendor_mobile: str | None = Form(None),
    item_category: str = Form(...),
    item_name: str = Form(...),
    qty: float = Form(...),
    unit: str = Form(...),
    rate: float = Form(...),
    amount: float = Form(...),
    gst_percent: float = Form(0),
    final_amount: float = Form(...),
    reason: str = Form(...),
    urgent_flag: bool = Form(False),
    requested_by: str = Form(...),
    geo_latitude: float | None = Form(None),
    geo_longitude: float | None = Form(None),
    geo_accuracy_m: float | None = Form(None),
    notes: str | None = Form(None),
    save_as_draft: bool = Form(False),
    bill_image: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    req = db.get(PurchaseRequest, request_id)
    if not req or req.is_deleted:
        raise HTTPException(404, "Request not found")

    if user.role != "admin":
        if req.requested_by_user_id != user.id or req.approval_status not in ["Pending", "Draft", "Hold"]:
            raise HTTPException(403, "Edit not permitted")

    if qty <= 0 or rate <= 0:
        raise HTTPException(400, "Quantity and rate must be greater than zero")
    if gst_percent < 0:
        raise HTTPException(400, "GST percent cannot be negative")

    old = _as_dict(req)
    old_status = req.approval_status
    computed_amount, computed_final_amount = _compute_amounts(qty, rate, gst_percent)
    req.request_date = request_date
    req.factory_id = factory_id
    req.vendor_id = vendor_id
    req.vendor_mobile = vendor_mobile
    req.item_category = item_category
    req.item_name = item_name
    req.qty = qty
    req.unit = unit
    req.rate = rate
    req.amount = computed_amount
    req.gst_percent = gst_percent
    req.final_amount = computed_final_amount
    req.reason = reason
    req.urgent_flag = urgent_flag
    req.requested_by = requested_by
    req.notes = notes

    if geo_latitude is not None and geo_longitude is not None:
        req.geo_latitude = geo_latitude
        req.geo_longitude = geo_longitude
        req.geo_accuracy_m = geo_accuracy_m
        req.geo_captured_at = datetime.utcnow()
        factory_obj = db.get(Factory, factory_id)
        req.is_in_factory, req.distance_from_factory_m = _compute_presence(factory_obj, geo_latitude, geo_longitude)

        _upsert_presence(
            db,
            user_id=user.id,
            factory_id=factory_id,
            latitude=geo_latitude,
            longitude=geo_longitude,
            accuracy_m=geo_accuracy_m,
            captured_at=req.geo_captured_at,
            is_in_factory=req.is_in_factory,
            distance_from_factory_m=req.distance_from_factory_m,
        )

    if bill_image:
        req.bill_image_path = _save_file(bill_image)

    if user.role == "factory":
        req.approval_status = "Draft" if save_as_draft else "Pending"
        req.is_unread_admin = not save_as_draft

    log_change(db, entity="purchase_request", entity_id=req.id, action="UPDATE", old_value=old, new_value=_as_dict(req), changed_by=user.id)
    db.commit()

    telegram_sent = True
    if user.role == "factory" and req.approval_status == "Pending" and old_status != "Pending":
        telegram_sent = _notify_request_submission(
            db=db,
            req=req,
            factory_id=factory_id,
            vendor_id=vendor_id,
            vendor_mobile=vendor_mobile,
            item_name=item_name,
            requested_by=requested_by,
            urgent_flag=urgent_flag,
        )

    message = "Updated"
    if user.role == "factory" and req.approval_status == "Pending" and old_status != "Pending" and not telegram_sent:
        message = "Updated, but Telegram notification failed"
    return {"message": message}


@router.post("/presence/ping")
def presence_ping(
    latitude: float = Form(...),
    longitude: float = Form(...),
    accuracy_m: float | None = Form(None),
    factory_id: int | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role != "factory":
        raise HTTPException(403, "Only factory users can update location")

    selected_factory_id = factory_id
    if not selected_factory_id:
        selected_factory_id = db.scalar(
            select(Factory.id).where(Factory.is_deleted.is_(False)).order_by(Factory.id.asc())
        )

    factory_obj = db.get(Factory, selected_factory_id) if selected_factory_id else None
    is_in_factory, distance_from_factory_m = _compute_presence(factory_obj, latitude, longitude)
    captured_at = datetime.utcnow()

    _upsert_presence(
        db,
        user_id=user.id,
        factory_id=selected_factory_id,
        latitude=latitude,
        longitude=longitude,
        accuracy_m=accuracy_m,
        captured_at=captured_at,
        is_in_factory=is_in_factory,
        distance_from_factory_m=distance_from_factory_m,
    )
    db.commit()

    return {
        "message": "Location updated",
        "is_in_factory": is_in_factory,
        "distance_from_factory_m": distance_from_factory_m,
        "last_seen_at": str(captured_at),
    }


@router.get("/presence/users")
def list_presence_users(
    db: Session = Depends(get_db),
    _user: User = Depends(admin_required),
):
    stale_before = datetime.utcnow() - timedelta(minutes=10)
    rows = db.execute(
        select(UserPresence, User, Factory)
        .join(User, User.id == UserPresence.user_id)
        .join(Factory, Factory.id == UserPresence.factory_id, isouter=True)
        .where(User.role == "factory")
        .order_by(User.name.asc())
    ).all()

    items = []
    for presence, usr, fac in rows:
        is_stale = presence.last_seen_at < stale_before
        if is_stale:
            status = "Offline"
        elif presence.is_in_factory is True:
            status = "In Factory"
        elif presence.is_in_factory is False:
            status = "Outside"
        else:
            status = "Unknown"

        items.append(
            {
                "user_id": usr.id,
                "user_name": usr.name,
                "username": usr.username,
                "factory": fac.name if fac else "",
                "status": status,
                "is_in_factory": presence.is_in_factory,
                "distance_from_factory_m": presence.distance_from_factory_m,
                "accuracy_m": presence.accuracy_m,
                "last_seen_at": str(presence.last_seen_at),
                "latitude": presence.latitude,
                "longitude": presence.longitude,
            }
        )

    return {"items": items}


@router.get("/requests/{request_id}/bill")
def view_bill(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Redirect to the bill image, whether stored in R2 or local uploads."""
    from fastapi.responses import RedirectResponse, FileResponse
    import os
    from pathlib import Path

    req = db.get(PurchaseRequest, request_id)
    if not req or req.is_deleted:
        raise HTTPException(404, "Request not found")
    if user.role != "admin" and req.requested_by_user_id != user.id:
        raise HTTPException(403, "Not authorized")

    path = (req.bill_image_path or "").strip()
    if not path:
        raise HTTPException(404, "No bill attached to this request")

    # R2 / S3 — full public URL → redirect the browser directly
    if path.startswith("http://") or path.startswith("https://"):
        return RedirectResponse(url=path, status_code=302)

    # Local storage — serve the file from disk
    local_path = Path(path.lstrip("/"))
    if not local_path.exists():
        upload_dir = Path(os.getenv("UPLOAD_DIR", "uploads"))
        local_path = upload_dir / local_path.name
    if local_path.exists():
        return FileResponse(str(local_path))

    raise HTTPException(404, "Bill file not found on server")


@router.delete("/requests/{request_id}")

def delete_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    req = db.get(PurchaseRequest, request_id)
    if not req or req.is_deleted:
        raise HTTPException(404, "Request not found")

    if user.role != "admin":
        if req.requested_by_user_id != user.id or req.approval_status not in ["Pending", "Draft", "Hold"]:
            raise HTTPException(403, "Delete not permitted")

    req.is_deleted = True
    log_change(db, entity="purchase_request", entity_id=req.id, action="SOFT_DELETE", old_value=_as_dict(req), changed_by=user.id)
    db.commit()
    return {"message": "Deleted"}


@router.post("/requests/{request_id}/approve")
def approve_request(
    request_id: int,
    approved_amount: float = Form(...),
    remarks: str | None = Form(None),
    priority: str | None = Form("Medium"),
    expected_payment_date: date | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(admin_required),
):
    req = db.get(PurchaseRequest, request_id)
    if not req or req.is_deleted:
        raise HTTPException(404, "Request not found")

    if approved_amount <= 0:
        raise HTTPException(400, "Approved amount must be greater than zero")

    old = _as_dict(req)
    req.approval_status = "Approved"
    req.approved_amount = approved_amount
    req.approval_remark = remarks
    req.priority = priority
    req.expected_payment_date = expected_payment_date
    req.approved_by = user.id
    req.approved_at = datetime.utcnow()
    req.is_unread_admin = False

    log_change(db, entity="purchase_request", entity_id=req.id, action="APPROVE", old_value=old, new_value=_as_dict(req), changed_by=user.id)
    db.commit()
    return {"message": "Approved"}


@router.post("/requests/{request_id}/reject")
def reject_request(
    request_id: int,
    reason: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(admin_required),
):
    req = db.get(PurchaseRequest, request_id)
    if not req or req.is_deleted:
        raise HTTPException(404, "Request not found")

    old = _as_dict(req)
    req.approval_status = "Rejected"
    req.approval_remark = reason
    req.approved_by = user.id
    req.approved_at = datetime.utcnow()
    req.is_unread_admin = False

    log_change(db, entity="purchase_request", entity_id=req.id, action="REJECT", old_value=old, new_value=_as_dict(req), changed_by=user.id)
    db.commit()
    return {"message": "Rejected"}


@router.post("/requests/{request_id}/hold")
def hold_request(
    request_id: int,
    remarks: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(admin_required),
):
    req = db.get(PurchaseRequest, request_id)
    if not req or req.is_deleted:
        raise HTTPException(404, "Request not found")

    old = _as_dict(req)
    req.approval_status = "Hold"
    req.approval_remark = remarks
    req.is_unread_admin = False

    log_change(db, entity="purchase_request", entity_id=req.id, action="HOLD", old_value=old, new_value=_as_dict(req), changed_by=user.id)
    db.commit()
    return {"message": "Moved to hold"}


@router.post("/requests/{request_id}/pay")
def mark_paid(
    request_id: int,
    payment_date: date = Form(...),
    payment_mode: str = Form(...),
    transaction_ref: str | None = Form(None),
    paid_amount: float = Form(...),
    partial_payment: bool = Form(False),
    remarks: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(admin_required),
):
    req = db.get(PurchaseRequest, request_id)
    if not req or req.is_deleted:
        raise HTTPException(404, "Request not found")
    if req.approval_status != "Approved":
        raise HTTPException(400, "Cannot mark paid unless approved")
    if paid_amount <= 0:
        raise HTTPException(400, "Paid amount must be greater than zero")

    approved_amount = req.approved_amount or req.final_amount
    total_paid = db.scalar(
        select(func.coalesce(func.sum(Payment.paid_amount), 0)).where(Payment.request_id == request_id)
    )
    if paid_amount > max(approved_amount - total_paid, 0):
        raise HTTPException(400, "Paid amount exceeds remaining balance")

    new_total_paid = total_paid + paid_amount
    balance = max(approved_amount - new_total_paid, 0)

    payment = Payment(
        request_id=request_id,
        payment_date=payment_date,
        payment_mode=payment_mode,
        transaction_ref=transaction_ref,
        paid_amount=paid_amount,
        balance_amount=balance,
        remark=remarks,
        created_by=user.id,
    )
    db.add(payment)

    if balance == 0:
        req.payment_status = "Paid"
    elif new_total_paid > 0:
        req.payment_status = "Partially Paid"
    else:
        req.payment_status = "Unpaid"

    log_change(
        db,
        entity="payment",
        entity_id=request_id,
        action="PAY",
        new_value={
            "paid_amount": paid_amount,
            "new_total_paid": new_total_paid,
            "balance": balance,
            "status": req.payment_status,
        },
        changed_by=user.id,
    )
    db.commit()
    return {"message": "Payment recorded", "balance": balance, "payment_status": req.payment_status}


@router.get("/notifications/unread-count")
def unread_count(db: Session = Depends(get_db), user: User = Depends(admin_required)):
    count = db.scalar(
        select(func.count(PurchaseRequest.id)).where(
            and_(PurchaseRequest.is_deleted.is_(False), PurchaseRequest.is_unread_admin.is_(True))
        )
    )
    return {"count": count, "user": user.username}


@router.post("/notifications/mark-read")
def mark_notifications_read(db: Session = Depends(get_db), user: User = Depends(admin_required)):
    rows = db.scalars(
        select(PurchaseRequest).where(
            and_(PurchaseRequest.is_deleted.is_(False), PurchaseRequest.is_unread_admin.is_(True))
        )
    ).all()
    for row in rows:
        row.is_unread_admin = False
    db.commit()
    return {"message": "Notifications marked as read"}
