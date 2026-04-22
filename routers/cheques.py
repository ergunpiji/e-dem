"""
Çek takibi
"""

from datetime import date, datetime
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Cheque, FinancialVendor, Customer, BankAccount, BankMovement, User
from templates_config import templates

router = APIRouter(prefix="/cheques", tags=["cheques"])


@router.get("", response_class=HTMLResponse, name="cheques_list")
async def cheques_list(
    request: Request,
    cheque_type: str = "",
    status_filter: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Cheque)
    if cheque_type:
        query = query.filter(Cheque.cheque_type == cheque_type)
    if status_filter:
        query = query.filter(Cheque.status == status_filter)
    cheques = query.order_by(Cheque.due_date.asc()).all()
    return templates.TemplateResponse(
        "cheques/list.html",
        {
            "request": request, "current_user": current_user,
            "cheques": cheques, "cheque_type": cheque_type,
            "status_filter": status_filter, "page_title": "Çekler",
        },
    )


@router.get("/new", response_class=HTMLResponse, name="cheque_new_get")
async def cheque_new_get(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    vendors = db.query(FinancialVendor).filter(FinancialVendor.active == True).order_by(FinancialVendor.name).all()  # noqa: E712
    customers = db.query(Customer).order_by(Customer.name).all()
    return templates.TemplateResponse(
        "cheques/form.html",
        {
            "request": request, "current_user": current_user,
            "vendors": vendors, "customers": customers,
            "cheque": None, "page_title": "Yeni Çek",
        },
    )


@router.post("/new", name="cheque_new_post")
async def cheque_new_post(
    vendor_id: int = Form(None),
    customer_id: int = Form(None),
    cheque_type: str = Form(...),
    cheque_no: str = Form(""),
    bank: str = Form(""),
    branch: str = Form(""),
    amount: float = Form(...),
    currency: str = Form("TRY"),
    cheque_date: str = Form(...),
    due_date: str = Form(...),
    notes: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    c = Cheque(
        vendor_id=vendor_id,
        customer_id=customer_id,
        cheque_type=cheque_type,
        cheque_no=cheque_no.strip(),
        bank=bank.strip(),
        branch=branch.strip(),
        amount=amount,
        currency=currency,
        cheque_date=date.fromisoformat(cheque_date),
        due_date=date.fromisoformat(due_date),
        status="beklemede",
        notes=notes.strip(),
    )
    db.add(c)
    db.commit()
    return RedirectResponse(url="/cheques", status_code=status.HTTP_302_FOUND)


@router.post("/{cheque_id}/status", name="cheque_status")
async def cheque_status(
    cheque_id: int,
    new_status: str = Form(...),
    bank_account_id: int = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    c = db.query(Cheque).get(cheque_id)
    if not c:
        raise HTTPException(status_code=404)
    c.status = new_status
    if new_status == "tahsil_edildi" and bank_account_id:
        db.add(BankMovement(
            account_id=bank_account_id,
            movement_date=date.today(),
            movement_type="giris",
            amount=c.amount,
            description=f"Çek tahsilat — {c.cheque_no or c.id}",
        ))
    db.commit()
    return RedirectResponse(url="/cheques", status_code=status.HTTP_302_FOUND)
