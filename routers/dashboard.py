"""
Dashboard — GET /dashboard
"""

from datetime import date, datetime
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from auth import get_current_user
from database import get_db
from models import (
    User, Reference, Invoice, CashBook, CashEntry,
    BankAccount, BankMovement, Employee
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


@router.get("/dashboard", response_class=HTMLResponse, name="dashboard")
async def dashboard(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = date.today()
    year_start = date(today.year, 1, 1)

    # Referans istatistikleri
    ref_aktif = db.query(func.count(Reference.id)).filter(
        Reference.status == "aktif"
    ).scalar() or 0
    ref_tamamlandi = db.query(func.count(Reference.id)).filter(
        Reference.status == "tamamlandi"
    ).scalar() or 0

    # Fatura istatistikleri (yıl içi) — KDV dahil, partial dahil
    _kesilen_invs = db.query(Invoice).filter(
        Invoice.invoice_type.in_(["kesilen", "komisyon"]),
        Invoice.status.in_(["approved", "partial", "paid"]),
        Invoice.invoice_date >= year_start,
    ).all()
    kesilen_yil = sum(i.total_with_vat for i in _kesilen_invs)

    _gelen_invs = db.query(Invoice).filter(
        Invoice.invoice_type == "gelen",
        Invoice.status.in_(["approved", "partial", "paid"]),
        Invoice.invoice_date >= year_start,
    ).all()
    gelen_yil = sum(i.total_with_vat for i in _gelen_invs)

    # Ödenmemiş fatura sayısı (approved + partial)
    odenmemis = db.query(func.count(Invoice.id)).filter(
        Invoice.status.in_(["approved", "partial"])
    ).scalar() or 0

    # Kasa bakiyeleri
    cash_books = db.query(CashBook).all()
    cash_total = sum(_cash_balance(db, b.id) for b in cash_books)

    # Banka bakiyeleri
    bank_accounts = db.query(BankAccount).all()
    bank_total = sum(_bank_balance(db, a.id) for a in bank_accounts)

    # Aktif çalışan
    aktif_calisan = db.query(func.count(Employee.id)).filter(
        Employee.active == True  # noqa: E712
    ).scalar() or 0

    # Son referanslar
    son_referanslar = (
        db.query(Reference)
        .order_by(Reference.created_at.desc())
        .limit(5)
        .all()
    )

    # Son faturalar
    son_faturalar = (
        db.query(Invoice)
        .order_by(Invoice.created_at.desc())
        .limit(5)
        .all()
    )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "current_user": current_user,
            "page_title": "Dashboard",
            "ref_aktif": ref_aktif,
            "ref_tamamlandi": ref_tamamlandi,
            "kesilen_yil": kesilen_yil,
            "gelen_yil": gelen_yil,
            "odenmemis": odenmemis,
            "cash_total": cash_total,
            "bank_total": bank_total,
            "aktif_calisan": aktif_calisan,
            "son_referanslar": son_referanslar,
            "son_faturalar": son_faturalar,
            "year": today.year,
        },
    )
