"""
Kullanıcı yönetimi (admin only)
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin, hash_password
from database import get_db
from models import User, Employee
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
    db: Session = Depends(get_db),
):
    employees = db.query(Employee).filter(Employee.active == True).order_by(Employee.name).all()
    return templates.TemplateResponse(
        "users/form.html",
        {"request": request, "current_user": current_user,
         "user": None, "employees": employees,
         "page_title": "Yeni Kullanıcı", "error": None},
    )


@router.post("/new", name="user_new_post")
async def user_new_post(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    is_admin: str = Form("0"),
    is_approver: str = Form("0"),
    employee_id: str = Form(""),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    if db.query(User).filter(User.email == email).first():
        employees = db.query(Employee).filter(Employee.active == True).order_by(Employee.name).all()
        return templates.TemplateResponse(
            "users/form.html",
            {"request": request, "current_user": current_user,
             "user": None, "employees": employees,
             "page_title": "Yeni Kullanıcı",
             "error": f"'{email}' e-posta adresi zaten kayıtlı."},
            status_code=400,
        )
    u = User(
        name=name.strip(),
        email=email,
        password_hash=hash_password(password),
        is_admin=(is_admin == "1"),
        is_approver=(is_approver == "1"),
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
    employees = db.query(Employee).filter(Employee.active == True).order_by(Employee.name).all()
    linked_employee = db.query(Employee).filter(Employee.user_id == user_id).first()
    u.linked_employee = linked_employee
    return templates.TemplateResponse(
        "users/form.html",
        {"request": request, "current_user": current_user,
         "user": u, "employees": employees,
         "page_title": f"Düzenle — {u.name}", "error": None},
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
    employee_id: str = Form(""),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    u = db.query(User).get(user_id)
    if not u:
        raise HTTPException(status_code=404)
    email = email.strip().lower()
    existing = db.query(User).filter(User.email == email, User.id != user_id).first()
    if existing:
        employees = db.query(Employee).filter(Employee.active == True).order_by(Employee.name).all()
        linked_employee = db.query(Employee).filter(Employee.user_id == user_id).first()
        u.linked_employee = linked_employee
        return templates.TemplateResponse(
            "users/form.html",
            {"request": request, "current_user": current_user,
             "user": u, "employees": employees,
             "page_title": f"Düzenle — {u.name}",
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

    # employee-user link güncelle
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
