"""
Kimlik doğrulama
GET  /login  → form
POST /login  → cookie set → /dashboard
GET  /logout → cookie sil → /login
POST /logout → cookie sil → /login
"""

import os

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

import auth as auth_module
from auth import COOKIE_NAME, ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token
from database import get_db
from templates_config import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse, name="login_get")
async def login_get(request: Request, db: Session = Depends(get_db)):
    user = auth_module.get_current_user_optional(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None, "current_user": None},
    )


@router.post("/login", name="login_post")
async def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = auth_module.authenticate_user(db, email, password)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request,
             "error": "E-posta adresi veya şifre hatalı.",
             "current_user": None,
             "email_value": email},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    token = create_access_token(data={
        "sub": str(user.id),
        "is_admin": user.is_admin,
    })
    _is_production = os.environ.get("ENVIRONMENT", "").lower() == "production"
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        secure=_is_production,
    )
    return response


@router.get("/logout", name="logout_get")
@router.post("/logout", name="logout_post")
async def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key=COOKIE_NAME)
    return response
