from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import verify_password

router = APIRouter(tags=["auth"])


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    normalized_username = username.strip().lower()
    user = db.scalar(
        select(User).where(func.lower(User.username) == normalized_username, User.is_active.is_(True))
    )
    if not user or not verify_password(password, user.password_hash):
        request.session["login_error"] = "Invalid username or password"
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    request.session.clear()
    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
