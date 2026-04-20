"""
E-dem — Finansal Tedarikçi Yönetimi (FinancialVendor)
Erişim: admin, muhasebe_muduru, muhasebe  (liste/düzenle)
Görüntüleme: mudur (GM), muhasebe ekibi
"""
import os
from datetime import date, datetime, timedelta
from collections import defaultdict

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import Session, sessionmaker

from auth import get_current_user
from database import get_db
from models import FinancialVendor, Invoice, InvoiceLog, User, _uuid, _now
from templates_config import templates

router = APIRouter(prefix="/vendors", tags=["vendors"])

# ── Finans agent DB (kredi kartı ekstrelerini okumak için) ────────────────────
_finans_raw_url = os.environ.get(
    "FINANS_AGENT_DB",
    os.environ.get("DATABASE_URL", "sqlite:///./agents/finans/finans_agent.db"),
)
if _finans_raw_url.startswith("postgres://"):
    _finans_raw_url = _finans_raw_url.replace("postgres://", "postgresql://", 1)
_finans_is_sqlite = _finans_raw_url.startswith("sqlite")
_finans_kwargs: dict = {"echo": False}
if _finans_is_sqlite:
    _finans_kwargs["connect_args"] = {"check_same_thread": False}
else:
    _finans_kwargs["pool_pre_ping"] = True
    _finans_kwargs["pool_recycle"]  = 300
    _finans_kwargs["pool_size"]     = 3
    _finans_kwargs["max_overflow"]  = 5
_finans_engine = create_engine(_finans_raw_url, **_finans_kwargs)
_FinansSession = sessionmaker(autocommit=False, autoflush=False, bind=_finans_engine)


def _get_cc_statements(today_str: str, end_str: str) -> list[dict]:
    """Ödenmemiş/kısmi kredi kartı ekstrelerini finans DB'den çek."""
    try:
        with _FinansSession() as sess:
            rows = sess.execute(
                text("""
                    SELECT s.id, s.due_date, s.total_amount, s.paid_amount, s.status,
                           c.name AS card_name, c.bank, c.last_four
                    FROM credit_card_statements s
                    JOIN credit_cards c ON c.id = s.card_id
                    WHERE s.status != 'odendi'
                      AND s.due_date >= :today
                      AND s.due_date <= :end
                    ORDER BY s.due_date
                """),
                {"today": today_str, "end": end_str},
            ).fetchall()
            return [dict(r._mapping) for r in rows]
    except Exception:
        return []

FINANCE_ROLES = {"admin", "muhasebe_muduru", "muhasebe"}
VIEW_ROLES    = {"admin", "muhasebe_muduru", "muhasebe", "mudur"}  # mudur = GM here


def _require_finance(current_user: User):
    if current_user.role not in FINANCE_ROLES and not current_user.is_gm:
        raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok.")


