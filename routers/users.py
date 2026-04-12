"""
E-dem — Kullanıcı yönetimi router'ı (Admin only)
GET    /users                    → Kullanıcı listesi
GET    /users/new                → Yeni kullanıcı formu
POST   /users/new                → Yeni kullanıcı oluştur
GET    /users/{id}/edit          → Düzenleme formu
POST   /users/{id}/edit          → Kullanıcı güncelle
POST   /users/{id}/delete        → Kullanıcı sil (soft delete)
GET    /users/org-titles         → Organizasyon unvanları yönetimi
POST   /users/org-titles/{id}    → Unvan bütçe limiti güncelle
"""

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import hash_password, require_admin
from database import get_db
from models import OrgTitle, User, USER_ROLES, _uuid, _now

router = APIRouter(prefix="/users", tags=["users"])
from templates_config import templates


def _get_org_titles(db: Session) -> list:
    return db.query(OrgTitle).order_by(OrgTitle.sort_order).all()


@router.get("", response_class=HTMLResponse, name="users_list")
async def users_list(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    welcome_for: str = "",
):
    users = db.query(User).order_by(User.created_at.desc()).all()
    welcome_user = db.query(User).filter(User.id == welcome_for).first() if welcome_for else None
    return templates.TemplateResponse(
        "users/list.html",
        {
            "request":      request,
            "current_user": current_user,
            "users":        users,
            "page_title":   "Kullanıcı Yönetimi",
            "user_roles":   USER_ROLES,
            "welcome_user": welcome_user,
        },
    )


@router.get("/org-titles", response_class=HTMLResponse, name="users_org_titles")
async def org_titles_page(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    saved: str = "",
):
    titles = _get_org_titles(db)
    # Tüm kullanıcı sayısını unvan başına hesapla
    user_counts = {}
    for u in db.query(User).filter(User.active == True).all():
        if u.org_title_id:
            user_counts[u.org_title_id] = user_counts.get(u.org_title_id, 0) + 1

    return templates.TemplateResponse(
        "users/org_titles.html",
        {
            "request":      request,
            "current_user": current_user,
            "titles":       titles,
            "user_counts":  user_counts,
            "page_title":   "Organizasyon Yapısı",
            "saved":        saved == "1",
        },
    )


@router.post("/org-titles/{title_id}", name="users_org_title_update")
async def org_title_update(
    title_id: str,
    budget_limit: str = Form(""),
    pm_permission_level: str = Form(""),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    title = db.query(OrgTitle).filter(OrgTitle.id == title_id).first()
    if title:
        val = budget_limit.strip().replace(".", "").replace(",", "")
        title.budget_limit = float(val) if val else None
        lvl = pm_permission_level.strip()
        title.pm_permission_level = lvl if lvl in ("mudur", "yonetici", "asistan") else None
        db.commit()
    return RedirectResponse(url="/users/org-titles?saved=1", status_code=status.HTTP_302_FOUND)


@router.get("/new", response_class=HTMLResponse, name="users_new")
async def users_new(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        "users/form.html",
        {
            "request":      request,
            "current_user": current_user,
            "user":         None,
            "page_title":   "Yeni Kullanıcı",
            "user_roles":   USER_ROLES,
            "org_titles":   _get_org_titles(db),
            "error":        None,
        },
    )


@router.post("/new", name="users_create")
async def users_create(
    request: Request,
    email:         str = Form(...),
    password:      str = Form(...),
    role:          str = Form(...),
    name:          str = Form(...),
    surname:       str = Form(...),
    title:         str = Form(""),
    phone:         str = Form(""),
    org_title_id:  str = Form(""),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter(User.email == email.lower().strip()).first()
    if existing:
        return templates.TemplateResponse(
            "users/form.html",
            {
                "request":      request,
                "current_user": current_user,
                "user":         None,
                "page_title":   "Yeni Kullanıcı",
                "user_roles":   USER_ROLES,
                "org_titles":   _get_org_titles(db),
                "error":        "Bu e-posta adresi zaten kayıtlı.",
                "form_data":    {"email": email, "role": role, "name": name, "surname": surname,
                                 "title": title, "phone": phone, "org_title_id": org_title_id},
            },
            status_code=400,
        )

    user = User(
        id=_uuid(),
        email=email.lower().strip(),
        password_hash=hash_password(password),
        role=role,
        name=name.strip(),
        surname=surname.strip(),
        title=title.strip(),
        phone=phone.strip(),
        org_title_id=org_title_id.strip() or None,
        active=True,
        created_at=_now(),
    )
    db.add(user)
    db.commit()
    # Hoşgeldin bildirimi için mailto: hazırla
    return RedirectResponse(
        url=f"/users?welcome_for={user.id}",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/{user_id}/edit", response_class=HTMLResponse, name="users_edit")
async def users_edit(
    user_id: str,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse(url="/users", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        "users/form.html",
        {
            "request":      request,
            "current_user": current_user,
            "user":         user,
            "page_title":   f"{user.full_name} — Düzenle",
            "user_roles":   USER_ROLES,
            "org_titles":   _get_org_titles(db),
            "error":        None,
        },
    )


@router.post("/{user_id}/edit", name="users_update")
async def users_update(
    user_id:  str,
    request: Request,
    email:         str = Form(...),
    role:          str = Form(...),
    name:          str = Form(...),
    surname:       str = Form(...),
    title:         str = Form(""),
    phone:         str = Form(""),
    password:      str = Form(""),
    active:        str = Form("on"),
    org_title_id:  str = Form(""),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse(url="/users", status_code=status.HTTP_302_FOUND)

    conflict = db.query(User).filter(
        User.email == email.lower().strip(),
        User.id != user_id,
    ).first()
    if conflict:
        return templates.TemplateResponse(
            "users/form.html",
            {
                "request":      request,
                "current_user": current_user,
                "user":         user,
                "page_title":   f"{user.full_name} — Düzenle",
                "user_roles":   USER_ROLES,
                "org_titles":   _get_org_titles(db),
                "error":        "Bu e-posta adresi başka bir kullanıcıya ait.",
            },
            status_code=400,
        )

    user.email        = email.lower().strip()
    user.role         = role
    user.name         = name.strip()
    user.surname      = surname.strip()
    user.title        = title.strip()
    user.phone        = phone.strip()
    user.active       = (active == "on")
    user.org_title_id = org_title_id.strip() or None

    if password.strip():
        user.password_hash = hash_password(password.strip())

    db.commit()
    return RedirectResponse(url="/users", status_code=status.HTTP_302_FOUND)


@router.post("/{user_id}/delete", name="users_delete")
async def users_delete(
    user_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user and user.id != current_user.id:
        user.active = False
        db.commit()
    return RedirectResponse(url="/users", status_code=status.HTTP_302_FOUND)
