"""
Nakit kasa yönetimi
"""

from datetime import date
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from auth import get_current_user, require_admin
from database import get_db
from models import CashBook, CashEntry, User
from templates_config import templates

router = APIRouter(prefix="/cash", tags=["cash"])


def _balance(db, book_id):
    ins = db.query(func.sum(CashEntry.amount)).filter(
        CashEntry.book_id == book_id, CashEntry.entry_type == "giris"
    ).scalar() or 0
    outs = db.query(func.sum(CashEntry.amount)).filter(
        CashEntry.book_id == book_id, CashEntry.entry_type == "cikis"
    ).scalar() or 0
    return ins - outs


@router.get("", response_class=HTMLResponse, name="cash_list")
async def cash_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    books = db.query(CashBook).all()
    books_with_balance = [{"book": b, "balance": _balance(db, b.id)} for b in books]
    return templates.TemplateResponse(
        "cash/list.html",
        {"request": request, "current_user": current_user,
         "books_with_balance": books_with_balance, "page_title": "Nakit Kasalar"},
    )


@router.get("/new", response_class=HTMLResponse, name="cash_new_get")
async def cash_new_get(
    request: Request,
    current_user: User = Depends(require_admin),
):
    return templates.TemplateResponse(
        "cash/book_form.html",
        {"request": request, "current_user": current_user,
         "book": None, "page_title": "Yeni Kasa"},
    )


@router.post("/new", name="cash_new_post")
async def cash_new_post(
    name: str = Form(...),
    currency: str = Form("TRY"),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    b = CashBook(name=name.strip(), currency=currency)
    db.add(b)
    db.commit()
    return RedirectResponse(url="/cash", status_code=status.HTTP_302_FOUND)


@router.get("/{book_id}", response_class=HTMLResponse, name="cash_detail")
async def cash_detail(
    book_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    book = db.query(CashBook).get(book_id)
    if not book:
        raise HTTPException(status_code=404)
    entries = db.query(CashEntry).filter(
        CashEntry.book_id == book_id
    ).order_by(CashEntry.entry_date.desc()).all()
    balance = _balance(db, book_id)
    return templates.TemplateResponse(
        "cash/detail.html",
        {
            "request": request, "current_user": current_user,
            "book": book, "entries": entries, "balance": balance,
            "page_title": book.name,
        },
    )


@router.post("/{book_id}/entry", name="cash_entry_add")
async def cash_entry_add(
    book_id: int,
    entry_date: str = Form(...),
    entry_type: str = Form(...),
    amount: float = Form(...),
    description: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    book = db.query(CashBook).get(book_id)
    if not book:
        raise HTTPException(status_code=404)
    db.add(CashEntry(
        book_id=book_id,
        entry_date=date.fromisoformat(entry_date),
        entry_type=entry_type,
        amount=amount,
        description=description.strip(),
    ))
    db.commit()
    return RedirectResponse(url=f"/cash/{book_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{book_id}/entry/{entry_id}/delete", name="cash_entry_delete")
async def cash_entry_delete(
    book_id: int,
    entry_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    e = db.query(CashEntry).get(entry_id)
    if e and e.book_id == book_id:
        db.delete(e)
        db.commit()
    return RedirectResponse(url=f"/cash/{book_id}", status_code=status.HTTP_302_FOUND)
