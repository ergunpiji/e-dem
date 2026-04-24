"""
Müşteri yönetimi (admin only)
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin
from database import get_db
from models import Customer, User
from templates_config import templates

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_class=HTMLResponse, name="customers_list")
async def customers_list(
    request: Request,
    q: str = "",
    active_only: str = "1",
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Customer)
    if active_only == "1":
        query = query.filter(Customer.active == True)  # noqa: E712
    if q:
        query = query.filter(Customer.name.ilike(f"%{q}%") | Customer.code.ilike(f"%{q}%"))
    customers = query.order_by(Customer.name).all()
    return templates.TemplateResponse(
        "customers/list.html",
        {"request": request, "current_user": current_user,
         "customers": customers, "q": q, "active_only": active_only,
         "page_title": "Müşteriler"},
    )


@router.get("/new", response_class=HTMLResponse, name="customer_new_get")
async def customer_new_get(
    request: Request,
    current_user: User = Depends(require_admin),
):
    return templates.TemplateResponse(
        "customers/form.html",
        {"request": request, "current_user": current_user,
         "customer": None, "page_title": "Yeni Müşteri", "error": None},
    )


@router.post("/new", name="customer_new_post")
async def customer_new_post(
    request: Request,
    name: str = Form(...),
    code: str = Form(...),
    sector: str = Form(""),
    tax_no: str = Form(""),
    tax_office: str = Form(""),
    address: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    code = code.strip().upper()[:3]
    if db.query(Customer).filter(Customer.code == code).first():
        return templates.TemplateResponse(
            "customers/form.html",
            {"request": request, "current_user": current_user,
             "customer": None, "page_title": "Yeni Müşteri",
             "error": f"'{code}' kodu zaten kullanılıyor."},
            status_code=400,
        )
    c = Customer(
        name=name.strip(), code=code, sector=sector.strip(),
        tax_no=tax_no.strip(), tax_office=tax_office.strip(),
        address=address.strip(), email=email.strip(), phone=phone.strip(),
    )
    db.add(c)
    db.commit()
    return RedirectResponse(url="/customers", status_code=status.HTTP_302_FOUND)


@router.get("/{customer_id}/edit", response_class=HTMLResponse, name="customer_edit_get")
async def customer_edit_get(
    customer_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    c = db.query(Customer).get(customer_id)
    if not c:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "customers/form.html",
        {"request": request, "current_user": current_user,
         "customer": c, "page_title": f"Düzenle — {c.name}", "error": None},
    )


@router.post("/{customer_id}/edit", name="customer_edit_post")
async def customer_edit_post(
    customer_id: int,
    request: Request,
    name: str = Form(...),
    code: str = Form(...),
    sector: str = Form(""),
    tax_no: str = Form(""),
    tax_office: str = Form(""),
    address: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    c = db.query(Customer).get(customer_id)
    if not c:
        raise HTTPException(status_code=404)
    code = code.strip().upper()[:3]
    existing = db.query(Customer).filter(Customer.code == code, Customer.id != customer_id).first()
    if existing:
        return templates.TemplateResponse(
            "customers/form.html",
            {"request": request, "current_user": current_user,
             "customer": c, "page_title": f"Düzenle — {c.name}",
             "error": f"'{code}' kodu zaten kullanılıyor."},
            status_code=400,
        )
    c.name = name.strip()
    c.code = code
    c.sector = sector.strip()
    c.tax_no = tax_no.strip()
    c.tax_office = tax_office.strip()
    c.address = address.strip()
    c.email = email.strip()
    c.phone = phone.strip()
    db.commit()
    return RedirectResponse(url="/customers", status_code=status.HTTP_302_FOUND)


@router.post("/{customer_id}/toggle-active", name="customer_toggle_active")
async def customer_toggle_active(
    customer_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    c = db.query(Customer).get(customer_id)
    if c:
        c.active = not c.active
        db.commit()
    return RedirectResponse(url="/customers", status_code=status.HTTP_302_FOUND)


@router.post("/{customer_id}/delete", name="customer_delete")
async def customer_delete(
    customer_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    c = db.query(Customer).get(customer_id)
    if c:
        try:
            db.delete(c)
            db.commit()
        except Exception:
            db.rollback()
    return RedirectResponse(url="/customers", status_code=status.HTTP_302_FOUND)
