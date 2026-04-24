"""
Finansal Tedarikçi (FinancialVendor) yönetimi
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import FinancialVendor, Invoice, Cheque, User, CashBook, BankAccount, CreditCard, PAYMENT_METHODS
from templates_config import templates

router = APIRouter(prefix="/vendors", tags=["vendors"])


def _primary_iban(bank_accounts_json: str) -> str:
    import json as _j
    try:
        accounts = _j.loads(bank_accounts_json or "[]")
        if accounts:
            return (accounts[0].get("iban") or "").strip()
    except Exception:
        pass
    return ""


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
    from datetime import date
    from sqlalchemy import func
    query = db.query(FinancialVendor)
    if q:
        query = query.filter(FinancialVendor.name.ilike(f"%{q}%"))
    vendors = query.order_by(FinancialVendor.name).all()

    today = date.today()
    vendor_ids = [v.id for v in vendors]

    # Batch: approved invoices per vendor
    approved_invoices = (
        db.query(Invoice.vendor_id, Invoice.amount, Invoice.due_date)
        .filter(Invoice.vendor_id.in_(vendor_ids), Invoice.status == "approved")
        .all()
    )

    unpaid_map: dict = {}
    overdue_map: dict = {}
    for inv in approved_invoices:
        unpaid_map[inv.vendor_id] = unpaid_map.get(inv.vendor_id, 0) + (inv.amount or 0)
        if inv.due_date and inv.due_date < today:
            overdue_map[inv.vendor_id] = overdue_map.get(inv.vendor_id, 0) + (inv.amount or 0)

    return templates.TemplateResponse(
        "vendors/list.html",
        {"request": request, "current_user": current_user,
         "vendors": vendors, "q": q, "page_title": "Tedarikçiler",
         "unpaid_map": unpaid_map, "overdue_map": overdue_map},
    )


@router.post("/quick-add", name="vendor_quick_add")
async def vendor_quick_add(
    name: str = Form(...),
    tax_no: str = Form(""),
    tax_office: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    payment_term: int = Form(30),
    vendor_type: str = Form("genel"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from fastapi.responses import JSONResponse
    name = name.strip()
    if not name:
        return JSONResponse({"error": "Ad zorunludur."}, status_code=422)
    # İsim çakışması kontrolü
    existing = db.query(FinancialVendor).filter(
        FinancialVendor.name.ilike(name)
    ).first()
    if existing:
        return JSONResponse(
            {"error": f'"{existing.name}" adında bir tedarikçi zaten var.',
             "existing": {"id": existing.id, "name": existing.name,
                          "payment_term": existing.payment_term or 30}},
            status_code=409,
        )
    v = FinancialVendor(
        name=name, vendor_type=vendor_type,
        tax_no=tax_no.strip(), tax_office=tax_office.strip(),
        phone=phone.strip(), email=email.strip(),
        payment_term=payment_term, active=True,
    )
    db.add(v)
    db.commit()
    return JSONResponse({"id": v.id, "name": v.name, "payment_term": v.payment_term or 30})


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
    location_type: str = Form("turkiye"),
    cities: str = Form(""),
    bank_accounts_json: str = Form("[]"),
    notes: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    primary_iban = _primary_iban(bank_accounts_json) or iban.strip()
    v = FinancialVendor(
        name=name.strip(), vendor_type=vendor_type,
        iban=primary_iban, tax_no=tax_no.strip(),
        tax_office=tax_office.strip(), address=address.strip(),
        phone=phone.strip(), email=email.strip(),
        payment_term=payment_term, contact=contact.strip(),
        location_type=location_type, cities=cities.strip(),
        bank_accounts_json=bank_accounts_json if bank_accounts_json != "[]" else None,
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

    cash_books    = db.query(CashBook).all()
    bank_accounts = db.query(BankAccount).all()
    credit_cards  = db.query(CreditCard).all()

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
            "cash_books": cash_books, "bank_accounts": bank_accounts,
            "credit_cards": credit_cards, "payment_methods": PAYMENT_METHODS,
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
    location_type: str = Form("turkiye"),
    cities: str = Form(""),
    bank_accounts_json: str = Form("[]"),
    notes: str = Form(""),
    active: str = Form("1"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    v = db.query(FinancialVendor).get(vendor_id)
    if not v:
        raise HTTPException(status_code=404)
    primary_iban = _primary_iban(bank_accounts_json) or iban.strip()
    v.name = name.strip()
    v.vendor_type = vendor_type
    v.iban = primary_iban
    v.tax_no = tax_no.strip()
    v.tax_office = tax_office.strip()
    v.address = address.strip()
    v.phone = phone.strip()
    v.email = email.strip()
    v.payment_term = payment_term
    v.contact = contact.strip()
    v.location_type = location_type
    v.cities = cities.strip()
    v.bank_accounts_json = bank_accounts_json if bank_accounts_json != "[]" else None
    v.notes = notes.strip()
    v.active = (active == "1")
    db.commit()
    return RedirectResponse(url=f"/vendors/{vendor_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{vendor_id}/delete", name="vendor_delete")
async def vendor_delete(
    vendor_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403)
    v = db.query(FinancialVendor).get(vendor_id)
    if v:
        db.delete(v)
        db.commit()
    return RedirectResponse(url="/vendors", status_code=status.HTTP_302_FOUND)
