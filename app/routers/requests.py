from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import admin_required, get_current_user
from app.models import Payment, PurchaseRequest, User, Vendor
from app.utils.audit import log_change
from app.utils.storage import save_upload

router = APIRouter(tags=["requests"])

def _as_dict(req: PurchaseRequest) -> dict:
    return {
        "id": req.id,
        "request_date": str(req.request_date),
        "factory_id": req.factory_id,
        "vendor": req.vendor.name if req.vendor else "",
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
    notes: str | None = Form(None),
    save_as_draft: bool = Form(False),
    bill_image: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role != "admin" and user.role != "factory":
        raise HTTPException(403, "Invalid role")

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
        amount=amount,
        gst_percent=gst_percent,
        final_amount=final_amount,
        reason=reason,
        urgent_flag=urgent_flag,
        requested_by=requested_by,
        requested_by_user_id=user.id,
        bill_image_path=_save_file(bill_image),
        notes=notes,
        approval_status="Draft" if save_as_draft else "Pending",
        payment_status="Unpaid",
        is_unread_admin=user.role == "factory",
    )
    db.add(req)
    db.flush()
    log_change(db, entity="purchase_request", entity_id=req.id, action="CREATE", new_value=_as_dict(req), changed_by=user.id)
    db.commit()
    return {"message": "Request saved", "id": req.id}


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
    notes: str | None = Form(None),
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

    old = _as_dict(req)
    req.request_date = request_date
    req.factory_id = factory_id
    req.vendor_id = vendor_id
    req.vendor_mobile = vendor_mobile
    req.item_category = item_category
    req.item_name = item_name
    req.qty = qty
    req.unit = unit
    req.rate = rate
    req.amount = amount
    req.gst_percent = gst_percent
    req.final_amount = final_amount
    req.reason = reason
    req.urgent_flag = urgent_flag
    req.requested_by = requested_by
    req.notes = notes

    if bill_image:
        req.bill_image_path = _save_file(bill_image)

    if user.role == "factory":
        req.is_unread_admin = True

    log_change(db, entity="purchase_request", entity_id=req.id, action="UPDATE", old_value=old, new_value=_as_dict(req), changed_by=user.id)
    db.commit()
    return {"message": "Updated"}


@router.delete("/requests/{request_id}")
def delete_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(admin_required),
):
    req = db.get(PurchaseRequest, request_id)
    if not req or req.is_deleted:
        raise HTTPException(404, "Request not found")

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

    approved_amount = req.approved_amount or req.final_amount
    total_paid = db.scalar(
        select(func.coalesce(func.sum(Payment.paid_amount), 0)).where(Payment.request_id == request_id)
    )
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
    elif partial_payment and new_total_paid > 0:
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
