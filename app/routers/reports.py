from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import and_, extract, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import admin_required
from app.models import Factory, Payment, PurchaseRequest, Vendor
from app.utils.report_export import export_rows_to_excel, export_rows_to_pdf

router = APIRouter(prefix="/reports", tags=["reports"])


def _req_to_dict(x: PurchaseRequest):
    return {
        "id": x.id,
        "request_date": str(x.request_date),
        "factory": x.factory.name if x.factory else "",
        "vendor": x.vendor.name if x.vendor else "",
        "item_category": x.item_category,
        "item_name": x.item_name,
        "qty": x.qty,
        "unit": x.unit,
        "final_amount": x.final_amount,
        "requested_by": x.requested_by,
        "approval_status": x.approval_status,
        "payment_status": x.payment_status,
    }


def _base_filtered(
    db: Session,
    from_date: date | None,
    to_date: date | None,
    vendor_id: int | None,
    factory_id: int | None,
    status: str | None,
    payment_status: str | None,
    item_category: str | None,
):
    q = select(PurchaseRequest).where(PurchaseRequest.is_deleted.is_(False))
    if from_date:
        q = q.where(PurchaseRequest.request_date >= from_date)
    if to_date:
        q = q.where(PurchaseRequest.request_date <= to_date)
    if vendor_id:
        q = q.where(PurchaseRequest.vendor_id == vendor_id)
    if factory_id:
        q = q.where(PurchaseRequest.factory_id == factory_id)
    if status:
        q = q.where(PurchaseRequest.approval_status == status)
    if payment_status:
        q = q.where(PurchaseRequest.payment_status == payment_status)
    if item_category:
        q = q.where(PurchaseRequest.item_category == item_category)
    return db.scalars(q).all()


def _rows_for_export(items: list[PurchaseRequest]):
    headers = [
        "ID",
        "Date",
        "Factory",
        "Vendor",
        "Item",
        "Qty",
        "Amount",
        "Approval Status",
        "Payment Status",
    ]
    rows = [
        [
            x.id,
            str(x.request_date),
            x.factory.name if x.factory else "",
            x.vendor.name if x.vendor else "",
            x.item_name,
            x.qty,
            x.final_amount,
            x.approval_status,
            x.payment_status,
        ]
        for x in items
    ]
    return headers, rows


@router.get("/daily")
def daily_report(
    report_date: date | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(admin_required),
):
    day = report_date or date.today()
    items = db.scalars(
        select(PurchaseRequest).where(
            and_(PurchaseRequest.request_date == day, PurchaseRequest.is_deleted.is_(False))
        )
    ).all()
    return {
        "date": str(day),
        "count": len(items),
        "total": sum(i.final_amount for i in items),
        "items": [_req_to_dict(i) for i in items],
    }


@router.get("/weekly")
def weekly_report(db: Session = Depends(get_db), _=Depends(admin_required)):
    today = date.today()
    start = today - timedelta(days=6)
    items = _base_filtered(db, start, today, None, None, None, None, None)
    return {
        "from": str(start),
        "to": str(today),
        "count": len(items),
        "total": sum(i.final_amount for i in items),
        "items": [_req_to_dict(i) for i in items],
    }


@router.get("/monthly")
def monthly_report(
    year: int | None = Query(None),
    month: int | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(admin_required),
):
    today = date.today()
    y = year or today.year
    m = month or today.month
    items = db.scalars(
        select(PurchaseRequest).where(
            and_(
                extract("year", PurchaseRequest.request_date) == y,
                extract("month", PurchaseRequest.request_date) == m,
                PurchaseRequest.is_deleted.is_(False),
            )
        )
    ).all()
    return {
        "year": y,
        "month": m,
        "count": len(items),
        "total": sum(i.final_amount for i in items),
        "items": [_req_to_dict(i) for i in items],
    }


@router.get("/vendor-wise")
def vendor_wise(db: Session = Depends(get_db), _=Depends(admin_required)):
    rows = db.execute(
        select(Vendor.name, func.count(PurchaseRequest.id), func.sum(PurchaseRequest.final_amount))
        .join(PurchaseRequest, PurchaseRequest.vendor_id == Vendor.id)
        .where(PurchaseRequest.is_deleted.is_(False))
        .group_by(Vendor.name)
        .order_by(func.sum(PurchaseRequest.final_amount).desc())
    ).all()
    return {"items": [{"vendor": r[0], "count": r[1], "total": float(r[2] or 0)} for r in rows]}


