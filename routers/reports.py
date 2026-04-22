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
    start: str = None,
    end: str = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    today = date.today()
    start_date = date.fromisoformat(start) if start else date(today.year, 1, 1)
    end_date = date.fromisoformat(end) if end else today

    events = []

    # Kasa hareketleri
    for e in db.query(CashEntry).filter(
        CashEntry.entry_date >= start_date, CashEntry.entry_date <= end_date
    ).all():
        sign = 1 if e.entry_type == "giris" else -1
        events.append({"date": e.entry_date, "amount": sign * e.amount,
                        "description": e.description or "", "source": "Kasa"})

    # Banka hareketleri
    for m in db.query(BankMovement).filter(
        BankMovement.movement_date >= start_date, BankMovement.movement_date <= end_date
    ).all():
        sign = 1 if m.movement_type == "giris" else -1
        events.append({"date": m.movement_date, "amount": sign * m.amount,
                        "description": m.description or "", "source": "Banka"})

    # Kredi kartı ekstre ödemeleri → due_date bazlı
    for stmt in db.query(CreditCardStatement).filter(
        CreditCardStatement.due_date >= start_date,
        CreditCardStatement.due_date <= end_date,
    ).all():
        events.append({"date": stmt.due_date, "amount": -stmt.total_amount,
                        "description": f"KK Ekstre — {stmt.card.name if stmt.card else ''}",
                        "source": "Kredi Kartı"})

    # Verilen çekler → due_date bazlı
    for c in db.query(Cheque).filter(
        Cheque.cheque_type == "verilen",
        Cheque.due_date >= start_date,
        Cheque.due_date <= end_date,
        Cheque.status.in_(["beklemede", "tahsil_edildi"]),
    ).all():
        events.append({"date": c.due_date, "amount": -c.amount,
                        "description": f"Çek — {c.cheque_no or c.id}",
                        "source": "Çek"})

    events.sort(key=lambda x: x["date"])

    running = 0.0
    for e in events:
        running += e["amount"]
        e["running"] = running

    return templates.TemplateResponse(
        "reports/cash_flow.html",
        {
            "request": request, "current_user": current_user,
            "events": events, "start": start_date, "end": end_date,
            "total": sum(e["amount"] for e in events),
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
