from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Factory, ItemCategory, PaymentMode, Unit, User, Vendor
from app.security import get_password_hash


DEFAULT_UNITS = ["pcs", "kg", "ton", "liter", "meter", "box", "nos"]
DEFAULT_PAYMENT_MODES = ["Cash", "UPI", "Bank Transfer", "Cheque"]
DEFAULT_CATEGORIES = ["Raw Material", "Consumable", "Maintenance", "Packaging", "Utility"]


def seed_defaults(db: Session) -> None:
    admin_user = db.scalar(select(User).where(User.username == "admin"))
    if not admin_user:
        db.add(
            User(
                name="System Admin",
                username="admin",
                password_hash=get_password_hash("admin123"),
                role="admin",
            )
        )
    elif not admin_user.is_active:
        admin_user.is_active = True

    factory_user = db.scalar(select(User).where(User.username == "factory1"))
    if not factory_user:
        db.add(
            User(
                name="Factory User",
                username="factory1",
                password_hash=get_password_hash("factory123"),
                role="factory",
            )
        )
    elif not factory_user.is_active:
        factory_user.is_active = True

    factory_exists = db.scalar(select(Factory).limit(1))
    if not factory_exists:
        db.add(Factory(name="Main Factory", location="Unit 1"))

    vendor_exists = db.scalar(select(Vendor).limit(1))
    if not vendor_exists:
        db.add(Vendor(name="Local Supplier", mobile="", address="", gst_no=""))

    existing_units = {u.name for u in db.scalars(select(Unit)).all()}
    for item in DEFAULT_UNITS:
        if item not in existing_units:
            db.add(Unit(name=item))

    existing_modes = {m.name for m in db.scalars(select(PaymentMode)).all()}
    for item in DEFAULT_PAYMENT_MODES:
        if item not in existing_modes:
            db.add(PaymentMode(name=item))

    existing_categories = {c.name for c in db.scalars(select(ItemCategory)).all()}
    for item in DEFAULT_CATEGORIES:
        if item not in existing_categories:
            db.add(ItemCategory(name=item))

    db.commit()
