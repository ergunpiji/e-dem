"""
Fatura yönetimi
"""

from datetime import date, datetime
from typing import List
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin
from database import get_db
from models import (
    Invoice, InvoicePayment, Reference, FinancialVendor, CashBook, BankAccount,
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
    request: Request,
    ref_id: int = Form(None),
    vendor_id: int = Form(None),
    invoice_type: str = Form(...),
    invoice_no: str = Form(""),
    invoice_date: str = Form(...),
    due_date: str = Form(""),
    currency: str = Form("TRY"),
    notes: str = Form(""),
    items_json: str = Form("[]"),
    send_to_gib: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
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
    db.refresh(inv)

    # "Kaydet ve GİB'e Gönder" basıldıysa ve modül aktifse otomatik gönder
    redirect_query = ""
    if (send_to_gib == "1" and invoice_type in ("kesilen", "komisyon")
            and current_user.is_admin):
        # Modül aktif mi?
        from models import SystemSetting
        s = db.query(SystemSetting).filter(
            SystemSetting.key == "module_einvoice_enabled"
        ).first()
        if s and s.value == "1":
            # Müşteri bilgisi tam mı?
            customer = inv.reference.customer if (inv.reference and inv.reference.customer) else None
            missing = []
            if not customer:
                missing.append("müşteri")
            else:
                if not customer.tax_no:
                    missing.append("vergi no")
                if not customer.tax_office:
                    missing.append("vergi dairesi")

            if missing:
                # Eksik bilgi var — kayıt edildi, gönderim atlandı, uyarı
                redirect_query = f"?ef_warning=" + ",".join(missing)
            else:
                # Gönder
                try:
                    from app import einvoice_module as mod
                    if mod is not None:
                        from datetime import datetime as _dt
                        # Mükellef cache kontrolü
                        if customer.is_efatura_user is None:
                            info = mod.provider.check_efatura_user(customer.tax_no)
                            customer.is_efatura_user = info.is_user
                            customer.efatura_alias = info.alias
                            customer.efatura_checked_at = _dt.utcnow()
                            db.flush()
                        is_efatura = bool(customer.is_efatura_user)

                        # Kalemlerden InvoicePayload üret
                        import json as _json
                        lines = []
                        try:
                            raw = _json.loads(inv.items_json or "[]")
                            for li in raw:
                                lines.append({
                                    "description": li.get("description") or "Hizmet",
                                    "quantity": float(li.get("qty") or 1),
                                    "unit": li.get("unit") or "ADET",
                                    "unit_price": float(li.get("price") or 0),
                                    "vat_rate": float(li.get("vat_rate") or inv.vat_rate or 0.20),
                                    "discount": float(li.get("discount") or 0),
                                })
                        except Exception:  # noqa: BLE001
                            pass
                        if not lines:
                            lines = [{
                                "description": inv.invoice_no or "Hizmet bedeli",
                                "quantity": 1, "unit": "ADET",
                                "unit_price": float(inv.amount or 0),
                                "vat_rate": float(inv.vat_rate or 0.20),
                                "discount": 0,
                            }]
                        payload_dict = {
                            "invoice_no": inv.invoice_no or f"INV-{inv.id}",
                            "invoice_date": inv.invoice_date.isoformat(),
                            "currency": inv.currency or "TRY",
                            "is_efatura": is_efatura,
                            "customer": {
                                "name": customer.name, "tax_no": customer.tax_no,
                                "tax_office": customer.tax_office,
                                "address": customer.address or "",
                                "email": customer.email or "",
                                "phone": customer.phone or "",
                                "alias": customer.efatura_alias,
                            },
                            "lines": lines,
                            "notes": inv.notes or "",
                        }
                        from prizma_einvoice import build_invoice_payload_from_dict, submit_payload
                        sub = submit_payload(
                            db,
                            invoice_id=inv.id,
                            payload=build_invoice_payload_from_dict(payload_dict),
                            submission_model=mod.Submission,
                            provider=mod.provider,
                            user_id=current_user.id,
                        )
                        inv.einvoice_status = sub.status
                        inv.einvoice_uuid = sub.uuid
                        inv.einvoice_pdf_url = sub.pdf_url
                        inv.einvoice_sent_at = sub.submitted_at
                        db.commit()
                        redirect_query = "?ef_sent=1"
                except Exception as exc:  # noqa: BLE001
                    print(f"[invoice-create-send] hata: {exc}", flush=True)
                    redirect_query = "?ef_error=1"

    return RedirectResponse(
        url=f"/invoices/{inv.id}{redirect_query}",
        status_code=status.HTTP_302_FOUND,
    )


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
    pay_amount: float = Form(None),
    pay_date: str = Form(""),
    cash_book_id: int = Form(None),
    bank_account_id: int = Form(None),
    credit_card_id: int = Form(None),
    cheque_no: str = Form(""),
    cheque_bank: str = Form(""),
    cheque_date: str = Form(""),
    cheque_due_date: str = Form(""),
    pay_notes: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from payment_helpers import apply_invoice_payment
    inv = db.query(Invoice).get(invoice_id)
    if not inv or inv.status == "paid":
        raise HTTPException(status_code=400, detail="Fatura bulunamadı veya zaten ödendi.")

    amount = pay_amount if pay_amount and pay_amount > 0 else inv.total_with_vat
    pdate = date.fromisoformat(pay_date) if pay_date else date.today()

    apply_invoice_payment(
        db, inv,
        payment_method=payment_method, amount=amount, pdate=pdate,
        current_user=current_user,
        cash_book_id=cash_book_id, bank_account_id=bank_account_id,
        credit_card_id=credit_card_id,
        cheque_no=cheque_no, cheque_bank=cheque_bank,
        cheque_date_str=cheque_date, cheque_due_date_str=cheque_due_date,
        pay_notes=pay_notes,
    )
    db.commit()
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{invoice_id}/payment/{payment_id}/delete", name="invoice_payment_delete")
async def invoice_payment_delete(
    invoice_id: int,
    payment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    inv = db.query(Invoice).get(invoice_id)
    pmt = db.query(InvoicePayment).filter(
        InvoicePayment.id == payment_id,
        InvoicePayment.invoice_id == invoice_id,
    ).first()
    if not pmt:
        raise HTTPException(status_code=404)

    # İlgili kasa/banka hareketlerini de sil
    for ce in list(inv.cash_entries):
        if ce.invoice_id == invoice_id and ce.amount == pmt.amount:
            db.delete(ce)
            break
    for bm in list(inv.bank_movements):
        if bm.invoice_id == invoice_id and bm.amount == pmt.amount:
            db.delete(bm)
            break

    db.delete(pmt)
    db.flush()

    # Status güncelle
    total = inv.total_with_vat
    remaining_payments = db.query(InvoicePayment).filter(
        InvoicePayment.invoice_id == invoice_id
    ).all()
    paid = sum(p.amount for p in remaining_payments)
    if paid <= 0.01:
        inv.status = "approved"
        inv.paid_at = None
        inv.payment_method = None
    elif paid >= total - 0.01:
        inv.status = "paid"
    else:
        inv.status = "partial"

    db.commit()
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=status.HTTP_302_FOUND)


@router.post("/pay-bulk", name="invoice_pay_bulk")
async def invoice_pay_bulk(
    invoice_ids: List[int] = Form(...),
    payment_method: str = Form(...),
    cash_book_id: int = Form(None),
    bank_account_id: int = Form(None),
    credit_card_id: int = Form(None),
    redirect_url: str = Form("/invoices"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Toplu ödeme — her fatura için InvoicePayment + yan kayıt yaratır (audit)."""
    from payment_helpers import apply_invoice_payment
    today = date.today()
    for inv_id in invoice_ids:
        inv = db.query(Invoice).get(inv_id)
        if not inv or inv.status == "paid":
            continue
        try:
            apply_invoice_payment(
                db, inv,
                payment_method=payment_method, amount=inv.remaining, pdate=today,
                current_user=current_user,
                cash_book_id=cash_book_id, bank_account_id=bank_account_id,
                credit_card_id=credit_card_id,
            )
        except HTTPException:
            # Bir fatura için hedef hesap eksikse atla; toplu işlemi yarıda kesme
            continue
    db.commit()
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)


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
