"""
Çalışan yönetimi
"""

import json
from datetime import date, datetime
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin
from database import get_db
from models import (
    Employee, SalaryPayment, EmployeeBenefit, EmployeeAdvance,
    GeneralExpense, GeneralExpenseCategory,
    BankAccount, CashBook, CashEntry, BankMovement,
    Reference, User
)
from templates_config import templates

router = APIRouter(prefix="/employees", tags=["employees"])


def _get_salary_category(db) -> int:
    cat = db.query(GeneralExpenseCategory).filter(
        GeneralExpenseCategory.name == "Maaş"
    ).first()
    if not cat:
        parent = db.query(GeneralExpenseCategory).filter(
            GeneralExpenseCategory.name == "Personel"
        ).first()
        cat = GeneralExpenseCategory(name="Maaş", parent_id=parent.id if parent else None, sort_order=1)
        db.add(cat)
        db.flush()
    return cat.id


def _get_benefit_category(db) -> int:
    cat = db.query(GeneralExpenseCategory).filter(
        GeneralExpenseCategory.name == "Yan Haklar"
    ).first()
    if not cat:
        parent = db.query(GeneralExpenseCategory).filter(
            GeneralExpenseCategory.name == "Personel"
        ).first()
        cat = GeneralExpenseCategory(name="Yan Haklar", parent_id=parent.id if parent else None, sort_order=2)
        db.add(cat)
        db.flush()
    return cat.id


