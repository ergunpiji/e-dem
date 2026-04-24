"""
HBF — Harcama Bildirim Formu yönetimi
"""

import json
from datetime import date as _date, datetime
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db, generate_hbf_no
from models import (
    HBF, HBF_STATUS_LABELS, Employee, Reference,
    User, CashBook, BankAccount, GeneralExpense,
    GeneralExpenseCategory, CashEntry, BankMovement,
    PAYMENT_METHODS,
)
from templates_config import templates

router = APIRouter(prefix="/hbf", tags=["hbf"])


def _parse_items(items_json: str) -> tuple[list, float]:
    try:
        items = json.loads(items_json or "[]")
    except Exception:
        items = []
    total = sum(float(i.get("amount", 0)) for i in items)
    return items, total


def _hbf_expense_category(db) -> int:
    cat = db.query(GeneralExpenseCategory).filter_by(name="HBF Harcaması").first()
    if not cat:
        parent = db.query(GeneralExpenseCategory).filter_by(name="Diğer", parent_id=None).first()
        cat = GeneralExpenseCategory(
            name="HBF Harcaması",
            parent_id=parent.id if parent else None,
            sort_order=99,
        )
        db.add(cat)
        db.flush()
    return cat.id


# ---------------------------------------------------------------------------
# Liste
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, name="hbf_list")
async def hbf_list(
    request: Request,
    status_filter: str = "all",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(HBF)
    if not (current_user.is_admin or current_user.is_approver):
        q = q.filter(HBF.created_by == current_user.id)
    if status_filter != "all":
        q = q.filter(HBF.status == status_filter)
    forms = q.order_by(HBF.created_at.desc()).all()
    return templates.TemplateResponse(
        "hbf/list.html",
        {
            "request": request, "current_user": current_user,
            "forms": forms, "status_filter": status_filter,
            "status_labels": HBF_STATUS_LABELS,
            "page_title": "Harcama Bildirimleri",
        },
    )


# ---------------------------------------------------------------------------
# Yeni HBF
# ---------------------------------------------------------------------------

@router.get("/new", response_class=HTMLResponse, name="hbf_new_get")
async def hbf_new_get(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    employees = db.query(Employee).filter(Employee.active == True).order_by(Employee.name).all()  # noqa: E712
    references = db.query(Reference).filter(Reference.status == "aktif").order_by(Reference.ref_no).all()
    return templates.TemplateResponse(
        "hbf/form.html",
        {
            "request": request, "current_user": current_user,
            "hbf": None, "employees": employees, "references": references,
            "page_title": "Yeni Harcama Bildirimi",
        },
    )


@router.post("/new", name="hbf_new_post")
async def hbf_new_post(
    title: str = Form(...),
    ref_id: int = Form(None),
    employee_id: int = Form(None),
    items_json: str = Form("[]"),
    notes: str = Form(""),
    action: str = Form("taslak"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items, total = _parse_items(items_json)
    hbf_status = "beklemede" if action == "gonder" else "taslak"
    hbf = HBF(
        hbf_no=generate_hbf_no(db),
        ref_id=ref_id or None,
        employee_id=employee_id or None,
        title=title.strip(),
        items_json=json.dumps(items, ensure_ascii=False),
        total_amount=total,
        status=hbf_status,
        notes=notes.strip() or None,
        created_by=current_user.id,
    )
    db.add(hbf)
    db.commit()
    return RedirectResponse(url=f"/hbf/{hbf.id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Detay
# ---------------------------------------------------------------------------

@router.get("/{hbf_id}", response_class=HTMLResponse, name="hbf_detail")
async def hbf_detail(
    hbf_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    hbf = db.query(HBF).get(hbf_id)
    if not hbf:
        raise HTTPException(status_code=404)
    if not (current_user.is_admin or current_user.is_approver or hbf.created_by == current_user.id):
        raise HTTPException(status_code=403)

    items, _ = _parse_items(hbf.items_json)
    cash_books = db.query(CashBook).all()
    bank_accounts = db.query(BankAccount).all()

    return templates.TemplateResponse(
        "hbf/detail.html",
        {
            "request": request, "current_user": current_user,
            "hbf": hbf, "items": items,
            "status_labels": HBF_STATUS_LABELS,
            "cash_books": cash_books, "bank_accounts": bank_accounts,
            "payment_methods": PAYMENT_METHODS,
            "today": _date.today(),
            "page_title": hbf.hbf_no,
        },
    )


# ---------------------------------------------------------------------------
# Düzenle (sadece taslak)
# ---------------------------------------------------------------------------

@router.get("/{hbf_id}/edit", response_class=HTMLResponse, name="hbf_edit_get")
async def hbf_edit_get(
    hbf_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    hbf = db.query(HBF).get(hbf_id)
    if not hbf or hbf.status != "taslak":
        raise HTTPException(status_code=404)
    if hbf.created_by != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403)
    employees = db.query(Employee).filter(Employee.active == True).order_by(Employee.name).all()  # noqa: E712
    references = db.query(Reference).filter(Reference.status == "aktif").order_by(Reference.ref_no).all()
    return templates.TemplateResponse(
        "hbf/form.html",
        {
            "request": request, "current_user": current_user,
            "hbf": hbf, "employees": employees, "references": references,
            "page_title": f"Düzenle — {hbf.hbf_no}",
        },
    )


@router.post("/{hbf_id}/edit", name="hbf_edit_post")
async def hbf_edit_post(
    hbf_id: int,
    title: str = Form(...),
    ref_id: int = Form(None),
    employee_id: int = Form(None),
    items_json: str = Form("[]"),
    notes: str = Form(""),
    action: str = Form("taslak"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    hbf = db.query(HBF).get(hbf_id)
    if not hbf or hbf.status != "taslak":
        raise HTTPException(status_code=404)
    items, total = _parse_items(items_json)
    hbf.title = title.strip()
    hbf.ref_id = ref_id or None
    hbf.employee_id = employee_id or None
    hbf.items_json = json.dumps(items, ensure_ascii=False)
    hbf.total_amount = total
    hbf.notes = notes.strip() or None
    if action == "gonder":
        hbf.status = "beklemede"
    db.commit()
    return RedirectResponse(url=f"/hbf/{hbf_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Gönder (taslak → beklemede)
# ---------------------------------------------------------------------------

@router.post("/{hbf_id}/submit", name="hbf_submit")
async def hbf_submit(
    hbf_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    hbf = db.query(HBF).get(hbf_id)
    if not hbf or hbf.status != "taslak":
        raise HTTPException(status_code=404)
    hbf.status = "beklemede"
    db.commit()
    return RedirectResponse(url=f"/hbf/{hbf_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Onayla / Reddet (is_approver veya admin)
# ---------------------------------------------------------------------------

@router.post("/{hbf_id}/approve", name="hbf_approve")
async def hbf_approve(
    hbf_id: int,
    approval_note: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not (current_user.is_admin or current_user.is_approver):
        raise HTTPException(status_code=403)
    hbf = db.query(HBF).get(hbf_id)
    if not hbf or hbf.status != "beklemede":
        raise HTTPException(status_code=404)
    hbf.status = "onaylandi"
    hbf.approved_by = current_user.id
    hbf.approved_at = datetime.utcnow()
    hbf.approval_note = approval_note.strip() or None
    db.commit()
    return RedirectResponse(url=f"/hbf/{hbf_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{hbf_id}/reject", name="hbf_reject")
async def hbf_reject(
    hbf_id: int,
    approval_note: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not (current_user.is_admin or current_user.is_approver):
        raise HTTPException(status_code=403)
    hbf = db.query(HBF).get(hbf_id)
    if not hbf or hbf.status != "beklemede":
        raise HTTPException(status_code=404)
    hbf.status = "reddedildi"
    hbf.approved_by = current_user.id
    hbf.approved_at = datetime.utcnow()
    hbf.approval_note = approval_note.strip() or None
    db.commit()
    return RedirectResponse(url=f"/hbf/{hbf_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Ödeme Kaydı (onaylandi → odendi)
# ---------------------------------------------------------------------------

@router.post("/{hbf_id}/pay", name="hbf_pay")
async def hbf_pay(
    hbf_id: int,
    pay_date: str = Form(""),
    payment_method: str = Form("banka"),
    bank_account_id: int = Form(None),
    cash_book_id: int = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403)
    hbf = db.query(HBF).get(hbf_id)
    if not hbf or hbf.status != "onaylandi":
        raise HTTPException(status_code=404)

    pdate = _date.fromisoformat(pay_date) if pay_date else _date.today()
    emp_name = hbf.employee.name if hbf.employee else "Çalışan"
    desc = f"HBF {hbf.hbf_no} — {emp_name}"

    # GeneralExpense kaydı
    cat_id = _hbf_expense_category(db)
    ge = GeneralExpense(
        category_id=cat_id,
        employee_id=hbf.employee_id,
        description=f"{hbf.hbf_no}: {hbf.title}",
        amount=hbf.total_amount,
        expense_date=pdate,
        source="hbf",
        created_by=current_user.id,
    )
    db.add(ge)
    db.flush()
    hbf.general_expense_id = ge.id

    # Kasa/Banka hareketi
    if payment_method == "nakit" and cash_book_id:
        db.add(CashEntry(
            book_id=cash_book_id, entry_date=pdate,
            entry_type="cikis", amount=hbf.total_amount, description=desc,
        ))
    elif payment_method == "banka" and bank_account_id:
        db.add(BankMovement(
            account_id=bank_account_id, movement_date=pdate,
            movement_type="cikis", amount=hbf.total_amount, description=desc,
        ))

    hbf.status = "odendi"
    hbf.paid_at = pdate
    hbf.payment_method = payment_method
    hbf.bank_account_id = bank_account_id if payment_method == "banka" else None
    hbf.cash_book_id = cash_book_id if payment_method == "nakit" else None
    db.commit()
    return RedirectResponse(url=f"/hbf/{hbf_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Sil (sadece taslak)
# ---------------------------------------------------------------------------

@router.post("/{hbf_id}/delete", name="hbf_delete")
async def hbf_delete(
    hbf_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    hbf = db.query(HBF).get(hbf_id)
    if hbf and (hbf.created_by == current_user.id or current_user.is_admin):
        if hbf.status == "taslak":
            db.delete(hbf)
            db.commit()
    return RedirectResponse(url="/hbf", status_code=status.HTTP_302_FOUND)