def _require_view(current_user: User):
    if current_user.role not in VIEW_ROLES and not current_user.is_gm:
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
    if current_user.role not in {*FINANCE_ROLES, "mudur"} and not current_user.is_gm:
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
    vendor_id:      str,
    invoice_id:     str,
    current_user:   User = Depends(get_current_user),
    db:             Session = Depends(get_db),
    payment_status: str   = Form("paid"),   # paid | partial
    paid_at:        str   = Form(""),
    paid_amount:    str   = Form(""),       # kısmi ödeme tutarı
    payment_method: str   = Form("banka"),  # banka | kredi_karti | cek
    cc_due_date:    str   = Form(""),       # kredi kartı son ödeme tarihi
):
    _require_finance(current_user)
    inv = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.vendor_id == vendor_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Fatura bulunamadı.")

    inv.paid_at    = paid_at or date.today().isoformat()
    inv.updated_at = _now()

    if payment_status == "partial" and paid_amount:
        try:
            amt = round(float(paid_amount), 2)
            inv.paid_amount = round((inv.paid_amount or 0.0) + amt, 2)

            # Kredi kartı kısmını ayrı izle (nakit akışında cc_due_date'e ayrı giriş)
            if payment_method == "kredi_karti":
                inv.cc_pending_amount = round((inv.cc_pending_amount or 0.0) + amt, 2)
                if cc_due_date:
                    inv.cc_due_date = cc_due_date   # en son CC vadesini güncelle

            # Tam ödendiyse otomatik "paid" yap
            if inv.paid_amount >= (inv.total_amount or 0.0):
                inv.payment_status = "paid"
                inv.payment_method = payment_method
            else:
                inv.payment_status = "partial"
                # Birden fazla yöntem olabilir; son yöntemi kaydet
                inv.payment_method = payment_method
        except (ValueError, TypeError):
            inv.payment_status = "partial"
    else:
        # Tam ödeme
        inv.payment_status    = "paid"
        inv.payment_method    = payment_method
        inv.paid_amount       = inv.total_amount or 0.0
        inv.cc_pending_amount = 0.0   # tam ödeme = kart borcu da kapandı
        if payment_method == "kredi_karti" and cc_due_date:
            inv.cc_due_date   = cc_due_date
        else:
            inv.cc_due_date   = None

    # Ödeme logu
    _log_amt = round(float(paid_amount), 2) if (payment_status == "partial" and paid_amount) else (inv.total_amount or 0.0)
    _log_cc  = cc_due_date if payment_method == "kredi_karti" and cc_due_date else None
    db.add(InvoiceLog(
        id=_uuid(), invoice_id=invoice_id, action="payment",
        actor_id=current_user.id, amount=_log_amt,
        payment_method=payment_method, cc_due_date=_log_cc,
        note=inv.paid_at or "",
    ))
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

    # ── Nakit akışı kalemleri oluştur ─────────────────────────────────────────
    # Her Invoice birden fazla kalem üretebilir (ör. kısmi CC + kalan bakiye).
    # Kalem formatı: {invoice, amount, eff_date, is_cc, cc_label}
    def _build_outgoing_items(invoices: list) -> list:
        items = []
        for inv in invoices:
            total  = inv.total_amount  or 0.0
            paid   = inv.paid_amount   or 0.0
            cc_pnd = inv.cc_pending_amount or 0.0
            remaining_cash = round(max(0.0, total - paid), 2)   # vadede ödenecek
            due = inv.due_date

            # 1) Kalan bakiye (banka/çek ile ödenecek) → orijinal vade tarihinde
            if remaining_cash > 0 and due:
                items.append({
                    "invoice":  inv,
                    "amount":   remaining_cash,
                    "eff_date": due,
                    "is_cc":    False,
                    "cc_label": None,
                })

            # 2) Kredi kartı ile taahhüt edilen tutar → cc_due_date'te ayrı giriş
            if cc_pnd > 0 and inv.cc_due_date:
                items.append({
                    "invoice":  inv,
                    "amount":   round(cc_pnd, 2),
                    "eff_date": inv.cc_due_date,
                    "is_cc":    True,
                    "cc_label": inv.cc_due_date,
                })

        return items

    # Ödenmemiş/kısmi gider faturaları — approved (kesilen/iade_kesilen hariç: onlar gelir)
    _expense_types_excl = ["kesilen", "iade_kesilen"]
    invoices_raw = (
        db.query(Invoice)
        .filter(
            Invoice.payment_status.in_(["unpaid", "partial"]),
            Invoice.status == "approved",
            Invoice.due_date != None,
            Invoice.invoice_type.notin_(_expense_types_excl),
        )
        .order_by(Invoice.due_date)
        .all()
    )
    # Tamamen ödendi ama CC borcu henüz bankadan çıkmadı
    cc_fully_paid = (
        db.query(Invoice)
        .filter(
            Invoice.payment_status == "paid",
            Invoice.cc_pending_amount > 0,
            Invoice.cc_due_date != None,
            Invoice.cc_due_date >= today_str,
            Invoice.cc_due_date <= end_str,
            Invoice.invoice_type.notin_(_expense_types_excl),
        )
        .all()
    )

    all_outgoing_items = _build_outgoing_items(invoices_raw) + _build_outgoing_items(cc_fully_paid)
    # Dönem aralığına filtrele
    all_outgoing_items = [
        it for it in all_outgoing_items
        if today_str <= (it["eff_date"] or "") <= end_str
    ]

    # Ödenmemiş müşteri alacakları (gelir) — approved, kesilen tip
    incoming = (
        db.query(Invoice)
        .filter(
            Invoice.payment_status.in_(["unpaid", "partial"]),
            Invoice.status == "approved",
            Invoice.invoice_type == "kesilen",
            Invoice.due_date != None,
            Invoice.due_date >= today_str,
            Invoice.due_date <= end_str,
        )
        .order_by(Invoice.due_date)
        .all()
    )

    # Kredi kartı ekstresi ödemeleri (finans agent DB'den)
    cc_statements = _get_cc_statements(today_str, end_str)
    # Kalem formatına dönüştür (is_cc_stmt=True ile ayırt edelim)
    cc_stmt_items = [
        {
            "invoice":    None,
            "amount":     round(max(0.0, (s["total_amount"] or 0) - (s["paid_amount"] or 0)), 2),
            "eff_date":   str(s["due_date"]),
            "is_cc":      True,
            "is_cc_stmt": True,
            "cc_label":   str(s["due_date"]),
            "card_name":  s["card_name"],
            "card_bank":  s["bank"] or "",
            "card_last4": s["last_four"] or "",
        }
        for s in cc_statements
        if round(max(0.0, (s["total_amount"] or 0) - (s["paid_amount"] or 0)), 2) > 0
    ]
    all_outgoing_items = all_outgoing_items + cc_stmt_items

    # Haftalık gruplama
    weeks_data = []
    for w in range(weeks):
        week_start = today + timedelta(weeks=w)
        week_end   = week_start + timedelta(days=6)
        ws_str = week_start.isoformat()
        we_str = week_end.isoformat()

        w_items = [it for it in all_outgoing_items if ws_str <= (it["eff_date"] or "") <= we_str]
        w_in    = [i  for i  in incoming           if ws_str <= (i.due_date or "")    <= we_str]

        weeks_data.append({
            "label":       f"Hafta {w+1}",
            "start":       week_start.strftime("%d.%m"),
            "end":         week_end.strftime("%d.%m"),
            "outgoing":    w_items,
            "incoming":    w_in,
            "total_out":   round(sum(it["amount"] for it in w_items), 2),
            "total_in":    round(sum(max(0.0, (i.total_amount or 0) - (i.paid_amount or 0)) for i in w_in), 2),
        })

    # Vadesi geçmiş (overdue)
    overdue = (
        db.query(Invoice)
        .filter(
            Invoice.payment_status.in_(["unpaid", "partial"]),
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
        "total_overdue": round(sum(max(0.0, (i.total_amount or 0) - (i.paid_amount or 0)) for i in overdue), 2),
    })
