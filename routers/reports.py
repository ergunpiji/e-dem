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
    CreditCardStatement, CreditCardTxn, Cheque, Customer, FinancialVendor,
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

        # KK harcamaları → ekstrenin son ödeme gününe göre (işlem bazında)
        for txn in (
            db.query(CreditCardTxn)
            .join(CreditCardStatement, CreditCardTxn.statement_id == CreditCardStatement.id)
            .filter(
                CreditCardTxn.is_refund == False,
                CreditCardStatement.status == "unpaid",
                CreditCardStatement.due_date >= wstart,
                CreditCardStatement.due_date <= wend,
            )
            .all()
        ):
            outgoing.append({
                "type": "cc_txn",
                "label": txn.description or "KK Harcaması",
                "sub": txn.card.name if txn.card else "Kredi Kartı",
                "date": txn.statement.due_date,
                "amount": txn.amount,
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
    today = date.today()
    year_prev = year - 1

    def is_past(m: int) -> bool:
        return year < today.year or (year == today.year and m <= today.month)

    # Cari yıl: GeneralExpense kategori × ay
    curr_by_cat_month: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for e in db.query(GeneralExpense).filter(
        extract("year", GeneralExpense.expense_date) == year
    ).all():
        curr_by_cat_month[e.category_id or 0][e.expense_date.month] += e.amount or 0

    # Önceki yıl: kategori toplamları
    prev_by_cat: dict[int, float] = defaultdict(float)
    for e in db.query(GeneralExpense).filter(
        extract("year", GeneralExpense.expense_date) == year_prev
    ).all():
        prev_by_cat[e.category_id or 0] += e.amount or 0

    # Bütçe satırları — hangi kategoriler seçili?
    budget = db.query(AnnualBudget).filter(AnnualBudget.year == year).first()
    budget_by_cat: dict[int, list[float]] = {}
    cats_with_bl: set[int] = set()
    if budget:
        for bl in budget.lines:
            if bl.category_id:
                budget_by_cat[bl.category_id] = [
                    getattr(bl, f"month_{m}", 0.0) for m in range(1, 13)
                ]
                cats_with_bl.add(bl.category_id)

    # Aktif kategori = BudgetLine olan + gerçek verisi olan
    cats_with_curr = {cid for cid, mm in curr_by_cat_month.items()
                      if cid != 0 and any(v > 0 for v in mm.values())}
    cats_with_prev = {cid for cid, tot in prev_by_cat.items() if cid != 0 and tot > 0}
    active_cat_id_set = cats_with_bl | cats_with_curr | cats_with_prev

    # Tüm üst kategoriler (section)
    top_cats = db.query(GeneralExpenseCategory).filter(
        GeneralExpenseCategory.parent_id.is_(None)
    ).order_by(GeneralExpenseCategory.sort_order).all()

    # TÜM section ve row'ları oluştur (aktif olmayanlar da dahil, hidden olarak render edilir)
    sections = []
    grand_prev = 0.0
    grand_curr_ytd = 0.0
    grand_monthly = [0.0] * 12
    grand_forecast = 0.0

    for top_cat in top_cats:
        children = sorted(top_cat.children, key=lambda c: c.sort_order) if top_cat.children else [top_cat]
        rows = []

        for child in children:
            active = child.id in active_cat_id_set
            has_actual = child.id in (cats_with_curr | cats_with_prev)
            prev_total = prev_by_cat.get(child.id, 0.0)
            monthly = [curr_by_cat_month[child.id].get(m, 0.0) for m in range(1, 13)]
            curr_ytd = sum(monthly[m - 1] for m in range(1, 13) if is_past(m))
            budget_months = budget_by_cat.get(child.id, [0.0] * 12)
            forecast = sum(
                monthly[m - 1] if is_past(m) else budget_months[m - 1]
                for m in range(1, 13)
            )
            rows.append({
                "cat_id": child.id,
                "label": child.name,
                "active": active,
                "has_actual": has_actual,
                "prev_total": prev_total,
                "curr_ytd": curr_ytd,
                "monthly": monthly,
                "budget": budget_months,
                "forecast": forecast,
            })

        # Grand totals: sadece aktif satırlar
        active_rows = [r for r in rows if r["active"]]
        sec_prev = sum(r["prev_total"] for r in active_rows)
        sec_ytd = sum(r["curr_ytd"] for r in active_rows)
        sec_monthly = [sum(r["monthly"][i] for r in active_rows) for i in range(12)]
        sec_budget = [sum(r["budget"][i] for r in active_rows) for i in range(12)]
        sec_forecast = sum(r["forecast"] for r in active_rows)

        grand_prev += sec_prev
        grand_curr_ytd += sec_ytd
        for i in range(12):
            grand_monthly[i] += sec_monthly[i]
        grand_forecast += sec_forecast

        sections.append({
            "cat_id": top_cat.id,
            "label": top_cat.name,
            "rows": rows,
            "prev_total": sec_prev,
            "curr_ytd": sec_ytd,
            "monthly_total": sec_monthly,
            "budget_monthly": sec_budget,
            "forecast": sec_forecast,
            "has_active": any(r["active"] for r in rows),
        })

    # Sabit giderler öngörüsü
    fixed_expenses = db.query(FixedExpense).filter(FixedExpense.active == True).all()
    fixed_by_month: dict[int, float] = defaultdict(float)
    for fe in fixed_expenses:
        for m in _fixed_expense_months(fe, year):
            fixed_by_month[m] += fe.amount or 0
    fixed_monthly = [fixed_by_month.get(m, 0.0) for m in range(1, 13)]

    return templates.TemplateResponse(
        "reports/activity.html",
        {
            "request": request, "current_user": current_user,
            "year": year,
            "year_prev": year_prev,
            "today": today,
            "months_short": ["Oca", "Şub", "Mar", "Nis", "May", "Haz",
                             "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"],
            "budget": budget,
            "sections": sections,
            "fixed_expenses": fixed_expenses,
            "fixed_monthly": fixed_monthly,
            "grand_prev": grand_prev,
            "grand_curr_ytd": grand_curr_ytd,
            "grand_monthly": grand_monthly,
            "grand_forecast": grand_forecast,
            "page_title": f"Faaliyet Raporu — {year}",
        },
    )


@router.post("/activity/budget", name="report_activity_budget_save")
async def report_activity_budget_save(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    import json as _json
    form = await request.form()
    year = int(form.get("year", date.today().year))

    budget = db.query(AnnualBudget).filter(AnnualBudget.year == year).first()
    if not budget:
        budget = AnnualBudget(year=year, created_by=current_user.id)
        db.add(budget)
        db.flush()

    # Section sıralamasını güncelle (sort_order)
    section_order_json = form.get("section_order_json", "")
    if section_order_json:
        try:
            order = _json.loads(section_order_json)
            for idx, sec_id in enumerate(order):
                cat = db.query(GeneralExpenseCategory).get(int(sec_id))
                if cat and cat.parent_id is None:
                    cat.sort_order = idx * 10
        except Exception:
            pass

    # show_cat_N hidden input'larından hangi kategoriler seçili
    active_cat_ids: set[int] = set()
    for key in form.keys():
        if key.startswith("show_cat_"):
            try:
                active_cat_ids.add(int(key[9:]))
            except ValueError:
                pass

    # Mevcut satırları temizle, aktif olanları yeniden yaz
    db.query(BudgetLine).filter(BudgetLine.budget_id == budget.id).delete()

    for cat_id in active_cat_ids:
        cat = db.query(GeneralExpenseCategory).get(cat_id)
        if not cat:
            continue
        label = form.get(f"label_cat_{cat_id}", cat.name)
        bl = BudgetLine(
            budget_id=budget.id,
            line_type="gider",
            category_id=cat_id,
            label=label,
        )
        for m in range(1, 13):
            try:
                val = float(form.get(f"line_cat_{cat_id}_month_{m}", 0) or 0)
            except (ValueError, TypeError):
                val = 0.0
            setattr(bl, f"month_{m}", val)
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
    db.flush()

    redirect_year = year or dt_date.today().year

    # Kategori seçildiyse bütçeyi otomatik doldur
    if fe.category_id:
        cat = db.query(GeneralExpenseCategory).get(fe.category_id)
        bgt = db.query(AnnualBudget).filter(AnnualBudget.year == redirect_year).first()
        if not bgt:
            bgt = AnnualBudget(year=redirect_year, created_by=current_user.id)
            db.add(bgt)
            db.flush()
        bl = db.query(BudgetLine).filter(
            BudgetLine.budget_id == bgt.id,
            BudgetLine.category_id == fe.category_id,
        ).first()
        if not bl:
            bl = BudgetLine(
                budget_id=bgt.id,
                line_type="gider",
                category_id=fe.category_id,
                label=cat.name if cat else fe.label,
            )
            db.add(bl)
            db.flush()
        for m in _fixed_expense_months(fe, redirect_year):
            current_val = getattr(bl, f"month_{m}", 0.0) or 0.0
            setattr(bl, f"month_{m}", current_val + fe.amount)

    db.commit()
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
