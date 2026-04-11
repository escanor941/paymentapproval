from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import and_, extract, func, select
from sqlalchemy.orm import Session
from starlette import status
from starlette.templating import Jinja2Templates

from app.database import get_db
from app.deps import get_current_user
from app.models import Factory, ItemCategory, PaymentMode, PurchaseRequest, Unit, User, Vendor

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="app/templates")


def _common_masters(db: Session):
    return {
        "factories": db.scalars(select(Factory).where(Factory.is_deleted.is_(False))).all(),
        "vendors": db.scalars(select(Vendor).where(Vendor.is_deleted.is_(False))).all(),
        "categories": db.scalars(select(ItemCategory).where(ItemCategory.is_deleted.is_(False))).all(),
        "units": db.scalars(select(Unit).where(Unit.is_deleted.is_(False))).all(),
        "payment_modes": db.scalars(select(PaymentMode).where(PaymentMode.is_deleted.is_(False))).all(),
    }


@router.get("/login")
def login_page(request: Request):
    err = request.session.pop("login_error", None)
    return templates.TemplateResponse("login.html", {"request": request, "error": err})


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    user = db.get(User, user_id)
    if not user or not user.is_active:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    if user.role == "admin":
        today = date.today()
        month = today.month
        year = today.year
        stats = {
            "new_requests": db.scalar(
                select(func.count(PurchaseRequest.id)).where(
                    and_(PurchaseRequest.is_deleted.is_(False), PurchaseRequest.is_unread_admin.is_(True))
                )
            ),
            "pending_approval": db.scalar(
                select(func.count(PurchaseRequest.id)).where(
                    and_(PurchaseRequest.is_deleted.is_(False), PurchaseRequest.approval_status == "Pending")
                )
            ),
            "approved": db.scalar(
                select(func.count(PurchaseRequest.id)).where(
                    and_(PurchaseRequest.is_deleted.is_(False), PurchaseRequest.approval_status == "Approved")
                )
            ),
            "rejected": db.scalar(
                select(func.count(PurchaseRequest.id)).where(
                    and_(PurchaseRequest.is_deleted.is_(False), PurchaseRequest.approval_status == "Rejected")
                )
            ),
            "pending_payment": db.scalar(
                select(func.count(PurchaseRequest.id)).where(
                    and_(
                        PurchaseRequest.is_deleted.is_(False),
                        PurchaseRequest.approval_status == "Approved",
                        PurchaseRequest.payment_status.in_(["Unpaid", "Partially Paid"]),
                    )
                )
            ),
            "paid_today": db.scalar(
                select(func.count(PurchaseRequest.id)).where(
                    and_(
                        PurchaseRequest.is_deleted.is_(False),
                        PurchaseRequest.payment_status == "Paid",
                        PurchaseRequest.updated_at >= today,
                    )
                )
            ),
            "month_spend": db.scalar(
                select(func.coalesce(func.sum(PurchaseRequest.final_amount), 0)).where(
                    and_(
                        PurchaseRequest.is_deleted.is_(False),
                        extract("month", PurchaseRequest.request_date) == month,
                        extract("year", PurchaseRequest.request_date) == year,
                    )
                )
            ),
        }
        return templates.TemplateResponse(
            "dashboard_admin.html",
            {
                "request": request,
                "user": user,
                "stats": stats,
                **_common_masters(db),
            },
        )

    return templates.TemplateResponse(
        "dashboard_factory.html",
        {"request": request, "user": user, **_common_masters(db)},
    )


@router.get("/masters")
def masters_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role != "admin":
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("masters.html", {"request": request, "user": user})


@router.get("/reports")
def reports_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role != "admin":
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        "reports.html",
        {
            "request": request,
            "user": user,
            **_common_masters(db),
        },
    )
