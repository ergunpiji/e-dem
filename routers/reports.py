"""
Raporlar
"""

from datetime import date
from collections import defaultdict
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, extract

from auth import get_current_user, require_admin
from database import get_db
from models import (
    Invoice, GeneralExpense, CashEntry, BankMovement,
    CreditCardStatement, Cheque, Customer, FinancialVendor,
    Employee, SalaryPayment, EmployeeBenefit, User
)
from templates_config import templates

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/pl", response_class=HTMLResponse, name="report_pl")
async def report_pl(
    request: Request,
    year: int = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not year:
        year = date.today().year

    invoices = db.query(Invoice).filter(
        Invoice.status.in_(["approved", "paid"]),
        extract("year", Invoice.invoice_date) == year,
    ).all()

    kesilen = sum(i.amount for i in invoices if i.invoice_type in ("kesilen", "komisyon"))
    iade_kesilen = sum(i.amount for i in invoices if i.invoice_type == "iade_kesilen")
    gelen = sum(i.amount for i in invoices if i.invoice_type == "gelen")
    iade_gelen = sum(i.amount for i in invoices if i.invoice_type == "iade_gelen")

    net_gelir = (kesilen - iade_kesilen)
    net_maliyet = (gelen - iade_gelen)

    expenses = db.query(GeneralExpense).filter(
        extract("year", GeneralExpense.expense_date) == year
    ).all()
    personel_gider = sum(e.amount for e in expenses if e.source in ("salary", "benefit"))
    diger_gider = sum(e.amount for e in expenses if e.source not in ("salary", "benefit"))

    gross_profit = net_gelir - net_maliyet
    net_profit = gross_profit - personel_gider - diger_gider

    return templates.TemplateResponse(
        "reports/pl.html",
        {
            "request": request, "current_user": current_user,
            "year": year,
            "kesilen": kesilen, "iade_kesilen": iade_kesilen,
            "net_gelir": net_gelir,
            "gelen": gelen, "iade_gelen": iade_gelen,
            "net_maliyet": net_maliyet,
            "gross_profit": gross_profit,
            "personel_gider": personel_gider,
            "diger_gider": diger_gider,
            "net_profit": net_profit,
            "page_title": f"P&L — {year}",
        },
    )


@router.get("/cash-flow", response_class=HTMLResponse, name="report_cash_flow")
async def report_cash_flow(
    request: Request,
    weeks: int = 8,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from datetime import timedelta
    today = date.today()
    week_start = today - timedelta(days=today.weekday())  # bu haftanın Pazartesi'si

    weeks_data = []
    for i in range(weeks):
        wstart = week_start + timedelta(weeks=i)
        wend = wstart + timedelta(days=6)
        label = f"H{i + 1}" if i > 0 else "Bu Hafta"

        incoming = []  # gelir: tahsilat beklenen kesilen faturalar + kasa/banka girişleri
        outgoing = []  # gider: ödeme bekleyen gelen faturalar, çekler, KK ekstreler, kasa/banka çıkışları

        # Kesilen faturalar → due_date'e göre beklenen tahsilat
        for inv in db.query(Invoice).filter(
            Invoice.invoice_type.in_(["kesilen", "komisyon"]),
            Invoice.status == "approved",
            Invoice.due_date >= wstart,
            Invoice.due_date <= wend,
        ).all():
            incoming.append({
                "type": "invoice",
                "label": inv.reference.ref_no if inv.reference else (inv.invoice_no or f"Fatura #{inv.id}"),
                "sub": inv.vendor.name if inv.vendor else "",
                "date": inv.due_date,
                "amount": inv.amount,
                "invoice_id": inv.id,
            })

        # Kasa girişleri
        for e in db.query(CashEntry).filter(
            CashEntry.entry_type == "giris",
            CashEntry.entry_date >= wstart,
            CashEntry.entry_date <= wend,
        ).all():
            incoming.append({
                "type": "cash",
                "label": e.description or "Kasa Girişi",
                "sub": "Kasa",
                "date": e.entry_date,
                "amount": e.amount,
            })

        # Banka girişleri
        for m in db.query(BankMovement).filter(
            BankMovement.movement_type == "giris",
            BankMovement.movement_date >= wstart,
            BankMovement.movement_date <= wend,
        ).all():
            incoming.append({
                "type": "bank",
                "label": m.description or "Banka Girişi",
                "sub": m.account.name if m.account else "Banka",
                "date": m.movement_date,
                "amount": m.amount,
            })

        # Gelen faturalar → due_date'e göre beklenen ödeme
        for inv in db.query(Invoice).filter(
            Invoice.invoice_type == "gelen",
            Invoice.status == "approved",
            Invoice.due_date >= wstart,
            Invoice.due_date <= wend,
        ).all():
            outgoing.append({
                "type": "invoice",
                "label": inv.vendor.name if inv.vendor else (inv.invoice_no or f"Fatura #{inv.id}"),
                "sub": inv.reference.ref_no if inv.reference else "",
                "date": inv.due_date,
                "amount": inv.amount,
            })

        # Verilen çekler → vade tarihine göre
        for c in db.query(Cheque).filter(
            Cheque.cheque_type == "verilen",
            Cheque.status == "beklemede",
            Cheque.due_date >= wstart,
            Cheque.due_date <= wend,
        ).all():
            outgoing.append({
                "type": "cheque",
                "label": f"Çek — {c.cheque_no or c.id}",
                "sub": c.vendor.name if c.vendor else "",
                "date": c.due_date,
                "amount": c.amount,
            })

        # KK ekstre ödemeleri → due_date'e göre
        for stmt in db.query(CreditCardStatement).filter(
            CreditCardStatement.status == "unpaid",
            CreditCardStatement.due_date >= wstart,
            CreditCardStatement.due_date <= wend,
        ).all():
            outgoing.append({
                "type": "cc_stmt",
                "label": f"KK Ekstre — {stmt.card.name if stmt.card else ''}",
                "sub": stmt.card.bank_name if stmt.card else "",
                "date": stmt.due_date,
                "amount": stmt.total_amount,
            })

        # Kasa çıkışları
        for e in db.query(CashEntry).filter(
            CashEntry.entry_type == "cikis",
            CashEntry.entry_date >= wstart,
            CashEntry.entry_date <= wend,
        ).all():
            outgoing.append({
                "type": "cash",
                "label": e.description or "Kasa Çıkışı",
                "sub": "Kasa",
                "date": e.entry_date,
                "amount": e.amount,
            })

        # Banka çıkışları
        for m in db.query(BankMovement).filter(
            BankMovement.movement_type == "cikis",
            BankMovement.movement_date >= wstart,
            BankMovement.movement_date <= wend,
        ).all():
            outgoing.append({
                "type": "bank",
                "label": m.description or "Banka Çıkışı",
                "sub": m.account.name if m.account else "Banka",
                "date": m.movement_date,
                "amount": m.amount,
            })

        total_in = sum(x["amount"] for x in incoming)
        total_out = sum(x["amount"] for x in outgoing)

        weeks_data.append({
            "label": label,
            "start": wstart.strftime("%d.%m"),
            "end": wend.strftime("%d.%m"),
            "total_in": total_in,
            "total_out": total_out,
            "incoming": sorted(incoming, key=lambda x: x["date"]),
            "outgoing": sorted(outgoing, key=lambda x: x["date"]),
        })

    # Vadesi geçmiş ödenmemiş faturalar (kesilen)
    overdue = db.query(Invoice).filter(
        Invoice.invoice_type.in_(["kesilen", "komisyon"]),
        Invoice.status == "approved",
        Invoice.due_date < today,
        Invoice.due_date.isnot(None),
    ).all()
    total_overdue = sum(i.amount for i in overdue)

    return templates.TemplateResponse(
        "reports/cash_flow.html",
        {
            "request": request, "current_user": current_user,
            "weeks_data": weeks_data, "weeks": weeks,
            "overdue": overdue, "total_overdue": total_overdue,
            "page_title": "Nakit Akışı",
        },
    )


@router.get("/ledger/customer/{customer_id}", response_class=HTMLResponse, name="report_customer_ledger")
async def report_customer_ledger(
    customer_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from models import Reference
    customer = db.query(Customer).get(customer_id)
    if not customer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
    refs = db.query(Reference).filter(Reference.customer_id == customer_id).all()
    ref_ids = [r.id for r in refs]
    invoices = db.query(Invoice).filter(
        Invoice.ref_id.in_(ref_ids),
        Invoice.status.in_(["approved", "paid"]),
    ).order_by(Invoice.invoice_date).all()

    total_kesilen = sum(i.amount for i in invoices if i.invoice_type == "kesilen")
    total_paid = sum(i.amount for i in invoices if i.status == "paid" and i.invoice_type == "kesilen")
    balance = total_kesilen - total_paid

    return templates.TemplateResponse(
        "reports/ledger.html",
        {
            "request": request, "current_user": current_user,
            "entity": customer, "entity_type": "customer",
            "invoices": invoices,
            "total_kesilen": total_kesilen, "total_paid": total_paid,
            "balance": balance,
            "page_title": f"Müşteri Cari — {customer.name}",
        },
    )


@router.get("/ledger/vendor/{vendor_id}", response_class=HTMLResponse, name="report_vendor_ledger")
async def report_vendor_ledger(
    vendor_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    vendor = db.query(FinancialVendor).get(vendor_id)
    if not vendor:
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
    invoices = db.query(Invoice).filter(
        Invoice.vendor_id == vendor_id,
        Invoice.status.in_(["approved", "paid"]),
    ).order_by(Invoice.invoice_date).all()

    total_gelen = sum(i.amount for i in invoices if i.invoice_type == "gelen")
    total_paid = sum(i.amount for i in invoices if i.status == "paid" and i.invoice_type == "gelen")
    balance = total_gelen - total_paid

    return templates.TemplateResponse(
        "reports/ledger.html",
        {
            "request": request, "current_user": current_user,
            "entity": vendor, "entity_type": "vendor",
            "invoices": invoices,
            "total_gelen": total_gelen, "total_paid": total_paid,
            "balance": balance,
            "page_title": f"Tedarikçi Cari — {vendor.name}",
        },
    )


@router.get("/payroll", response_class=HTMLResponse, name="report_payroll")
async def report_payroll(
    request: Request,
    period: str = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not period:
        today = date.today()
        period = today.strftime("%Y-%m")

    salaries = db.query(SalaryPayment).filter(SalaryPayment.period == period).all()
    benefits = db.query(EmployeeBenefit).filter(EmployeeBenefit.period == period).all()
    total_gross = sum(s.gross_amount for s in salaries)
    total_net = sum(s.net_amount for s in salaries)
    total_benefits = sum(b.amount for b in benefits)

    emp_data = {}
    for s in salaries:
        emp_data.setdefault(s.employee_id, {"employee": s.employee, "gross": 0, "net": 0, "benefits": 0})
        emp_data[s.employee_id]["gross"] += s.gross_amount
        emp_data[s.employee_id]["net"] += s.net_amount
    for b in benefits:
        emp_data.setdefault(b.employee_id, {"employee": b.employee, "gross": 0, "net": 0, "benefits": 0})
        emp_data[b.employee_id]["benefits"] += b.amount

    return templates.TemplateResponse(
        "reports/payroll.html",
        {
            "request": request, "current_user": current_user,
            "period": period,
            "emp_rows": list(emp_data.values()),
            "total_gross": total_gross, "total_net": total_net,
            "total_benefits": total_benefits,
            "grand_total": total_net + total_benefits,
            "page_title": f"Bordro — {period}",
        },
    )
