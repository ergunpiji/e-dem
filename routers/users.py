"""
Kullanıcı yönetimi (admin only)
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from typing import Optional

from auth import get_current_user, require_admin, hash_password
from database import get_db
from models import User, Employee, ROLE_ORDER, ROLE_LABELS
from templates_config import templates

router = APIRouter(prefix="/users", tags=["users"])


def _get_form_context(db, current_user, user=None, error=None, page_title="Kullanıcı"):
    employees = db.query(Employee).filter(Employee.active == True).order_by(Employee.name).all()
    # Müdür atanabilecek kullanıcılar: mudur ve üzeri roller, kendisi hariç
    managers = db.query(User).filter(
        User.active == True,
        User.role.in_(["mudur", "genel_mudur", "admin", "super_admin"]),
    ).order_by(User.name).all()
    if user:
        managers = [m for m in managers if m.id != user.id]
    linked_employee = None
    if user:
        linked_employee = db.query(Employee).filter(Employee.user_id == user.id).first()
    return {
        "current_user": current_user,
        "user": user,
        "employees": employees,
        "managers": managers,
        "roles": ROLE_ORDER,
        "role_labels": ROLE_LABELS,
        "page_title": page_title,
        "error": error,
        "linked_employee": linked_employee,
    }


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
         "users": users, "role_labels": ROLE_LABELS, "page_title": "Kullanıcılar"},
    )


@router.get("/new", response_class=HTMLResponse, name="user_new_get")
async def user_new_get(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    ctx = _get_form_context(db, current_user, page_title="Yeni Kullanıcı")
    return templates.TemplateResponse("users/form.html", {"request": request, **ctx})


@router.post("/new", name="user_new_post")
async def user_new_post(
    request: Request,
    name: str = Form(...),
    surname: str = Form(""),
    title: str = Form(""),
    phone: str = Form(""),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("kullanici"),
    manager_id: Optional[int] = Form(None),
    employee_id: str = Form(""),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    if role not in ROLE_ORDER:
        role = "kullanici"
    # super_admin yalnızca mevcut super_admin atayabilir
    if role == "super_admin" and not current_user.has_role_min("super_admin"):
        role = "admin"
    if db.query(User).filter(User.email == email).first():
        ctx = _get_form_context(db, current_user, page_title="Yeni Kullanıcı",
                                error=f"'{email}' e-posta adresi zaten kayıtlı.")
        return templates.TemplateResponse("users/form.html",
                                          {"request": request, **ctx}, status_code=400)
    u = User(
        name=name.strip(),
        surname=surname.strip() or None,
        title=title.strip() or None,
        phone=phone.strip() or None,
        email=email,
        password_hash=hash_password(password),
        role=role,
        manager_id=manager_id or None,
        active=True,
    )
    db.add(u)
    db.flush()
    if employee_id:
        emp = db.query(Employee).get(int(employee_id))
        if emp:
            old = db.query(Employee).filter(Employee.user_id == u.id).first()
            if old:
                old.user_id = None
            emp.user_id = u.id
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
    ctx = _get_form_context(db, current_user, user=u, page_title=f"Düzenle — {u.name}")
    return templates.TemplateResponse("users/form.html", {"request": request, **ctx})


@router.post("/{user_id}/edit", name="user_edit_post")
async def user_edit_post(
    user_id: int,
    request: Request,
    name: str = Form(...),
    surname: str = Form(""),
    title: str = Form(""),
    phone: str = Form(""),
    email: str = Form(...),
    password: str = Form(""),
    role: str = Form("kullanici"),
    manager_id: Optional[int] = Form(None),
    active: str = Form("1"),
    employee_id: str = Form(""),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    u = db.query(User).get(user_id)
    if not u:
        raise HTTPException(status_code=404)
    email = email.strip().lower()
    if role not in ROLE_ORDER:
        role = "kullanici"
    if role == "super_admin" and not current_user.has_role_min("super_admin"):
        role = u.role  # yetkisiz ise değiştirme
    existing = db.query(User).filter(User.email == email, User.id != user_id).first()
    if existing:
        ctx = _get_form_context(db, current_user, user=u,
                                page_title=f"Düzenle — {u.name}",
                                error=f"'{email}' e-posta adresi zaten kayıtlı.")
        return templates.TemplateResponse("users/form.html",
                                          {"request": request, **ctx}, status_code=400)
    u.name = name.strip()
    u.surname = surname.strip() or None
    u.title = title.strip() or None
    u.phone = phone.strip() or None
    u.email = email
    u.role = role
    u.manager_id = manager_id or None
    u.active = (active == "1")
    if password.strip():
        u.password_hash = hash_password(password.strip())

    old_link = db.query(Employee).filter(Employee.user_id == user_id).first()
    if old_link:
        old_link.user_id = None
    if employee_id:
        emp = db.query(Employee).get(int(employee_id))
        if emp:
            emp.user_id = user_id

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
