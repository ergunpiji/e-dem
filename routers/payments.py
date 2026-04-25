"""
Haftalık Ödeme Listesi — Genel Müdür için
GET /payments/weekly                   — sayfa
POST /payments/weekly/decide            — onayla / reddet / ertele / yöntem değiştir
POST /payments/settings/weekday         — admin: ödeme günü ayarla
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from auth import require_admin, require_gm
from database import get_db
from models import (
    User, Invoice, Cheque, CreditCardStatement, CreditCard, CreditCardTxn,
    Employee, SalaryPayment, PayrollDecision, SystemSetting,
    BankAccount, BankMovement, CashEntry,
    PAYMENT_METHODS,
)
from templates_config import templates


router = APIRouter(prefix="/payments", tags=["payments"])

WEEKDAYS_TR = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
PAYMENT_METHOD_LABELS = dict(PAYMENT_METHODS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_payment_weekday(db: Session) -> int:
    s = db.query(SystemSetting).filter(SystemSetting.key == "payment_weekday").first()
    if not s:
        return 2
    try:
        v = int(s.value)
        return v if 0 <= v <= 6 else 2
    except (TypeError, ValueError):
        return 2


def _set_payment_weekday(db: Session, weekday: int) -> None:
    s = db.query(SystemSetting).filter(SystemSetting.key == "payment_weekday").first()
    if s:
        s.value = str(weekday)
    else:
        db.add(SystemSetting(key="payment_weekday", value=str(weekday)))


def _next_payment_date(weekday: int, today: Optional[date] = None) -> date:
    if today is None:
        today = date.today()
    days_ahead = (weekday - today.weekday()) % 7
    return today + timedelta(days=days_ahead)


def _show_in_list(item, ref_date: date) -> bool:
    """Listede gösterilecek mi? Onaylananlar görünür kalır (yeşil ışık,
    fiili ödeme yapılınca status değişip filtreden düşer). Reddedilenler
    listeden kaldırılır. Ertelenenler ancak vade geldiğinde tekrar çıkar."""
    d = item.gm_decision
    if d is None:
        return True
    if d == "approved":
        return True
    if d == "rejected":
        return False
    if d == "postponed":
        return bool(item.gm_postpone_until and item.gm_postpone_until <= ref_date)
    return True


def _is_actionable(item) -> bool:
    """Henüz karar verilmemiş veya ertelenmiş — checkbox/onay butonu görünür."""
    return item.gm_decision in (None, "postponed")


def _cash_total(db) -> float:
    ins = db.query(func.sum(CashEntry.amount)).filter(CashEntry.entry_type == "giris").scalar() or 0
    outs = db.query(func.sum(CashEntry.amount)).filter(CashEntry.entry_type == "cikis").scalar() or 0
    return ins - outs


def _bank_total(db) -> float:
    accounts = db.query(BankAccount).all()
    total = 0.0
    for a in accounts:
        opening = a.opening_balance or 0
        ins = db.query(func.sum(BankMovement.amount)).filter(
            BankMovement.account_id == a.id, BankMovement.movement_type == "giris"
        ).scalar() or 0
        outs = db.query(func.sum(BankMovement.amount)).filter(
            BankMovement.account_id == a.id, BankMovement.movement_type == "cikis"
        ).scalar() or 0
        total += opening + ins - outs
    return total


def _cc_outstanding(db, card_id) -> float:
    unpaid = db.query(func.sum(CreditCardStatement.total_amount)).filter(
        CreditCardStatement.card_id == card_id,
        CreditCardStatement.status == "unpaid",
    ).scalar() or 0
    unassigned = db.query(func.sum(CreditCardTxn.amount)).filter(
        CreditCardTxn.card_id == card_id,
        CreditCardTxn.statement_id == None,  # noqa: E711
        CreditCardTxn.is_refund == False,  # noqa: E712
    ).scalar() or 0
    return unpaid + unassigned


def _payroll_due(db, period: str) -> dict:
    employees = db.query(Employee).filter(Employee.active == True).all()  # noqa: E712
    paid_ids = {p.employee_id for p in db.query(SalaryPayment).filter(SalaryPayment.period == period).all()}
    unpaid = [e for e in employees if e.id not in paid_ids]
    total = sum(e.net_salary or 0 for e in unpaid)
    return {"unpaid_count": len(unpaid), "total": total, "employees": unpaid}


def _method_label(code: Optional[str]) -> str:
    if not code:
        return "—"
    return PAYMENT_METHOD_LABELS.get(code, code)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/weekly", response_class=HTMLResponse, name="weekly_payments")
async def weekly_payments_view(
    request: Request,
    current_user: User = Depends(require_gm),
    db: Session = Depends(get_db),
):
    weekday = _get_payment_weekday(db)
    next_date = _next_payment_date(weekday)
    today = date.today()
    period = today.strftime("%Y-%m")

    # Faturalar
    inv_q = db.query(Invoice).filter(
        Invoice.invoice_type == "gelen",
        Invoice.status.in_(["approved", "partial"]),
        Invoice.due_date != None,  # noqa: E711
        Invoice.due_date <= next_date,
    ).order_by(Invoice.due_date.asc()).all()
    invoices = [i for i in inv_q if i.remaining > 0 and _show_in_list(i, next_date)]

    # Çekler
    chq_q = db.query(Cheque).filter(
        Cheque.cheque_type == "verilen",
        Cheque.status == "beklemede",
        Cheque.due_date <= next_date,
    ).order_by(Cheque.due_date.asc()).all()
    cheques = [c for c in chq_q if _show_in_list(c, next_date)]

    # KK Ekstreleri (Çarşamba kuralından bağımsız — kendi vadesi geçerli)
    cc_q = db.query(CreditCardStatement).filter(
        CreditCardStatement.status == "unpaid",
        CreditCardStatement.due_date <= next_date,
    ).order_by(CreditCardStatement.due_date.asc()).all()
    cc_stmts = [s for s in cc_q if _show_in_list(s, next_date)]

    # Maaş — bu ay ödenmemiş aktifler
    payroll_info = _payroll_due(db, period)
    payroll_decision = db.query(PayrollDecision).filter(PayrollDecision.period == period).first()
    payroll_show = (
        payroll_info["total"] > 0 and (
            payroll_decision is None
            or _show_in_list(payroll_decision, next_date)
        )
    )

    # Birleşik liste — template tek tablo render eder
    items = []
    for inv in invoices:
        items.append({
            "kalem_type": "invoice",
            "kalem_id": inv.id,
            "type_label": "Fatura",
            "type_color": "primary",
            "party": inv.vendor.name if inv.vendor else "—",
            "ref_no": inv.reference.ref_no if inv.reference else "—",
            "ref_url": f"/references/{inv.ref_id}" if inv.ref_id else None,
            "detail_url": f"/invoices/{inv.id}",
            "due_date": inv.due_date,
            "amount": inv.remaining,
            "method_code": inv.gm_method_override or inv.payment_method,
            "method_label": _method_label(inv.gm_method_override or inv.payment_method),
            "method_override": inv.gm_method_override,
            "gm_decision": inv.gm_decision,
            "gm_postpone_until": inv.gm_postpone_until,
            "actionable": _is_actionable(inv),
        })

    for c in cheques:
        party = (c.vendor.name if c.vendor else None) or "—"
        items.append({
            "kalem_type": "cheque",
            "kalem_id": c.id,
            "type_label": "Çek",
            "type_color": "warning",
            "party": party,
            "ref_no": c.cheque_no or "—",
            "ref_url": None,
            "detail_url": "/cheques",
            "due_date": c.due_date,
            "amount": c.amount,
            "method_code": c.gm_method_override or "cek",
            "method_label": _method_label(c.gm_method_override or "cek"),
            "method_override": c.gm_method_override,
            "gm_decision": c.gm_decision,
            "gm_postpone_until": c.gm_postpone_until,
            "actionable": _is_actionable(c),
        })

    for s in cc_stmts:
        items.append({
            "kalem_type": "cc_statement",
            "kalem_id": s.id,
            "type_label": "KK Ekstre",
            "type_color": "danger",
            "party": s.card.name if s.card else "—",
            "ref_no": "—",
            "ref_url": None,
            "detail_url": f"/credit-cards/{s.card_id}",
            "due_date": s.due_date,
            "amount": s.total_amount,
            "method_code": s.gm_method_override or "kredi_karti",
            "method_label": _method_label(s.gm_method_override or "kredi_karti"),
            "method_override": s.gm_method_override,
            "gm_decision": s.gm_decision,
            "gm_postpone_until": s.gm_postpone_until,
            "actionable": _is_actionable(s),
        })

    if payroll_show:
        method = (payroll_decision.gm_method_override if payroll_decision else None) or "banka"
        items.append({
            "kalem_type": "payroll",
            "kalem_id": period,
            "type_label": "Maaş",
            "type_color": "info",
            "party": f"Personel ({payroll_info['unpaid_count']} kişi)",
            "ref_no": period,
            "ref_url": None,
            "detail_url": "/employees",
            "due_date": None,
            "amount": payroll_info["total"],
            "method_code": method,
            "method_label": _method_label(method),
            "method_override": payroll_decision.gm_method_override if payroll_decision else None,
            "gm_decision": payroll_decision.gm_decision if payroll_decision else None,
            "gm_postpone_until": payroll_decision.gm_postpone_until if payroll_decision else None,
            "actionable": _is_actionable(payroll_decision) if payroll_decision else True,
        })

    # Vade tarihine göre sırala (maaş sona)
    items.sort(key=lambda x: (x["due_date"] is None, x["due_date"] or date.max))

    grand_total = sum(it["amount"] for it in items)

    # Özet
    cash_balance = _cash_total(db)
    bank_balance = _bank_total(db)
    cards = db.query(CreditCard).order_by(CreditCard.name).all()
    card_summary = []
    for c in cards:
        used = _cc_outstanding(db, c.id)
        # Sonraki ödenmemiş ekstrenin vadesi
        next_stmt = db.query(CreditCardStatement).filter(
            CreditCardStatement.card_id == c.id,
            CreditCardStatement.status == "unpaid",
        ).order_by(CreditCardStatement.due_date.asc()).first()
        card_summary.append({
            "id": c.id, "name": c.name,
            "limit": c.credit_limit or 0,
            "used": used,
            "available": (c.credit_limit or 0) - used,
            "next_due": next_stmt.due_date if next_stmt else None,
        })
    cc_total_used = sum(c["used"] for c in card_summary)
    cc_total_available = sum(c["available"] for c in card_summary)

    return templates.TemplateResponse(
        "payments/weekly.html",
        {
            "request": request, "current_user": current_user,
            "page_title": "Haftalık Ödeme Listesi",
            "next_date": next_date,
            "weekday": weekday,
            "weekday_name": WEEKDAYS_TR[weekday],
            "weekdays_tr": WEEKDAYS_TR,
            "items": items,
            "grand_total": grand_total,
            "cash_balance": cash_balance,
            "bank_balance": bank_balance,
            "card_summary": card_summary,
            "cc_total_used": cc_total_used,
            "cc_total_available": cc_total_available,
            "payment_methods": PAYMENT_METHODS,
        },
    )


@router.post("/weekly/decide", name="weekly_payment_decide")
async def weekly_payment_decide(
    kalem_type: str = Form(...),
    kalem_id: str = Form(...),
    action: str = Form(...),
    postpone_date: str = Form(""),
    method_override: str = Form(""),
    current_user: User = Depends(require_gm),
    db: Session = Depends(get_db),
):
    if action not in ("approve", "reject", "postpone", "method"):
        raise HTTPException(400, "Geçersiz aksiyon")

    if kalem_type == "invoice":
        item = db.query(Invoice).get(int(kalem_id))
    elif kalem_type == "cheque":
        item = db.query(Cheque).get(int(kalem_id))
    elif kalem_type == "cc_statement":
        item = db.query(CreditCardStatement).get(int(kalem_id))
    elif kalem_type == "payroll":
        item = db.query(PayrollDecision).filter(PayrollDecision.period == kalem_id).first()
        if not item:
            item = PayrollDecision(period=kalem_id)
            db.add(item)
            db.flush()
    else:
        raise HTTPException(400, "Geçersiz kalem tipi")

    if not item:
        raise HTTPException(404, "Kalem bulunamadı")

    now = datetime.utcnow()
    if action == "approve":
        item.gm_decision = "approved"
        item.gm_decision_at = now
        item.gm_decision_by = current_user.id
        item.gm_postpone_until = None
    elif action == "reject":
        item.gm_decision = "rejected"
        item.gm_decision_at = now
        item.gm_decision_by = current_user.id
        item.gm_postpone_until = None
    elif action == "postpone":
        try:
            new_date = date.fromisoformat(postpone_date)
        except (ValueError, TypeError):
            raise HTTPException(400, "Geçersiz erteleme tarihi")
        if new_date <= date.today():
            raise HTTPException(400, "Erteleme tarihi gelecekte olmalı")
        item.gm_decision = "postponed"
        item.gm_decision_at = now
        item.gm_decision_by = current_user.id
        item.gm_postpone_until = new_date
    elif action == "method":
        valid = {m[0] for m in PAYMENT_METHODS}
        if method_override not in valid:
            raise HTTPException(400, "Geçersiz ödeme yöntemi")
        item.gm_method_override = method_override

    db.commit()
    return RedirectResponse(url="/payments/weekly", status_code=303)


@router.post("/weekly/bulk-approve", name="weekly_payment_bulk_approve")
async def weekly_payment_bulk_approve(
    request: Request,
    current_user: User = Depends(require_gm),
    db: Session = Depends(get_db),
):
    form = await request.form()
    entries = form.getlist("items")
    now = datetime.utcnow()
    count = 0
    for entry in entries:
        if ":" not in entry:
            continue
        kalem_type, kalem_id = entry.split(":", 1)
        if kalem_type == "invoice":
            item = db.query(Invoice).get(int(kalem_id))
        elif kalem_type == "cheque":
            item = db.query(Cheque).get(int(kalem_id))
        elif kalem_type == "cc_statement":
            item = db.query(CreditCardStatement).get(int(kalem_id))
        elif kalem_type == "payroll":
            item = db.query(PayrollDecision).filter(PayrollDecision.period == kalem_id).first()
            if not item:
                item = PayrollDecision(period=kalem_id)
                db.add(item)
                db.flush()
        else:
            continue
        if not item:
            continue
        item.gm_decision = "approved"
        item.gm_decision_at = now
        item.gm_decision_by = current_user.id
        item.gm_postpone_until = None
        count += 1
    db.commit()
    return RedirectResponse(url="/payments/weekly", status_code=303)


@router.post("/settings/weekday", name="weekly_payment_set_weekday")
async def set_payment_weekday(
    weekday: int = Form(...),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not (0 <= weekday <= 6):
        raise HTTPException(400, "Geçersiz gün (0-6 olmalı)")
    _set_payment_weekday(db, weekday)
    db.commit()
    return RedirectResponse(url="/payments/weekly", status_code=303)
