"""
Raporlar
"""

from datetime import date
from collections import defaultdict
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, extract

from fastapi import Form, HTTPException
from fastapi.responses import RedirectResponse
from auth import get_current_user, require_admin
from database import get_db
from models import (
    Invoice, GeneralExpense, CashEntry, BankMovement,
    CreditCardStatement, Cheque, Customer, FinancialVendor,
    Employee, SalaryPayment, EmployeeBenefit, User,
    AnnualBudget, BudgetLine, FixedExpense, GeneralExpenseCategory,
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


# ---------------------------------------------------------------------------
# Faaliyet Raporu
# ---------------------------------------------------------------------------

def _fixed_expense_months(fe: FixedExpense, year: int) -> list[int]:
    """Verilen yılda hangi aylarda bu sabit gider gerçekleşir, liste döner."""
    months = []
    for m in range(1, 13):
        month_start = date(year, m, 1)
        # Bitiş tarihi kontrolü
        if fe.end_date and month_start > fe.end_date:
            continue
        # Başlangıç tarihi kontrolü (ay bazında)
        if date(year, m, 1) < date(fe.start_date.year, fe.start_date.month, 1):
            continue
        if fe.recurrence == "monthly":
            months.append(m)
        elif fe.recurrence == "quarterly":
            # start_date'in ayından itibaren her 3 ayda bir
            start_month = fe.start_date.month
            if (m - start_month) % 3 == 0:
                months.append(m)
        elif fe.recurrence == "yearly":
            if m == fe.start_date.month:
                months.append(m)
        elif fe.recurrence == "once":
            if year == fe.start_date.year and m == fe.start_date.month:
                months.append(m)
    return months


@router.get("/activity", response_class=HTMLResponse, name="report_activity")
async def report_activity(
    request: Request,
    year: int = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not year:
        year = date.today().year

    # --- Gerçekleşen veriler ---
    # Kesilen faturalar (gelir) — invoice_date bazında
    kesilen_by_month = defaultdict(float)
    gelen_by_month = defaultdict(float)
    for inv in db.query(Invoice).filter(
        extract("year", Invoice.invoice_date) == year,
        Invoice.status.in_(["approved", "paid"]),
    ).all():
        m = inv.invoice_date.month
        if inv.invoice_type in ("kesilen", "komisyon"):
            kesilen_by_month[m] += inv.amount or 0
        elif inv.invoice_type in ("iade_kesilen",):
            kesilen_by_month[m] -= inv.amount or 0
        elif inv.invoice_type == "gelen":
            gelen_by_month[m] += inv.amount or 0
        elif inv.invoice_type == "iade_gelen":
            gelen_by_month[m] -= inv.amount or 0

    # Genel giderler — kategori ve ay bazında
    expenses = db.query(GeneralExpense).filter(
        extract("year", GeneralExpense.expense_date) == year,
    ).all()

    # Maaş + haklar ayrı topla
    maas_by_month: dict[int, float] = defaultdict(float)
    gider_by_cat_month: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for e in expenses:
        m = e.expense_date.month
        if e.source in ("salary", "benefit"):
            maas_by_month[m] += e.amount or 0
        else:
            gider_by_cat_month[e.category_id or 0][m] += e.amount or 0

    # Maaş ödemeleri (salary_payments tablosu — period: "YYYY-MM")
    for sp in db.query(SalaryPayment).filter(
        SalaryPayment.period.like(f"{year}-%")
    ).all():
        try:
            m = int(sp.period.split("-")[1])
            maas_by_month[m] += sp.net_amount or 0
        except Exception:
            pass

    # --- Bütçe verileri ---
    budget = db.query(AnnualBudget).filter(AnnualBudget.year == year).first()
    budget_lines_by_key: dict[str, BudgetLine] = {}
    if budget:
        for bl in budget.lines:
            key = bl.label if not bl.category_id else f"cat_{bl.category_id}"
            budget_lines_by_key[key] = bl

    # --- Sabit giderler ---
    fixed_expenses = db.query(FixedExpense).filter(FixedExpense.active == True).all()
    fixed_by_month: dict[int, float] = defaultdict(float)
    for fe in fixed_expenses:
        for m in _fixed_expense_months(fe, year):
            fixed_by_month[m] += fe.amount or 0

    # --- Genel gider kategorileri (üst kategori listesi) ---
    top_cats = db.query(GeneralExpenseCategory).filter(
        GeneralExpenseCategory.parent_id.is_(None)
    ).order_by(GeneralExpenseCategory.sort_order).all()

    # --- Özet toplamlar ---
    def month_vals(d: dict) -> list:
        return [d.get(m, 0.0) for m in range(1, 13)]

    total_gelir_actual = [kesilen_by_month.get(m, 0.0) for m in range(1, 13)]
    total_gelen_actual = [gelen_by_month.get(m, 0.0) for m in range(1, 13)]
    total_maas_actual = [maas_by_month.get(m, 0.0) for m in range(1, 13)]
    total_fixed_projected = [fixed_by_month.get(m, 0.0) for m in range(1, 13)]

    # Genel gider gerçekleşen (tüm kategoriler toplam, maaş hariç)
    genel_actual_by_month = defaultdict(float)
    for cat_id, month_map in gider_by_cat_month.items():
        for m, amt in month_map.items():
            genel_actual_by_month[m] += amt
    total_genel_actual = [genel_actual_by_month.get(m, 0.0) for m in range(1, 13)]

    # Net
    today = date.today()
    net_actual = []
    for m in range(1, 13):
        net_actual.append(
            kesilen_by_month.get(m, 0.0)
            - gelen_by_month.get(m, 0.0)
            - maas_by_month.get(m, 0.0)
            - genel_actual_by_month.get(m, 0.0)
        )

    # Bütçe line helpers
    def bl_months(key: str) -> list:
        bl = budget_lines_by_key.get(key)
        if not bl:
            return [0.0] * 12
        return [getattr(bl, f"month_{m}", 0.0) for m in range(1, 13)]

    return templates.TemplateResponse(
        "reports/activity.html",
        {
            "request": request, "current_user": current_user,
            "year": year,
            "months": ["Oca", "Şub", "Mar", "Nis", "May", "Haz",
                       "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"],
            "budget": budget,
            "budget_lines_by_key": budget_lines_by_key,
            "fixed_expenses": fixed_expenses,
            # Gerçekleşen
            "total_gelir_actual": total_gelir_actual,
            "total_gelen_actual": total_gelen_actual,
            "total_maas_actual": total_maas_actual,
            "total_genel_actual": total_genel_actual,
            "total_fixed_projected": total_fixed_projected,
            "net_actual": net_actual,
            # Kategori bazlı gider gerçekleşen
            "top_cats": top_cats,
            "gider_by_cat_month": gider_by_cat_month,
            # Bütçe helpers
            "bl_months": bl_months,
            "today": today,
            "page_title": f"Faaliyet Raporu — {year}",
        },
    )


@router.post("/activity/budget", name="report_activity_budget_save")
async def report_activity_budget_save(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from fastapi import status as http_status
    form = await request.form()
    year = int(form.get("year", date.today().year))

    budget = db.query(AnnualBudget).filter(AnnualBudget.year == year).first()
    if not budget:
        budget = AnnualBudget(year=year, created_by=current_user.id)
        db.add(budget)
        db.flush()

    # Mevcut satırları temizle
    db.query(BudgetLine).filter(BudgetLine.budget_id == budget.id).delete()

    # Form'dan satırları topla: line_TYPE_IDX_month_M
    # Format: line_gelir_0_month_1, line_gelen_0_month_1, line_cat_7_month_1, ...
    lines_map: dict[str, dict] = {}
    for key, val in form.items():
        if not key.startswith("line_"):
            continue
        parts = key.split("_")
        # line_{type}_{idx_or_catid}_month_{m}
        # e.g. line_gelir_0_month_1 → type=gelir, idx=0, m=1
        # e.g. line_cat_7_month_3 → type=cat, idx=7, m=3
        if len(parts) < 5:
            continue
        line_key = f"{parts[1]}_{parts[2]}"  # gelir_0 or cat_7
        month_num = int(parts[-1])
        if line_key not in lines_map:
            lines_map[line_key] = {"type": parts[1], "idx": parts[2], "months": {}}
        try:
            lines_map[line_key]["months"][month_num] = float(val or 0)
        except ValueError:
            lines_map[line_key]["months"][month_num] = 0.0

    # Label bilgisi
    for line_key, data in lines_map.items():
        label = form.get(f"label_{line_key}", line_key)
        cat_id = None
        if data["type"] == "cat":
            try:
                cat_id = int(data["idx"])
            except ValueError:
                pass
        bl = BudgetLine(
            budget_id=budget.id,
            line_type=data["type"] if data["type"] != "cat" else "gider",
            category_id=cat_id,
            label=label,
        )
        for m in range(1, 13):
            setattr(bl, f"month_{m}", data["months"].get(m, 0.0))
        db.add(bl)

    db.commit()
    return RedirectResponse(url=f"/reports/activity?year={year}", status_code=303)


@router.post("/activity/fixed-expense/add", name="report_activity_fixed_add")
async def report_activity_fixed_add(
    label: str = Form(...),
    amount: float = Form(...),
    recurrence: str = Form("monthly"),
    start_date: str = Form(...),
    end_date: str = Form(""),
    category_id: int = Form(None),
    notes: str = Form(""),
    year: int = Form(None),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from datetime import date as dt_date
    fe = FixedExpense(
        label=label.strip(),
        amount=amount,
        recurrence=recurrence,
        start_date=dt_date.fromisoformat(start_date),
        end_date=dt_date.fromisoformat(end_date) if end_date else None,
        category_id=category_id or None,
        notes=notes.strip(),
        active=True,
        created_by=current_user.id,
    )
    db.add(fe)
    db.commit()
    redirect_year = year or date.today().year
    return RedirectResponse(url=f"/reports/activity?year={redirect_year}", status_code=303)


@router.post("/activity/fixed-expense/{fe_id}/delete", name="report_activity_fixed_delete")
async def report_activity_fixed_delete(
    fe_id: int,
    year: int = Form(None),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    fe = db.query(FixedExpense).get(fe_id)
    if fe:
        db.delete(fe)
        db.commit()
    redirect_year = year or date.today().year
    return RedirectResponse(url=f"/reports/activity?year={redirect_year}", status_code=303)