@router.get("", response_class=HTMLResponse, name="employees_list")
async def employees_list(
    request: Request,
    active_only: str = "1",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from models import EmployeeAdvance, GeneralExpense
    query = db.query(Employee)
    if active_only == "1":
        query = query.filter(Employee.active == True)  # noqa: E712
    employees = query.order_by(Employee.name).all()

    emp_ids = [e.id for e in employees]

    # Açık avans bakiyeleri (open/partial)
    advance_balance: dict = {}
    for adv in db.query(EmployeeAdvance).filter(
        EmployeeAdvance.employee_id.in_(emp_ids),
        EmployeeAdvance.status.in_(["open", "partial"]),
    ).all():
        remaining = (adv.amount or 0) - (adv.repaid_amount or 0)
        advance_balance[adv.employee_id] = advance_balance.get(adv.employee_id, 0) + remaining

    # Çalışana atanmış genel giderler (HBF / masraf beyanı gibi)
    expense_totals: dict = {}
    for exp in db.query(GeneralExpense).filter(
        GeneralExpense.employee_id.in_(emp_ids)
    ).all():
        expense_totals[exp.employee_id] = expense_totals.get(exp.employee_id, 0) + (exp.amount or 0)

    return templates.TemplateResponse(
        "employees/list.html",
        {"request": request, "current_user": current_user,
         "employees": employees, "active_only": active_only,
         "advance_balance": advance_balance, "expense_totals": expense_totals,
         "page_title": "Çalışanlar"},
    )


@router.get("/new", response_class=HTMLResponse, name="employee_new_get")
async def employee_new_get(
    request: Request,
    current_user: User = Depends(require_admin),
):
    return templates.TemplateResponse(
        "employees/form.html",
        {"request": request, "current_user": current_user,
         "employee": None, "page_title": "Yeni Çalışan"},
    )


@router.post("/new", name="employee_new_post")
async def employee_new_post(
    name: str = Form(...),
    title: str = Form(""),
    department: str = Form(""),
    start_date: str = Form(...),
    gross_salary: float = Form(0.0),
    net_salary: float = Form(0.0),
    iban: str = Form(""),
    notes: str = Form(""),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    e = Employee(
        name=name.strip(), title=title.strip(), department=department.strip(),
        start_date=date.fromisoformat(start_date),
        gross_salary=gross_salary, net_salary=net_salary,
        iban=iban.strip(), active=True, notes=notes.strip(),
    )
    db.add(e)
    db.commit()
    return RedirectResponse(url=f"/employees/{e.id}", status_code=status.HTTP_302_FOUND)


@router.get("/{employee_id}", response_class=HTMLResponse, name="employee_detail")
async def employee_detail(
    employee_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    emp = db.query(Employee).get(employee_id)
    if not emp:
        raise HTTPException(status_code=404)
    bank_accounts = db.query(BankAccount).order_by(BankAccount.name).all()
    cash_books = db.query(CashBook).order_by(CashBook.name).all()
    references = db.query(Reference).filter(Reference.status == "aktif").order_by(Reference.ref_no).all()
    return templates.TemplateResponse(
        "employees/detail.html",
        {
            "request": request, "current_user": current_user,
            "employee": emp,
            "salary_payments": sorted(emp.salary_payments, key=lambda x: x.period, reverse=True),
            "benefits": sorted(emp.benefits, key=lambda x: x.period, reverse=True),
            "advances": sorted(emp.advances, key=lambda x: x.advance_date, reverse=True),
            "bank_accounts": bank_accounts, "cash_books": cash_books,
            "references": references,
            "today": date.today().isoformat(),
            "page_title": emp.name,
        },
    )


@router.get("/{employee_id}/edit", response_class=HTMLResponse, name="employee_edit_get")
async def employee_edit_get(
    employee_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    emp = db.query(Employee).get(employee_id)
    if not emp:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "employees/form.html",
        {"request": request, "current_user": current_user,
         "employee": emp, "page_title": f"Düzenle — {emp.name}"},
    )


@router.post("/{employee_id}/edit", name="employee_edit_post")
async def employee_edit_post(
    employee_id: int,
    name: str = Form(...),
    title: str = Form(""),
    department: str = Form(""),
    start_date: str = Form(...),
    end_date: str = Form(""),
    gross_salary: float = Form(0.0),
    net_salary: float = Form(0.0),
    iban: str = Form(""),
    active: str = Form("1"),
    notes: str = Form(""),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    emp = db.query(Employee).get(employee_id)
    if not emp:
        raise HTTPException(status_code=404)
    emp.name = name.strip()
    emp.title = title.strip()
    emp.department = department.strip()
    emp.start_date = date.fromisoformat(start_date)
    emp.end_date = date.fromisoformat(end_date) if end_date else None
    emp.gross_salary = gross_salary
    emp.net_salary = net_salary
    emp.iban = iban.strip()
    emp.active = (active == "1")
    emp.notes = notes.strip()
    db.commit()
    return RedirectResponse(url=f"/employees/{employee_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{employee_id}/salary", name="employee_salary_post")
async def employee_salary_post(
    employee_id: int,
    period: str = Form(...),
    gross_amount: float = Form(...),
    net_amount: float = Form(...),
    payment_method: str = Form("banka"),
    bank_account_id: int = Form(None),
    notes: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    emp = db.query(Employee).get(employee_id)
    if not emp:
        raise HTTPException(status_code=404)

    cat_id = _get_salary_category(db)
    paid_at = datetime.utcnow()
    paid_date = paid_at.date()

    expense = GeneralExpense(
        category_id=cat_id,
        expense_date=paid_date,
        amount=net_amount,
        payment_method=payment_method,
        employee_id=employee_id,
        source="salary",
        description=f"Maaş — {emp.name} — {period}",
        created_by=current_user.id,
    )
    db.add(expense)
    db.flush()

    sp = SalaryPayment(
        employee_id=employee_id, period=period,
        gross_amount=gross_amount, net_amount=net_amount,
        payment_method=payment_method,
        bank_account_id=bank_account_id if payment_method == "banka" else None,
        paid_at=paid_at, general_expense_id=expense.id, notes=notes.strip(),
    )
    db.add(sp)

    if payment_method == "banka" and bank_account_id:
        db.add(BankMovement(
            account_id=bank_account_id,
            movement_date=paid_date,
            movement_type="cikis",
            amount=net_amount,
            description=f"Maaş — {emp.name} — {period}",
        ))
    elif payment_method == "nakit":
        books = db.query(CashBook).first()
        if books:
            db.add(CashEntry(
                book_id=books.id, entry_date=paid_date,
                entry_type="cikis", amount=net_amount,
                description=f"Maaş — {emp.name} — {period}",
            ))

    db.commit()
    return RedirectResponse(url=f"/employees/{employee_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{employee_id}/benefit", name="employee_benefit_post")
async def employee_benefit_post(
    employee_id: int,
    benefit_type: str = Form(...),
    period: str = Form(...),
    amount: float = Form(...),
    payment_method: str = Form("banka"),
    notes: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    emp = db.query(Employee).get(employee_id)
    if not emp:
        raise HTTPException(status_code=404)

    cat_id = _get_benefit_category(db)
    paid_at = datetime.utcnow()

    expense = GeneralExpense(
        category_id=cat_id,
        expense_date=paid_at.date(),
        amount=amount,
        payment_method=payment_method,
        employee_id=employee_id,
        source="benefit",
        description=f"Yan Hak ({benefit_type}) — {emp.name} — {period}",
        created_by=current_user.id,
    )
    db.add(expense)
    db.flush()

    db.add(EmployeeBenefit(
        employee_id=employee_id, benefit_type=benefit_type,
        period=period, amount=amount,
        paid_at=paid_at, payment_method=payment_method,
        general_expense_id=expense.id, notes=notes.strip(),
    ))
    db.commit()
    return RedirectResponse(url=f"/employees/{employee_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{employee_id}/advance", name="employee_advance_post")
async def employee_advance_post(
    employee_id: int,
    amount: float = Form(...),
    advance_date: str = Form(...),
    reason: str = Form(""),
    advance_type: str = Form("maas"),
    ref_id: int = Form(None),
    payment_method: str = Form("nakit"),
    bank_account_id: int = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    emp = db.query(Employee).get(employee_id)
    if not emp:
        raise HTTPException(status_code=404)
    adv_date = date.fromisoformat(advance_date)

    adv = EmployeeAdvance(
        employee_id=employee_id, amount=amount, advance_date=adv_date,
        reason=reason.strip(), status="open", repaid_amount=0,
        advance_type=advance_type,
        ref_id=ref_id if advance_type == "is" else None,
        payment_method=payment_method,
        bank_account_id=bank_account_id if payment_method == "banka" else None,
    )
    db.add(adv)

    adv_type_label = "İş Avansı" if advance_type == "is" else "Maaş Avansı"
    desc = f"{adv_type_label} — {emp.name}"

    if payment_method == "banka" and bank_account_id:
        db.add(BankMovement(
            account_id=bank_account_id, movement_date=adv_date,
            movement_type="cikis", amount=amount, description=desc,
        ))
    elif payment_method == "nakit":
        book = db.query(CashBook).first()
        if book:
            db.add(CashEntry(
                book_id=book.id, entry_date=adv_date,
                entry_type="cikis", amount=amount, description=desc,
            ))
    db.commit()
    return RedirectResponse(url=f"/employees/{employee_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{employee_id}/advance/{advance_id}/repay", name="employee_advance_repay")
async def employee_advance_repay(
    employee_id: int,
    advance_id: int,
    repay_amount: float = Form(...),
    repay_date: str = Form(...),
    payment_method: str = Form("nakit"),
    bank_account_id: int = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    adv = db.query(EmployeeAdvance).get(advance_id)
    if not adv or adv.employee_id != employee_id:
        raise HTTPException(status_code=404)
    adv.repaid_amount = (adv.repaid_amount or 0) + repay_amount
    if adv.repaid_amount >= adv.amount:
        adv.status = "closed"
        adv.closed_at = date.fromisoformat(repay_date)
        adv.closed_by = current_user.id
    else:
        adv.status = "partial"
    rep_date = date.fromisoformat(repay_date)
    emp = db.query(Employee).get(employee_id)

    # maas_kesintisi = maaştan düşüldü, nakit hareketi yok
    if payment_method != "maas_kesintisi":
        if payment_method == "banka" and bank_account_id:
            db.add(BankMovement(
                account_id=bank_account_id, movement_date=rep_date,
                movement_type="giris", amount=repay_amount,
                description=f"Maaş avansı geri ödeme — {emp.name if emp else ''}",
            ))
        elif payment_method == "nakit":
            book = db.query(CashBook).first()
            if book:
                db.add(CashEntry(
                    book_id=book.id, entry_date=rep_date,
                    entry_type="giris", amount=repay_amount,
                    description=f"Maaş avansı geri ödeme — {emp.name if emp else ''}",
                ))
    db.commit()
    return RedirectResponse(url=f"/employees/{employee_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{employee_id}/advance/{advance_id}/close-is", name="employee_advance_close_is")
async def employee_advance_close_is(
    employee_id: int,
    advance_id: int,
    close_date: str = Form(...),
    expense_items_json: str = Form("[]"),
    cash_return: float = Form(0.0),
    cash_book_id: int = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """İş avansı kapatma: çalışan fiş/fatura ibraz eder, kalan nakit kasaya iade edilir."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403)
    adv = db.query(EmployeeAdvance).get(advance_id)
    if not adv or adv.employee_id != employee_id or adv.advance_type != "is":
        raise HTTPException(status_code=404)

    try:
        items = json.loads(expense_items_json or "[]")
    except Exception:
        items = []

    total_expenses = sum(float(i.get("amount", 0)) for i in items)
    close_dt = date.fromisoformat(close_date)
    emp = db.query(Employee).get(employee_id)

    # Harcama kaydı oluştur (GeneralExpense)
    if total_expenses > 0:
        cat = db.query(GeneralExpenseCategory).filter_by(name="HBF Harcaması").first()
        if not cat:
            cat = db.query(GeneralExpenseCategory).first()
        for item in items:
            amt = float(item.get("amount", 0))
            if amt <= 0:
                continue
            db.add(GeneralExpense(
                category_id=cat.id if cat else None,
                employee_id=employee_id,
                description=item.get("description", "İş Avansı Harcaması"),
                amount=amt,
                expense_date=close_dt,
                source="advance",
                created_by=current_user.id,
            ))

    # Nakit iade → kasaya giriş
    actual_return = min(cash_return, adv.amount - total_expenses)
    if actual_return > 0 and cash_book_id:
        db.add(CashEntry(
            book_id=cash_book_id, entry_date=close_dt,
            entry_type="giris", amount=actual_return,
            description=f"İş avansı nakit iadesi — {emp.name if emp else ''}",
        ))

    adv.expense_items_json = json.dumps(items, ensure_ascii=False)
    adv.cash_return_amount = actual_return
    adv.repaid_amount = total_expenses + actual_return
    adv.status = "closed"
    adv.closed_at = close_dt
    adv.closed_by = current_user.id
    db.commit()
    return RedirectResponse(url=f"/employees/{employee_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{employee_id}/toggle-active", name="employee_toggle_active")
async def employee_toggle_active(
    employee_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    emp = db.query(Employee).get(employee_id)
    if emp:
        emp.active = not emp.active
        db.commit()
    return RedirectResponse(url="/employees", status_code=status.HTTP_302_FOUND)


@router.post("/{employee_id}/delete", name="employee_delete")
async def employee_delete(
    employee_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    emp = db.query(Employee).get(employee_id)
    if emp:
        try:
            db.delete(emp)
            db.commit()
        except Exception:
            db.rollback()
    return RedirectResponse(url="/employees", status_code=status.HTTP_302_FOUND)
