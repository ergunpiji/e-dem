"""
Fatura yönetimi
"""

from datetime import date, datetime
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin
from database import get_db
from models import (
    Invoice, Reference, FinancialVendor, CashBook, BankAccount,
    CreditCard, CreditCardTxn, Cheque, CashEntry, BankMovement,
    User, INVOICE_TYPES, PAYMENT_METHODS, VAT_RATES
)
from templates_config import templates

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.get("", response_class=HTMLResponse, name="invoices_list")
async def invoices_list(
    request: Request,
    invoice_type: str = "",
    status_filter: str = "",
    q: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Invoice)
    if invoice_type:
        query = query.filter(Invoice.invoice_type == invoice_type)
    if status_filter:
        query = query.filter(Invoice.status == status_filter)
    if q:
        query = query.filter(Invoice.invoice_no.ilike(f"%{q}%"))
    invoices = query.order_by(Invoice.invoice_date.desc()).all()
    return templates.TemplateResponse(
        "invoices/list.html",
        {
            "request": request, "current_user": current_user,
            "invoices": invoices, "invoice_types": INVOICE_TYPES,
            "invoice_type": invoice_type, "status_filter": status_filter,
            "q": q, "page_title": "Faturalar",
        },
    )


@router.get("/new", response_class=HTMLResponse, name="invoice_new_get")
async def invoice_new_get(
    request: Request,
    ref_id: int = None,
    vendor_id: int = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    import json
    refs = db.query(Reference).filter(Reference.status == "aktif").order_by(Reference.ref_no).all()
    vendors = db.query(FinancialVendor).filter(FinancialVendor.active == True).order_by(FinancialVendor.name).all()  # noqa: E712
    vendors_json = json.dumps([
        {"id": v.id, "name": v.name, "payment_term": v.payment_term or 30}
        for v in vendors
    ])
    refs_json = json.dumps([
        {"id": r.id, "text": r.ref_no + " — " + r.title}
        for r in refs
    ])
    return templates.TemplateResponse(
        "invoices/form.html",
        {
            "request": request, "current_user": current_user,
            "invoice": None, "refs": refs, "vendors": vendors,
            "vendors_json": vendors_json, "refs_json": refs_json,
            "invoice_types": INVOICE_TYPES, "vat_rates": VAT_RATES,
            "preselected_ref_id": ref_id,
            "preselected_vendor_id": vendor_id,
            "page_title": "Fatura Girişi",
        },
    )


@router.post("/new", name="invoice_new_post")
async def invoice_new_post(
    ref_id: int = Form(None),
    vendor_id: int = Form(None),
    invoice_type: str = Form(...),
    invoice_no: str = Form(""),
    invoice_date: str = Form(...),
    due_date: str = Form(""),
    currency: str = Form("TRY"),
    notes: str = Form(""),
    items_json: str = Form("[]"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    import json as _json
    net_total, vat_total = _parse_items(items_json)
    amount = net_total
    vat_rate = (vat_total / net_total) if net_total else 0.0
    inv = Invoice(
        ref_id=ref_id,
        vendor_id=vendor_id,
        invoice_type=invoice_type,
        invoice_no=invoice_no.strip(),
        invoice_date=date.fromisoformat(invoice_date),
        due_date=date.fromisoformat(due_date) if due_date else None,
        amount=amount,
        vat_rate=round(vat_rate, 4),
        currency=currency,
        status="approved",
        notes=notes.strip(),
        items_json=items_json if items_json != "[]" else None,
        created_by=current_user.id,
    )
    db.add(inv)
    db.commit()
    return RedirectResponse(url=f"/invoices/{inv.id}", status_code=status.HTTP_302_FOUND)


@router.get("/{invoice_id}", response_class=HTMLResponse, name="invoice_detail")
async def invoice_detail(
    invoice_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    inv = db.query(Invoice).get(invoice_id)
    if not inv:
        raise HTTPException(status_code=404)
    cash_books = db.query(CashBook).all()
    bank_accounts = db.query(BankAccount).all()
    credit_cards = db.query(CreditCard).all()
    return templates.TemplateResponse(
        "invoices/detail.html",
        {
            "request": request, "current_user": current_user,
            "invoice": inv, "cash_books": cash_books,
            "bank_accounts": bank_accounts, "credit_cards": credit_cards,
            "payment_methods": PAYMENT_METHODS,
            "page_title": f"Fatura — {inv.invoice_no or inv.id}",
        },
    )


def _parse_items(items_json: str):
    """Returns (net_total, vat_total) from items JSON string."""
    import json as _json
    try:
        items = _json.loads(items_json or "[]")
    except Exception:
        items = []
    net_total = sum(float(i.get("net", 0)) for i in items)
    vat_total = sum(float(i.get("vat_amt", 0)) for i in items)
    return net_total, vat_total


@router.get("/{invoice_id}/edit", response_class=HTMLResponse, name="invoice_edit_get")
async def invoice_edit_get(
    invoice_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    import json
    inv = db.query(Invoice).get(invoice_id)
    if not inv:
        raise HTTPException(status_code=404)
    refs = db.query(Reference).filter(Reference.status == "aktif").order_by(Reference.ref_no).all()
    vendors = db.query(FinancialVendor).filter(FinancialVendor.active == True).order_by(FinancialVendor.name).all()  # noqa: E712
    vendors_json = json.dumps([
        {"id": v.id, "name": v.name, "payment_term": v.payment_term or 30}
        for v in vendors
    ])
    refs_json = json.dumps([
        {"id": r.id, "text": r.ref_no + " — " + r.title}
        for r in refs
    ])
    return templates.TemplateResponse(
        "invoices/form.html",
        {
            "request": request, "current_user": current_user,
            "invoice": inv, "refs": refs, "vendors": vendors,
            "vendors_json": vendors_json, "refs_json": refs_json,
            "invoice_types": INVOICE_TYPES, "vat_rates": VAT_RATES,
            "preselected_ref_id": None,
            "preselected_vendor_id": None,
            "page_title": f"Düzenle — Fatura {inv.invoice_no or inv.id}",
        },
    )


@router.post("/{invoice_id}/edit", name="invoice_edit_post")
async def invoice_edit_post(
    invoice_id: int,
    ref_id: int = Form(None),
    vendor_id: int = Form(None),
    invoice_type: str = Form(...),
    invoice_no: str = Form(""),
    invoice_date: str = Form(...),
    due_date: str = Form(""),
    currency: str = Form("TRY"),
    notes: str = Form(""),
    items_json: str = Form("[]"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    inv = db.query(Invoice).get(invoice_id)
    if not inv:
        raise HTTPException(status_code=404)
    net_total, vat_total = _parse_items(items_json)
    inv.ref_id = ref_id
    inv.vendor_id = vendor_id
    inv.invoice_type = invoice_type
    inv.invoice_no = invoice_no.strip()
    inv.invoice_date = date.fromisoformat(invoice_date)
    inv.due_date = date.fromisoformat(due_date) if due_date else None
    inv.amount = net_total
    inv.vat_rate = round((vat_total / net_total) if net_total else 0.0, 4)
    inv.currency = currency
    inv.notes = notes.strip()
    inv.items_json = items_json if items_json != "[]" else None
    db.commit()
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{invoice_id}/pay", name="invoice_pay")
async def invoice_pay(
    invoice_id: int,
    payment_method: str = Form(...),
    cash_book_id: int = Form(None),
    bank_account_id: int = Form(None),
    credit_card_id: int = Form(None),
    cheque_no: str = Form(""),
    cheque_bank: str = Form(""),
    cheque_date: str = Form(""),
    cheque_due_date: str = Form(""),
    cheque_amount: float = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    inv = db.query(Invoice).get(invoice_id)
    if not inv or inv.status == "paid":
        raise HTTPException(status_code=400, detail="Fatura bulunamadı veya zaten ödendi.")

    inv.payment_method = payment_method
    inv.paid_at = datetime.utcnow()
    inv.status = "paid"
    total = inv.amount * (1 + inv.vat_rate)
    desc = f"Fatura {inv.invoice_no or inv.id}" + (f" — {inv.vendor.name}" if inv.vendor else "")

    if payment_method == "nakit" and cash_book_id:
        inv.cash_book_id = cash_book_id
        db.add(CashEntry(
            book_id=cash_book_id,
            entry_date=date.today(),
            entry_type="cikis",
            amount=total,
            description=desc,
            invoice_id=invoice_id,
            ref_id=inv.ref_id,
        ))

    elif payment_method == "banka" and bank_account_id:
        inv.bank_account_id = bank_account_id
        db.add(BankMovement(
            account_id=bank_account_id,
            movement_date=date.today(),
            movement_type="cikis",
            amount=total,
            description=desc,
            invoice_id=invoice_id,
            ref_id=inv.ref_id,
        ))

    elif payment_method == "kredi_karti" and credit_card_id:
        inv.credit_card_id = credit_card_id
        db.add(CreditCardTxn(
            card_id=credit_card_id,
            txn_date=date.today(),
            amount=total,
            description=desc,
            invoice_id=invoice_id,
            ref_id=inv.ref_id,
        ))

    elif payment_method == "cek":
        cheque = Cheque(
            vendor_id=inv.vendor_id,
            cheque_type="verilen",
            cheque_no=cheque_no.strip(),
            bank=cheque_bank.strip(),
            amount=cheque_amount or total,
            currency=inv.currency,
            cheque_date=date.fromisoformat(cheque_date) if cheque_date else date.today(),
            due_date=date.fromisoformat(cheque_due_date) if cheque_due_date else date.today(),
            status="beklemede",
        )
        db.add(cheque)
        db.flush()
        inv.cheque_id = cheque.id

    db.commit()
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{invoice_id}/delete", name="invoice_delete")
async def invoice_delete(
    invoice_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    inv = db.query(Invoice).get(invoice_id)
    if inv:
        db.delete(inv)
        db.commit()
    return RedirectResponse(url="/invoices", status_code=status.HTTP_302_FOUND)
