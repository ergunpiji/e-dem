"""
Kullanıcı yönetimi (admin only)
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin, hash_password
from database import get_db
from models import User
from templates_config import templates

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_class=HTMLResponse, name="users_list")
async def users_list(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    users = db.query(User).order_by(User.name).all()
    return templates.TemplateResponse(
        "users/list.html",
        {"request": request, "current_user": current_user,
         "users": users, "page_title": "Kullanıcılar"},
    )


@router.get("/new", response_class=HTMLResponse, name="user_new_get")
async def user_new_get(
    request: Request,
    current_user: User = Depends(require_admin),
):
    return templates.TemplateResponse(
        "users/form.html",
        {"request": request, "current_user": current_user,
         "user": None, "page_title": "Yeni Kullanıcı", "error": None},
    )


@router.post("/new", name="user_new_post")
async def user_new_post(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    is_admin: str = Form("0"),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    if db.query(User).filter(User.email == email).first():
        return templates.TemplateResponse(
            "users/form.html",
            {"request": request, "current_user": current_user,
             "user": None, "page_title": "Yeni Kullanıcı",
             "error": f"'{email}' e-posta adresi zaten kayıtlı."},
            status_code=400,
        )
    u = User(
        name=name.strip(),
        email=email,
        password_hash=hash_password(password),
        is_admin=(is_admin == "1"),
        active=True,
    )
    db.add(u)
    db.commit()
    return RedirectResponse(url="/users", status_code=status.HTTP_302_FOUND)


@router.get("/{user_id}/edit", response_class=HTMLResponse, name="user_edit_get")
async def user_edit_get(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    u = db.query(User).get(user_id)
    if not u:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "users/form.html",
        {"request": request, "current_user": current_user,
         "user": u, "page_title": f"Düzenle — {u.name}", "error": None},
    )


@router.post("/{user_id}/edit", name="user_edit_post")
async def user_edit_post(
    user_id: int,
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(""),
    is_admin: str = Form("0"),
    is_approver: str = Form("0"),
    active: str = Form("1"),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    u = db.query(User).get(user_id)
    if not u:
        raise HTTPException(status_code=404)
    email = email.strip().lower()
    existing = db.query(User).filter(User.email == email, User.id != user_id).first()
    if existing:
        return templates.TemplateResponse(
            "users/form.html",
            {"request": request, "current_user": current_user,
             "user": u, "page_title": f"Düzenle — {u.name}",
             "error": f"'{email}' e-posta adresi zaten kayıtlı."},
            status_code=400,
        )
    u.name = name.strip()
    u.email = email
    u.is_admin = (is_admin == "1")
    u.is_approver = (is_approver == "1")
    u.active = (active == "1")
    if password.strip():
        u.password_hash = hash_password(password.strip())
    db.commit()
    return RedirectResponse(url="/users", status_code=status.HTTP_302_FOUND)


@router.post("/{user_id}/delete", name="user_delete")
async def user_delete(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Kendi hesabınızı silemezsiniz.")
    u = db.query(User).get(user_id)
    if u:
        u.active = False
        db.commit()
    return RedirectResponse(url="/users", status_code=status.HTTP_302_FOUND)
