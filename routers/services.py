"""
E-dem — Hizmet kataloğu router'ı (Admin only)
"""

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin
from database import get_db
from models import CustomCategory, Service, SERVICE_CATEGORIES, User, _uuid

router = APIRouter(prefix="/services", tags=["services"])
from templates_config import templates


@router.get("", response_class=HTMLResponse, name="services_list")
async def services_list(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    services    = db.query(Service).order_by(Service.category, Service.name).all()
    custom_cats = db.query(CustomCategory).all()

    # Servisleri kategoriye göre grupla
    grouped: dict = {}
    for svc in services:
        grouped.setdefault(svc.category, []).append(svc)

    return templates.TemplateResponse(
        "services/list.html",
        {
            "request":           request,
            "current_user":      current_user,
            "grouped_services":  grouped,
            "service_categories": SERVICE_CATEGORIES,
            "custom_categories": custom_cats,
            "page_title":        "Hizmet Kataloğu",
        },
    )


@router.get("/api", name="services_api")
async def services_api(
    category: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Katalogdan ekle için JSON endpoint"""
    query = db.query(Service).filter(Service.active == True)
    if category:
        query = query.filter(Service.category == category)
    services = query.order_by(Service.name).all()
    return JSONResponse([s.to_dict() for s in services])


@router.post("/new", name="services_create")
async def services_create(
    category:    str = Form(...),
    name:        str = Form(...),
    unit:        str = Form("Adet"),
    description: str = Form(""),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    svc = Service(id=_uuid(), category=category, name=name.strip(), unit=unit.strip(), description=description.strip(), active=True)
    db.add(svc)
    db.commit()
    return RedirectResponse(url="/services", status_code=status.HTTP_302_FOUND)


@router.post("/{svc_id}/toggle", name="services_toggle")
async def services_toggle(
    svc_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    svc = db.query(Service).filter(Service.id == svc_id).first()
    if svc:
        svc.active = not svc.active
        db.commit()
    return RedirectResponse(url="/services", status_code=status.HTTP_302_FOUND)


@router.post("/{svc_id}/delete", name="services_delete")
async def services_delete(
    svc_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    svc = db.query(Service).filter(Service.id == svc_id).first()
    if svc:
        db.delete(svc)
        db.commit()
    return RedirectResponse(url="/services", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Özel Kategoriler
# ---------------------------------------------------------------------------

@router.post("/categories/new", name="custom_cat_create")
async def custom_cat_create(
    name:      str = Form(...),
    icon:      str = Form("📋"),
    bg_color:  str = Form("#e0f2fe"),
    txt_color: str = Form("#0c4a6e"),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    cat = CustomCategory(id=_uuid(), name=name.strip(), icon=icon, bg_color=bg_color, txt_color=txt_color)
    db.add(cat)
    db.commit()
    return RedirectResponse(url="/services", status_code=status.HTTP_302_FOUND)


@router.post("/categories/{cat_id}/delete", name="custom_cat_delete")
async def custom_cat_delete(
    cat_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    cat = db.query(CustomCategory).filter(CustomCategory.id == cat_id).first()
    if cat:
        db.delete(cat)
        db.commit()
    return RedirectResponse(url="/services", status_code=status.HTTP_302_FOUND)
