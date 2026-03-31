"""
E-dem — Müşteri yönetimi router'ı (Admin only, PM autocomplete)
"""

import json
import os
import shutil

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin
from database import get_db
from models import Customer, User, _uuid, _now

router = APIRouter(prefix="/customers", tags=["customers"])
from templates_config import templates


@router.get("", response_class=HTMLResponse, name="customers_list")
async def customers_list(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    customers = db.query(Customer).order_by(Customer.name).all()
    return templates.TemplateResponse(
        "customers/list.html",
        {
            "request":      request,
            "current_user": current_user,
            "customers":    customers,
            "page_title":   "Müşteri Yönetimi",
        },
    )


@router.get("/autocomplete")
async def customers_autocomplete(
    q: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """PM için müşteri autocomplete endpoint'i"""
    query = db.query(Customer)
    if q:
        query = query.filter(Customer.name.ilike(f"%{q}%"))
    customers = query.order_by(Customer.name).limit(20).all()
    return JSONResponse([{"id": c.id, "name": c.name, "code": c.code} for c in customers])


@router.get("/new", response_class=HTMLResponse, name="customers_new")
async def customers_new(
    request: Request,
    current_user: User = Depends(require_admin),
):
    return templates.TemplateResponse(
        "customers/form.html",
        {
            "request":      request,
            "current_user": current_user,
            "customer":     None,
            "page_title":   "Yeni Müşteri",
            "error":        None,
        },
    )


@router.post("/new", name="customers_create")
async def customers_create(
    name:          str = Form(...),
    code:          str = Form(...),
    sector:        str = Form(""),
    address:       str = Form(""),
    tax_office:    str = Form(""),
    tax_number:    str = Form(""),
    email:         str = Form(""),
    phone:         str = Form(""),
    notes:         str = Form(""),
    contacts_json: str = Form("[]"),
    payment_term:  str = Form(""),
    request: Request = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    code_clean = code.lower().strip()[:10]

    existing = db.query(Customer).filter(Customer.code == code_clean).first()
    if existing:
        return templates.TemplateResponse(
            "customers/form.html",
            {
                "request":      request,
                "current_user": current_user,
                "customer":     None,
                "page_title":   "Yeni Müşteri",
                "error":        f"'{code_clean}' kodu zaten kullanılıyor.",
            },
            status_code=400,
        )

    customer = Customer(
        id=_uuid(),
        name=name.strip(),
        code=code_clean,
        sector=sector.strip(),
        address=address.strip(),
        tax_office=tax_office.strip(),
        tax_number=tax_number.strip(),
        email=email.strip(),
        phone=phone.strip(),
        notes=notes.strip(),
        contacts_json=contacts_json,
        payment_term=payment_term.strip(),
        created_at=_now(),
    )
    db.add(customer)
    db.commit()
    return RedirectResponse(url="/customers", status_code=status.HTTP_302_FOUND)


@router.get("/{customer_id}/edit", response_class=HTMLResponse, name="customers_edit")
async def customers_edit(
    customer_id: str,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return RedirectResponse(url="/customers", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        "customers/form.html",
        {
            "request":      request,
            "current_user": current_user,
            "customer":     customer,
            "page_title":   f"{customer.name} — Düzenle",
            "error":        None,
        },
    )


@router.post("/{customer_id}/edit", name="customers_update")
async def customers_update(
    customer_id: str,
    request: Request,
    name:          str = Form(...),
    code:          str = Form(...),
    sector:        str = Form(""),
    address:       str = Form(""),
    tax_office:    str = Form(""),
    tax_number:    str = Form(""),
    email:         str = Form(""),
    phone:         str = Form(""),
    notes:         str = Form(""),
    contacts_json: str = Form("[]"),
    payment_term:  str = Form(""),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return RedirectResponse(url="/customers", status_code=status.HTTP_302_FOUND)

    code_clean = code.lower().strip()[:10]
    conflict = db.query(Customer).filter(
        Customer.code == code_clean, Customer.id != customer_id
    ).first()
    if conflict:
        return templates.TemplateResponse(
            "customers/form.html",
            {
                "request":      request,
                "current_user": current_user,
                "customer":     customer,
                "page_title":   f"{customer.name} — Düzenle",
                "error":        f"'{code_clean}' kodu başka müşteriye ait.",
            },
            status_code=400,
        )

    customer.name          = name.strip()
    customer.code          = code_clean
    customer.sector        = sector.strip()
    customer.address       = address.strip()
    customer.tax_office    = tax_office.strip()
    customer.tax_number    = tax_number.strip()
    customer.email         = email.strip()
    customer.phone         = phone.strip()
    customer.notes         = notes.strip()
    customer.contacts_json = contacts_json
    customer.payment_term  = payment_term.strip()
    db.commit()
    return RedirectResponse(url="/customers", status_code=status.HTTP_302_FOUND)


@router.post("/{customer_id}/upload-template", name="customers_upload_template")
async def customers_upload_template(
    customer_id:   str,
    template_file: UploadFile = File(...),
    current_user:  User = Depends(require_admin),
    db:            Session = Depends(get_db),
):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return RedirectResponse(url="/customers", status_code=status.HTTP_302_FOUND)

    upload_dir = "static/uploads/customer_templates"
    os.makedirs(upload_dir, exist_ok=True)

    ext = os.path.splitext(template_file.filename or "")[1].lower()
    if ext not in (".xlsx", ".xls"):
        return RedirectResponse(
            url=f"/customers/{customer_id}/edit?error=Sadece+.xlsx+dosyası+yüklenebilir",
            status_code=status.HTTP_302_FOUND,
        )

    # Eski template'i sil
    if customer.excel_template_path and os.path.exists(customer.excel_template_path):
        os.remove(customer.excel_template_path)

    save_path = os.path.join(upload_dir, f"{customer_id}{ext}")
    with open(save_path, "wb") as f:
        shutil.copyfileobj(template_file.file, f)

    customer.excel_template_path = save_path
    db.commit()
    return RedirectResponse(
        url=f"/customers/{customer_id}/edit?saved=template",
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/{customer_id}/excel-config", name="customers_excel_config")
async def customers_excel_config(
    customer_id:        str,
    data_start_row:     str = Form("2"),
    col_service_name:   str = Form(""),
    col_unit:           str = Form(""),
    col_qty:            str = Form(""),
    col_nights:         str = Form(""),
    col_sale_price:     str = Form(""),
    col_vat_rate:       str = Form(""),
    col_sale_price_inc: str = Form(""),
    col_total_inc:      str = Form(""),
    current_user:       User = Depends(require_admin),
    db:                 Session = Depends(get_db),
):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return RedirectResponse(url="/customers", status_code=status.HTTP_302_FOUND)

    config = {
        "data_start_row": int(data_start_row or 2),
        "columns": {
            "service_name":   col_service_name.strip().upper() or None,
            "unit":           col_unit.strip().upper() or None,
            "qty":            col_qty.strip().upper() or None,
            "nights":         col_nights.strip().upper() or None,
            "sale_price":     col_sale_price.strip().upper() or None,
            "vat_rate":       col_vat_rate.strip().upper() or None,
            "sale_price_inc": col_sale_price_inc.strip().upper() or None,
            "total_inc":      col_total_inc.strip().upper() or None,
        },
    }
    # None değerleri kaldır
    config["columns"] = {k: v for k, v in config["columns"].items() if v}
    customer.excel_config_json = json.dumps(config, ensure_ascii=False)
    db.commit()
    return RedirectResponse(
        url=f"/customers/{customer_id}/edit?saved=config",
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/{customer_id}/upload-doc", name="customers_upload_doc")
async def customers_upload_doc(
    customer_id: str,
    doc_file:    UploadFile = File(...),
    current_user: User = Depends(require_admin),
    db:           Session = Depends(get_db),
):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return RedirectResponse(url="/customers", status_code=status.HTTP_302_FOUND)

    upload_dir = f"static/uploads/customer_docs/{customer_id}"
    os.makedirs(upload_dir, exist_ok=True)

    filename = os.path.basename(doc_file.filename or "dosya")
    save_path = os.path.join(upload_dir, filename)
    with open(save_path, "wb") as f:
        shutil.copyfileobj(doc_file.file, f)

    # Mevcut dosya listesine ekle
    try:
        doc_list = json.loads(customer.docs_json or "[]")
    except Exception:
        doc_list = []
    doc_list.append({"name": filename, "path": save_path})
    customer.docs_json = json.dumps(doc_list, ensure_ascii=False)
    db.commit()
    return RedirectResponse(url=f"/customers/{customer_id}/edit", status_code=status.HTTP_302_FOUND)


@router.post("/{customer_id}/delete-doc", name="customers_delete_doc")
async def customers_delete_doc(
    customer_id: str,
    filename:    str = Form(...),
    current_user: User = Depends(require_admin),
    db:           Session = Depends(get_db),
):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return RedirectResponse(url="/customers", status_code=status.HTTP_302_FOUND)

    try:
        doc_list = json.loads(customer.docs_json or "[]")
    except Exception:
        doc_list = []

    remaining = []
    for d in doc_list:
        if d["name"] == filename:
            try:
                os.remove(d["path"])
            except Exception:
                pass
        else:
            remaining.append(d)

    customer.docs_json = json.dumps(remaining, ensure_ascii=False)
    db.commit()
    return RedirectResponse(url=f"/customers/{customer_id}/edit", status_code=status.HTTP_302_FOUND)


@router.post("/{customer_id}/delete", name="customers_delete")
async def customers_delete(
    customer_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if customer:
        db.delete(customer)
        db.commit()
    return RedirectResponse(url="/customers", status_code=status.HTTP_302_FOUND)
