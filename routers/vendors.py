"""
Finansal Tedarikçi (FinancialVendor) yönetimi
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import FinancialVendor, Invoice, Cheque, User
from templates_config import templates

router = APIRouter(prefix="/vendors", tags=["vendors"])

VENDOR_TYPES = [
    ("genel", "Genel Tedarikçi"),
    ("otel", "Otel"),
    ("etkinlik", "Etkinlik Mekanı"),
    ("teknik", "Teknik Ekipman"),
    ("transfer", "Transfer"),
    ("catering", "Catering"),
    ("tasarim", "Tasarım & Baskı"),
    ("diger", "Diğer"),
]


@router.get("", response_class=HTMLResponse, name="vendors_list")
async def vendors_list(
    request: Request,
    q: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(FinancialVendor)
    if q:
        query = query.filter(FinancialVendor.name.ilike(f"%{q}%"))
    vendors = query.order_by(FinancialVendor.name).all()
    return templates.TemplateResponse(
        "vendors/list.html",
        {"request": request, "current_user": current_user,
         "vendors": vendors, "q": q, "page_title": "Tedarikçiler"},
    )


@router.get("/new", response_class=HTMLResponse, name="vendor_new_get")
async def vendor_new_get(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(
        "vendors/form.html",
        {"request": request, "current_user": current_user,
         "vendor": None, "vendor_types": VENDOR_TYPES,
         "page_title": "Yeni Tedarikçi"},
    )


@router.post("/new", name="vendor_new_post")
async def vendor_new_post(
    name: str = Form(...),
    vendor_type: str = Form("genel"),
    iban: str = Form(""),
    tax_no: str = Form(""),
    tax_office: str = Form(""),
    address: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    payment_term: int = Form(30),
    contact: str = Form(""),
    notes: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    v = FinancialVendor(
        name=name.strip(), vendor_type=vendor_type,
        iban=iban.strip(), tax_no=tax_no.strip(),
        tax_office=tax_office.strip(), address=address.strip(),
        phone=phone.strip(), email=email.strip(),
        payment_term=payment_term, contact=contact.strip(),
        notes=notes.strip(), active=True,
    )
    db.add(v)
    db.commit()
    return RedirectResponse(url=f"/vendors/{v.id}", status_code=status.HTTP_302_FOUND)


@router.get("/{vendor_id}", response_class=HTMLResponse, name="vendor_detail")
async def vendor_detail(
    vendor_id: int,
    request: Request,
    period: str = "all",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from datetime import date, timedelta
    v = db.query(FinancialVendor).get(vendor_id)
    if not v:
        raise HTTPException(status_code=404)

    today = date.today()
    inv_q = db.query(Invoice).filter(Invoice.vendor_id == vendor_id)
    if period != "all":
        cutoff = today - timedelta(days=int(period))
        inv_q = inv_q.filter(Invoice.invoice_date >= cutoff)
    invoices = inv_q.order_by(Invoice.invoice_date.desc()).all()

    cheques = db.query(Cheque).filter(Cheque.vendor_id == vendor_id).order_by(Cheque.due_date.desc()).all()

    total_amount  = sum(i.amount for i in invoices)
    paid_amount   = sum(i.amount for i in invoices if i.status == "paid")
    unpaid_amount = sum(i.amount for i in invoices if i.status == "approved")
    overdue_amount = sum(
        i.amount for i in invoices
        if i.status == "approved" and i.due_date and i.due_date < today
    )

    return templates.TemplateResponse(
        "vendors/detail.html",
        {
            "request": request, "current_user": current_user,
            "vendor": v, "invoices": invoices, "cheques": cheques,
            "total_amount": total_amount, "paid_amount": paid_amount,
            "unpaid_amount": unpaid_amount, "overdue_amount": overdue_amount,
            "period": period, "today": today,
            "page_title": v.name,
        },
    )


@router.get("/{vendor_id}/edit", response_class=HTMLResponse, name="vendor_edit_get")
async def vendor_edit_get(
    vendor_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    v = db.query(FinancialVendor).get(vendor_id)
    if not v:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "vendors/form.html",
        {"request": request, "current_user": current_user,
         "vendor": v, "vendor_types": VENDOR_TYPES,
         "page_title": f"Düzenle — {v.name}"},
    )


@router.post("/{vendor_id}/edit", name="vendor_edit_post")
async def vendor_edit_post(
    vendor_id: int,
    name: str = Form(...),
    vendor_type: str = Form("genel"),
    iban: str = Form(""),
    tax_no: str = Form(""),
    tax_office: str = Form(""),
    address: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    payment_term: int = Form(30),
    contact: str = Form(""),
    notes: str = Form(""),
    active: str = Form("1"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    v = db.query(FinancialVendor).get(vendor_id)
    if not v:
        raise HTTPException(status_code=404)
    v.name = name.strip()
    v.vendor_type = vendor_type
    v.iban = iban.strip()
    v.tax_no = tax_no.strip()
    v.tax_office = tax_office.strip()
    v.address = address.strip()
    v.phone = phone.strip()
    v.email = email.strip()
    v.payment_term = payment_term
    v.contact = contact.strip()
    v.notes = notes.strip()
    v.active = (active == "1")
    db.commit()
    return RedirectResponse(url=f"/vendors/{vendor_id}", status_code=status.HTTP_302_FOUND)
