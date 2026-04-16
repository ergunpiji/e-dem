"""
E-dem — Finansal Tedarikçi Yönetimi (FinancialVendor)
Erişim: admin, muhasebe_muduru, muhasebe  (liste/düzenle)
Görüntüleme: mudur (GM), muhasebe ekibi
"""
from datetime import date, datetime, timedelta
from collections import defaultdict

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import FinancialVendor, Invoice, User, _uuid, _now
from templates_config import templates

router = APIRouter(prefix="/vendors", tags=["vendors"])

FINANCE_ROLES = {"admin", "muhasebe_muduru", "muhasebe"}
VIEW_ROLES    = {"admin", "muhasebe_muduru", "muhasebe", "mudur"}  # mudur = GM here


def _require_finance(current_user: User):
    if current_user.role not in FINANCE_ROLES:
        raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok.")


def _require_view(current_user: User):
    if current_user.role not in VIEW_ROLES:
        raise HTTPException(status_code=403, detail="Bu sayfayı görüntüleme yetkiniz yok.")


# ---------------------------------------------------------------------------
# GET /vendors/autocomplete  — JSON autocomplete (fatura formunda kullanılır)
# ---------------------------------------------------------------------------

@router.get("/autocomplete", name="vendors_autocomplete")
async def vendors_autocomplete(
    q: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role not in {*FINANCE_ROLES, "mudur"}:
        return JSONResponse([])
    term = f"%{q.strip()}%"
    vendors = (
        db.query(FinancialVendor)
        .filter(FinancialVendor.is_active == True, FinancialVendor.name.ilike(term))
        .order_by(FinancialVendor.name)
        .limit(20)
        .all()
    )
    return JSONResponse([
        {
            "id":           v.id,
            "name":         v.name,
            "payment_term": v.payment_term,
            "email":        v.email,
            "phone":        v.phone,
        }
        for v in vendors
    ])


# ---------------------------------------------------------------------------
# GET /vendors  — Liste
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, name="vendors_list")
async def vendors_list(
    request: Request,
    q: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_view(current_user)

    query = db.query(FinancialVendor).filter(FinancialVendor.is_active == True)
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(FinancialVendor.name.ilike(term))
    vendors = query.order_by(FinancialVendor.name).all()

    # Her tedarikçi için ödenmemiş toplam hesapla
    unpaid_map = {}
    overdue_map = {}
    today_str = date.today().isoformat()
    for v in vendors:
        unpaid = (
            db.query(func.sum(Invoice.total_amount))
            .filter(Invoice.vendor_id == v.id, Invoice.payment_status == "unpaid",
                    Invoice.status == "approved")
            .scalar() or 0.0
        )
        overdue = (
            db.query(func.sum(Invoice.total_amount))
            .filter(Invoice.vendor_id == v.id, Invoice.payment_status == "unpaid",
                    Invoice.status == "approved",
                    Invoice.due_date < today_str, Invoice.due_date != None)
            .scalar() or 0.0
        )
        unpaid_map[v.id]  = round(unpaid,  2)
        overdue_map[v.id] = round(overdue, 2)

    return templates.TemplateResponse("vendors/list.html", {
        "request":      request,
        "current_user": current_user,
        "page_title":   "Finansal Tedarikçiler",
        "vendors":      vendors,
        "q":            q,
        "unpaid_map":   unpaid_map,
        "overdue_map":  overdue_map,
        "can_edit":     current_user.role in FINANCE_ROLES,
    })


# ---------------------------------------------------------------------------
# GET /vendors/new  — Yeni tedarikçi formu
# ---------------------------------------------------------------------------

@router.get("/new", response_class=HTMLResponse, name="vendors_new")
async def vendors_new(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_finance(current_user)
    return templates.TemplateResponse("vendors/form.html", {
        "request":      request,
        "current_user": current_user,
        "page_title":   "Yeni Tedarikçi",
        "vendor":       None,
        "edit_mode":    False,
    })


# ---------------------------------------------------------------------------
# POST /vendors/new
# ---------------------------------------------------------------------------

@router.post("/new", name="vendors_create")
async def vendors_create(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    name:         str = Form(...),
    tax_number:   str = Form(""),
    tax_office:   str = Form(""),
    address:      str = Form(""),
    email:        str = Form(""),
    phone:        str = Form(""),
    payment_term: str = Form("30"),
    notes:        str = Form(""),
):
    _require_finance(current_user)
    vendor = FinancialVendor(
        id           = _uuid(),
        name         = name.strip(),
        tax_number   = tax_number.strip(),
        tax_office   = tax_office.strip(),
        address      = address.strip(),
        email        = email.strip(),
        phone        = phone.strip(),
        payment_term = int(payment_term or 30),
        notes        = notes.strip(),
        is_active    = True,
        created_by   = current_user.id,
        created_at   = _now(),
        updated_at   = _now(),
    )
    db.add(vendor)
    db.commit()
    return RedirectResponse(url=f"/vendors/{vendor.id}", status_code=303)


# ---------------------------------------------------------------------------
# GET /vendors/{id}  — Tedarikçi kartı
# ---------------------------------------------------------------------------

@router.get("/{vendor_id}", response_class=HTMLResponse, name="vendors_card")
async def vendors_card(
    vendor_id: str,
    request: Request,
    period: str = "all",   # all | 30 | 90 | 180 | 365
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_view(current_user)
    vendor = db.query(FinancialVendor).filter(FinancialVendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Tedarikçi bulunamadı.")

    inv_q = db.query(Invoice).filter(Invoice.vendor_id == vendor_id)

    # Dönem filtresi
    if period != "all":
        days = int(period)
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        inv_q = inv_q.filter(Invoice.invoice_date >= cutoff)

    invoices = inv_q.order_by(Invoice.invoice_date.desc()).all()

    # Özet hesaplamalar
    today_str = date.today().isoformat()
    total_amount   = sum(inv.total_amount or 0 for inv in invoices if inv.status == "approved")
    paid_amount    = sum(inv.total_amount or 0 for inv in invoices
                        if inv.status == "approved" and inv.payment_status in ("paid", "partial"))
    unpaid_amount  = sum(inv.total_amount or 0 for inv in invoices
                        if inv.status == "approved" and inv.payment_status == "unpaid")
    overdue_amount = sum(inv.total_amount or 0 for inv in invoices
                        if inv.status == "approved" and inv.payment_status == "unpaid"
                        and inv.due_date and inv.due_date < today_str)

    return templates.TemplateResponse("vendors/card.html", {
        "request":        request,
        "current_user":   current_user,
        "page_title":     vendor.name,
        "vendor":         vendor,
        "invoices":       invoices,
        "period":         period,
        "total_amount":   round(total_amount,   2),
        "paid_amount":    round(paid_amount,    2),
        "unpaid_amount":  round(unpaid_amount,  2),
        "overdue_amount": round(overdue_amount, 2),
        "today_str":      today_str,
        "can_edit":       current_user.role in FINANCE_ROLES,
    })


# ---------------------------------------------------------------------------
# GET /vendors/{id}/edit
# ---------------------------------------------------------------------------

@router.get("/{vendor_id}/edit", response_class=HTMLResponse, name="vendors_edit")
async def vendors_edit(
    vendor_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(current_user)
    vendor = db.query(FinancialVendor).filter(FinancialVendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Tedarikçi bulunamadı.")
    return templates.TemplateResponse("vendors/form.html", {
        "request":      request,
        "current_user": current_user,
        "page_title":   f"Düzenle — {vendor.name}",
        "vendor":       vendor,
        "edit_mode":    True,
    })


# ---------------------------------------------------------------------------
# POST /vendors/{id}/edit
# ---------------------------------------------------------------------------

@router.post("/{vendor_id}/edit", name="vendors_update")
async def vendors_update(
    vendor_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    name:         str = Form(...),
    tax_number:   str = Form(""),
    tax_office:   str = Form(""),
    address:      str = Form(""),
    email:        str = Form(""),
    phone:        str = Form(""),
    payment_term: str = Form("30"),
    notes:        str = Form(""),
):
    _require_finance(current_user)
    vendor = db.query(FinancialVendor).filter(FinancialVendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Tedarikçi bulunamadı.")
    vendor.name         = name.strip()
    vendor.tax_number   = tax_number.strip()
    vendor.tax_office   = tax_office.strip()
    vendor.address      = address.strip()
    vendor.email        = email.strip()
    vendor.phone        = phone.strip()
    vendor.payment_term = int(payment_term or 30)
    vendor.notes        = notes.strip()
    vendor.updated_at   = _now()
    db.commit()
    return RedirectResponse(url=f"/vendors/{vendor.id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /vendors/{id}/delete
# ---------------------------------------------------------------------------

@router.post("/{vendor_id}/delete", name="vendors_delete")
async def vendors_delete(
    vendor_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(current_user)
    vendor = db.query(FinancialVendor).filter(FinancialVendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Tedarikçi bulunamadı.")
    # Soft delete
    vendor.is_active  = False
    vendor.updated_at = _now()
    db.commit()
    return RedirectResponse(url="/vendors", status_code=303)


# ---------------------------------------------------------------------------
# POST /vendors/{id}/mark-paid  — Fatura ödemesini işaretle
# ---------------------------------------------------------------------------

@router.post("/{vendor_id}/invoices/{invoice_id}/mark-paid", name="vendors_mark_paid")
async def vendors_mark_paid(
    vendor_id:  str,
    invoice_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    payment_status: str = Form("paid"),   # paid | partial
    paid_at:        str = Form(""),
):
    _require_finance(current_user)
    inv = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.vendor_id == vendor_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Fatura bulunamadı.")
    inv.payment_status = payment_status
    inv.paid_at        = paid_at or date.today().isoformat()
    inv.updated_at     = _now()
    db.commit()
    return RedirectResponse(url=f"/vendors/{vendor_id}", status_code=303)


# ---------------------------------------------------------------------------
# GET /cash-flow  — Nakit Akışı tahmini
# ---------------------------------------------------------------------------

@router.get("/cash-flow/view", response_class=HTMLResponse, name="cash_flow")
async def cash_flow(
    request: Request,
    weeks: int = 8,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_view(current_user)

    today = date.today()
    end_date = today + timedelta(weeks=weeks)
    end_str  = end_date.isoformat()
    today_str = today.isoformat()

    # Vadesi gelen ödenmemiş faturalar (gider) — sadece approved
    outgoing = (
        db.query(Invoice)
        .filter(
            Invoice.payment_status == "unpaid",
            Invoice.status == "approved",
            Invoice.due_date != None,
            Invoice.due_date >= today_str,
            Invoice.due_date <= end_str,
        )
        .order_by(Invoice.due_date)
        .all()
    )

    # Vadesi gelen ödenmemiş müşteri faturaları (gelir, kesilen tip) — sadece approved
    incoming = (
        db.query(Invoice)
        .filter(
            Invoice.payment_status == "unpaid",
            Invoice.status == "approved",
            Invoice.invoice_type == "kesilen",
            Invoice.due_date != None,
            Invoice.due_date >= today_str,
            Invoice.due_date <= end_str,
        )
        .order_by(Invoice.due_date)
        .all()
    )

    # Haftalık gruplama
    weeks_data = []
    for w in range(weeks):
        week_start = today + timedelta(weeks=w)
        week_end   = week_start + timedelta(days=6)
        ws_str = week_start.isoformat()
        we_str = week_end.isoformat()

        w_out = [i for i in outgoing  if ws_str <= (i.due_date or "") <= we_str]
        w_in  = [i for i in incoming  if ws_str <= (i.due_date or "") <= we_str]

        weeks_data.append({
            "label":       f"Hafta {w+1}",
            "start":       week_start.strftime("%d.%m"),
            "end":         week_end.strftime("%d.%m"),
            "outgoing":    w_out,
            "incoming":    w_in,
            "total_out":   round(sum(i.total_amount or 0 for i in w_out), 2),
            "total_in":    round(sum(i.total_amount or 0 for i in w_in),  2),
        })

    # Vadesi geçmiş (overdue)
    overdue = (
        db.query(Invoice)
        .filter(
            Invoice.payment_status == "unpaid",
            Invoice.status == "approved",
            Invoice.due_date != None,
            Invoice.due_date < today_str,
        )
        .order_by(Invoice.due_date)
        .all()
    )

    return templates.TemplateResponse("vendors/cash_flow.html", {
        "request":      request,
        "current_user": current_user,
        "page_title":   "Nakit Akışı",
        "weeks_data":   weeks_data,
        "overdue":      overdue,
        "weeks":        weeks,
        "today_str":    today_str,
        "total_overdue": round(sum(i.total_amount or 0 for i in overdue), 2),
    })
