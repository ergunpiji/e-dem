"""
Dashboard — GET /dashboard
"""

from datetime import date
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, extract

from auth import get_current_user
from database import get_db
from models import (
    User, Reference, Invoice, CashBook, CashEntry,
    BankAccount, BankMovement, GeneralExpense,
    CreditCard, CreditCardStatement, CreditCardTxn,
)
from templates_config import templates

router = APIRouter()


def _cash_balance(db, book_id):
    ins = db.query(func.sum(CashEntry.amount)).filter(
        CashEntry.book_id == book_id, CashEntry.entry_type == "giris"
    ).scalar() or 0
    outs = db.query(func.sum(CashEntry.amount)).filter(
        CashEntry.book_id == book_id, CashEntry.entry_type == "cikis"
    ).scalar() or 0
    return ins - outs


def _bank_balance(db, account_id):
    account = db.query(BankAccount).get(account_id)
    opening = account.opening_balance if account else 0
    ins = db.query(func.sum(BankMovement.amount)).filter(
        BankMovement.account_id == account_id, BankMovement.movement_type == "giris"
    ).scalar() or 0
    outs = db.query(func.sum(BankMovement.amount)).filter(
        BankMovement.account_id == account_id, BankMovement.movement_type == "cikis"
    ).scalar() or 0
    return opening + ins - outs


def _cc_outstanding(db, card_id):
    """Ödenmemiş ekstreler + ekstreye atanmamış (refund hariç) işlemler."""
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


@router.get("/dashboard", response_class=HTMLResponse, name="dashboard")
async def dashboard(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = date.today()
    year = today.year

    # YTD Kâr — reports.py P&L mantığıyla aynı
    ytd_invoices = db.query(Invoice).filter(
        Invoice.status.in_(["approved", "partial", "paid"]),
        extract("year", Invoice.invoice_date) == year,
    ).all()
    kesilen = sum(i.total_with_vat for i in ytd_invoices if i.invoice_type in ("kesilen", "komisyon"))
    iade_kesilen = sum(i.total_with_vat for i in ytd_invoices if i.invoice_type == "iade_kesilen")
    gelen = sum(i.total_with_vat for i in ytd_invoices if i.invoice_type == "gelen")
    iade_gelen = sum(i.total_with_vat for i in ytd_invoices if i.invoice_type == "iade_gelen")
    net_gelir = kesilen - iade_kesilen
    net_maliyet = gelen - iade_gelen

    ytd_expenses = db.query(GeneralExpense).filter(
        extract("year", GeneralExpense.expense_date) == year
    ).all()
    toplam_gider = sum(e.amount for e in ytd_expenses)
    ytd_kar = net_gelir - net_maliyet - toplam_gider

    # Tahsilat beklenen — kesilen/komisyon faturalarının kalan tutarı
    receivable_invs = db.query(Invoice).filter(
        Invoice.invoice_type.in_(["kesilen", "komisyon"]),
        Invoice.status.in_(["approved", "partial"]),
    ).all()
    tahsilat_beklenen = sum(i.remaining for i in receivable_invs)

    # Ödenecek tutar — gelen faturaların kalan tutarı + tüm KK bakiyeleri
    payable_invs = db.query(Invoice).filter(
        Invoice.invoice_type == "gelen",
        Invoice.status.in_(["approved", "partial"]),
    ).all()
    fatura_odeme = sum(i.remaining for i in payable_invs)

    cards = db.query(CreditCard).all()
    kk_bakiye = sum(_cc_outstanding(db, c.id) for c in cards)

    odeme_yapilacak = fatura_odeme + kk_bakiye

    # Yıl içi kesilen/gelen toplamları (bilgi amaçlı, alt satır)
    kesilen_yil = net_gelir
    gelen_yil = net_maliyet

    # Kasa & banka bakiyeleri
    cash_books = db.query(CashBook).all()
    cash_total = sum(_cash_balance(db, b.id) for b in cash_books)
    bank_accounts = db.query(BankAccount).all()
    bank_total = sum(_bank_balance(db, a.id) for a in bank_accounts)

    # Son referanslar & faturalar
    son_referanslar = (
        db.query(Reference).order_by(Reference.created_at.desc()).limit(5).all()
    )
    son_faturalar = (
        db.query(Invoice).order_by(Invoice.created_at.desc()).limit(5).all()
    )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "current_user": current_user,
            "page_title": "Dashboard",
            "ytd_kar": ytd_kar,
            "tahsilat_beklenen": tahsilat_beklenen,
            "odeme_yapilacak": odeme_yapilacak,
            "kk_bakiye": kk_bakiye,
            "kesilen_yil": kesilen_yil,
            "gelen_yil": gelen_yil,
            "cash_total": cash_total,
            "bank_total": bank_total,
            "son_referanslar": son_referanslar,
            "son_faturalar": son_faturalar,
            "year": year,
        },
    )