@router.get("/item-wise")
def item_wise(db: Session = Depends(get_db), _=Depends(admin_required)):
    rows = db.execute(
        select(PurchaseRequest.item_name, func.count(PurchaseRequest.id), func.sum(PurchaseRequest.final_amount))
        .where(PurchaseRequest.is_deleted.is_(False))
        .group_by(PurchaseRequest.item_name)
        .order_by(func.sum(PurchaseRequest.final_amount).desc())
    ).all()
    return {"items": [{"item": r[0], "count": r[1], "total": float(r[2] or 0)} for r in rows]}


@router.get("/factory-wise")
def factory_wise(db: Session = Depends(get_db), _=Depends(admin_required)):
    rows = db.execute(
        select(Factory.name, func.count(PurchaseRequest.id), func.sum(PurchaseRequest.final_amount))
        .join(PurchaseRequest, PurchaseRequest.factory_id == Factory.id)
        .where(PurchaseRequest.is_deleted.is_(False))
        .group_by(Factory.name)
        .order_by(func.sum(PurchaseRequest.final_amount).desc())
    ).all()
    return {"items": [{"factory": r[0], "count": r[1], "total": float(r[2] or 0)} for r in rows]}


@router.get("/pending-payment")
def pending_payment_report(db: Session = Depends(get_db), _=Depends(admin_required)):
    items = db.scalars(
        select(PurchaseRequest).where(
            and_(
                PurchaseRequest.is_deleted.is_(False),
                PurchaseRequest.approval_status == "Approved",
                PurchaseRequest.payment_status.in_(["Unpaid", "Partially Paid"]),
            )
        )
    ).all()
    return {"count": len(items), "items": [_req_to_dict(i) for i in items]}


@router.get("/user-wise")
def user_wise_report(db: Session = Depends(get_db), _=Depends(admin_required)):
    rows = db.execute(
        select(PurchaseRequest.requested_by, func.count(PurchaseRequest.id), func.sum(PurchaseRequest.final_amount))
        .where(PurchaseRequest.is_deleted.is_(False))
        .group_by(PurchaseRequest.requested_by)
        .order_by(func.sum(PurchaseRequest.final_amount).desc())
    ).all()
    return {"items": [{"user": r[0], "count": r[1], "total": float(r[2] or 0)} for r in rows]}


@router.get("/rejected")
def rejected_report(db: Session = Depends(get_db), _=Depends(admin_required)):
    items = db.scalars(
        select(PurchaseRequest).where(
            and_(PurchaseRequest.approval_status == "Rejected", PurchaseRequest.is_deleted.is_(False))
        )
    ).all()
    return {"count": len(items), "items": [_req_to_dict(i) for i in items]}


@router.get("/cash-vs-bank")
def cash_vs_bank(db: Session = Depends(get_db), _=Depends(admin_required)):
    rows = db.execute(select(Payment.payment_mode, func.sum(Payment.paid_amount)).group_by(Payment.payment_mode)).all()
    return {"items": [{"payment_mode": r[0], "total": float(r[1] or 0)} for r in rows]}


@router.get("/all")
def all_with_filters(
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    vendor_id: int | None = Query(None),
    factory_id: int | None = Query(None),
    status: str | None = Query(None),
    payment_status: str | None = Query(None),
    user: str | None = Query(None),
    item_category: str | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(admin_required),
):
    rows = _base_filtered(db, from_date, to_date, vendor_id, factory_id, status, payment_status, item_category)
    if user:
        rows = [x for x in rows if x.requested_by == user]
    return {"count": len(rows), "items": [_req_to_dict(x) for x in rows]}


@router.get("/export")
def export_report(
    format: str = Query("excel", pattern="^(excel|pdf)$"),
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    vendor_id: int | None = Query(None),
    factory_id: int | None = Query(None),
    status: str | None = Query(None),
    payment_status: str | None = Query(None),
    item_category: str | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(admin_required),
):
    rows = _base_filtered(db, from_date, to_date, vendor_id, factory_id, status, payment_status, item_category)
    headers, values = _rows_for_export(rows)

    if format == "excel":
        data = export_rows_to_excel("Purchase Report", headers, values)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=purchase_report.xlsx"},
        )

    data = export_rows_to_pdf("Purchase Report", headers, values)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=purchase_report.pdf"},
    )
